"""Tests for deterministic first-pass ebook structural analysis."""

from siftforge.ebook.evidence import (
    BlockRoleHint,
    MarkerEvidence,
    MarkerKind,
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
    BookStructuralAnalyzer,
    ListKind,
    ListNode,
    ParagraphNode,
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
        marker=marker,
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
            "Trong thực tế tôi nhận ra rằng hầu như mọi người cha đều",
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
