"""Apply reviewed text corrections as immutable overlays on page evidence."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import PageBlockEvidence, PageExtraction, TextSpanEvidence

_CORRECTION_MODEL = "TextCorrectionOverlay-v1"


class TextCorrectionError(ValueError):
    """Raised when a persisted text correction no longer matches its source."""


def apply_text_corrections(
    page: PageExtraction,
    payload: dict[str, Any],
) -> PageExtraction:
    """Return page evidence with validated review corrections overlaid.

    The normalized Gemini artifact remains immutable on disk. Every correction
    targets one deterministic span and carries the original text slice so stale
    review decisions fail loudly after a re-extraction.
    """
    if payload.get("correction_model") != _CORRECTION_MODEL:
        raise TextCorrectionError(
            f"unsupported correction model: {payload.get('correction_model')!r}"
        )
    if payload.get("page_id") != page.page_id:
        raise TextCorrectionError("correction page_id does not match page evidence")
    raw_corrections = payload.get("corrections")
    if not isinstance(raw_corrections, list):
        raise TextCorrectionError("corrections must be a list")

    edits_by_span: dict[str, list[tuple[int, int, str, str]]] = {}
    for index, item in enumerate(raw_corrections):
        if not isinstance(item, dict):
            raise TextCorrectionError(f"corrections[{index}] must be an object")
        span_id = _required_string(item, "span_id", index)
        start = _non_negative_int(item, "span_start", index)
        end = _non_negative_int(item, "span_end", index)
        if end < start:
            raise TextCorrectionError(
                f"corrections[{index}].span_end must be >= span_start"
            )
        original = _string(item, "original_text", index)
        replacement = _string(item, "replacement_text", index)
        edits_by_span.setdefault(span_id, []).append(
            (start, end, original, replacement)
        )

    known_span_ids = {
        span.span_id for block in page.blocks for span in block.spans
    }
    unknown = sorted(set(edits_by_span) - known_span_ids)
    if unknown:
        raise TextCorrectionError(
            f"corrections reference unknown span IDs: {', '.join(unknown)}"
        )

    updated_blocks = tuple(
        _apply_block_corrections(block, edits_by_span)
        for block in page.blocks
    )
    return replace(page, blocks=updated_blocks)


def _apply_block_corrections(
    block: PageBlockEvidence,
    edits_by_span: dict[str, list[tuple[int, int, str, str]]],
) -> PageBlockEvidence:
    """Apply all relevant span-local edits without altering span semantics."""
    spans = tuple(
        _apply_span_corrections(span, edits_by_span.get(span.span_id, []))
        for span in block.spans
    )
    return replace(block, spans=spans)


def _apply_span_corrections(
    span: TextSpanEvidence,
    edits: list[tuple[int, int, str, str]],
) -> TextSpanEvidence:
    """Apply non-overlapping edits from right to left after drift checks."""
    if not edits:
        return span
    ordered = sorted(edits, key=lambda item: (item[0], item[1]))
    previous_end = -1
    for start, end, original, _ in ordered:
        if start < previous_end:
            raise TextCorrectionError(
                f"overlapping corrections for span {span.span_id}"
            )
        if end > len(span.text):
            raise TextCorrectionError(
                f"correction range exceeds span {span.span_id}"
            )
        if span.text[start:end] != original:
            raise TextCorrectionError(
                f"stale correction for span {span.span_id}: expected "
                f"{original!r} at {start}:{end}"
            )
        previous_end = end

    text = span.text
    for start, end, _, replacement in reversed(ordered):
        text = f"{text[:start]}{replacement}{text[end:]}"
    return replace(span, text=text)


def _required_string(payload: dict[str, Any], key: str, index: int) -> str:
    """Return one required non-empty correction string field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise TextCorrectionError(
            f"corrections[{index}].{key} must be a non-empty string"
        )
    return value


def _string(payload: dict[str, Any], key: str, index: int) -> str:
    """Return one required correction string, including an empty edit value."""
    value = payload.get(key)
    if not isinstance(value, str):
        raise TextCorrectionError(
            f"corrections[{index}].{key} must be a string"
        )
    return value


def _non_negative_int(payload: dict[str, Any], key: str, index: int) -> int:
    """Return one non-negative integer without accepting booleans."""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TextCorrectionError(
            f"corrections[{index}].{key} must be a non-negative integer"
        )
    return value
