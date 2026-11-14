import os
os.environ.setdefault("ORBIS_DB", ":memory:")
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest

from backend.app.schema import Category, DocType, ExtractionResult, Requirement
from eval.metrics import calibration_report, category_rows, score


def _req(desc, doc_type, **kw):
    base = dict(category=Category.document, description=desc, doc_type=doc_type, verified=True, confidence=0.9)
    base.update(kw)
    return Requirement(**base)


def test_score_records_misses_extras_and_calibration():
    labels = {
        "source": "x.txt",
        "deadlines": [],
        "requirements": [
            {"category": "document", "doc_type": "cv", "match": "resume", "mandatory": True},
            {"category": "document", "doc_type": "passport", "match": "passport", "mandatory": True},
        ],
    }
    result = ExtractionResult(requirements=[
        _req("Updated resume", DocType.cv),
        _req("Birth certificate", DocType.other, verified=False, confidence=0.4),
    ])
    s = score(result, labels)
    c = s.by_category["document"]
    assert (c.tp, c.fn, c.fp) == (1, 1, 1)
    assert sorted(f["kind"] for f in s.failures) == ["missed", "spurious"]
    assert s.calibration == [(0.9, True), (0.4, False)]


def test_wrong_flags_become_failures():
    labels = {"source": "x.txt", "deadlines": [], "requirements": [
        {"category": "document", "doc_type": "cv", "match": "resume", "mandatory": False, "has_condition": True}]}
    s = score(ExtractionResult(requirements=[_req("Resume", DocType.cv)]), labels)
    assert sorted(f["kind"] for f in s.failures) == ["wrong_condition", "wrong_mandatory"]


def test_calibration_ece():
    # says 0.9, right half the time: gap of 0.4 in a single bin
    rep = calibration_report([(0.9, True), (0.9, False)])
    assert rep["n"] == 2
    assert rep["ece"] == pytest.approx(0.4)
    assert calibration_report([])["ece"] is None


def test_category_rows_use_none_for_no_data():
    from collections import defaultdict
    from eval.metrics import Counts
    d = defaultdict(Counts)
    d["fee"].fp = 2  # extras only: recall is undefined, not zero
    row = category_rows(d)[0]
    assert row["recall"] is None and row["precision"] == 0.0


def test_eval_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import backend.app.main as m

    (tmp_path / "rules.json").write_text('{"extractor": "rules-v1"}', encoding="utf-8")
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")
    monkeypatch.setattr(m, "EVAL_DIR", tmp_path)
    body = TestClient(m.app).get("/api/eval").json()
    assert body["runs"] == {"rules": {"extractor": "rules-v1"}}
