"""Tests for the first versioned ebook extraction contract."""

from siftforge.ebook.extraction import EBOOK_PAGE_PROMPT, EBOOK_PAGE_SCHEMA


def test_ebook_contract_is_explicitly_versioned() -> None:
    """Prompt and schema versions should be stable provenance identifiers."""
    assert EBOOK_PAGE_PROMPT.name == "ebook_page_transcription"
    assert EBOOK_PAGE_PROMPT.version == "1"
    assert EBOOK_PAGE_SCHEMA.name == "ebook_page_content"
    assert EBOOK_PAGE_SCHEMA.version == "1"


def test_ebook_schema_preserves_review_signals() -> None:
    """Schema should expose uncertainty and non-body page artifacts."""
    block_types = EBOOK_PAGE_SCHEMA.json_schema["properties"]["blocks"]["items"][
        "properties"
    ]["type"]["enum"]

    assert "page_header" in block_types
    assert "page_footer" in block_types
    assert "page_number" in block_types
    assert "warnings" in EBOOK_PAGE_SCHEMA.json_schema["required"]
