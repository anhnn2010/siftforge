"""Tests for deterministic first-pass ebook structural analysis."""

from siftforge.ebook.evidence import (
    BlockRoleHint,
    HeadingRoleHint,
    MarkerEvidence,
    MarkerKind,
    NormalizedRegion,
    PageBlockEvidence,
    PageExtraction,
    SourceTypography,
    TextSpanEvidence,
)
from siftforge.ebook.models import (
    CapsStyle,
    FontPosture,
    FontWeight,
    PageKind,
    VerticalPosition,
)
from siftforge.ebook.structure import (
    AttributionNode,
    BookStructuralAnalyzer,
    ContainerCandidateKind,
    FigureNode,
    FootnoteNode,
    InsetRole,
    ListKind,
    ListNode,
    ParagraphNode,
    QuotationNode,
    RelationshipKind,
    VerseNode,
)
from siftforge.extraction.models import SourceRef


def _typography(
    posture: FontPosture = FontPosture.ROMAN,
) -> SourceTypography:
    """Return ordinary source typography for analyzer fixtures."""
    return SourceTypography(
        posture=posture,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.BASELINE,
        caps_style=CapsStyle.NORMAL,
    )


def _block(
    page_id: str,
    index: int,
    role: BlockRoleHint,
    text: str,
    *,
    language: str | None = "vi",
    marker: MarkerEvidence | None = None,
    semantic_line_break_after: bool = False,
    heading_role_hint: HeadingRoleHint = HeadingRoleHint.UNKNOWN,
    region: NormalizedRegion | None = None,
) -> PageBlockEvidence:
    """Build one deterministic page-evidence block for tests."""
    block_id = f"{page_id}:block:{index:04d}"
    span = TextSpanEvidence(
        span_id=f"{block_id}:span:0001",
        text=text,
        language=language,
        source_typography=_typography(),
        semantic_line_break_after=semantic_line_break_after,
    )
    return PageBlockEvidence(
        block_id=block_id,
        sequence_index=index - 1,
        role_hint=role,
        spans=(span,),
        dominant_language=language,
        heading_role_hint=heading_role_hint,
        marker=marker,
        region=region,
    )


def _page(
    page_number: int,
    *blocks: PageBlockEvidence,
) -> PageExtraction:
    """Build one physical page with stable source provenance."""
    page_id = f"page-{page_number:04d}"
    return PageExtraction(
        page_id=page_id,
        source=SourceRef(
            source_id=page_id,
            uri=f"book.pdf#page={page_number}",
            media_type="application/pdf",
        ),
        page_kind_hint=PageKind.TEXT,
        dominant_language="vi",
        printed_page_number=str(page_number),
        blocks=blocks,
    )


def test_running_footer_is_removed_normalized_and_marked_repeated() -> None:
    """Repeated footer text should be excluded and normalized across pages."""
    page_402 = _page(
        402,
        _block("page-0402", 1, BlockRoleHint.PARAGRAPH, "Nội dung A."),
        _block(
            "page-0402",
            2,
            BlockRoleHint.PAGE_FOOTER,
            "402 18 NĂM KIM CƯƠNG",
        ),
        _block("page-0402", 3, BlockRoleHint.PAGE_NUMBER, "402", language=None),
    )
    page_403 = _page(
        403,
        _block("page-0403", 1, BlockRoleHint.PARAGRAPH, "Nội dung B."),
        _block(
            "page-0403",
            2,
            BlockRoleHint.PAGE_FOOTER,
            "18 NĂM KIM CƯƠNG 403",
        ),
        _block("page-0403", 3, BlockRoleHint.PAGE_NUMBER, "403", language=None),
    )

    result = BookStructuralAnalyzer().analyze((page_402, page_403))

    assert len(result.document.nodes) == 2
    footers = [
        item
        for item in result.running_furniture
        if item.role_hint is BlockRoleHint.PAGE_FOOTER
    ]
    assert [item.normalized_text for item in footers] == [
        "18 NĂM KIM CƯƠNG",
        "18 NĂM KIM CƯƠNG",
    ]
    assert all(item.repeated for item in footers)


