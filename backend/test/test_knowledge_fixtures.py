from pathlib import Path


EXPECTED_FIXTURES = {
    "clean-policy.md",
    "clean-handbook.docx",
    "messy-notes.docx",
    "text-report.pdf",
    "scanned-notice.pdf",
    "clean-projects.xlsx",
    "messy-operations.xlsx",
}


def test_fixture_inventory_is_complete():
    fixtures_dir = Path(__file__).parents[2] / "knowledge" / "fixtures"
    assert {path.name for path in fixtures_dir.iterdir() if path.is_file()} == EXPECTED_FIXTURES
