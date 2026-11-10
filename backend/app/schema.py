"""Core data model for Orbis.

Everything the system claims about a program (a requirement or a deadline) carries a
Citation pointing at the exact passage in a source document. That is the trust layer:
claims without a verifiable citation are dropped or flagged for review.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceKind(str, Enum):
    pdf = "pdf"
    webpage = "webpage"
    text = "text"


class Category(str, Enum):
    document = "document"
    test_score = "test_score"
    fee = "fee"
    essay = "essay"
    form = "form"
    eligibility = "eligibility"
    other = "other"


class DocType(str, Enum):
    """Kinds of documents a student can upload. Used to match against requirements."""
    transcript = "transcript"
    cv = "cv"
    sop = "sop"
    lor = "lor"
    score_report = "score_report"
    english_test = "english_test"
    passport = "passport"
    portfolio = "portfolio"
    other = "other"


class TaskState(str, Enum):
    missing = "missing"
    satisfied = "satisfied"
    needs_review = "needs_review"
    expired = "expired"


class Source(BaseModel):
    id: str
    kind: SourceKind
    name: str
    url: Optional[str] = None
    fetched_at: datetime = Field(default_factory=utcnow)
    pages: list[str] = Field(default_factory=list)  # page 1 == pages[0]


class Citation(BaseModel):
    source_id: str
    page: int = 1
    quote: str


class Requirement(BaseModel):
    id: str = ""
    program_id: str = ""
    category: Category
    description: str
    doc_type: Optional[DocType] = None
    mandatory: bool = True
    conditions: list[str] = Field(default_factory=list)  # e.g. "waived for English-medium graduates"
    citation: Optional[Citation] = None
    confidence: float = 0.8
    verified: bool = False  # True only if the quote was found in the source text


class Deadline(BaseModel):
    id: str = ""
    program_id: str = ""
    label: str  # e.g. "Round 1"
    due: date
    time_note: Optional[str] = None  # e.g. "11:59 PM PST" (kept verbatim, never guessed)
    citation: Optional[Citation] = None
    confidence: float = 0.8
    verified: bool = False


class ExtractionResult(BaseModel):
    requirements: list[Requirement] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)


class Program(BaseModel):
    id: str
    name: str
    source_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class UserDocument(BaseModel):
    id: str = ""
    doc_type: DocType
    filename: str
    expiry: Optional[date] = None
    uploaded_at: datetime = Field(default_factory=utcnow)


class Task(BaseModel):
    requirement_id: str
    program_id: str
    description: str
    category: Category
    mandatory: bool
    state: TaskState
    matched_document_id: Optional[str] = None
    note: Optional[str] = None
    citation: Optional[Citation] = None
    verified: bool = False
    confidence: float = 0.8
