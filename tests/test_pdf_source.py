"""Tests for PDF source discovery."""

from pathlib import Path

from pypdf import PdfWriter

from siftforge.extraction.sources import PDFSource


def _make_blank_fixture(path: Path) -> None:
    """Create a two-page blank PDF fixture."""
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.add_blank_page(width=320, height=400)
    with path.open("wb") as handle:
        writer.write(handle)


def test_pdf_source_analyzes_and_yields_independent_pages(tmp_path: Path) -> None:
    """PDFSource should classify and identify pages independently."""
    pdf_path = tmp_path / "fixture.pdf"
    _make_blank_fixture(pdf_path)

    source = PDFSource(pdf_path)
    analysis = source.analyze()
    pages = list(source.iter_items())

    assert analysis.page_count == 2
    assert analysis.blank_pages == 2
    assert analysis.image_only_pages == 0
    assert analysis.is_image_only is False

    assert len(pages) == 2
    assert pages[0].metadata["page_number"] == 1
    assert pages[1].metadata["page_number"] == 2
    assert pages[0].sha256 != pages[1].sha256
    assert pages[0].uri.endswith("#page=1")
    assert pages[1].uri.endswith("#page=2")
