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
    DocumentRelationship,
    DocumentTextSpan,
    FigureNode,
    FootnoteNode,
    ImageNode,
    ParagraphNode,
    RelationshipKind,
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
    assert manifest["content"] == "text/content.xhtml"
    assert manifest["contents"] == ["text/content.xhtml"]


def test_epub_ready_service_projects_footnotes_into_endnotes(
    tmp_path: Path,
) -> None:
    """Source footnotes should persist as dedicated semantic EPUB endnotes."""
    assembly = tmp_path / "assembly"
    (assembly / "structure").mkdir(parents=True)
    document = BookDocument(
        nodes=(
            ParagraphNode(
                node_id="p1",
                spans=(
                    DocumentTextSpan(
                        span_id="s1",
                        text="Nội dung",
                        language="vi",
                        source_typography=_typography(),
                    ),
                    DocumentTextSpan(
                        span_id="ref-1",
                        text="1",
                        language=None,
                        source_typography=_typography(),
                    ),
                ),
            ),
            FootnoteNode(
                node_id="note-1",
                spans=(
                    DocumentTextSpan(
                        span_id="note-span-1",
                        text="Chú thích.",
                        language="vi",
                        source_typography=_typography(),
                    ),
                ),
                label="1",
            ),
        ),
        relationships=(
            DocumentRelationship(
                relationship_id="rel-1",
                kind=RelationshipKind.FOOTNOTE_REF,
                source_id="ref-1",
                target_id="note-1",
                confidence=1.0,
            ),
        ),
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
    )

    assert run.render.endnotes_path is not None
    assert run.render.endnotes_path.name == "endnotes.xhtml"
    body = run.render.content_path.read_text(encoding="utf-8")
    endnotes = run.render.endnotes_path.read_text(encoding="utf-8")
    assert 'href="endnotes.xhtml#note-1"' in body
    assert 'epub:type="backlink"' in endnotes
    manifest = json.loads(
        (run.output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["endnotes"] == "text/endnotes.xhtml"
    assert manifest["contents"][-1] == "text/endnotes.xhtml"
