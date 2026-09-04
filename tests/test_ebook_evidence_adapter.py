"""Tests for conservative migration from v4 page content to evidence models."""

from siftforge.ebook.evidence import (
    BlockRoleHint,
    HeadingRoleHint,
    page_content_to_evidence,
)
from siftforge.ebook.models import (
    Block,
    BlockType,
    CapsStyle,
    FontPosture,
    FontWeight,
    PageContent,
    PageKind,
    TextAlignment,
    TextDecoration,
    TextSpan,
    Typography,
    VerticalPosition,
)
from siftforge.extraction.models import SourceRef


def _typography(
    posture: FontPosture = FontPosture.ROMAN,
    weight: FontWeight = FontWeight.NORMAL,
    decorations: tuple[TextDecoration, ...] = (),
) -> Typography:
    """Return a complete legacy typography fixture."""
    return Typography(
        posture=posture,
        weight=weight,
        vertical_position=VerticalPosition.BASELINE,
        caps_style=CapsStyle.NORMAL,
        decorations=decorations,
    )


def _page() -> PageContent:
    """Return a v4 page containing several role and typography cases."""
    return PageContent(
        page_id="page-0398",
        page_kind=PageKind.TEXT,
        language="vi",
        printed_page_number="398",
        blocks=(
            Block(
                type=BlockType.HEADING,
                content=(
                    TextSpan(
                        text="TÌNH HUỐNG",
                        typography=_typography(weight=FontWeight.BOLD),
                    ),
                ),
                language="vi",
                level=2,
                alignment=TextAlignment.CENTER,
            ),
            Block(
                type=BlockType.PARAGRAPH,
                content=(
                    TextSpan(text="Và đây là ", typography=_typography()),
                    TextSpan(
                        text="cách ứng xử",
                        typography=_typography(
                            posture=FontPosture.ITALIC,
                            decorations=(TextDecoration.UNDERLINE,),
                        ),
                    ),
                ),
                language="vi",
                alignment=TextAlignment.LEFT,
            ),
            Block(
                type=BlockType.LIST,
                content=(TextSpan(text="♥ Một mục", typography=_typography()),),
                language="vi",
            ),
            Block(
                type=BlockType.QUOTE,
                content=(TextSpan(text="A quote", typography=_typography()),),
                language="en",
            ),
            Block(
                type=BlockType.PAGE_FOOTER,
                content=(
                    TextSpan(text="18 NĂM KIM CƯƠNG", typography=_typography()),
                ),
                language="vi",
            ),
        ),
        warnings=("example warning",),
    )


def _source() -> SourceRef:
    """Return explicit source provenance required by the adapter."""
    return SourceRef(
        source_id="pdf:abc:page:0398",
        uri="file:///book.pdf#page=398",
        sha256="abc",
        media_type="image/jpeg",
    )


def _legacy_text(page: PageContent) -> str:
    """Flatten v4 text in source block and span order."""
    return "".join(block.text for block in page.blocks)


def _evidence_text(page: PageContent) -> str:
    """Flatten evidence text using the same source order."""
    evidence = page_content_to_evidence(page, _source())
    return "".join(block.text for block in evidence.blocks)


def test_adapter_preserves_page_data_and_block_order() -> None:
    """Migration should preserve all v4 page-level and ordered text evidence."""
    page = _page()
    evidence = page_content_to_evidence(page, _source())

    assert evidence.page_id == page.page_id
    assert evidence.source == _source()
    assert evidence.page_kind_hint is PageKind.TEXT
    assert evidence.dominant_language == "vi"
    assert evidence.printed_page_number == "398"
    assert evidence.warnings == ("example warning",)
    assert _evidence_text(page) == _legacy_text(page)
    assert [block.sequence_index for block in evidence.blocks] == [0, 1, 2, 3, 4]


def test_adapter_preserves_typography_and_block_language() -> None:
    """Source typography and known v4 language must survive without inference."""
    evidence = page_content_to_evidence(_page(), _source())
    paragraph = evidence.blocks[1]
    italic_span = paragraph.spans[1]

    assert paragraph.dominant_language == "vi"
    assert italic_span.language == "vi"
    assert italic_span.source_typography.posture is FontPosture.ITALIC
    assert italic_span.source_typography.weight is FontWeight.NORMAL
    assert italic_span.source_typography.decorations == (TextDecoration.UNDERLINE,)


def test_adapter_preserves_heading_level_only_as_hint() -> None:
    """Legacy heading level should remain evidence without inventing a role."""
    heading = page_content_to_evidence(_page(), _source()).blocks[0]

    assert heading.role_hint is BlockRoleHint.HEADING
    assert heading.heading_level_hint == 2
    assert heading.heading_role_hint is HeadingRoleHint.UNKNOWN
    assert heading.alignment is TextAlignment.CENTER


def test_adapter_keeps_list_and_quote_as_page_local_hints() -> None:
    """Legacy list and quote classifications must not become final structure."""
    evidence = page_content_to_evidence(_page(), _source())

    assert evidence.blocks[2].role_hint is BlockRoleHint.LIST
    assert evidence.blocks[3].role_hint is BlockRoleHint.QUOTE


def test_adapter_does_not_invent_marker_region_or_span_language() -> None:
    """New evidence fields should stay unresolved when v4 did not contain them."""
    evidence = page_content_to_evidence(_page(), _source())
    list_block = evidence.blocks[2]

    assert list_block.marker is None
    assert list_block.region is None
    assert list_block.spans[0].language == list_block.dominant_language


def test_adapter_generates_deterministic_ids() -> None:
    """Repeated conversion of the same page should produce identical stable IDs."""
    first = page_content_to_evidence(_page(), _source())
    second = page_content_to_evidence(_page(), _source())

    assert [block.block_id for block in first.blocks] == [
        block.block_id for block in second.blocks
    ]
    assert first.blocks[0].block_id == "page-0398:block:0001"
    assert first.blocks[1].spans[1].span_id == "page-0398:block:0002:span:0002"
