"""Run the benchmark:  python -m eval.run_eval [--extractor rules|llm]

Compares extractor output against hand-labelled ground truth in data/labels/ and writes
  eval/results/<rules|llm>.json   one file per extractor, read by the dashboard (GET /api/eval)
  eval/results.json               the latest run, kept for convenience
so every change to a prompt or model leaves a measurable trail.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.app.extract import LLMExtractor, RuleBasedExtractor
from backend.app.ingest import from_text
from backend.app.pipeline import run_pipeline

from .metrics import Scores, calibration_report, category_rows, score

ROOT = Path(__file__).resolve().parents[1]

# The bar this project set for quoting accuracy figures (see Orbis context, section 9).
MIN_DOCUMENTS = 10
MIN_ITEMS = 150
MAX_FAILURES = 200  # keep results files small; failures_total holds the real count


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", choices=["rules", "llm"], default="rules")
    args = ap.parse_args()
    extractor = RuleBasedExtractor() if args.extractor == "rules" else LLMExtractor()

    total, latencies, per_file = Scores(), [], {}
    for label_path in sorted((ROOT / "data" / "labels").glob("*.json")):
        labels = json.loads(label_path.read_text())
        text = (ROOT / "data" / "sources" / labels["source"]).read_text(encoding="utf-8")
        source = from_text(labels["source"], text)
        t0 = time.perf_counter()
        result, _ = run_pipeline(source, extractor)
        latencies.append(time.perf_counter() - t0)
        s = score(result, labels)
        per_file[labels["source"]] = {"req_recall": round(s.requirements.recall, 3), "dl_recall": round(s.deadlines.recall, 3)}
        total.merge(s)

    labelled = total.requirements.tp + total.requirements.fn + total.deadlines.tp + total.deadlines.fn
    report = {
        "extractor": extractor.name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents": len(latencies),
        "dataset": {
            "documents": len(latencies),
            "labelled_items": labelled,
            "min_documents": MIN_DOCUMENTS,
            "min_items": MIN_ITEMS,
            "meets_minimum": len(latencies) >= MIN_DOCUMENTS and labelled >= MIN_ITEMS,
        },
        "requirements": {"precision": round(total.requirements.precision, 3), "recall": round(total.requirements.recall, 3), "f1": round(total.requirements.f1, 3)},
        "deadlines": {"precision": round(total.deadlines.precision, 3), "recall": round(total.deadlines.recall, 3), "f1": round(total.deadlines.f1, 3)},
        "mandatory_flag_accuracy": round(total.mandatory_correct / max(total.mandatory_total, 1), 3),
        "condition_detection_accuracy": round(total.condition_correct / max(total.condition_total, 1), 3),
        "citation_validity": round(total.citation_validity, 3),
        "hallucination_rate": round(total.hallucination_rate, 3),
        "median_latency_s": round(statistics.median(latencies), 3),
        "by_category": category_rows(total.by_category),
        "calibration": calibration_report(total.calibration),
        "failures_total": len(total.failures),
        "failures": total.failures[:MAX_FAILURES],
        "per_document": per_file,
    }

    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2)
    (out_dir / f"{args.extractor}.json").write_text(payload, encoding="utf-8")
    (ROOT / "eval" / "results.json").write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
