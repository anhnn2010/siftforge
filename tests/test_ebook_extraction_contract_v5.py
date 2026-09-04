"""Tests for the staged v5 ebook page-evidence extraction contract."""

from siftforge.ebook.extraction import (
    EBOOK_PAGE_PROMPT,
    EBOOK_PAGE_PROMPT_V5,
    EBOOK_PAGE_SCHEMA,
    EBOOK_PAGE_SCHEMA_V5,
)


def _block_schema() -> dict[str, object]:
    """Return the JSON Schema fragment for one v5 evidence block."""
    return EBOOK_PAGE_SCHEMA_V5.json_schema["properties"]["blocks"]["items"]


def _span_schema() -> dict[str, object]:
    """Return the JSON Schema fragment for one v5 evidence text span."""
    return _block_schema()["properties"]["content"]["items"]


def test_v5_contract_is_explicitly_versioned_but_not_active_yet() -> None:
    """Milestone 1F-2 should stage v5 without switching the working runtime."""
    assert EBOOK_PAGE_PROMPT.version == "4"
    assert EBOOK_PAGE_SCHEMA.version == "4"
    assert EBOOK_PAGE_PROMPT_V5.name == "ebook_page_evidence"
    assert EBOOK_PAGE_PROMPT_V5.version == "5"
    assert EBOOK_PAGE_SCHEMA_V5.name == "ebook_page_evidence"
    assert EBOOK_PAGE_SCHEMA_V5.version == "5"


def test_v5_schema_models_role_hints_instead_of_final_list_containers() -> None:
    """Page extraction should emit local leaf evidence for structural analysis."""
    role_hint = _block_schema()["properties"]["role_hint"]

    assert "list_item" in role_hint["enum"]
    assert "verse" in role_hint["enum"]
    assert "attribution" in role_hint["enum"]
    assert "list" not in role_hint["enum"]


def test_v5_schema_supports_language_and_semantic_breaks_per_span() -> None:
    """Mixed language and meaningful line boundaries must survive page reflow."""
    span_schema = _span_schema()

    assert "language" in span_schema["required"]
    assert "source_typography" in span_schema["required"]
    assert "semantic_line_break_after" in span_schema["required"]
    assert span_schema["properties"]["semantic_line_break_after"] == {
        "type": "boolean"
    }


def test_v5_source_typography_keeps_unknown_as_first_class_state() -> None:
    """Visual typography must stay explicit without forcing semantic emphasis."""
    typography = _span_schema()["properties"]["source_typography"]["properties"]

    assert "unknown" in typography["posture"]["enum"]
    assert "unknown" in typography["weight"]["enum"]
    assert "unknown" in typography["vertical_position"]["enum"]
    assert "unknown" in typography["caps_style"]["enum"]


def test_v5_schema_separates_marker_evidence_from_readable_text() -> None:
    """Markers should be representable without declaring their final semantics."""
    marker = _block_schema()["properties"]["marker"]["anyOf"][0]
    kinds = marker["properties"]["kind"]["enum"]

    assert kinds == [
        "bullet",
        "numeric",
        "alphabetic",
        "dash",
        "graphic",
        "unknown",
    ]
    assert "raw_text" in marker["required"]
    assert "ordinal" in marker["required"]


def test_v5_schema_supports_heading_role_hints_separately_from_level() -> None:
    """Heading role and local level hint should remain independent evidence."""
    block = _block_schema()
    roles = block["properties"]["heading_role_hint"]["enum"]

    assert "chapter_label" in roles
    assert "chapter_title" in roles
    assert "subtitle" in roles
    assert "genre_label" in roles
    assert "scenario_label" in roles
    assert "scenario_title" in roles
    assert "heading_level_hint" in block["required"]


def test_v5_schema_supports_normalized_image_regions() -> None:
    """Image evidence should be able to identify crop regions on the source page."""
    region = _block_schema()["properties"]["region"]["anyOf"][0]
    properties = region["properties"]

    assert region["required"] == ["x", "y", "width", "height"]
    assert properties["x"]["minimum"] == 0
    assert properties["x"]["maximum"] == 1
    assert properties["width"]["minimum"] == 0
    assert properties["width"]["maximum"] == 1


def test_v5_prompt_captures_regression_round_design_boundaries() -> None:
    """Prompt text should encode the important evidence-vs-semantics boundaries."""
    prompt = EBOOK_PAGE_PROMPT_V5.text

    assert "NOT the final ebook structure" in prompt
    assert "Do not invent stable IDs" in prompt
    assert "Repeated dialogue turns are not automatically a list" in prompt
    assert (
        "Visual list formatting does not by itself prove semantic list structure"
        in prompt
    )
    assert "Never substitute an arbitrary Unicode glyph or emoji" in prompt
    assert "semantic_line_break_after" in prompt
    assert "does NOT assert EPUB" in prompt
    assert "semantic emphasis or strong importance" in prompt
    assert "tight normalized region" in prompt
