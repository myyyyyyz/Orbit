"""KnowledgeRun lifecycle rules without persistence side effects."""

from __future__ import annotations

from collections.abc import Iterable

from .models import RunStatus


ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    "planned": frozenset({"approved", "rejected", "invalidated"}),
    "review_required": frozenset({"approved", "rejected", "invalidated"}),
    "approved": frozenset({"indexing", "invalidated"}),
    "indexing": frozenset({"evaluating", "failed"}),
    "evaluating": frozenset({"promoted", "failed"}),
    "promoted": frozenset({"rolled_back"}),
}


class InvalidRunTransition(ValueError):
    """Raised when a caller requests a lifecycle transition outside the whitelist."""


def initial_status(review_flags: Iterable[bool]) -> RunStatus:
    """Choose the persisted state for a newly generated folder plan."""

    return "review_required" if any(review_flags) else "planned"


def transition_status(current: RunStatus, target: RunStatus) -> RunStatus:
    """Validate one transition and return the accepted target status."""

    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidRunTransition(f"不允许从 {current} 转换为 {target}")
    return target

