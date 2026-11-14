"""Orbis API. Every route is scoped to the signed-in user (see current_user)."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .extract import Extractor, get_extractor
from .ingest import MAX_BYTES, from_pdf, from_text, from_url, new_id
from .match import build_tasks
from .pipeline import run_pipeline
from .schema import Deadline, DocType, Program, Requirement, Source, UserDocument
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval" / "results"
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Orbis", version="0.1.0")
store = Store()
_extractor: Extractor | None = None


def extractor() -> Extractor:
    global _extractor
    if _extractor is None:
        _extractor = get_extractor()
    return _extractor


def current_user() -> str:
    """TEMPORARY: everyone is the same user until the auth endpoints exist.
    Replace the body with the real session or JWT check (return the user id, or raise 401)."""
    return "local"


# ---------------------------------------------------------------- helpers
def _ingest_program(user: str, name: str, source: Source) -> dict:
    result, stats = run_pipeline(source, extractor())
    program = Program(id=new_id(), name=name, source_ids=[source.id])
    store.put(user, "sources", source)
    store.put(user, "programs", program)
    for r in result.requirements:
        r.id, r.program_id = new_id(), program.id
        store.put(user, "requirements", r, program.id)
    for d in result.deadlines:
        d.id, d.program_id = new_id(), program.id
        store.put(user, "deadlines", d, program.id)
    return {"program": program, "stats": stats.__dict__, "extractor": extractor().name}


_FILENAME_HINTS: list[tuple[re.Pattern, DocType]] = [
    (re.compile(r"transcript|marksheet|grade", re.I), DocType.transcript),
    (re.compile(r"resume|cv", re.I), DocType.cv),
    (re.compile(r"sop|statement|purpose", re.I), DocType.sop),
    (re.compile(r"lor|recommend|reference", re.I), DocType.lor),
    (re.compile(r"gre|gmat|sat|score", re.I), DocType.score_report),
    (re.compile(r"ielts|toefl|duolingo|pte", re.I), DocType.english_test),
    (re.compile(r"passport", re.I), DocType.passport),
    (re.compile(r"portfolio|sample", re.I), DocType.portfolio),
]


def guess_doc_type(filename: str) -> DocType:
    for pat, t in _FILENAME_HINTS:
        if pat.search(filename):
            return t
    return DocType.other


# ---------------------------------------------------------------- programs
class ProgramIn(BaseModel):
    name: str
    url: Optional[str] = None
    text: Optional[str] = None


@app.post("/api/programs")
def create_program(body: ProgramIn, user: str = Depends(current_user)):
    if not body.url and not body.text:
        raise HTTPException(422, "Provide a url or pasted text.")
    try:
        source = from_url(body.url, name=body.name) if body.url else from_text(body.name, body.text or "")
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return _ingest_program(user, body.name, source)


@app.post("/api/programs/upload")
async def upload_program(name: str = Form(...), file: UploadFile = File(...), user: str = Depends(current_user)):
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is too large.")
    try:
        if (file.filename or "").lower().endswith(".pdf"):
            source = from_pdf(name, data)
        else:
            source = from_text(name, data.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return _ingest_program(user, name, source)


@app.get("/api/programs")
def list_programs(user: str = Depends(current_user)):
    return store.list(user, "programs", Program)


@app.delete("/api/programs/{program_id}")
def delete_program(program_id: str, user: str = Depends(current_user)):
    store.delete_program(user, program_id)
    return {"ok": True}


@app.get("/api/programs/{program_id}")
def get_program(program_id: str, user: str = Depends(current_user)):
    program = store.get(user, "programs", program_id, Program)
    if not program:
        raise HTTPException(404, "Program not found.")
    return {
        "program": program,
        "requirements": store.list(user, "requirements", Requirement, program_id),
        "deadlines": sorted(store.list(user, "deadlines", Deadline, program_id), key=lambda d: d.due),
    }


# ---------------------------------------------------------------- sources (for the "view source" panel)
@app.get("/api/sources/{source_id}")
def get_source(source_id: str, user: str = Depends(current_user)):
    src = store.get(user, "sources", source_id, Source)
    if not src:
        raise HTTPException(404, "Source not found.")
    return {"id": src.id, "name": src.name, "url": src.url, "fetched_at": src.fetched_at, "pages": src.pages}


# ---------------------------------------------------------------- the student's documents
class DocumentIn(BaseModel):
    filename: str
    doc_type: Optional[DocType] = None
    expiry: Optional[date] = None


@app.post("/api/documents")
def add_document(body: DocumentIn, user: str = Depends(current_user)):
    doc = UserDocument(id=new_id(), filename=body.filename,
                       doc_type=body.doc_type or guess_doc_type(body.filename), expiry=body.expiry)
    store.put(user, "documents", doc)
    return doc


@app.get("/api/documents")
def list_documents(user: str = Depends(current_user)):
    return store.list(user, "documents", UserDocument)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, user: str = Depends(current_user)):
    store.delete(user, "documents", doc_id)
    return {"ok": True}


# ---------------------------------------------------------------- checklist and timeline
@app.get("/api/checklist/{program_id}")
def checklist(program_id: str, user: str = Depends(current_user)):
    reqs = store.list(user, "requirements", Requirement, program_id)
    docs = store.list(user, "documents", UserDocument)
    tasks = build_tasks(reqs, docs)
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t.state.value] = counts.get(t.state.value, 0) + 1
    return {"tasks": tasks, "counts": counts}


@app.get("/api/timeline")
def timeline(user: str = Depends(current_user)):
    names = {p.id: p.name for p in store.list(user, "programs", Program)}
    today = date.today()
    items = []
    for d in store.list(user, "deadlines", Deadline):
        items.append({**d.model_dump(mode="json"), "program_name": names.get(d.program_id, "Unknown"),
                      "days_left": (d.due - today).days})
    return sorted(items, key=lambda x: x["due"])


# ---------------------------------------------------------------- demo data and privacy
@app.post("/api/demo/seed")
def seed_demo(user: str = Depends(current_user)):
    created = []
    for path in sorted((ROOT / "data" / "sources").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        name = text.splitlines()[0].split(" (sample")[0].strip() or path.stem
        created.append(_ingest_program(user, name, from_text(name, text))["program"])
    return created


@app.delete("/api/me")
def delete_everything(user: str = Depends(current_user)):
    store.wipe(user)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "extractor": extractor().name}


# ---------------------------------------------------------------- pages
@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(STATIC / "landing.html")


@app.get("/app", include_in_schema=False)
def app_page():
    return FileResponse(STATIC / "index.html")


@app.get("/api/eval")
def eval_results():
    runs = {}
    for p in sorted(EVAL_DIR.glob("*.json")):
        try:
            runs[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {"runs": runs}

app.mount("/static", StaticFiles(directory=STATIC), name="static")
