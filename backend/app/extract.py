"""Extractors turn a Source into structured requirements and deadlines.

Two implementations share one interface so they can be benchmarked head to head:
  * RuleBasedExtractor: deterministic baseline, runs offline, used in tests and as a floor.
  * LLMExtractor: Claude with a strict JSON contract, validated by Pydantic.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from typing import Protocol

from .schema import (
    Category, Citation, Deadline, DocType, ExtractionResult, Requirement, Source,
)


class Extractor(Protocol):
    name: str

    def extract(self, source: Source) -> ExtractionResult: ...


# ---------------------------------------------------------------- date parsing
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9

_MON = r"(?P<mon>[A-Za-z]{3,9})\.?"
_DATE_PATTERNS = [
    re.compile(rf"{_MON}\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>\d{{4}})"),
    re.compile(rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON},?\s+(?P<year>\d{{4}})"),
]
_ISO = re.compile(r"(?P<year>\d{4})-(?P<m>\d{2})-(?P<day>\d{2})")


def find_date(text: str) -> date | None:
    """Return the first fully specified date in text. Never guesses a missing year."""
    m = _ISO.search(text)
    if m:
        try:
            return date(int(m["year"]), int(m["m"]), int(m["day"]))
        except ValueError:
            pass
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            mon = _MONTHS.get(m["mon"].lower())
            if mon:
                try:
                    return date(int(m["year"]), mon, int(m["day"]))
                except ValueError:
                    continue
    return None


_TIME_NOTE = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)(?:\s*[A-Z]{2,4}\b)?|\bmidnight\b", re.I)

# ---------------------------------------------------------------- rule-based baseline
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+(?P<body>.+)$")

_RULES: list[tuple[re.Pattern, Category, DocType | None]] = [
    (re.compile(r"\btranscripts?\b|\bmark ?sheets?\b", re.I), Category.document, DocType.transcript),
    (re.compile(r"\bresume\b|\bcv\b|curriculum vitae", re.I), Category.document, DocType.cv),
    (re.compile(r"statement of purpose|\bsop\b|personal statement|statement of intent", re.I), Category.essay, DocType.sop),
    (re.compile(r"letters? of recommendation|recommendation letters?|\breferees?\b|\breferences?\b", re.I), Category.document, DocType.lor),
    (re.compile(r"\bgre\b|\bgmat\b|\bsat\b|\bact\b", re.I), Category.test_score, DocType.score_report),
    (re.compile(r"\bielts\b|\btoefl\b|duolingo|\bpte\b|english proficiency", re.I), Category.test_score, DocType.english_test),
    (re.compile(r"\bpassport\b", re.I), Category.document, DocType.passport),
    (re.compile(r"portfolio|writing sample", re.I), Category.document, DocType.portfolio),
    (re.compile(r"application fee|processing fee|fee of", re.I), Category.fee, None),
    (re.compile(r"\bminimum\b.*\b(gpa|cgpa|percent|%)\b|\bbachelor'?s\b|\bdegree\b", re.I), Category.eligibility, None),
]
_CONDITION = re.compile(r"\b(?:if|unless|only if|waived|exempt(?:ed)?|except)\b.*$", re.I)
_DEADLINE_HINT = re.compile(r"deadline|due|closes?|last date|apply by|round \d|early (?:action|decision)|priority", re.I)


class RuleBasedExtractor:
    name = "rules-v1"

    def extract(self, source: Source) -> ExtractionResult:
        reqs: list[Requirement] = []
        dls: list[Deadline] = []
        for page_no, page in enumerate(source.pages, start=1):
            for raw in page.splitlines():
                line = raw.strip()
                if not line:
                    continue
                body = _BULLET.match(line)
                text = body["body"].strip() if body else line

                d = find_date(text)
                if d and _DEADLINE_HINT.search(text):
                    label = re.split(r"[:\-\u2013\u2014]", text, maxsplit=1)[0].strip()[:80] or "Deadline"
                    tn = _TIME_NOTE.search(text)
                    dls.append(Deadline(
                        label=label, due=d, time_note=tn.group(0) if tn else None,
                        citation=Citation(source_id=source.id, page=page_no, quote=text),
                        confidence=0.75,
                    ))
                    continue

                if not body:
                    continue
                for pat, cat, dtype in _RULES:
                    if pat.search(text):
                        cond = _CONDITION.search(text)
                        reqs.append(Requirement(
                            category=cat,
                            description=text.rstrip("."),
                            doc_type=dtype,
                            mandatory=not re.search(r"\boptional\b|\bnot required\b|\brecommended\b", text, re.I),
                            conditions=[cond.group(0).strip().rstrip(".")] if cond else [],
                            citation=Citation(source_id=source.id, page=page_no, quote=text),
                            confidence=0.7,
                        ))
                        break
        return ExtractionResult(requirements=reqs, deadlines=dls)


# ---------------------------------------------------------------- LLM extractor
SYSTEM_PROMPT = """You extract application requirements and deadlines from university documents.

