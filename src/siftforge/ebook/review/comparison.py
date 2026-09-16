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
_SENTENCE_BOUNDARIES = frozenset(".!?;\n")
_MAX_MERGE_GAP = 12


def compare_with_ocr(
    *,
    page_number: int,
    projection: ProjectedText,
    ocr: OcrPage,
) -> tuple[float, tuple[ReviewFinding, ...]]:
    """Align one projected Gemini page with independent local OCR text.

    Nearby character-level opcodes are coalesced into one human-sized phrase.
    This avoids presenting several noisy cards for one badly recognized word.
    """
    matcher = SequenceMatcher(
        None,
        projection.text,
        ocr.text,
        autojunk=False,
    )
    groups = _difference_groups(
        matcher.get_opcodes(),
        projection.text,
        ocr.text,
    )
    findings: list[ReviewFinding] = []
    for sequence, (first_start, first_end, second_start, second_end) in enumerate(
        groups,
        start=1,
    ):
        first = projection.text[first_start:first_end]
        second = ocr.text[second_start:second_end]
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
                block_role=anchor.block_role if anchor else None,
            )
        )
    return matcher.ratio(), tuple(findings)


def _difference_groups(
    opcodes: list[tuple[str, int, int, int, int]],
    first_text: str,
    second_text: str,
) -> tuple[tuple[int, int, int, int], ...]:
    """Coalesce nearby diff opcodes into phrase-level review units."""
    differences = [
        index for index, opcode in enumerate(opcodes) if opcode[0] != "equal"
    ]
    if not differences:
        return ()

    groups: list[tuple[int, int, int, int]] = []
    first_index = differences[0]
    _, first_start, first_end, second_start, second_end = opcodes[first_index]
    previous_index = first_index

    for current_index in differences[1:]:
        bridge = opcodes[previous_index + 1 : current_index]
        if _bridge_is_mergeable(bridge, first_text, second_text):
            _, _, first_end, _, second_end = opcodes[current_index]
        else:
            groups.append((first_start, first_end, second_start, second_end))
            _, first_start, first_end, second_start, second_end = opcodes[current_index]
        previous_index = current_index

    groups.append((first_start, first_end, second_start, second_end))
    return tuple(groups)


def _bridge_is_mergeable(
    bridge: list[tuple[str, int, int, int, int]],
    first_text: str,
    second_text: str,
) -> bool:
    """Return whether equal text between diffs is short enough to group."""
    if not bridge:
        return True
    if any(item[0] != "equal" for item in bridge):
        return False
    for _, first_start, first_end, second_start, second_end in bridge:
        first_gap = first_text[first_start:first_end]
        second_gap = second_text[second_start:second_end]
        if max(len(first_gap), len(second_gap)) > _MAX_MERGE_GAP:
            return False
        if any(char in _SENTENCE_BOUNDARIES for char in first_gap + second_gap):
            return False
    return True


def _classify_difference(first: str, second: str) -> ReviewKind:
    """Classify a localized alignment range for review display."""
    if _same_without_whitespace(first, second):
        return ReviewKind.WHITESPACE
    if not first and second.isspace():
        return ReviewKind.WHITESPACE
    if not second and first.isspace():
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


def _same_without_whitespace(first: str, second: str) -> bool:
    """Return whether two non-identical strings differ only in whitespace."""
    if first == second:
        return False
    return "".join(first.split()) == "".join(second.split())


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
