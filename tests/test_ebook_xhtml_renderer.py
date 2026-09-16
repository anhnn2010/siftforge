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

    assert '<blockquote class="verse" id="verse-1">' in xhtml
    assert xhtml.count('class="verse-line"') == 2
    assert xhtml.count("<br />") == 1
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
    assert 'href="endnotes.xhtml#note-1"' in xhtml
    assert '<sup class="noteref">' in xhtml
    assert result.endnotes_path is not None
    endnotes = result.endnotes_path.read_text(encoding="utf-8")
    assert 'epub:type="endnote"' in endnotes



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
    assert 'href="endnotes.xhtml#note-1"' in xhtml


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
    assert result.endnotes_path is not None
    xhtml = result.endnotes_path.read_text(encoding="utf-8")

    assert xhtml.count('class="endnote-label">1</span>') == 1
    assert ">1 1 Hiện tượng" not in xhtml
    assert 'epub:type="endnote"' in xhtml

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

    assert '<p id="subtitle-1" class="heading-label role-subtitle">' in xhtml
    assert 'epub:type="noteref"' in xhtml
    assert 'href="endnotes.xhtml#note-1"' in xhtml
    assert '<sup class="noteref">' in xhtml

def test_renderer_keeps_adjacent_subtitle_footnotes_visibly_separate(
    tmp_path: Path,
) -> None:
    """Adjacent subtitle labels should remain separate block boxes in readers."""
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
            SemanticHeading(
                node_id="subtitle-2",
                content=(
                    _inline("Cá chép vượt vũ môn!"),
                    _inline(
                        "2",
                        role=InlineRole.FOOTNOTE_REF,
                        target_id="note-2",
                        source_span_id="span-ref-2",
                    ),
                ),
                role=HeadingRole.SUBTITLE,
                level=None,
            ),
            SemanticFootnote(
                node_id="note-1",
                content=(_inline("Chú thích một"),),
                label="1",
            ),
            SemanticFootnote(
                node_id="note-2",
                content=(_inline("Chú thích hai"),),
                label="2",
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")
    css = result.stylesheet_path.read_text(encoding="utf-8")

    first = '<p id="subtitle-1" class="heading-label role-subtitle">'
    second = '<p id="subtitle-2" class="heading-label role-subtitle">'
    assert first in xhtml
    assert second in xhtml
    assert xhtml.index(first) < xhtml.index(second)
    assert xhtml.count('<sup class="noteref">') == 2
    assert ".heading-label {\n  display: block;" in css
    assert ".noteref {\n  font-size: 0.75em;" in css



def test_renderer_splits_top_level_navigation_headings_into_spine_documents(
    tmp_path: Path,
) -> None:
    """Reader-facing navigable headings should start separate XHTML files."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticHeading(
                node_id="chapter-1",
                content=(_inline("Chương một"),),
                role=HeadingRole.CHAPTER_TITLE,
                level=1,
            ),
            SemanticParagraph(
                node_id="p1",
                content=(_inline("Nội dung một."),),
            ),
            SemanticHeading(
                node_id="chapter-2",
                content=(_inline("Chương hai"),),
                role=HeadingRole.CHAPTER_TITLE,
                level=1,
            ),
            SemanticParagraph(
                node_id="p2",
                content=(_inline("Nội dung hai."),),
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )

    assert [path.name for path in result.content_paths] == [
        "chapter-0001.xhtml",
        "chapter-0002.xhtml",
    ]
    first = result.content_paths[0].read_text(encoding="utf-8")
    second = result.content_paths[1].read_text(encoding="utf-8")
    assert 'id="chapter-1"' in first
    assert 'id="chapter-2"' not in first
    assert 'id="chapter-2"' in second


def test_renderer_uses_explicit_cross_document_footnote_links_and_backlinks(
    tmp_path: Path,
) -> None:
    """Noterefs and return links should name their target XHTML document."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticHeading(
                node_id="chapter-1",
                content=(
                    _inline("Chương một"),
                    _inline(
                        "1",
                        role=InlineRole.FOOTNOTE_REF,
                        target_id="note-1",
                        source_span_id="ref-1",
                    ),
                ),
                role=HeadingRole.CHAPTER_TITLE,
                level=1,
            ),
            SemanticHeading(
                node_id="chapter-2",
                content=(_inline("Chương hai"),),
                role=HeadingRole.CHAPTER_TITLE,
                level=1,
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
    first = result.content_paths[0].read_text(encoding="utf-8")
    second = result.content_paths[1].read_text(encoding="utf-8")
    assert result.endnotes_path is not None
    endnotes = result.endnotes_path.read_text(encoding="utf-8")

    assert 'href="endnotes.xhtml#note-1"' in first
    assert 'id="ref-1"' in first
    assert 'id="chapter-2"' in second
    assert 'href="chapter-0001.xhtml#ref-1"' in endnotes
    assert 'class="footnote-backlink" epub:type="backlink"' in endnotes
    assert '<li id="note-1" epub:type="endnote">' in endnotes
    assert '<p><span class="endnote-label">1</span>' in endnotes


def test_renderer_groups_title_and_subtitles_with_hgroup(tmp_path: Path) -> None:
    """A title plus supporting subtitles should form one semantic heading group."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticHeading(
                node_id="chapter-title",
                content=(_inline("Lời mở đầu"),),
                role=HeadingRole.CHAPTER_TITLE,
                level=1,
            ),
            SemanticHeading(
                node_id="subtitle-1",
                content=(_inline("Thứ Sáu ngày 13"),),
                role=HeadingRole.SUBTITLE,
                level=None,
            ),
            SemanticHeading(
                node_id="subtitle-2",
                content=(_inline("Cá chép vượt vũ môn!"),),
                role=HeadingRole.SUBTITLE,
                level=None,
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )
    xhtml = result.content_path.read_text(encoding="utf-8")

    assert '<hgroup class="heading-group">' in xhtml
    assert '<h1 id="chapter-title" class="role-chapter-title">' in xhtml
    assert '<p id="subtitle-1" class="heading-label role-subtitle">' in xhtml
    assert '<p id="subtitle-2" class="heading-label role-subtitle">' in xhtml


def test_renderer_avoids_fallback_and_semantic_section_filename_collision(
    tmp_path: Path,
) -> None:
    """Fallback body chunks must not collide with semantic section filenames."""
    document = SemanticBookDocument(
        title="Book",
        language="vi",
        author=None,
        nodes=(
            SemanticParagraph(
                node_id="opening",
                content=(_inline("Opening text."),),
            ),
            SemanticHeading(
                node_id="section-title",
                content=(_inline("Section title"),),
                role=HeadingRole.SECTION_TITLE,
                level=1,
            ),
            SemanticParagraph(
                node_id="section-body",
                content=(_inline("Section body."),),
            ),
        ),
    )

    result = EpubReadyXhtmlRenderer().render(
        document,
        asset_root=tmp_path,
        output_root=tmp_path / "out",
    )

    names = [path.name for path in result.content_paths]
    assert names == ["section-0001.xhtml", "section-0002.xhtml"]
    assert len(names) == len(set(names))
