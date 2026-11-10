"""Extract, then verify. Nothing reaches the user as fact without passing the verify step."""
from __future__ import annotations

from dataclasses import dataclass

from .extract import Extractor
from .schema import ExtractionResult, Source
from .verify import verify_citation

UNVERIFIED_PENALTY = 0.5


@dataclass
class PipelineStats:
    requirements: int = 0
    deadlines: int = 0
    unverified: int = 0


def run_pipeline(source: Source, extractor: Extractor) -> tuple[ExtractionResult, PipelineStats]:
    result = extractor.extract(source)
    stats = PipelineStats(requirements=len(result.requirements), deadlines=len(result.deadlines))
    for item in [*result.requirements, *result.deadlines]:
        ok, page = verify_citation(item.citation, source)
        item.verified = ok
        if ok and item.citation:
            item.citation.page = page
        else:
            item.confidence = round(item.confidence * UNVERIFIED_PENALTY, 3)
            stats.unverified += 1
    return result, stats
