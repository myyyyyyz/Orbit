import json
from pathlib import Path

from app.knowledge_agent.catalog import STRATEGY_CATALOG


ROOT = Path(__file__).resolve().parents[2]


def test_expected_strategy_labels_cover_every_fixture():
    label_path = ROOT / "knowledge" / "evals" / "expected-strategies.jsonl"
    labels = [
        json.loads(line)
        for line in label_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    fixture_names = {
        path.name
        for path in (ROOT / "knowledge" / "fixtures").iterdir()
        if path.is_file()
    }

    assert {label["source"] for label in labels} == fixture_names
    assert all(
        label["expected_strategy_id"] in STRATEGY_CATALOG for label in labels
    )
    assert all(isinstance(label["requires_review"], bool) for label in labels)
    assert all(label["rationale"].strip() for label in labels)
    assert all(label["expected_signals"] for label in labels)
