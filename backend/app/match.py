"""Compare what a program requires with what the student has, and report the gaps."""
from __future__ import annotations

from datetime import date

from .schema import Category, Requirement, Task, TaskState, UserDocument

LOW_CONFIDENCE = 0.6


def build_tasks(requirements: list[Requirement], documents: list[UserDocument], today: date | None = None) -> list[Task]:
    today = today or date.today()
    by_type: dict[str, list[UserDocument]] = {}
    for d in documents:
        by_type.setdefault(d.doc_type.value, []).append(d)

    tasks: list[Task] = []
    for r in requirements:
        state, matched, note = TaskState.missing, None, None
        docs = by_type.get(r.doc_type.value, []) if r.doc_type else []

        if r.doc_type and docs:
            fresh = [d for d in docs if not d.expiry or d.expiry >= today]
            if fresh:
                state, matched = TaskState.satisfied, fresh[0].id
            else:
                state, matched = TaskState.expired, docs[0].id
                note = f"Your {r.doc_type.value.replace('_', ' ')} expired on {docs[0].expiry}."
        elif r.doc_type is None:
            if r.category in (Category.eligibility, Category.other):
                state, note = TaskState.needs_review, "Check this against your own situation."
            elif r.category == Category.fee:
                note = "Paid at submission."
        elif r.conditions:
            state, note = TaskState.needs_review, "May not apply to you: " + "; ".join(r.conditions)

        if not r.verified or r.confidence < LOW_CONFIDENCE:
            # An unverified claim is never presented as settled fact.
            if state != TaskState.expired:
                state = TaskState.needs_review
            note = (note + " " if note else "") + "Could not confirm this against the source. Check the official page."

        tasks.append(Task(
            requirement_id=r.id, program_id=r.program_id, description=r.description,
            category=r.category, mandatory=r.mandatory, state=state,
            matched_document_id=matched, note=note, citation=r.citation,
            verified=r.verified, confidence=r.confidence,
        ))
    return tasks
