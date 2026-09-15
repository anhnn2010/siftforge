"""Tests for semantic XHTML rendering."""

from pathlib import Path

from siftforge.ebook.renderers import EpubReadyXhtmlRenderer
from siftforge.ebook.semantic import (
    InlineRole,
    SemanticBookDocument,
    SemanticFigure,
    SemanticFootnote,
    SemanticHeading,
    SemanticInline,
    SemanticList,
    SemanticListItem,
    SemanticParagraph,
    SemanticVerse,
    SemanticVerseLine,
)
from siftforge.ebook.structure import HeadingRole, ListKind, SemanticMark


def _inline(text: str, **kwargs: object) -> SemanticInline:
    """Build one semantic inline fixture."""
    return SemanticInline(text=text, language="vi", **kwargs)


def test_renderer_does_not_emit_source_style_without_semantic_marks(
    tmp_path: Path,
) -> None:
    """Plain semantic text must stay plain in XHTML."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticParagraph(
                node_id="p1",
                content=(_inline("Nội dung"),),
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")

    assert "<em>" not in xhtml
    assert "<strong>" not in xhtml


def test_renderer_emits_explicit_emphasis(tmp_path: Path) -> None:
    """Explicit semantic marks should become corresponding XHTML markup."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticParagraph(
                node_id="p1",
                content=(
                    _inline(
                        "quan trọng",
                        marks=(SemanticMark.EMPHASIS,),
                    ),
                ),
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")

    assert "<em>quan trọng</em>" in xhtml


def test_renderer_preserves_ordered_list_start_without_marker_text(
    tmp_path: Path,
) -> None:
    """Ordered list ordinals should become structure rather than readable text."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticList(
                node_id="list-1",
                kind=ListKind.ORDERED,
                items=(
                    SemanticListItem(
                        node_id="item-10",
                        content=(_inline("Mục mười"),),
                        ordinal=10,
                    ),
                    SemanticListItem(
                        node_id="item-11",
                        content=(_inline("Mục mười một"),),
                        ordinal=11,
                    ),
                ),
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")

    assert '<ol id="list-1" start="10">' in xhtml
    assert ">10. Mục mười<" not in xhtml


def test_renderer_outputs_verse_lines_as_semantic_line_elements(
    tmp_path: Path,
) -> None:
    """Verse lines should remain explicit after XHTML rendering."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticVerse(
                node_id="verse-1",
                lines=(
                    SemanticVerseLine(
                        node_id="line-1",
                        content=(_inline("Dòng một"),),
                    ),
                    SemanticVerseLine(
                        node_id="line-2",
                        content=(_inline("Dòng hai"),),
                    ),
                ),
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")

    assert xhtml.count('class="verse-line"') == 2
    assert "Dòng một" in xhtml
    assert "Dòng hai" in xhtml


def test_renderer_links_footnote_reference_to_footnote_body(tmp_path: Path) -> None:
    """Footnote relations should become EPUB noteref links."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticParagraph(
                node_id="p1",
                content=(
                    _inline(
                        "1",
                        role=InlineRole.FOOTNOTE_REF,
                        target_id="note-1",
                        source_span_id="span-ref-1",
                    ),
                ),
            ),
            SemanticFootnote(
                node_id="note-1",
                content=(_inline("Nội dung chú thích"),),
                label="1",
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")

    assert 'epub:type="noteref"' in xhtml
    assert 'href="#note-1"' in xhtml
    assert 'epub:type="footnote"' in xhtml



def test_renderer_keeps_heading_footnote_reference_clickable(tmp_path: Path) -> None:
    """Body headings should retain clickable noteref markup after TOC cleanup."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticHeading(
                node_id="heading-1",
                content=(
                    _inline("Rối loạn phát triển"),
                    _inline(
                        "1",
                        role=InlineRole.FOOTNOTE_REF,
                        target_id="note-1",
                        source_span_id="span-ref-1",
                    ),
                ),
                role=HeadingRole.SECTION_TITLE,
                level=2,
            ),
            SemanticFootnote(
                node_id="note-1",
                content=(_inline("Nội dung chú thích"),),
                label="1",
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")

    assert '<h2 id="heading-1" class="role-section-title">' in xhtml
    assert 'epub:type="noteref"' in xhtml
    assert 'href="#note-1"' in xhtml


def test_renderer_outputs_footnote_label_once(tmp_path: Path) -> None:
    """A semantic footnote should render its structural label exactly once."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticFootnote(
                node_id="note-1",
                content=(_inline(" Hiện tượng được giải thích."),),
                label="1",
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")

    assert xhtml.count('class="footnote-label">1</span>') == 1
    assert ">1 1 Hiện tượng" not in xhtml

def test_renderer_copies_figure_assets(tmp_path: Path) -> None:
    """Referenced figure assets should be copied with stable relative paths."""
    assembly = tmp_path / "assembly"
    source = assembly / "assets" / "figures" / "figure.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png-bytes")
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticFigure(
                node_id="figure-1",
                asset_id="assets/figures/figure.png",
                caption=(_inline("Chú thích"),),
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=assembly,
        output_root=tmp_path / "out",
    )

    assert len(result.copied_assets) == 1
    assert (tmp_path / "out" / "assets" / "figures" / "figure.png").is_file()
    xhtml = result.content_path.read_text(encoding="utf-8")
    assert 'src="../assets/figures/figure.png"' in xhtml
    assert "<figcaption>" in xhtml


def test_renderer_keeps_subtitle_footnote_reference_clickable(tmp_path: Path) -> None:
    """Subtitle-like body labels should retain noteref semantics outside the TOC."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticHeading(
                node_id="subtitle-1",
                content=(
                    _inline("Thứ Sáu ngày 13"),
                    _inline(
                        "1",
                        role=InlineRole.FOOTNOTE_REF,
                        target_id="note-1",
                        source_span_id="span-ref-1",
                    ),
                ),
                role=HeadingRole.SUBTITLE,
                level=None,
            ),
            SemanticFootnote(
                node_id="note-1",
                content=(_inline("Nội dung chú thích"),),
                label="1",
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")

    assert 'class="heading-label role-subtitle"' in xhtml
    assert 'epub:type="noteref"' in xhtml
    assert 'href="#note-1"' in xhtml
