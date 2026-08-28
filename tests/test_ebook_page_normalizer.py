"""Tests for strict provider-output to ebook-domain normalization."""

import pytest

from siftforge.ebook.extraction import (
    EbookPageNormalizationError,
    EbookPageNormalizer,
)
from siftforge.ebook.models import FontPosture, VerticalPosition


def _typography(
    posture: str = "roman",
    vertical_position: str = "baseline",
) -> dict[str, object]:
    """Return a complete explicit typography fixture."""
    return {
        "posture": posture,
        "weight": "normal",
        "vertical_position": vertical_position,
        "caps_style": "normal",
        "decorations": [],
    }


def _payload() -> dict[str, object]:
    """Return a page-18-shaped mixed-language fixture."""
    return {
        "page_kind": "text",
        "language": "vi",
        "printed_page_number": "18",
        "blocks": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "text": "Nguyên văn bản tiếng Anh:",
                        "typography": _typography(posture="roman"),
                    }
                ],
                "language": "vi",
                "level": None,
                "alignment": "left",
            },
            {
                "type": "paragraph",
                "content": [
                    {
                        "text": "December 13",
                        "typography": _typography(posture="italic"),
                    },
                    {
                        "text": "th",
                        "typography": _typography(
                            posture="italic",
                            vertical_position="superscript",
                        ),
                    },
                ],
                "language": "en",
                "level": None,
                "alignment": "left",
            },
        ],
        "warnings": [],
    }


def test_normalizer_builds_explicit_roman_and_italic_states() -> None:
    """Normalizer should distinguish roman from italic rather than infer absence."""
    page = EbookPageNormalizer().normalize("page-18", _payload())

    roman = page.blocks[0].content[0].typography
    italic = page.blocks[1].content[0].typography
    superscript = page.blocks[1].content[1].typography

    assert roman.posture is FontPosture.ROMAN
    assert italic.posture is FontPosture.ITALIC
    assert superscript.vertical_position is VerticalPosition.SUPERSCRIPT


def test_normalizer_serializes_explicit_typography() -> None:
    """Normalized artifact should preserve explicit typography dimensions."""
    normalizer = EbookPageNormalizer()
    page = normalizer.normalize("page-18", _payload())

    serialized = normalizer.to_dict(page)
    first_typography = serialized["blocks"][0]["content"][0]["typography"]

    assert first_typography["posture"] == "roman"
    assert first_typography["weight"] == "normal"
    assert first_typography["vertical_position"] == "baseline"


def test_normalizer_accepts_unknown_typography_state() -> None:
    """Uncertain visual evidence should survive normalization as unknown."""
    payload = _payload()
    blocks = payload["blocks"]
    assert isinstance(blocks, list)
    first_block = blocks[0]
    assert isinstance(first_block, dict)
    content = first_block["content"]
    assert isinstance(content, list)
    first_span = content[0]
    assert isinstance(first_span, dict)
    typography = first_span["typography"]
    assert isinstance(typography, dict)
    typography["posture"] = "unknown"

    page = EbookPageNormalizer().normalize("page-18", payload)

    assert page.blocks[0].content[0].typography.posture is FontPosture.UNKNOWN


def test_normalizer_rejects_missing_typography_dimension() -> None:
    """Provider output must not silently fall back to inferred typography."""
    payload = _payload()
    blocks = payload["blocks"]
    assert isinstance(blocks, list)
    first_block = blocks[0]
    assert isinstance(first_block, dict)
    content = first_block["content"]
    assert isinstance(content, list)
    first_span = content[0]
    assert isinstance(first_span, dict)
    typography = first_span["typography"]
    assert isinstance(typography, dict)
    del typography["posture"]

    with pytest.raises(EbookPageNormalizationError, match="posture must be a string"):
        EbookPageNormalizer().normalize("page-18", payload)
