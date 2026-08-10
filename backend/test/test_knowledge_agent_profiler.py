from pathlib import Path

import pytest

from app.knowledge_agent.profiler import profile_file, scan_folder


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def test_profiles_text_and_scanned_pdfs_differently():
    text_pdf = profile_file(FIXTURES / "text-report.pdf", root=FIXTURES)
    scanned_pdf = profile_file(FIXTURES / "scanned-notice.pdf", root=FIXTURES)

    assert text_pdf.file_type == "pdf"
    assert text_pdf.page_count >= 1
    assert text_pdf.text_extraction_ratio >= 0.1
    assert scanned_pdf.text_extraction_ratio < 0.1


def test_profiles_docx_and_xlsx_structure():
    docx = profile_file(FIXTURES / "clean-handbook.docx", root=FIXTURES)
    xlsx = profile_file(FIXTURES / "messy-operations.xlsx", root=FIXTURES)

    assert docx.heading_count >= 2
    assert docx.table_count >= 1
    assert docx.image_count >= 1
    assert xlsx.sheet_count >= 2
    assert xlsx.merged_cell_count >= 1
    assert xlsx.table_quality == "messy"


def test_scan_folder_is_deterministic_and_disallows_escape(tmp_path):
    profiles = scan_folder(FIXTURES)

    assert [profile.source_path for profile in profiles] == sorted(
        profile.source_path for profile in profiles
    )
    assert len(profiles) == 7

    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        profile_file(outside, root=FIXTURES)
