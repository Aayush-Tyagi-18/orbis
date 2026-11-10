"""Scoring for extraction quality. Matching is one-to-one and deliberately strict."""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.schema import Deadline, ExtractionResult, Requirement


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

    def merge(self, o: "Scores") -> None:
        self.requirements += o.requirements
        self.deadlines += o.deadlines
        for k in ("mandatory_correct", "mandatory_total", "condition_correct", "condition_total", "items", "unverified"):
            setattr(self, k, getattr(self, k) + getattr(o, k))

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


def score(result: ExtractionResult, labels: dict) -> Scores:
    s = Scores()
    used: set[int] = set()
    for lab in labels["requirements"]:
        hit = next((i for i, r in enumerate(result.requirements) if i not in used and _req_matches(lab, r)), None)
        if hit is None:
            s.requirements.fn += 1
            continue
        used.add(hit)
        s.requirements.tp += 1
        r = result.requirements[hit]
        s.mandatory_total += 1
        s.mandatory_correct += int(r.mandatory == lab.get("mandatory", True))
        s.condition_total += 1
        s.condition_correct += int(bool(r.conditions) == lab.get("has_condition", False))
    s.requirements.fp += len(result.requirements) - len(used)

    dused: set[int] = set()
    for lab in labels["deadlines"]:
        def ok(d: Deadline) -> bool:
            return d.due.isoformat() == lab["due"] and lab.get("label_contains", "").lower() in d.label.lower()
        hit = next((i for i, d in enumerate(result.deadlines) if i not in dused and ok(d)), None)
        if hit is None:
            s.deadlines.fn += 1
        else:
            dused.add(hit); s.deadlines.tp += 1
    s.deadlines.fp += len(result.deadlines) - len(dused)

    items = [*result.requirements, *result.deadlines]
    s.items = len(items)
    s.unverified = sum(1 for i in items if not i.verified)
    return s
