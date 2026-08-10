from pathlib import Path

from app.knowledge_agent.executors.registry import build_executor_registry
from app.knowledge_agent.profiler import profile_file


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def test_markdown_executor_preserves_heading_path():
    source = FIXTURES / "clean-policy.md"
    profile = profile_file(source, root=FIXTURES)

    chunks = build_executor_registry()["markdown_hierarchical_v1"].execute(
        source, profile=profile, run_id="run-1"
    )

    assert chunks
    support = next(chunk for chunk in chunks if "Support levels" in chunk.text)
    assert support.heading_path == ("Starbridge Operations Policy", "Support levels")
    assert support.source_path == "clean-policy.md"
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
