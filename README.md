# Orbis

*Your world, intelligently organized.*

Orbis turns the scattered requirements of a university application into a verified checklist and
deadline timeline, then tells you exactly what you still need to provide. **v1 wedge: master's
applications.** The engine is domain-agnostic (requirements, deadlines, citations, matching), so
insurance policies or government forms can reuse it later.

## What makes it different from "paste it into a chatbot"

1. **Every claim is cited and verified.** Each requirement and deadline carries the exact quote and page it
   came from. `verify.py` checks that the quote really exists in the source; claims that fail are
   down-weighted and shown as "Not verified" instead of being stated as fact.
2. **Conditions are first-class.** "Required unless you studied in English" is stored as a condition, so Orbis
   asks you to check it instead of silently demanding or skipping it.
3. **It is measured.** `eval/` scores extraction against hand-labelled ground truth (precision, recall,
   condition detection, citation validity, hallucination rate, latency). Every prompt or model change
   leaves a number behind.
4. **Privacy basics are built in.** SSRF-guarded URL fetching, upload size limits, XSS-safe UI rendering,
   and a one-click "Delete all my data".

## UI notes

Playful, colorful, dark-first (light mode follows the system setting). The logo is interactive: it leans
toward your cursor, speeds up on hover, pulses on click, and five quick clicks (or the Konami code) trigger
hyperdrive. Finishing a program's checklist sets off confetti.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional: add ANTHROPIC_API_KEY for the LLM extractor
uvicorn backend.app.main:app --reload
# open http://localhost:8000 and click "Load sample programs"
```

Without an API key Orbis uses the rule-based baseline. With `ANTHROPIC_API_KEY` set it uses Claude
(`ORBIS_MODEL` to override the model).

```bash
python -m pytest -q                       # 14 tests
python -m eval.run_eval --extractor rules # benchmark (add --extractor llm with a key)
docker build -t orbis . && docker run -p 8080:8080 orbis
```

## Layout

```
backend/app/schema.py    data model (Requirement, Deadline, Citation, Task...)
backend/app/ingest.py    PDF / web / text -> page-addressable Source (SSRF guarded)
backend/app/extract.py   RuleBasedExtractor (baseline) and LLMExtractor (Claude, strict JSON)
backend/app/verify.py    quote-in-source check, exact plus fuzzy (OCR tolerant)
backend/app/pipeline.py  extract -> verify -> confidence adjustment
backend/app/match.py     requirements vs your documents -> missing / satisfied / expired / needs review
backend/app/main.py      FastAPI endpoints
backend/app/static/      single-page UI with source panel and highlighted citations
eval/                    metrics + benchmark runner
data/sources, data/labels  sample sources and ground truth
```

## Honest status

- The bundled benchmark is **2 synthetic documents**. The numbers it prints prove the harness works, not
  that the extractor is good. Replace them with 10+ real programs and 150+ hand-labelled items before
  quoting any accuracy figure.
- Single user, SQLite, no auth. Multi-user isolation, Postgres and a job queue are the next milestone.
- No OCR yet: scanned PDFs are rejected with a clear message.
- User documents are tracked by name and type only. Reading their contents (GPA, scores, expiry) is next.
- Requirements change every cycle. Orbis shows when each source was fetched and always points back to the
  official page.

## Roadmap

| Week | Goal |
|---|---|
| 1 | Pick 10 real programs, collect sources, hand-label ground truth |
| 2 | Real-world ingestion hardening (messy HTML, multi-page PDFs, OCR) |
| 3 to 4 | Run the LLM extractor on the real set, improve conditional logic and dates against the benchmark |
| 5 | Read uploaded user documents and extract fields |
| 6 | Smarter gap detection (e.g. "2 of 3 recommendation letters"), reminders |
| 7 | Auth, Postgres, queue, deploy, load test, design doc, threat model, user study |
