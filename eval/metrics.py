"""Scoring for extraction quality. Matching is one-to-one and deliberately strict.

Besides the headline numbers, score() records what the dashboard needs:
  * by_category: tp/fp/fn per requirement category, plus a "deadline" pseudo-category
  * failures:    one record per miss, extra item, unverified match or wrong flag
  * calibration: (stated confidence, was it correct) for every extracted item
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from backend.app.schema import Deadline, ExtractionResult, Requirement

DEADLINE = "deadline"


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def __iadd__(self, other: "Counts") -> "Counts":
        self.tp += other.tp; self.fp += other.fp; self.fn += other.fn
        return self


@dataclass
class Scores:
    requirements: Counts = field(default_factory=Counts)
    deadlines: Counts = field(default_factory=Counts)
    mandatory_correct: int = 0
    mandatory_total: int = 0
    condition_correct: int = 0
    condition_total: int = 0
    items: int = 0
    unverified: int = 0
    by_category: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    failures: list[dict] = field(default_factory=list)
    calibration: list[tuple[float, bool]] = field(default_factory=list)

    def merge(self, o: "Scores") -> None:
        self.requirements += o.requirements
        self.deadlines += o.deadlines
        for k in ("mandatory_correct", "mandatory_total", "condition_correct", "condition_total", "items", "unverified"):
            setattr(self, k, getattr(self, k) + getattr(o, k))
        for cat, c in o.by_category.items():
            self.by_category[cat] += c
        self.failures.extend(o.failures)
        self.calibration.extend(o.calibration)

    @property
    def citation_validity(self) -> float:
        return 1 - self.unverified / self.items if self.items else 0.0

    @property
    def hallucination_rate(self) -> float:
        return self.unverified / self.items if self.items else 0.0


def _req_matches(label: dict, r: Requirement) -> bool:
    want_dt = label.get("doc_type")
    return (
        r.category.value == label["category"]
        and (r.doc_type.value if r.doc_type else None) == want_dt
        and label["match"].lower() in r.description.lower()
    )


def _fail(kind: str, type_: str, category: str, text: str, source: str,
          quote: str | None = None, confidence: float | None = None, verified: bool | None = None) -> dict:
    return {"kind": kind, "type": type_, "category": category, "text": text, "source": source,
            "quote": quote, "confidence": confidence, "verified": verified}


def score(result: ExtractionResult, labels: dict) -> Scores:
    s = Scores()
    src = labels.get("source", "")

    # ---- requirements
    used: set[int] = set()
    for lab in labels["requirements"]:
        cat = lab["category"]
        hit = next((i for i, r in enumerate(result.requirements) if i not in used and _req_matches(lab, r)), None)
        if hit is None:
            s.requirements.fn += 1
            s.by_category[cat].fn += 1
            s.failures.append(_fail("missed", "requirement", cat, f'Expected something like "{lab["match"]}"', src))
            continue
        used.add(hit)
        r = result.requirements[hit]
        s.requirements.tp += 1
        s.by_category[cat].tp += 1
        quote = r.citation.quote if r.citation else None

        s.mandatory_total += 1
        ok_m = r.mandatory == lab.get("mandatory", True)
        s.mandatory_correct += int(ok_m)
        if not ok_m:
            s.failures.append(_fail("wrong_mandatory", "requirement", cat,
                                    f'{r.description} (labelled {"required" if lab.get("mandatory", True) else "optional"})',
                                    src, quote, r.confidence, r.verified))

        s.condition_total += 1
        ok_c = bool(r.conditions) == lab.get("has_condition", False)
        s.condition_correct += int(ok_c)
        if not ok_c:
            expected = "has a condition" if lab.get("has_condition", False) else "has no condition"
            s.failures.append(_fail("wrong_condition", "requirement", cat,
                                    f"{r.description} (labelled: {expected})", src, quote, r.confidence, r.verified))

        if not r.verified:
            s.failures.append(_fail("unverified", "requirement", cat, r.description, src, quote, r.confidence, False))

    for i, r in enumerate(result.requirements):
        correct = i in used
        s.calibration.append((r.confidence, correct))
        if not correct:
            s.requirements.fp += 1
            s.by_category[r.category.value].fp += 1
            s.failures.append(_fail("spurious", "requirement", r.category.value, r.description, src,
                                    r.citation.quote if r.citation else None, r.confidence, r.verified))

    # ---- deadlines
    dused: set[int] = set()
    for lab in labels["deadlines"]:
        def ok(d: Deadline) -> bool:
            return d.due.isoformat() == lab["due"] and lab.get("label_contains", "").lower() in d.label.lower()
        hit = next((i for i, d in enumerate(result.deadlines) if i not in dused and ok(d)), None)
        if hit is None:
            s.deadlines.fn += 1
            s.by_category[DEADLINE].fn += 1
            s.failures.append(_fail("missed", "deadline", DEADLINE,
                                    f'Expected {lab["due"]} ({lab.get("label_contains", "any label")})', src))
        else:
            dused.add(hit)
            s.deadlines.tp += 1
            s.by_category[DEADLINE].tp += 1
            d = result.deadlines[hit]
            if not d.verified:
                s.failures.append(_fail("unverified", "deadline", DEADLINE, f"{d.label}: {d.due}", src,
                                        d.citation.quote if d.citation else None, d.confidence, False))

    for i, d in enumerate(result.deadlines):
        correct = i in dused
        s.calibration.append((d.confidence, correct))
        if not correct:
            s.deadlines.fp += 1
            s.by_category[DEADLINE].fp += 1
            s.failures.append(_fail("spurious", "deadline", DEADLINE, f"{d.label}: {d.due}", src,
                                    d.citation.quote if d.citation else None, d.confidence, d.verified))

    items = [*result.requirements, *result.deadlines]
    s.items = len(items)
    s.unverified = sum(1 for i in items if not i.verified)
    return s


# ---------------------------------------------------------------- report helpers
def category_rows(by_category: dict[str, Counts]) -> list[dict]:
    """One row per category for the dashboard. None means 'no data', not zero."""
    rows = []
    for cat, c in sorted(by_category.items(), key=lambda kv: (kv[0] == DEADLINE, kv[0])):
        rows.append({
            "category": cat, "tp": c.tp, "fp": c.fp, "fn": c.fn,
            "precision": round(c.precision, 3) if (c.tp + c.fp) else None,
            "recall": round(c.recall, 3) if (c.tp + c.fn) else None,
        })
    return rows


def calibration_report(pairs: list[tuple[float, bool]], bins: int = 5) -> dict:
    """Reliability bins and expected calibration error (ECE).

    A well-calibrated extractor is right about 80% of the time when it says 0.8.
    ECE is the average gap between stated confidence and actual accuracy, weighted by bin size.
    """
    n = len(pairs)
    clamped = [(min(max(c, 0.0), 1.0), ok) for c, ok in pairs]
    rows, ece = [], 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inb = [(c, ok) for c, ok in clamped if lo <= c < hi or (b == bins - 1 and c == 1.0)]
        if not inb:
            rows.append({"lo": round(lo, 2), "hi": round(hi, 2), "n": 0, "mean_confidence": None, "accuracy": None})
            continue
        mean_c = sum(c for c, _ in inb) / len(inb)
        acc = sum(1 for _, ok in inb if ok) / len(inb)
        ece += len(inb) / n * abs(acc - mean_c)
        rows.append({"lo": round(lo, 2), "hi": round(hi, 2), "n": len(inb),
                     "mean_confidence": round(mean_c, 3), "accuracy": round(acc, 3)})
    return {"n": n, "bins": rows, "ece": round(ece, 3) if n else None}
