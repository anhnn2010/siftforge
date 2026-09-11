"""Tests for EPUB-ready assembly consumption and artifact generation."""

import json
from pathlib import Path

from siftforge.ebook.evidence import NormalizedRegion, SourceTypography
from siftforge.ebook.models import (
    CapsStyle,
    FontPosture,
    FontWeight,
    VerticalPosition,
)
from siftforge.ebook.pipeline import EbookEpubReadyService
from siftforge.ebook.structure import (
    BookDocument,
    DocumentTextSpan,
    FigureNode,
    ImageNode,
    ParagraphNode,
    book_document_to_dict,
)


def _typography() -> SourceTypography:
    """Return ordinary typography for persisted structure fixtures."""
    return SourceTypography(
        posture=FontPosture.ROMAN,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.BASELINE,
        caps_style=CapsStyle.NORMAL,
    )


def test_epub_ready_service_loads_assembly_and_writes_xhtml(tmp_path: Path) -> None:
    """Persisted BookDocument should become reusable semantic XHTML artifacts."""
    assembly = tmp_path / "assembly"
    (assembly / "structure").mkdir(parents=True)
    asset = assembly / "assets" / "figures" / "figure.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"png")
    document = BookDocument(
        nodes=(
            ParagraphNode(
                node_id="p1",
                spans=(
                    DocumentTextSpan(
                        span_id="s1",
                        text="Xin chào.",
                        language="vi",
                        source_typography=_typography(),
                    ),
                ),
            ),
            FigureNode(
                node_id="figure-1",
                image=ImageNode(
                    node_id="image-1",
                    source_region=NormalizedRegion(
                        x=0.1,
                        y=0.1,
                        width=0.5,
                        height=0.5,
                    ),
                    asset_id="assets/figures/figure.png",
                ),
            ),
        )
    )
    (assembly / "structure" / "book.json").write_text(
        json.dumps(book_document_to_dict(document), ensure_ascii=False),
        encoding="utf-8",
    )

    run = EbookEpubReadyService().build(
        assembly,
        tmp_path / "epub-ready",
        title="Sách thử",
        language="vi",
        author="Tác giả",
    )

    assert run.warnings == ()
    assert (run.output_dir / "semantic" / "document.json").is_file()
    assert (run.output_dir / "text" / "content.xhtml").is_file()
    assert (run.output_dir / "styles" / "book.css").is_file()
    assert (run.output_dir / "assets" / "figures" / "figure.png").is_file()
    manifest = json.loads(
        (run.output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["format"] == "epub-ready-xhtml"
    assert manifest["title"] == "Sách thử"