def test_numeric_list_items_group_across_physical_page_boundary() -> None:
    """Explicit sequential numeric items should form one cross-page list."""
    page_377 = _page(
        377,
        _block(
            "page-0377",
            1,
            BlockRoleHint.LIST_ITEM,
            "Mục chín.",
            marker=MarkerEvidence(
                kind=MarkerKind.NUMERIC,
                raw_text="9.",
                ordinal=9,
            ),
        ),
        _block("page-0377", 2, BlockRoleHint.PAGE_NUMBER, "377", language=None),
    )
    page_378 = _page(
        378,
        _block(
            "page-0378",
            1,
            BlockRoleHint.LIST_ITEM,
            "Biết nói không lúc cần.",
            marker=MarkerEvidence(
                kind=MarkerKind.NUMERIC,
                raw_text="10.",
                ordinal=10,
            ),
        ),
        _block(
            "page-0378",
            2,
            BlockRoleHint.LIST_ITEM,
            "Đòi hỏi bản thân cao hơn.",
            marker=MarkerEvidence(
                kind=MarkerKind.NUMERIC,
                raw_text="11.",
                ordinal=11,
            ),
        ),
    )

    result = BookStructuralAnalyzer().analyze((page_377, page_378))

    assert len(result.document.nodes) == 1
    list_node = result.document.nodes[0]
    assert isinstance(list_node, ListNode)
    assert list_node.kind is ListKind.ORDERED
    assert [item.ordinal for item in list_node.items] == [9, 10, 11]
    assert [item.spans[0].text for item in list_node.items] == [
        "Mục chín.",
        "Biết nói không lúc cần.",
        "Đòi hỏi bản thân cao hơn.",
    ]


