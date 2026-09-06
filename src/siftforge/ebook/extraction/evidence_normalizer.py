"""Normalize v5 provider JSON into strict page-local ebook evidence."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Any, TypeVar

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
    build_block_id,
    build_span_id,
)
from siftforge.ebook.models import (
    CapsStyle,
    FontPosture,
    FontWeight,
    PageKind,
    TextAlignment,
    TextDecoration,
    VerticalPosition,
)
from siftforge.extraction.models import SourceRef

from .normalizer import EbookPageNormalizationError

EnumT = TypeVar("EnumT", bound=StrEnum)

_ROOT_KEYS = frozenset(
    {
        "page_kind_hint",
        "dominant_language",
        "printed_page_number",
        "blocks",
        "warnings",
    }
)
_BLOCK_KEYS = frozenset(
    {
        "role_hint",
        "content",
        "dominant_language",
        "heading_level_hint",
        "heading_role_hint",
        "marker",
        "region",
        "alignment",
    }
)
_SPAN_KEYS = frozenset(
    {
        "text",
        "language",
        "source_typography",
        "semantic_line_break_after",
    }
)
_TYPOGRAPHY_KEYS = frozenset(
    {
        "posture",
        "weight",
        "vertical_position",
        "caps_style",
        "decorations",
    }
)
_MARKER_KEYS = frozenset({"kind", "raw_text", "ordinal"})
_REGION_KEYS = frozenset({"x", "y", "width", "height"})
_V5_BLOCK_ROLE_HINTS = frozenset(
    role for role in BlockRoleHint if role is not BlockRoleHint.LIST
)


class EbookPageEvidenceNormalizer:
    """Validate v5 provider data and build typed ``PageExtraction`` evidence.

    The normalizer intentionally performs no book-level interpretation. It
    validates the v5 page-evidence contract, assigns deterministic identifiers,
    and preserves local evidence exactly enough for later structural analysis.
    """

    def normalize(
        self,
        page_id: str,
        source: SourceRef,
        payload: Any,
    ) -> PageExtraction:
        """Normalize one v5 provider payload into page-local evidence.

        Args:
            page_id: Stable identity assigned by the ebook application.
            source: Physical-page provenance associated with the payload.
            payload: Decoded provider JSON matching the staged v5 contract.

        Returns:
            Strict immutable page evidence with deterministic block/span IDs.

        Raises:
            EbookPageNormalizationError: If any contract field or cross-field
                invariant is invalid.
        """
        root = self._require_dict(payload, "page")
        self._require_exact_keys(root, _ROOT_KEYS, "page")

        page_kind_hint = self._enum_value(
            PageKind,
            root.get("page_kind_hint"),
            "page_kind_hint",
        )
        dominant_language = self._optional_string(
            root.get("dominant_language"),
            "dominant_language",
        )
        printed_page_number = self._optional_string(
            root.get("printed_page_number"),
            "printed_page_number",
        )
        warnings = self._string_tuple(root.get("warnings"), "warnings")

        raw_blocks = root.get("blocks")
        if not isinstance(raw_blocks, list):
            raise EbookPageNormalizationError("blocks must be a list")

        blocks = tuple(
            self._normalize_block(page_id, block_payload, block_index)
            for block_index, block_payload in enumerate(raw_blocks)
        )

        return PageExtraction(
            page_id=page_id,
            source=source,
            page_kind_hint=page_kind_hint,
            dominant_language=dominant_language,
            printed_page_number=printed_page_number,
            blocks=blocks,
            warnings=warnings,
        )

    def to_dict(self, page: PageExtraction) -> dict[str, Any]:
        """Serialize typed page evidence into stable JSON-compatible data.

        The serialized normalized artifact includes deterministic IDs and source
        provenance that were not part of the provider's raw v5 JSON response.
        """
        return {
            "page_id": page.page_id,
            "source": {
                "source_id": page.source.source_id,
                "uri": page.source.uri,
                "sha256": page.source.sha256,
                "media_type": page.source.media_type,
                "metadata": page.source.metadata,
            },
            "page_kind_hint": page.page_kind_hint.value,
            "dominant_language": page.dominant_language,
            "printed_page_number": page.printed_page_number,
            "blocks": [self._block_to_dict(block) for block in page.blocks],
            "warnings": list(page.warnings),
        }

    def _normalize_block(
        self,
        page_id: str,
        payload: Any,
        block_index: int,
    ) -> PageBlockEvidence:
        """Normalize one v5 block and enforce page-local invariants."""
        path = f"blocks[{block_index}]"
        block_data = self._require_dict(payload, path)
        self._require_exact_keys(block_data, _BLOCK_KEYS, path)

        role_hint = self._enum_value(
            BlockRoleHint,
            block_data.get("role_hint"),
            f"{path}.role_hint",
        )
        if role_hint not in _V5_BLOCK_ROLE_HINTS:
            raise EbookPageNormalizationError(
                f"{path}.role_hint has unsupported v5 value {role_hint.value!r}"
            )
        dominant_language = self._optional_string(
            block_data.get("dominant_language"),
            f"{path}.dominant_language",
        )
        heading_level_hint = self._heading_level(
            block_data.get("heading_level_hint"),
            f"{path}.heading_level_hint",
        )
        heading_role_hint = self._enum_value(
            HeadingRoleHint,
            block_data.get("heading_role_hint"),
            f"{path}.heading_role_hint",
        )
        alignment = self._optional_enum_value(
            TextAlignment,
            block_data.get("alignment"),
            f"{path}.alignment",
        )
        marker = self._normalize_marker(block_data.get("marker"), f"{path}.marker")
        region = self._normalize_region(block_data.get("region"), f"{path}.region")

        raw_content = block_data.get("content")
        if not isinstance(raw_content, list):
            raise EbookPageNormalizationError(f"{path}.content must be a list")

        block_id = build_block_id(page_id, block_index)
        spans = tuple(
            self._normalize_span(block_id, span_payload, path, span_index)
            for span_index, span_payload in enumerate(raw_content)
        )

        if role_hint is not BlockRoleHint.HEADING:
            if heading_level_hint is not None:
                raise EbookPageNormalizationError(
                    f"{path}.heading_level_hint must be null for non-heading blocks"
                )
            if heading_role_hint is not HeadingRoleHint.UNKNOWN:
                raise EbookPageNormalizationError(
                    f"{path}.heading_role_hint must be 'unknown' for non-heading "
                    "blocks"
                )

        return PageBlockEvidence(
            block_id=block_id,
            sequence_index=block_index,
            role_hint=role_hint,
            spans=spans,
            dominant_language=dominant_language,
            alignment=alignment,
            heading_level_hint=heading_level_hint,
            heading_role_hint=heading_role_hint,
            marker=marker,
            region=region,
        )

    def _normalize_span(
        self,
        block_id: str,
        payload: Any,
        block_path: str,
        span_index: int,
    ) -> TextSpanEvidence:
        """Normalize one v5 span with explicit local evidence state."""
        path = f"{block_path}.content[{span_index}]"
        span_data = self._require_dict(payload, path)
        self._require_exact_keys(span_data, _SPAN_KEYS, path)

        text = span_data.get("text")
        if not isinstance(text, str):
            raise EbookPageNormalizationError(f"{path}.text must be a string")
        language = self._optional_string(span_data.get("language"), f"{path}.language")
        source_typography = self._normalize_source_typography(
            span_data.get("source_typography"),
            f"{path}.source_typography",
        )
        semantic_line_break_after = span_data.get("semantic_line_break_after")
        if not isinstance(semantic_line_break_after, bool):
            raise EbookPageNormalizationError(
                f"{path}.semantic_line_break_after must be a boolean"
            )

        return TextSpanEvidence(
            span_id=build_span_id(block_id, span_index),
            text=text,
            language=language,
            source_typography=source_typography,
            semantic_line_break_after=semantic_line_break_after,
        )

    def _normalize_source_typography(
        self,
        payload: Any,
        path: str,
    ) -> SourceTypography:
        """Normalize observed source typography without semantic interpretation."""
        typography_data = self._require_dict(payload, path)
        self._require_exact_keys(typography_data, _TYPOGRAPHY_KEYS, path)

        posture = self._enum_value(
            FontPosture,
            typography_data.get("posture"),
            f"{path}.posture",
        )
        weight = self._enum_value(
            FontWeight,
            typography_data.get("weight"),
            f"{path}.weight",
        )
        vertical_position = self._enum_value(
            VerticalPosition,
            typography_data.get("vertical_position"),
            f"{path}.vertical_position",
        )
        caps_style = self._enum_value(
            CapsStyle,
            typography_data.get("caps_style"),
            f"{path}.caps_style",
        )

        raw_decorations = typography_data.get("decorations")
        if not isinstance(raw_decorations, list):
            raise EbookPageNormalizationError(
                f"{path}.decorations must be a list"
            )

        decorations: list[TextDecoration] = []
        seen: set[TextDecoration] = set()
        for decoration_index, raw_decoration in enumerate(raw_decorations):
            decoration = self._enum_value(
                TextDecoration,
                raw_decoration,
                f"{path}.decorations[{decoration_index}]",
            )
            if decoration in seen:
                raise EbookPageNormalizationError(
                    f"{path}.decorations contains duplicate {decoration.value!r}"
                )
            seen.add(decoration)
            decorations.append(decoration)

        return SourceTypography(
            posture=posture,
            weight=weight,
            vertical_position=vertical_position,
            caps_style=caps_style,
            decorations=tuple(decorations),
        )

    def _normalize_marker(self, payload: Any, path: str) -> MarkerEvidence | None:
        """Normalize optional visual marker evidence without inferring semantics."""
        if payload is None:
            return None
        marker_data = self._require_dict(payload, path)
        self._require_exact_keys(marker_data, _MARKER_KEYS, path)

        kind = self._enum_value(MarkerKind, marker_data.get("kind"), f"{path}.kind")
        raw_text = self._optional_string(
            marker_data.get("raw_text"),
            f"{path}.raw_text",
        )
        ordinal = self._optional_positive_integer(
            marker_data.get("ordinal"),
            f"{path}.ordinal",
        )

        return MarkerEvidence(kind=kind, raw_text=raw_text, ordinal=ordinal)

    def _normalize_region(self, payload: Any, path: str) -> NormalizedRegion | None:
        """Normalize an optional source region and ensure it remains on the page."""
        if payload is None:
            return None
        region_data = self._require_dict(payload, path)
        self._require_exact_keys(region_data, _REGION_KEYS, path)

        x = self._normalized_number(region_data.get("x"), f"{path}.x")
        y = self._normalized_number(region_data.get("y"), f"{path}.y")
        width = self._normalized_number(region_data.get("width"), f"{path}.width")
        height = self._normalized_number(region_data.get("height"), f"{path}.height")

        if x + width > 1:
            raise EbookPageNormalizationError(
                f"{path}.x + {path}.width must be at most 1"
            )
        if y + height > 1:
            raise EbookPageNormalizationError(
                f"{path}.y + {path}.height must be at most 1"
            )

        return NormalizedRegion(x=x, y=y, width=width, height=height)

    @staticmethod
    def _block_to_dict(block: PageBlockEvidence) -> dict[str, Any]:
        """Serialize one typed evidence block into JSON-compatible data."""
        marker = None
        if block.marker is not None:
            marker = {
                "kind": block.marker.kind.value,
                "raw_text": block.marker.raw_text,
                "ordinal": block.marker.ordinal,
            }

        region = None
        if block.region is not None:
            region = {
                "x": block.region.x,
                "y": block.region.y,
                "width": block.region.width,
                "height": block.region.height,
            }

        return {
            "block_id": block.block_id,
            "sequence_index": block.sequence_index,
            "role_hint": block.role_hint.value,
            "content": [
                {
                    "span_id": span.span_id,
                    "text": span.text,
                    "language": span.language,
                    "source_typography": {
                        "posture": span.source_typography.posture.value,
                        "weight": span.source_typography.weight.value,
                        "vertical_position": (
                            span.source_typography.vertical_position.value
                        ),
                        "caps_style": span.source_typography.caps_style.value,
                        "decorations": [
                            decoration.value
                            for decoration in span.source_typography.decorations
                        ],
                    },
                    "semantic_line_break_after": span.semantic_line_break_after,
                }
                for span in block.spans
            ],
            "dominant_language": block.dominant_language,
            "heading_level_hint": block.heading_level_hint,
            "heading_role_hint": block.heading_role_hint.value,
            "marker": marker,
            "region": region,
            "alignment": (
                block.alignment.value if block.alignment is not None else None
            ),
        }

    @staticmethod
    def _require_dict(value: Any, path: str) -> dict[str, Any]:
        """Require an object-like dictionary at the supplied logical path."""
        if not isinstance(value, dict):
            raise EbookPageNormalizationError(f"{path} must be an object")
        return value

    @staticmethod
    def _require_exact_keys(
        value: dict[str, Any],
        expected: frozenset[str],
        path: str,
    ) -> None:
        """Require exactly the properties declared by the v5 extraction contract."""
        actual = frozenset(value)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            raise EbookPageNormalizationError(
                f"{path} is missing required fields: {', '.join(missing)}"
            )
        if extra:
            raise EbookPageNormalizationError(
                f"{path} contains unsupported fields: {', '.join(extra)}"
            )

    @staticmethod
    def _optional_string(value: Any, path: str) -> str | None:
        """Validate an optional string without silently coercing provider output."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise EbookPageNormalizationError(f"{path} must be a string or null")
        return value

    @staticmethod
    def _string_tuple(value: Any, path: str) -> tuple[str, ...]:
        """Validate a list of strings and return its immutable representation."""
        if not isinstance(value, list):
            raise EbookPageNormalizationError(f"{path} must be a list")
        if not all(isinstance(item, str) for item in value):
            raise EbookPageNormalizationError(f"{path} must contain only strings")
        return tuple(value)

    @staticmethod
    def _heading_level(value: Any, path: str) -> int | None:
        """Validate a nullable heading-level hint between one and six."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise EbookPageNormalizationError(
                f"{path} must be an integer or null"
            )
        if value < 1 or value > 6:
            raise EbookPageNormalizationError(f"{path} must be between 1 and 6")
        return value

    @staticmethod
    def _optional_positive_integer(value: Any, path: str) -> int | None:
        """Validate a nullable positive integer without accepting booleans."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise EbookPageNormalizationError(
                f"{path} must be a positive integer or null"
            )
        if value < 1:
            raise EbookPageNormalizationError(
                f"{path} must be a positive integer or null"
            )
        return value

    @staticmethod
    def _normalized_number(value: Any, path: str) -> float:
        """Validate one real coordinate in the normalized inclusive range [0, 1]."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EbookPageNormalizationError(f"{path} must be a number")
        normalized = float(value)
        if not isfinite(normalized):
            raise EbookPageNormalizationError(f"{path} must be a finite number")
        if normalized < 0 or normalized > 1:
            raise EbookPageNormalizationError(f"{path} must be between 0 and 1")
        return normalized

    @staticmethod
    def _enum_value(
        enum_type: type[EnumT],
        value: Any,
        path: str,
    ) -> EnumT:
        """Validate and convert one required string enum value."""
        if not isinstance(value, str):
            raise EbookPageNormalizationError(f"{path} must be a string")
        try:
            return enum_type(value)
        except ValueError as exc:
            raise EbookPageNormalizationError(
                f"{path} has unsupported value {value!r}"
            ) from exc

    @classmethod
    def _optional_enum_value(
        cls,
        enum_type: type[EnumT],
        value: Any,
        path: str,
    ) -> EnumT | None:
        """Validate and convert one nullable string enum value."""
        if value is None:
            return None
        return cls._enum_value(enum_type, value, path)
