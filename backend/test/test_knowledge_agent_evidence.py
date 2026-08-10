from pathlib import Path

from app.knowledge_agent.evidence import read_evidence


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def test_read_evidence_supports_every_fixture_type():
    samples = {
        path.name: read_evidence(path, max_chars=6000)
        for path in FIXTURES.iterdir()
        if path.is_file()
    }

    assert "Support levels" in samples["clean-policy.md"]
    assert "Starbridge Delivery Handbook" in samples["clean-handbook.docx"]
    assert "ORB-2407" in samples["text-report.pdf"]
    assert "Projects" in samples["clean-projects.xlsx"]
    assert samples["scanned-notice.pdf"] == ""


def test_read_evidence_never_exceeds_limit():
    sample = read_evidence(FIXTURES / "clean-policy.md", max_chars=40)

    assert len(sample) <= 40
