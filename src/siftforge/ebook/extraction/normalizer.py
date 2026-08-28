"""Convert provider JSON into validated typed ebook page content."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypeVar

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

EnumT = TypeVar("EnumT", bound=StrEnum)


class EbookPageNormalizationError(ValueError):
    """Raised when provider output cannot become a valid ebook page model."""


class EbookPageNormalizer:
    """Validate provider data and build a typed `PageContent` model."""

    def normalize(self, page_id: str, payload: Any) -> PageContent:
        """Normalize one provider payload into typed ebook page content."""
        root = self._require_dict(payload, "page")
        page_kind = self._enum_value(PageKind, root.get("page_kind"), "page_kind")
        language = self._optional_string(root.get("language"), "language")
        printed_page_number = self._optional_string(
            root.get("printed_page_number"),
            "printed_page_number",
        )
        warnings = self._string_tuple(root.get("warnings"), "warnings")

        raw_blocks = root.get("blocks")
        if not isinstance(raw_blocks, list):
            raise EbookPageNormalizationError("blocks must be a list")

        blocks = tuple(
            self._normalize_block(block_payload, index)
            for index, block_payload in enumerate(raw_blocks)
        )

        return PageContent(
            page_id=page_id,
            page_kind=page_kind,
            language=language,
            printed_page_number=printed_page_number,
            blocks=blocks,
            warnings=warnings,
        )

    def to_dict(self, page: PageContent) -> dict[str, Any]:
        """Serialize typed page content into stable JSON-compatible data."""
        return {
            "page_id": page.page_id,
            "page_kind": page.page_kind.value,
            "language": page.language,
            "printed_page_number": page.printed_page_number,
            "blocks": [
                {
                    "type": block.type.value,
                    "content": [
                        {
                            "text": span.text,
                            "typography": {
                                "posture": span.typography.posture.value,
                                "weight": span.typography.weight.value,
                                "vertical_position": (
                                    span.typography.vertical_position.value
                                ),
                                "caps_style": span.typography.caps_style.value,
                                "decorations": [
                                    decoration.value
                                    for decoration
                                    in span.typography.decorations
                                ],
                            },
                        }
                        for span in block.content
                    ],
                    "language": block.language,
                    "level": block.level,
                    "alignment": (
                        block.alignment.value
                        if block.alignment is not None
                        else None
                    ),
                }
                for block in page.blocks
            ],
            "warnings": list(page.warnings),
        }

    def _normalize_block(self, payload: Any, index: int) -> Block:
        """Normalize one block while attaching useful path context to failures."""
        path = f"blocks[{index}]"
        block_data = self._require_dict(payload, path)
        block_type = self._enum_value(
            BlockType,
            block_data.get("type"),
            f"{path}.type",
        )
        language = self._optional_string(
            block_data.get("language"),
            f"{path}.language",
        )
        level = self._heading_level(block_data.get("level"), f"{path}.level")
        alignment = self._optional_enum_value(
            TextAlignment,
            block_data.get("alignment"),
            f"{path}.alignment",
        )

        raw_content = block_data.get("content")
        if not isinstance(raw_content, list):
            raise EbookPageNormalizationError(f"{path}.content must be a list")

        content = tuple(
            self._normalize_span(span_payload, path, span_index)
            for span_index, span_payload in enumerate(raw_content)
        )

        if block_type is not BlockType.HEADING and level is not None:
            raise EbookPageNormalizationError(
                f"{path}.level must be null for non-heading blocks"
            )

        return Block(
            type=block_type,
            content=content,
            language=language,
            level=level,
            alignment=alignment,
        )

    def _normalize_span(
        self,
        payload: Any,
        block_path: str,
        index: int,
    ) -> TextSpan:
        """Normalize one rich-text span with explicit typography state."""
        path = f"{block_path}.content[{index}]"
        span_data = self._require_dict(payload, path)

        text = span_data.get("text")
        if not isinstance(text, str):
            raise EbookPageNormalizationError(f"{path}.text must be a string")

        typography_data = self._require_dict(
            span_data.get("typography"),
            f"{path}.typography",
        )
        typography = self._normalize_typography(
            typography_data,
            f"{path}.typography",
        )
        return TextSpan(text=text, typography=typography)

    def _normalize_typography(
        self,
        payload: dict[str, Any],
        path: str,
    ) -> Typography:
        """Normalize all explicit typography dimensions for one text span."""
        posture = self._enum_value(
            FontPosture,
            payload.get("posture"),
            f"{path}.posture",
        )
        weight = self._enum_value(
            FontWeight,
            payload.get("weight"),
            f"{path}.weight",
        )
        vertical_position = self._enum_value(
            VerticalPosition,
            payload.get("vertical_position"),
            f"{path}.vertical_position",
        )
        caps_style = self._enum_value(
            CapsStyle,
            payload.get("caps_style"),
            f"{path}.caps_style",
        )

        raw_decorations = payload.get("decorations")
        if not isinstance(raw_decorations, list):
            raise EbookPageNormalizationError(
                f"{path}.decorations must be a list"
            )

        decorations: list[TextDecoration] = []
        seen: set[TextDecoration] = set()
        for index, raw_decoration in enumerate(raw_decorations):
            decoration = self._enum_value(
                TextDecoration,
                raw_decoration,
                f"{path}.decorations[{index}]",
            )
            if decoration in seen:
                raise EbookPageNormalizationError(
                    f"{path}.decorations contains duplicate {decoration.value!r}"
                )
            seen.add(decoration)
            decorations.append(decoration)

        return Typography(
            posture=posture,
            weight=weight,
            vertical_position=vertical_position,
            caps_style=caps_style,
            decorations=tuple(decorations),
        )

    @staticmethod
    def _require_dict(value: Any, path: str) -> dict[str, Any]:
        """Require an object-like dictionary at the supplied logical path."""
        if not isinstance(value, dict):
            raise EbookPageNormalizationError(f"{path} must be an object")
        return value

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
            raise EbookPageNormalizationError(
                f"{path} must contain only strings"
            )
        return tuple(value)

    @staticmethod
    def _heading_level(value: Any, path: str) -> int | None:
        """Validate a nullable heading level between one and six."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise EbookPageNormalizationError(
                f"{path} must be an integer or null"
            )
        if value < 1 or value > 6:
            raise EbookPageNormalizationError(
                f"{path} must be between 1 and 6"
            )
        return value

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
