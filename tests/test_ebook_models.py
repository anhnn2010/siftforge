"""Tests for typed rich-text ebook-domain models."""

from siftforge.ebook.models import (
    Block,
    BlockType,
    CapsStyle,
    FontPosture,
    FontWeight,
    PageContent,
    PageKind,
    TextAlignment,
    TextSpan,
    Typography,
    VerticalPosition,
)


def _roman() -> Typography:
    """Return ordinary upright baseline typography."""
    return Typography(
        posture=FontPosture.ROMAN,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.BASELINE,
        caps_style=CapsStyle.NORMAL,
    )


def test_block_plain_text_is_derived_from_rich_text_spans() -> None:
    """Plain text should remain available without discarding typography."""
    italic = Typography(
        posture=FontPosture.ITALIC,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.BASELINE,
        caps_style=CapsStyle.NORMAL,
    )
    block = Block(
        type=BlockType.PARAGRAPH,
        content=(
            TextSpan(text="Điều này ", typography=_roman()),
            TextSpan(text="rất quan trọng", typography=italic),
            TextSpan(text=".", typography=_roman()),
        ),
        language="vi",
        alignment=TextAlignment.JUSTIFY,
    )

    assert block.text == "Điều này rất quan trọng."
    assert block.content[1].typography.posture is FontPosture.ITALIC
    assert block.language == "vi"


def test_page_content_represents_footer_and_number() -> None:
    """Typed page model should retain running furniture separately from body."""
    page = PageContent(
        page_id="page-18",
        page_kind=PageKind.TEXT,
        language="vi",
        printed_page_number="18",
        blocks=(
            Block(
                type=BlockType.PAGE_FOOTER,
                content=(TextSpan(text="18 NĂM KIM CƯƠNG", typography=_roman()),),
                language="vi",
            ),
            Block(
                type=BlockType.PAGE_NUMBER,
                content=(TextSpan(text="18", typography=_roman()),),
            ),
        ),
    )

    assert page.blocks[0].type is BlockType.PAGE_FOOTER
    assert page.blocks[1].type is BlockType.PAGE_NUMBER