Return ONLY a JSON object, no prose and no code fences, with this shape:
{
  "requirements": [{
    "category": "document|test_score|fee|essay|form|eligibility|other",
    "description": "short plain-language statement of what the applicant must provide or satisfy",
    "doc_type": "transcript|cv|sop|lor|score_report|english_test|passport|portfolio|other|null",
    "mandatory": true,
    "conditions": ["each exception or condition as its own short string, copied closely from the text"],
    "page": 1,
    "quote": "an exact, contiguous passage copied verbatim from the page that supports this item",
    "confidence": 0.0
  }],
  "deadlines": [{
    "label": "e.g. Round 1, Early Decision, Scholarship deadline",
    "due": "YYYY-MM-DD",
    "time_note": "time and timezone exactly as written, or null",
    "page": 1,
    "quote": "exact contiguous passage containing the date",
    "confidence": 0.0
  }]
}

Rules:
- The quote must be copied character for character from the text. Never paraphrase it.
- One requirement per item. Keep conditions (waivers, exceptions, 'if ...') out of the description and in conditions.
- Only output a deadline when the day, month and year are all stated. Never infer a year.
- If the document does not say something, omit it. Do not guess.
- confidence reflects how clearly the text states the item."""


class LLMExtractor:
    def __init__(self, model: str | None = None, chunk_chars: int = 14000):
        from anthropic import Anthropic  # lazy import so tests run without a key

        self.client = Anthropic()
        self.model = model or os.getenv("ORBIS_MODEL", "claude-sonnet-5-5")
        self.chunk_chars = chunk_chars
        self.name = f"llm:{self.model}"

    def _chunks(self, source: Source) -> list[str]:
        chunks, cur, size = [], [], 0
        for i, page in enumerate(source.pages, start=1):
            block = f"[[PAGE {i}]]\n{page}\n"
            if cur and size + len(block) > self.chunk_chars:
                chunks.append("".join(cur)); cur, size = [], 0
            cur.append(block); size += len(block)
        if cur:
            chunks.append("".join(cur))
        return chunks

    @staticmethod
    def _parse(raw: str) -> dict:
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("Model returned no JSON object.")
        return json.loads(raw[start : end + 1])

    def extract(self, source: Source) -> ExtractionResult:
        result = ExtractionResult()
        seen_req: set[str] = set()
        seen_dl: set[tuple[str, date]] = set()
        for chunk in self._chunks(source):
            msg = self.client.messages.create(
                model=self.model, max_tokens=4096, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": chunk}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            try:
                data = self._parse(text)
            except (ValueError, json.JSONDecodeError):
                continue  # a malformed chunk must not take down the whole source
            for r in data.get("requirements", []):
                try:
                    req = Requirement(
                        category=r["category"], description=r["description"],
                        doc_type=(r.get("doc_type") if r.get("doc_type") not in (None, "null") else None),
                        mandatory=bool(r.get("mandatory", True)),
                        conditions=[c for c in r.get("conditions", []) if c],
                        citation=Citation(source_id=source.id, page=int(r.get("page", 1)), quote=r.get("quote", "")),
                        confidence=float(r.get("confidence", 0.7)),
                    )
                except Exception:
                    continue
                key = re.sub(r"\W+", " ", req.description.lower()).strip()
                if key not in seen_req:
                    seen_req.add(key); result.requirements.append(req)
            for d in data.get("deadlines", []):
                try:
                    dl = Deadline(
                        label=d["label"], due=datetime.strptime(d["due"], "%Y-%m-%d").date(),
                        time_note=d.get("time_note"),
                        citation=Citation(source_id=source.id, page=int(d.get("page", 1)), quote=d.get("quote", "")),
                        confidence=float(d.get("confidence", 0.7)),
                    )
                except Exception:
                    continue
                key2 = (dl.label.lower(), dl.due)
                if key2 not in seen_dl:
                    seen_dl.add(key2); result.deadlines.append(dl)
        return result


def get_extractor() -> Extractor:
    """LLM extractor when a key is configured, otherwise the offline baseline."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return LLMExtractor()
    return RuleBasedExtractor()
