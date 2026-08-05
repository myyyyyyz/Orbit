import pytest

from app.knowledge_agent.run_state import (
    InvalidRunTransition,
    initial_status,
    transition_status,
)


def test_initial_status_requires_review_when_any_document_requires_it():
    assert initial_status([False, True]) == "review_required"
    assert initial_status([False, False]) == "planned"


def test_only_whitelisted_run_transition_is_allowed():
    assert transition_status("planned", "approved") == "approved"

    with pytest.raises(InvalidRunTransition, match="planned.*promoted"):
        transition_status("planned", "promoted")


@pytest.mark.parametrize(
    ("terminal_status", "target_status"),
    [
        ("rejected", "approved"),
        ("failed", "indexing"),
        ("rolled_back", "promoted"),
        ("invalidated", "approved"),
    ],
)
def test_terminal_statuses_cannot_transition(terminal_status, target_status):
    with pytest.raises(InvalidRunTransition):
        transition_status(terminal_status, target_status)

