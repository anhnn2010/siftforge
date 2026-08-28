"""Tests for the versioned ebook extraction contract."""

from siftforge.ebook.extraction import EBOOK_PAGE_PROMPT, EBOOK_PAGE_SCHEMA


def _span_schema() -> dict[str, object]:
    """Return the JSON Schema fragment for one rich-text span."""
    block_schema = EBOOK_PAGE_SCHEMA.json_schema["properties"]["blocks"]["items"]
    return block_schema["properties"]["content"]["items"]


def test_ebook_contract_is_explicitly_versioned() -> None:
    """Prompt and schema versions should be stable provenance identifiers."""
    assert EBOOK_PAGE_PROMPT.name == "ebook_page_transcription"
    assert EBOOK_PAGE_PROMPT.version == "4"
    assert EBOOK_PAGE_SCHEMA.name == "ebook_page_content"
    assert EBOOK_PAGE_SCHEMA.version == "4"


def test_ebook_schema_requires_explicit_typography() -> None:
    """Each text span should declare every mutually exclusive typography state."""
    span_schema = _span_schema()
    typography = span_schema["properties"]["typography"]

    assert typography["required"] == [
        "posture",
        "weight",
        "vertical_position",
        "caps_style",
        "decorations",
    ]
    assert typography["properties"]["posture"]["enum"] == [
        "roman",
        "italic",
        "unknown",
    ]
    assert typography["properties"]["weight"]["enum"] == [
        "normal",
        "bold",
        "unknown",
    ]


def test_ebook_schema_keeps_unknown_as_first_class_typography_state() -> None:
    """Uncertain styling should be representable without guessing."""
    span_schema = _span_schema()
    typography = span_schema["properties"]["typography"]["properties"]

    assert "unknown" in typography["posture"]["enum"]
    assert "unknown" in typography["weight"]["enum"]
    assert "unknown" in typography["vertical_position"]["enum"]
    assert "unknown" in typography["caps_style"]["enum"]


def test_ebook_schema_supports_language_per_block() -> None:
    """Mixed-language pages should not be flattened into one page language."""
    block_schema = EBOOK_PAGE_SCHEMA.json_schema["properties"]["blocks"]["items"]

    assert "language" in block_schema["required"]
    assert "language" in block_schema["properties"]
