"""Character-level alignment for Gemini extraction versus local OCR."""

from __future__ import annotations

import string
from difflib import SequenceMatcher

from .models import (
    OcrPage,
    ProjectedText,
    ReviewFinding,
    ReviewKind,
    ReviewSeverity,
    ReviewSource,
)
from .projection import anchor_for_range

_PUNCTUATION = frozenset(string.punctuation + "“”‘’«»…–—")


def compare_with_ocr(
    *,
    page_number: int,
    projection: ProjectedText,
    ocr: OcrPage,
) -> tuple[float, tuple[ReviewFinding, ...]]:
    """Align one projected Gemini page with independent local OCR text."""
    matcher = SequenceMatcher(
        None,
        projection.text,
        ocr.text,
        autojunk=False,
    )
    findings: list[ReviewFinding] = []
    sequence = 0
    for tag, first_start, first_end, second_start, second_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        first = projection.text[first_start:first_end]
        second = ocr.text[second_start:second_end]
        sequence += 1
        kind = _classify_difference(first, second)
        severity = _severity(kind, first, second)
        anchor = anchor_for_range(projection, first_start, first_end)
        findings.append(
            ReviewFinding(
                finding_id=f"page-{page_number:04d}-ocr-{sequence:04d}",
                page_id=(anchor.page_id if anchor else ""),
                page_number=page_number,
                source=ReviewSource.OCR,
                kind=kind,
                severity=severity,
                gemini_start=first_start,
                gemini_end=first_end,
                reference_start=second_start,
                reference_end=second_end,
                gemini_text=first,
                reference_text=second,
                block_id=anchor.block_id if anchor else None,
                span_id=anchor.span_id if anchor else None,
            )
        )
    return matcher.ratio(), tuple(findings)


def _classify_difference(first: str, second: str) -> ReviewKind:
    """Classify a localized alignment opcode for review display."""
    if not first and second.isspace():
        return ReviewKind.WHITESPACE
    if not second and first.isspace():
        return ReviewKind.WHITESPACE
    if first and second and first.strip() == second.strip():
        return ReviewKind.WHITESPACE
    if not first:
        return ReviewKind.MISSING_TEXT
    if not second:
        return ReviewKind.EXTRA_TEXT
    if _all_punctuation(first) and _all_punctuation(second):
        return ReviewKind.PUNCTUATION
    if len(first) <= 2 and len(second) <= 2:
        return ReviewKind.CHARACTER
    return ReviewKind.REPLACEMENT


def _all_punctuation(value: str) -> bool:
    """Return whether all non-space characters are punctuation."""
    stripped = value.replace(" ", "")
    return bool(stripped) and all(char in _PUNCTUATION for char in stripped)


def _severity(kind: ReviewKind, first: str, second: str) -> ReviewSeverity:
    """Assign a simple human-review priority without auto-correcting text."""
    if kind in {ReviewKind.WHITESPACE, ReviewKind.PUNCTUATION}:
        return ReviewSeverity.MINOR
    if max(len(first), len(second)) <= 2:
        return ReviewSeverity.MINOR
    return ReviewSeverity.MAJOR