def test_nonsequential_ordered_items_start_a_new_list() -> None:
    """Conflicting explicit ordinals should not be silently grouped."""
    page = _page(
        378,
        _block(
            "page-0378",
            1,
            BlockRoleHint.LIST_ITEM,
            "Mục mười.",
            marker=MarkerEvidence(
                kind=MarkerKind.NUMERIC,
                raw_text="10.",
                ordinal=10,
            ),
        ),
        _block(
            "page-0378",
            2,
            BlockRoleHint.LIST_ITEM,
            "Mục mười hai.",
            marker=MarkerEvidence(
                kind=MarkerKind.NUMERIC,
                raw_text="12.",
                ordinal=12,
            ),
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 2
    assert all(isinstance(node, ListNode) for node in result.document.nodes)


def test_dash_dialogue_remains_paragraphs_when_not_marked_as_list() -> None:
    """Dialogue dashes must not be reinterpreted as list markers by shape."""
    page = _page(
        397,
        _block(
            "page-0397",
            1,
            BlockRoleHint.PARAGRAPH,
            "– Cô còn nhớ em không?",
        ),
        _block(
            "page-0397",
            2,
            BlockRoleHint.PARAGRAPH,
            "– Mi tên Nga!",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 2
    assert all(isinstance(node, ParagraphNode) for node in result.document.nodes)


def test_graphic_marked_dialogue_remains_paragraphs() -> None:
    """Visual heart markers alone must not force semantic list grouping."""
    marker = MarkerEvidence(kind=MarkerKind.GRAPHIC)
    page = _page(
        412,
        _block(
            "page-0412",
            1,
            BlockRoleHint.PARAGRAPH,
            "Mẹ quên mật khẩu rồi.",
            marker=marker,
        ),
        _block(
            "page-0412",
            2,
            BlockRoleHint.PARAGRAPH,
            "Con không thích mẹ đọc thư.",
            marker=marker,
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 2
    assert all(isinstance(node, ParagraphNode) for node in result.document.nodes)


def test_cross_page_paragraph_continuation_is_retained_as_candidate() -> None:
    """Strong cross-page prose evidence should create a scored relation only."""
    first = _page(
        398,
        _block(
            "page-0398",
            1,
            BlockRoleHint.PARAGRAPH,
            (
                "Trong thực tế tôi nhận ra rằng hầu như "
                "mọi người cha đều"
            ),
        ),
    )
    second = _page(
        399,
        _block(
            "page-0399",
            1,
            BlockRoleHint.PARAGRAPH,
            "mong muốn những điều tốt đẹp cho con.",
        ),
    )

    result = BookStructuralAnalyzer().analyze((first, second))

    assert len(result.continuation_candidates) == 1
    candidate = result.continuation_candidates[0]
    assert candidate.kind is RelationshipKind.CONTINUES_TO
    assert candidate.confidence == 0.99
    assert "previous page ends without terminal punctuation" in candidate.reasons
    assert "next page starts with a lowercase letter" in candidate.reasons
    assert len(result.document.nodes) == 2


def test_terminal_sentence_does_not_create_continuation_candidate() -> None:
    """Complete page-ending prose should not be joined merely by adjacency."""
    first = _page(
        397,
        _block(
            "page-0397",
            1,
            BlockRoleHint.PARAGRAPH,
            "Ô hô hô… hứt hứt…",
        ),
    )
    second = _page(
        398,
        _block(
            "page-0398",
            1,
            BlockRoleHint.PARAGRAPH,
            "Tuần vừa rồi con chị về tố cáo:",
        ),
    )

    result = BookStructuralAnalyzer().analyze((first, second))

    assert result.continuation_candidates == ()


def test_list_item_to_paragraph_can_be_a_continuation_candidate() -> None:
    """A list item may continue as an unmarked paragraph on the next page."""
    first = _page(
        105,
        _block(
            "page-0105",
            1,
            BlockRoleHint.LIST_ITEM,
            "Sử dụng một loại bột giúp dinh dưỡng thẩm thấu qua",
            marker=MarkerEvidence(kind=MarkerKind.GRAPHIC),
        ),
    )
    second = _page(
        106,
        _block(
            "page-0106",
            1,
            BlockRoleHint.PARAGRAPH,
            "niêm mạc và hỗ trợ trẻ hồi phục.",
        ),
    )

    result = BookStructuralAnalyzer().analyze((first, second))

    assert len(result.continuation_candidates) == 1
    candidate = result.continuation_candidates[0]
    assert ":node:list-item" in candidate.source_id
    assert ":node:paragraph" in candidate.target_id


def test_verse_semantic_breaks_become_logical_lines() -> None:
    """Verse evidence should preserve semantic lines in the logical model."""
    page_id = "page-0152"
    block_id = f"{page_id}:block:0001"
    block = PageBlockEvidence(
        block_id=block_id,
        sequence_index=0,
        role_hint=BlockRoleHint.VERSE,
        spans=(
            TextSpanEvidence(
                span_id=f"{block_id}:span:0001",
                text="Có vàng, vàng chẳng hay phô",
                language="vi",
                source_typography=_typography(FontPosture.ITALIC),
                semantic_line_break_after=True,
            ),
            TextSpanEvidence(
                span_id=f"{block_id}:span:0002",
                text="Có con, con nói trầm trồ mẹ nghe.",
                language="vi",
                source_typography=_typography(FontPosture.ITALIC),
                semantic_line_break_after=False,
            ),
        ),
        dominant_language="vi",
    )
    page = _page(152, block)

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 1
    verse = result.document.nodes[0]
    assert isinstance(verse, VerseNode)
    assert [line.spans[0].text for line in verse.lines] == [
        "Có vàng, vàng chẳng hay phô",
        "Có con, con nói trầm trồ mẹ nghe.",
    ]


def test_unsupported_image_evidence_is_reported_instead_of_dropped() -> None:
    """Unsupported evidence should remain visible until figure resolution exists."""
    page = _page(
        116,
        _block("page-0116", 1, BlockRoleHint.IMAGE, "", language=None),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert result.document.nodes == ()
    assert [block.block_id for block in result.unresolved_blocks] == [
        "page-0116:block:0001"
    ]


def test_analysis_is_deterministic_for_same_page_evidence() -> None:
    """Repeated analysis of identical evidence should produce equal results."""
    page = _page(
        384,
        _block(
            "page-0384",
            1,
            BlockRoleHint.LIST_ITEM,
            "Cơ thể của Minh Khuê bé nhỏ.",
            marker=MarkerEvidence(kind=MarkerKind.DASH, raw_text="–"),
        ),
        _block(
            "page-0384",
            2,
            BlockRoleHint.LIST_ITEM,
            "Minh Khuê có tố chất khác.",
            marker=MarkerEvidence(kind=MarkerKind.DASH, raw_text="–"),
        ),
    )
    analyzer = BookStructuralAnalyzer()

    first = analyzer.analyze((page,))
    second = analyzer.analyze((page,))

    assert first == second


def test_duplicate_page_ids_are_rejected() -> None:
    """Duplicate physical page identities should fail deterministically."""
    page = _page(
        18,
        _block("page-0018", 1, BlockRoleHint.PARAGRAPH, "Nội dung."),
    )

    try:
        BookStructuralAnalyzer().analyze((page, page))
    except ValueError as exc:
        assert str(exc) == "page_id values must be unique within one analysis"
    else:
        raise AssertionError("expected duplicate page_id validation to fail")


def test_list_grouping_does_not_skip_a_physical_page() -> None:
    """A missing-body page must break list grouping across physical pages."""
    page_1 = _page(
        1,
        _block(
            "page-0001",
            1,
            BlockRoleHint.LIST_ITEM,
            "Mục một.",
            marker=MarkerEvidence(
                kind=MarkerKind.NUMERIC,
                raw_text="1.",
                ordinal=1,
            ),
        ),
    )
    page_2 = _page(
        2,
        _block("page-0002", 1, BlockRoleHint.PAGE_NUMBER, "2", language=None),
    )
    page_3 = _page(
        3,
        _block(
            "page-0003",
            1,
            BlockRoleHint.LIST_ITEM,
            "Mục hai.",
            marker=MarkerEvidence(
                kind=MarkerKind.NUMERIC,
                raw_text="2.",
                ordinal=2,
            ),
        ),
    )

    result = BookStructuralAnalyzer().analyze((page_1, page_2, page_3))

    assert len(result.document.nodes) == 2
    assert all(isinstance(node, ListNode) for node in result.document.nodes)


def test_logical_span_provenance_points_to_only_its_source_span() -> None:
    """Each logical span should trace to its own page-evidence span identity."""
    page_id = "page-0018"
    block_id = f"{page_id}:block:0001"
    block = PageBlockEvidence(
        block_id=block_id,
        sequence_index=0,
        role_hint=BlockRoleHint.PARAGRAPH,
        spans=(
            TextSpanEvidence(
                span_id=f"{block_id}:span:0001",
                text="Nguyên văn bản tiếng Anh:",
                language="vi",
                source_typography=_typography(),
            ),
            TextSpanEvidence(
                span_id=f"{block_id}:span:0002",
                text="December 13th, 2014",
                language="en",
                source_typography=_typography(FontPosture.ITALIC),
            ),
        ),
        dominant_language="vi",
    )
    result = BookStructuralAnalyzer().analyze((_page(18, block),))
    paragraph = result.document.nodes[0]

    assert isinstance(paragraph, ParagraphNode)
    assert paragraph.spans[0].provenance[0].span_ids == (
        f"{block_id}:span:0001",
    )
    assert paragraph.spans[1].provenance[0].span_ids == (
        f"{block_id}:span:0002",
    )


def test_same_page_quote_blocks_group_into_one_quotation() -> None:
    """Adjacent quote blocks on one page should share one quotation container."""
    page = _page(
        87,
        _block(
            "page-0087",
            1,
            BlockRoleHint.QUOTE,
            "“Đoạn trích thứ nhất.",
        ),
        _block(
            "page-0087",
            2,
            BlockRoleHint.QUOTE,
            "Đoạn trích thứ hai.”",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 1
    quotation = result.document.nodes[0]
    assert isinstance(quotation, QuotationNode)
    assert len(quotation.children) == 2
    assert [child.spans[0].text for child in quotation.children] == [
        "“Đoạn trích thứ nhất.",
        "Đoạn trích thứ hai.”",
    ]


def test_cross_page_quote_blocks_remain_candidates_until_resolved() -> None:
    """Physical-page quote boundaries should not be merged automatically."""
    first = _page(
        87,
        _block(
            "page-0087",
            1,
            BlockRoleHint.QUOTE,
            "“Đoạn trích bắt đầu và còn tiếp",
        ),
    )
    second = _page(
        88,
        _block(
            "page-0088",
            1,
            BlockRoleHint.QUOTE,
            "phần tiếp theo của cùng đoạn trích.”",
        ),
    )

    result = BookStructuralAnalyzer().analyze((first, second))

    assert len(result.document.nodes) == 2
    assert all(isinstance(node, QuotationNode) for node in result.document.nodes)
    assert len(result.continuation_candidates) == 1
    assert result.continuation_candidates[0].confidence == 0.99


def test_consecutive_same_page_verse_blocks_group_into_one_verse() -> None:
    """Explicit adjacent verse blocks on one page should share a container."""
    page = _page(
        68,
        _block(
            "page-0068",
            1,
            BlockRoleHint.VERSE,
            "Mẹ cần con để trưởng thành,",
        ),
        _block(
            "page-0068",
            2,
            BlockRoleHint.VERSE,
            "Con là sức mạnh trong vành nôi ngoan.",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 1
    verse = result.document.nodes[0]
    assert isinstance(verse, VerseNode)
    assert [line.spans[0].text for line in verse.lines] == [
        "Mẹ cần con để trưởng thành,",
        "Con là sức mạnh trong vành nôi ngoan.",
    ]


def test_image_region_and_adjacent_caption_resolve_to_figure() -> None:
    """An image region followed by a caption should become one figure."""
    region = NormalizedRegion(x=0.125, y=0.08, width=0.805, height=0.338)
    page = _page(
        116,
        _block(
            "page-0116",
            1,
            BlockRoleHint.IMAGE,
            "",
            language=None,
            region=region,
        ),
        _block(
            "page-0116",
            2,
            BlockRoleHint.CAPTION,
            "Kỷ niệm Minh Khuê tròn 2 tuổi (1/6/1999)",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 1
    figure = result.document.nodes[0]
    assert isinstance(figure, FigureNode)
    assert figure.image.source_region == region
    assert figure.image.asset_id is None
    assert figure.caption is not None
    assert figure.caption.spans[0].text == (
        "Kỷ niệm Minh Khuê tròn 2 tuổi (1/6/1999)"
    )
    assert result.unresolved_blocks == ()


def test_multiple_image_caption_pairs_remain_separate_figures() -> None:
    """Page-116-like evidence should create two independent figures."""
    first_region = NormalizedRegion(x=0.1, y=0.1, width=0.8, height=0.3)
    second_region = NormalizedRegion(x=0.1, y=0.5, width=0.8, height=0.3)
    page = _page(
        116,
        _block(
            "page-0116",
            1,
            BlockRoleHint.IMAGE,
            "",
            language=None,
            region=first_region,
        ),
        _block(
            "page-0116",
            2,
            BlockRoleHint.CAPTION,
            "Ảnh thứ nhất",
        ),
        _block(
            "page-0116",
            3,
            BlockRoleHint.IMAGE,
            "",
            language=None,
            region=second_region,
        ),
        _block(
            "page-0116",
            4,
            BlockRoleHint.CAPTION,
            "Ảnh thứ hai",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 2
    assert all(isinstance(node, FigureNode) for node in result.document.nodes)
    first, second = result.document.nodes
    assert isinstance(first, FigureNode)
    assert isinstance(second, FigureNode)
    assert first.caption is not None
    assert second.caption is not None
    assert first.caption.spans[0].text == "Ảnh thứ nhất"
    assert second.caption.spans[0].text == "Ảnh thứ hai"


def test_image_without_region_keeps_image_and_caption_unresolved() -> None:
    """Figure resolution must not invent crop geometry absent from evidence."""
    page = _page(
        116,
        _block(
            "page-0116",
            1,
            BlockRoleHint.IMAGE,
            "",
            language=None,
        ),
        _block(
            "page-0116",
            2,
            BlockRoleHint.CAPTION,
            "Một chú thích",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert result.document.nodes == ()
    assert [block.role_hint for block in result.unresolved_blocks] == [
        BlockRoleHint.IMAGE,
        BlockRoleHint.CAPTION,
    ]


def test_genre_label_records_inset_opening_candidate_without_swallowing_body() -> None:
    """Genre-label evidence should surface an inset candidate, not guess extent."""
    page = _page(
        348,
        _block(
            "page-0348",
            1,
            BlockRoleHint.HEADING,
            "Đừng so sánh",
        ),
        _block(
            "page-0348",
            2,
            BlockRoleHint.HEADING,
            "(Truyện ngụ ngôn)",
            heading_role_hint=HeadingRoleHint.GENRE_LABEL,
        ),
        _block(
            "page-0348",
            3,
            BlockRoleHint.PARAGRAPH,
            "Một chú cún bắt đầu câu chuyện.",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 3
    assert len(result.container_candidates) == 1
    candidate = result.container_candidates[0]
    assert candidate.kind is ContainerCandidateKind.INSET
    assert candidate.role is InsetRole.UNKNOWN
    assert candidate.confidence == 0.90
    assert candidate.source_block_ids == (
        "page-0348:block:0001",
        "page-0348:block:0002",
    )
    assert "title-like heading" in candidate.reasons[1]


def test_unstyled_embedded_excerpt_is_not_guessed_from_language_specific_text() -> None:
    """Page-397-like prose cues should remain prose without explicit evidence."""
    page = _page(
        397,
        _block(
            "page-0397",
            1,
            BlockRoleHint.PARAGRAPH,
            "Tôi xin trích câu chuyện của bạn Nguyễn Thanh Nga:",
        ),
        _block(
            "page-0397",
            2,
            BlockRoleHint.PARAGRAPH,
            "Thời cắp sách đến trường...",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 2
    assert result.container_candidates == ()


def test_image_region_without_caption_still_resolves_to_figure() -> None:
    """A source-backed image may form a figure without a caption."""
    region = NormalizedRegion(x=0.1, y=0.2, width=0.7, height=0.5)
    page = _page(
        28,
        _block(
            "page-0028",
            1,
            BlockRoleHint.IMAGE,
            "",
            language=None,
            region=region,
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 1
    figure = result.document.nodes[0]
    assert isinstance(figure, FigureNode)
    assert figure.caption is None
    assert figure.image.source_region == region


def test_orphan_caption_stays_unresolved() -> None:
    """A caption without an adjacent image must not attach to distant content."""
    page = _page(
        28,
        _block(
            "page-0028",
            1,
            BlockRoleHint.CAPTION,
            "Chú thích không có ảnh tương ứng.",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert result.document.nodes == ()
    assert result.unresolved_blocks == (page.blocks[0],)



def test_superscript_reference_links_to_unique_same_page_footnote() -> None:
    """A matching superscript label should link to one same-page footnote."""
    page_id = "page-0118"
    body_id = f"{page_id}:block:0001"
    footnote_id = f"{page_id}:block:0002"
    superscript = SourceTypography(
        posture=FontPosture.ROMAN,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.SUPERSCRIPT,
        caps_style=CapsStyle.NORMAL,
    )
    body = PageBlockEvidence(
        block_id=body_id,
        sequence_index=0,
        role_hint=BlockRoleHint.HEADING,
        spans=(
            TextSpanEvidence(
                span_id=f"{body_id}:span:0001",
                text="Rối loạn phát triển",
                language="vi",
                source_typography=_typography(),
            ),
            TextSpanEvidence(
                span_id=f"{body_id}:span:0002",
                text="1",
                language=None,
                source_typography=superscript,
            ),
        ),
        dominant_language="vi",
    )
    footnote = PageBlockEvidence(
        block_id=footnote_id,
        sequence_index=1,
        role_hint=BlockRoleHint.FOOTNOTE,
        spans=(
            TextSpanEvidence(
                span_id=f"{footnote_id}:span:0001",
                text="1",
                language=None,
                source_typography=superscript,
            ),
            TextSpanEvidence(
                span_id=f"{footnote_id}:span:0002",
                text="Nội dung chú thích.",
                language="vi",
                source_typography=_typography(),
            ),
        ),
        dominant_language="vi",
    )

    result = BookStructuralAnalyzer().analyze((_page(118, body, footnote),))

    footnote_node = result.document.nodes[1]
    assert isinstance(footnote_node, FootnoteNode)
    assert footnote_node.label == "1"
    relationships = [
        relation
        for relation in result.document.relationships
        if relation.kind is RelationshipKind.FOOTNOTE_REF
    ]
    assert len(relationships) == 1
    relation = relationships[0]
    assert relation.source_id == f"{body_id}:span:0002"
    assert relation.target_id == footnote_node.node_id
    assert relation.confidence == 1.0


def test_superscript_suffix_is_not_treated_as_footnote_reference() -> None:
    """A superscript suffix such as 'th' must not become a footnote link."""
    page_id = "page-0018"
    block_id = f"{page_id}:block:0001"
    superscript = SourceTypography(
        posture=FontPosture.ITALIC,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.SUPERSCRIPT,
        caps_style=CapsStyle.NORMAL,
    )
    block = PageBlockEvidence(
        block_id=block_id,
        sequence_index=0,
        role_hint=BlockRoleHint.PARAGRAPH,
        spans=(
            TextSpanEvidence(
                span_id=f"{block_id}:span:0001",
                text="December 13",
                language="en",
                source_typography=_typography(FontPosture.ITALIC),
            ),
            TextSpanEvidence(
                span_id=f"{block_id}:span:0002",
                text="th",
                language="en",
                source_typography=superscript,
            ),
        ),
        dominant_language="en",
    )

    result = BookStructuralAnalyzer().analyze((_page(18, block),))

    assert all(
        relation.kind is not RelationshipKind.FOOTNOTE_REF
        for relation in result.document.relationships
    )


def test_duplicate_footnote_labels_are_not_linked_by_guessing() -> None:
    """Ambiguous same-page footnote labels should remain unlinked."""
    page_id = "page-0013"
    ref_id = f"{page_id}:block:0001"
    superscript = SourceTypography(
        posture=FontPosture.ROMAN,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.SUPERSCRIPT,
        caps_style=CapsStyle.NORMAL,
    )
    reference = PageBlockEvidence(
        block_id=ref_id,
        sequence_index=0,
        role_hint=BlockRoleHint.PARAGRAPH,
        spans=(
            TextSpanEvidence(
                span_id=f"{ref_id}:span:0001",
                text="Nội dung",
                language="vi",
                source_typography=_typography(),
            ),
            TextSpanEvidence(
                span_id=f"{ref_id}:span:0002",
                text="1",
                language=None,
                source_typography=superscript,
            ),
        ),
        dominant_language="vi",
    )

    def footnote_block(index: int) -> PageBlockEvidence:
        """Build one duplicate-label footnote fixture."""
        block_id = f"{page_id}:block:{index:04d}"
        return PageBlockEvidence(
            block_id=block_id,
            sequence_index=index - 1,
            role_hint=BlockRoleHint.FOOTNOTE,
            spans=(
                TextSpanEvidence(
                    span_id=f"{block_id}:span:0001",
                    text="1",
                    language=None,
                    source_typography=superscript,
                ),
                TextSpanEvidence(
                    span_id=f"{block_id}:span:0002",
                    text=f"Chú thích {index}.",
                    language="vi",
                    source_typography=_typography(),
                ),
            ),
            dominant_language="vi",
        )

    result = BookStructuralAnalyzer().analyze(
        (_page(13, reference, footnote_block(2), footnote_block(3)),)
    )

    assert all(
        relation.kind is not RelationshipKind.FOOTNOTE_REF
        for relation in result.document.relationships
    )


def test_attribution_after_quote_links_to_quotation() -> None:
    """An explicit attribution after one quote should link to that quote."""
    page = _page(
        94,
        _block(
            "page-0094",
            1,
            BlockRoleHint.QUOTE,
            "“Bản chất của sự sống là tính phụ thuộc lẫn nhau”",
        ),
        _block(
            "page-0094",
            2,
            BlockRoleHint.ATTRIBUTION,
            "(Đức Phật)",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    quotation, attribution = result.document.nodes
    assert isinstance(quotation, QuotationNode)
    assert isinstance(attribution, AttributionNode)
    relationships = [
        relation
        for relation in result.document.relationships
        if relation.kind is RelationshipKind.ATTRIBUTION_OF
    ]
    assert len(relationships) == 1
    assert relationships[0].source_id == attribution.node_id
    assert relationships[0].target_id == quotation.node_id


def test_attribution_before_verse_links_to_verse() -> None:
    """An explicit attribution before one verse should link to that verse."""
    page = _page(
        49,
        _block(
            "page-0049",
            1,
            BlockRoleHint.ATTRIBUTION,
            "Đại Bàng Con (Dân ca Nga)",
        ),
        _block(
            "page-0049",
            2,
            BlockRoleHint.VERSE,
            "Một câu hát.",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    attribution, verse = result.document.nodes
    assert isinstance(attribution, AttributionNode)
    assert isinstance(verse, VerseNode)
    relation = next(
        relation
        for relation in result.document.relationships
        if relation.kind is RelationshipKind.ATTRIBUTION_OF
    )
    assert relation.source_id == attribution.node_id
    assert relation.target_id == verse.node_id


def test_attribution_between_two_possible_targets_remains_unlinked() -> None:
    """An attribution between two valid targets should not be guessed."""
    page = _page(
        49,
        _block("page-0049", 1, BlockRoleHint.VERSE, "Một câu hát."),
        _block(
            "page-0049",
            2,
            BlockRoleHint.ATTRIBUTION,
            "Tên tác giả",
        ),
        _block("page-0049", 3, BlockRoleHint.QUOTE, "“Một câu trích dẫn.”"),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert all(
        relation.kind is not RelationshipKind.ATTRIBUTION_OF
        for relation in result.document.relationships
    )


def test_bilingual_adjacent_quotes_form_translation_candidate() -> None:
    """Different-language adjacent quotes should remain separate and relate."""
    page = _page(
        271,
        _block(
            "page-0271",
            1,
            BlockRoleHint.QUOTE,
            "“Education is an act of love and wisdom.”",
            language="en",
        ),
        _block(
            "page-0271",
            2,
            BlockRoleHint.QUOTE,
            (
                "“Giáo dục là một hành động của tình yêu "
                "và trí tuệ.”"
            ),
            language="vi",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 2
    original, translated = result.document.nodes
    assert isinstance(original, QuotationNode)
    assert isinstance(translated, QuotationNode)
    relations = [
        relation
        for relation in result.document.relationships
        if relation.kind is RelationshipKind.TRANSLATION_OF
    ]
    assert len(relations) == 1
    relation = relations[0]
    assert relation.source_id == translated.node_id
    assert relation.target_id == original.node_id
    assert relation.confidence == 0.80


def test_adjacent_attribution_strengthens_translation_candidate() -> None:
    """Shared attribution context should strengthen a bilingual quote pair."""
    page = _page(
        271,
        _block(
            "page-0271",
            1,
            BlockRoleHint.ATTRIBUTION,
            "Lã Hồ Minh Khuê (từ Đại học Harvard)",
        ),
        _block(
            "page-0271",
            2,
            BlockRoleHint.QUOTE,
            "“Education is an act of love and wisdom.”",
            language="en",
        ),
        _block(
            "page-0271",
            3,
            BlockRoleHint.QUOTE,
            (
                "“Giáo dục là một hành động của tình yêu "
                "và trí tuệ.”"
            ),
            language="vi",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    relation = next(
        relation
        for relation in result.document.relationships
        if relation.kind is RelationshipKind.TRANSLATION_OF
    )
    assert relation.confidence == 0.90
    assert "attribution context" in relation.reasons[-1]


def test_same_language_quote_blocks_still_share_one_quotation() -> None:
    """Language-aware splitting must not break same-language quote grouping."""
    page = _page(
        87,
        _block(
            "page-0087",
            1,
            BlockRoleHint.QUOTE,
            "“Đoạn thứ nhất.",
            language="vi",
        ),
        _block(
            "page-0087",
            2,
            BlockRoleHint.QUOTE,
            "Đoạn thứ hai.”",
            language="vi",
        ),
    )

    result = BookStructuralAnalyzer().analyze((page,))

    assert len(result.document.nodes) == 1
    assert isinstance(result.document.nodes[0], QuotationNode)
    assert all(
        relation.kind is not RelationshipKind.TRANSLATION_OF
        for relation in result.document.relationships
    )
