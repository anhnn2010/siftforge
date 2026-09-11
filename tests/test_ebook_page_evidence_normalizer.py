"""Tests for strict normalization of staged v5 ebook page evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from siftforge.ebook.evidence import (
    BlockRoleHint,
    HeadingRoleHint,
    MarkerKind,
)
from siftforge.ebook.extraction import (
    EbookPageEvidenceNormalizer,
    EbookPageNormalizationError,
)
from siftforge.ebook.models import (
    FontPosture,
    FontWeight,
    PageKind,
    TextAlignment,
    VerticalPosition,
)
from siftforge.extraction.models import SourceRef


def _source() -> SourceRef:
    """Return deterministic source provenance for normalizer tests."""
    return SourceRef(
        source_id="pdf:abc:page:0152",
        uri="file:///books/18-nam-kim-cuong.pdf#page=152",
        sha256="abc123",
        media_type="image/jpeg",
        metadata={"page_number": 152},
    )


def _typography(**overrides: Any) -> dict[str, Any]:
    """Return one complete v5 source-typography payload."""
    payload: dict[str, Any] = {
        "posture": "roman",
        "weight": "normal",
        "vertical_position": "baseline",
        "caps_style": "normal",
        "decorations": [],
    }
    payload.update(overrides)
    return payload


def _span(text: str, **overrides: Any) -> dict[str, Any]:
    """Return one complete v5 text-span payload."""
    payload: dict[str, Any] = {
        "text": text,
        "language": "vi",
        "source_typography": _typography(),
        "semantic_line_break_after": False,
    }
    payload.update(overrides)
    return payload


def _block(**overrides: Any) -> dict[str, Any]:
    """Return one complete ordinary v5 block payload."""
    payload: dict[str, Any] = {
        "role_hint": "paragraph",
        "content": [_span("Nội dung")],
        "dominant_language": "vi",
        "heading_level_hint": None,
        "heading_role_hint": "unknown",
        "marker": None,
        "region": None,
        "alignment": "left",
    }
    payload.update(overrides)
    return payload


def _page_payload() -> dict[str, Any]:
    """Return a representative valid v5 page-evidence payload."""
    return {
        "page_kind_hint": "text",
        "dominant_language": "vi",
        "printed_page_number": "152",
        "blocks": [
            _block(
                role_hint="heading",
                content=[
                    _span(
                        "Đừng hy sinh",
                        source_typography=_typography(
                            posture="italic",
                            weight="bold",
                        ),
                    )
                ],
                heading_level_hint=2,
                heading_role_hint="section_title",
                alignment="center",
            ),
            _block(
                role_hint="verse",
                content=[
                    _span(
                        "Có vàng, vàng chẳng hay phô",
                        semantic_line_break_after=True,
                    ),
                    _span(
                        "Có con, con nói trầm trồ mẹ nghe.",
                        semantic_line_break_after=True,
                    ),
                ],
                alignment="center",
            ),
            _block(
                role_hint="list_item",
                content=[_span("Hoặc vì ngại làm tổn thương...")],
                marker={
                    "kind": "bullet",
                    "raw_text": "♥",
                    "ordinal": None,
                },
            ),
            _block(
                role_hint="image",
                content=[],
                dominant_language=None,
                region={
                    "x": 0.1,
                    "y": 0.2,
                    "width": 0.8,
                    "height": 0.5,
                },
                alignment="center",
            ),
        ],
        "warnings": [],
    }


def test_v5_normalizer_builds_typed_page_evidence() -> None:
    """A valid payload should retain all page-local evidence without inference."""
    page = EbookPageEvidenceNormalizer().normalize(
        page_id="page-0152",
        source=_source(),
        payload=_page_payload(),
    )

    assert page.page_id == "page-0152"
    assert page.source == _source()
    assert page.page_kind_hint is PageKind.TEXT
    assert page.dominant_language == "vi"
    assert page.printed_page_number == "152"
    assert len(page.blocks) == 4

    heading = page.blocks[0]
    assert heading.block_id == "page-0152:block:0001"
    assert heading.sequence_index == 0
    assert heading.role_hint is BlockRoleHint.HEADING
    assert heading.heading_level_hint == 2
    assert heading.heading_role_hint is HeadingRoleHint.SECTION_TITLE
    assert heading.alignment is TextAlignment.CENTER
    assert heading.spans[0].span_id == "page-0152:block:0001:span:0001"
    assert heading.spans[0].source_typography.posture is FontPosture.ITALIC
    assert heading.spans[0].source_typography.weight is FontWeight.BOLD
    assert (
        heading.spans[0].source_typography.vertical_position
        is VerticalPosition.BASELINE
    )

    verse = page.blocks[1]
    assert verse.role_hint is BlockRoleHint.VERSE
    assert [span.semantic_line_break_after for span in verse.spans] == [
        True,
        True,
    ]

    list_item = page.blocks[2]
    assert list_item.role_hint is BlockRoleHint.LIST_ITEM
    assert list_item.marker is not None
    assert list_item.marker.kind is MarkerKind.BULLET
    assert list_item.marker.raw_text == "♥"

    image = page.blocks[3]
    assert image.region is not None
    assert image.region.x == pytest.approx(0.1)
    assert image.region.width == pytest.approx(0.8)


def test_v5_normalizer_assigns_deterministic_ids() -> None:
    """The same page identity and array order must always produce the same IDs."""
    normalizer = EbookPageEvidenceNormalizer()
    first = normalizer.normalize("page-0152", _source(), _page_payload())
    second = normalizer.normalize("page-0152", _source(), _page_payload())

    assert [block.block_id for block in first.blocks] == [
        block.block_id for block in second.blocks
    ]
    assert [
        span.span_id for block in first.blocks for span in block.spans
    ] == [span.span_id for block in second.blocks for span in block.spans]


def test_v5_normalizer_serializes_ids_and_source_provenance() -> None:
    """Normalized artifacts should contain generated IDs and source provenance."""
    normalizer = EbookPageEvidenceNormalizer()
    page = normalizer.normalize("page-0152", _source(), _page_payload())

    data = normalizer.to_dict(page)

    assert data["page_id"] == "page-0152"
    assert data["source"]["source_id"] == "pdf:abc:page:0152"
    assert data["blocks"][0]["block_id"] == "page-0152:block:0001"
    assert (
        data["blocks"][0]["content"][0]["span_id"]
        == "page-0152:block:0001:span:0001"
    )
    assert data["blocks"][1]["content"][0]["semantic_line_break_after"]
    assert data["blocks"][2]["marker"] == {
        "kind": "bullet",
        "raw_text": "♥",
        "ordinal": None,
    }


def test_v5_normalizer_rejects_unknown_contract_fields() -> None:
    """Direct normalization should remain strict even when JSON Schema is bypassed."""
    payload = _page_payload()
    payload["unexpected"] = "value"

    with pytest.raises(
        EbookPageNormalizationError,
        match="page contains unsupported fields: unexpected",
    ):
        EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)


def test_v5_normalizer_rejects_heading_hints_on_non_heading_block() -> None:
    """Heading-specific hints must not leak onto ordinary evidence blocks."""
    payload = _page_payload()
    payload["blocks"][2]["heading_level_hint"] = 3

    with pytest.raises(
        EbookPageNormalizationError,
        match="heading_level_hint must be null for non-heading blocks",
    ):
        EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)

    payload = _page_payload()
    payload["blocks"][2]["heading_role_hint"] = "subtitle"

    with pytest.raises(
        EbookPageNormalizationError,
        match="heading_role_hint must be 'unknown' for non-heading blocks",
    ):
        EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)



def test_v5_normalizer_rejects_legacy_list_role_hint() -> None:
    """The v5 contract must not accept the legacy whole-list page block role."""
    payload = _page_payload()
    payload["blocks"][2]["role_hint"] = "list"

    with pytest.raises(
        EbookPageNormalizationError,
        match="role_hint has unsupported v5 value 'list'",
    ):
        EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)

def test_v5_normalizer_rejects_invalid_semantic_line_break_type() -> None:
    """Semantic line evidence must be an explicit boolean rather than coercible data."""
    payload = _page_payload()
    payload["blocks"][1]["content"][0]["semantic_line_break_after"] = 1

    with pytest.raises(
        EbookPageNormalizationError,
        match="semantic_line_break_after must be a boolean",
    ):
        EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)


def test_v5_normalizer_rejects_invalid_marker_ordinal() -> None:
    """Marker ordinals must be null or positive integers and must reject booleans."""
    for invalid in (0, -1, True, "10"):
        payload = _page_payload()
        payload["blocks"][2]["marker"]["ordinal"] = invalid

        with pytest.raises(
            EbookPageNormalizationError,
            match="must be a positive integer or null",
        ):
            EbookPageEvidenceNormalizer().normalize(
                "page-0152",
                _source(),
                payload,
            )


def test_v5_normalizer_rejects_region_that_extends_past_page() -> None:
    """Individually normalized coordinates must still form an in-page rectangle."""
    payload = _page_payload()
    payload["blocks"][3]["region"] = {
        "x": 0.8,
        "y": 0.2,
        "width": 0.3,
        "height": 0.4,
    }

    with pytest.raises(
        EbookPageNormalizationError,
        match=r"region\.x \+ blocks\[3\]\.region\.width must be at most 1",
    ):
        EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)


def test_v5_normalizer_rejects_boolean_region_coordinate() -> None:
    """Python booleans must not be accepted as JSON numbers for coordinates."""
    payload = _page_payload()
    payload["blocks"][3]["region"]["x"] = True

    with pytest.raises(
        EbookPageNormalizationError,
        match=r"blocks\[3\]\.region\.x must be a number",
    ):
        EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)



def test_v5_normalizer_rejects_nan_region_coordinate() -> None:
    """Normalized source coordinates must be finite JSON-like numbers."""
    payload = _page_payload()
    payload["blocks"][3]["region"]["x"] = float("nan")

    with pytest.raises(
        EbookPageNormalizationError,
        match=r"blocks\[3\]\.region\.x must be a finite number",
    ):
        EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)

def test_v5_normalizer_rejects_duplicate_source_decorations() -> None:
    """Repeated decoration enum values should not survive typed normalization."""
    payload = _page_payload()
    typography = payload["blocks"][0]["content"][0]["source_typography"]
    typography["decorations"] = ["underline", "underline"]

    with pytest.raises(
        EbookPageNormalizationError,
        match="decorations contains duplicate 'underline'",
    ):
        EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)


def test_v5_normalizer_does_not_infer_marker_from_readable_text() -> None:
    """Readable prefixes remain untouched when provider marker evidence is null."""
    payload = _page_payload()
    payload["blocks"] = [
        _block(
            role_hint="paragraph",
            content=[_span("– Cô còn nhớ em không?")],
            marker=None,
        )
    ]

    page = EbookPageEvidenceNormalizer().normalize(
        "page-0397",
        _source(),
        payload,
    )

    assert page.blocks[0].text == "– Cô còn nhớ em không?"
    assert page.blocks[0].marker is None


def test_v5_normalizer_preserves_graphic_marker_without_unicode_invention() -> None:
    """A graphic marker with null raw text must remain graphic-only evidence."""
    payload = _page_payload()
    payload["blocks"] = [
        _block(
            role_hint="heading",
            content=[_span("TÌNH HUỐNG")],
            heading_level_hint=2,
            heading_role_hint="scenario_label",
            marker={"kind": "graphic", "raw_text": None, "ordinal": None},
            alignment="center",
        )
    ]

    page = EbookPageEvidenceNormalizer().normalize(
        "page-0402",
        _source(),
        payload,
    )

    assert page.blocks[0].text == "TÌNH HUỐNG"
    assert page.blocks[0].marker is not None
    assert page.blocks[0].marker.kind is MarkerKind.GRAPHIC
    assert page.blocks[0].marker.raw_text is None


def test_normalizer_does_not_mutate_provider_payload() -> None:
    """Strict normalization must not mutate the raw provider payload."""
    payload = _page_payload()
    before = deepcopy(payload)

    EbookPageEvidenceNormalizer().normalize("page-0152", _source(), payload)

    assert payload == before


def test_v5_normalizer_round_trips_normalized_artifact() -> None:
    """Canonical normalized JSON should load without losing deterministic IDs."""
    normalizer = EbookPageEvidenceNormalizer()
    page = normalizer.normalize("page-0152", _source(), _page_payload())
    artifact = normalizer.to_dict(page)

    loaded = normalizer.from_dict(artifact)

    assert loaded == page
    assert normalizer.to_dict(loaded) == artifact


def test_v5_normalizer_rejects_modified_artifact_ids() -> None:
    """Persisted block IDs must remain deterministic and tamper-evident."""
    normalizer = EbookPageEvidenceNormalizer()
    page = normalizer.normalize("page-0152", _source(), _page_payload())
    artifact = normalizer.to_dict(page)
    artifact["blocks"][0]["block_id"] = "wrong:block:id"

    with pytest.raises(EbookPageNormalizationError, match="block_id must equal"):
        normalizer.from_dict(artifact)
