from datetime import date, timedelta

from backend.app.extract import RuleBasedExtractor, find_date
from backend.app.ingest import from_text
from backend.app.match import build_tasks
from backend.app.pipeline import run_pipeline
from backend.app.schema import (
    Category, Citation, DocType, ExtractionResult, Requirement, TaskState, UserDocument,
)
from backend.app.verify import verify_citation


# ---- dates
def test_find_date_formats():
    assert find_date("due January 5, 2027") == date(2027, 1, 5)
    assert find_date("due 5 January 2027") == date(2027, 1, 5)
    assert find_date("due 2027-01-05") == date(2027, 1, 5)


def test_find_date_never_guesses_year():
    assert find_date("Applications open on September 1") is None


# ---- verification
def test_verify_exact_and_page_correction():
    src = from_text("s", "intro\n\f Submit official transcripts from every university attended.")
    ok, page = verify_citation(Citation(source_id=src.id, page=1, quote="official transcripts from every university"), src)
    assert ok and page == 2


def test_verify_rejects_fabricated_quote():
    src = from_text("s", "Submit a resume.")
    ok, _ = verify_citation(Citation(source_id=src.id, page=1, quote="Submit a notarized birth certificate"), src)
    assert not ok


def test_verify_tolerates_small_ocr_noise():
    src = from_text("s", "Three letters of recommendation, at least two from academic referees are required")
    q = "Three letters of recomrnendation, at least two from academic referees are required"
    ok, _ = verify_citation(Citation(source_id=src.id, page=1, quote=q), src)
    assert ok


# ---- extraction + pipeline
SAMPLE = """- Round 1 deadline: January 5, 2027, 11:59 PM EST
- Updated resume or CV
- TOEFL or IELTS scores are required unless you completed your degree at an English-medium institution
- GRE scores are optional
"""


def test_rule_extractor_finds_items_and_conditions():
    src = from_text("s", SAMPLE)
    res, stats = run_pipeline(src, RuleBasedExtractor())
    assert [d.due for d in res.deadlines] == [date(2027, 1, 5)]
    assert res.deadlines[0].time_note.startswith("11:59 PM")
    by_type = {r.doc_type: r for r in res.requirements}
    assert by_type[DocType.english_test].conditions
    assert by_type[DocType.score_report].mandatory is False
    assert stats.unverified == 0


def test_pipeline_flags_hallucinated_items():
    class Liar:
        name = "liar"
        def extract(self, source):
            return ExtractionResult(requirements=[Requirement(
                category=Category.document, description="Notarized birth certificate", doc_type=DocType.other,
                citation=Citation(source_id=source.id, page=1, quote="Notarized birth certificate required"), confidence=0.9)])
    src = from_text("s", "Submit a resume.")
    res, stats = run_pipeline(src, Liar())
    assert stats.unverified == 1
    assert res.requirements[0].verified is False
    assert res.requirements[0].confidence < 0.9


# ---- matching
def _req(**kw):
    base = dict(id="r1", program_id="p", category=Category.document, description="x", verified=True, confidence=0.8)
    base.update(kw)
    return Requirement(**base)


def test_missing_vs_satisfied():
    reqs = [_req(id="a", doc_type=DocType.transcript), _req(id="b", doc_type=DocType.cv)]
    docs = [UserDocument(id="d1", doc_type=DocType.transcript, filename="t.pdf")]
    states = {t.requirement_id: t.state for t in build_tasks(reqs, docs)}
    assert states == {"a": TaskState.satisfied, "b": TaskState.missing}


def test_expired_document_is_flagged():
    docs = [UserDocument(id="d1", doc_type=DocType.english_test, filename="ielts.pdf", expiry=date.today() - timedelta(days=3))]
    t = build_tasks([_req(doc_type=DocType.english_test)], docs)[0]
    assert t.state == TaskState.expired


def test_unverified_requirement_is_never_settled_fact():
    docs = [UserDocument(id="d1", doc_type=DocType.cv, filename="cv.pdf")]
    t = build_tasks([_req(doc_type=DocType.cv, verified=False)], docs)[0]
    assert t.state == TaskState.needs_review


def test_conditional_missing_item_asks_for_review():
    t = build_tasks([_req(doc_type=DocType.passport, conditions=["international applicants only"])], [])[0]
    assert t.state == TaskState.needs_review
