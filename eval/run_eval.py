"""Run the benchmark:  python -m eval.run_eval [--extractor rules|llm]

Compares extractor output against hand-labelled ground truth in data/labels/ and writes
eval/results.json so every change to a prompt or model leaves a measurable trail.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from backend.app.extract import LLMExtractor, RuleBasedExtractor
from backend.app.ingest import from_text
from backend.app.pipeline import run_pipeline

from .metrics import Scores, score

ROOT = Path(__file__).resolve().parents[1]


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

    report = {
        "extractor": extractor.name,
        "documents": len(latencies),
        "requirements": {"precision": round(total.requirements.precision, 3), "recall": round(total.requirements.recall, 3), "f1": round(total.requirements.f1, 3)},
        "deadlines": {"precision": round(total.deadlines.precision, 3), "recall": round(total.deadlines.recall, 3), "f1": round(total.deadlines.f1, 3)},
        "mandatory_flag_accuracy": round(total.mandatory_correct / max(total.mandatory_total, 1), 3),
        "condition_detection_accuracy": round(total.condition_correct / max(total.condition_total, 1), 3),
        "citation_validity": round(total.citation_validity, 3),
        "hallucination_rate": round(total.hallucination_rate, 3),
        "median_latency_s": round(statistics.median(latencies), 3),
        "per_document": per_file,
    }
    (ROOT / "eval" / "results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
