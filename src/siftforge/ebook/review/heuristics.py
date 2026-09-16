"""Conservative textual heuristics that flag, but never repair, source text."""

from __future__ import annotations

from .models import (
    ProjectedText,
    ReviewFinding,
    ReviewKind,
    ReviewSeverity,
    ReviewSource,
)
from .projection import anchor_for_range


def find_suspicious_boundaries(
    *,
    page_number: int,
    projection: ProjectedText,
) -> tuple[ReviewFinding, ...]:
    """Flag likely missing spaces even when Gemini and OCR agree.

    These checks intentionally create review candidates only. They do not claim
    the source is wrong and they never mutate normalized extraction artifacts.
    """
    findings: list[ReviewFinding] = []
    sequence = 0
    text = projection.text
    for index in range(1, len(text)):
        previous = text[index - 1]
        current = text[index]
        suggested: str | None = None
        if previous.isalpha() and current.isdigit():
            suggested = _insert_space_at(text, index)
        elif (
            index >= 2
            and text[index - 1] == "."
            and text[index - 2].islower()
            and current.isupper()
        ):
            suggested = _insert_space_at(text, index)
        if suggested is None:
            continue
        token_start, token_end = _token_window(text, index)
        observed = text[token_start:token_end]
        replacement = suggested[token_start : token_end + 1]
        sequence += 1
        anchor = anchor_for_range(projection, token_start, token_end)
        findings.append(
            ReviewFinding(
                finding_id=f"page-{page_number:04d}-heur-{sequence:04d}",
                page_id=(anchor.page_id if anchor else ""),
                page_number=page_number,
                source=ReviewSource.HEURISTIC,
                kind=ReviewKind.SUSPICIOUS_BOUNDARY,
                severity=ReviewSeverity.MAJOR,
                gemini_start=token_start,
                gemini_end=token_end,
                reference_start=None,
                reference_end=None,
                gemini_text=observed,
                reference_text="",
                block_id=anchor.block_id if anchor else None,
                span_id=anchor.span_id if anchor else None,
                block_role=anchor.block_role if anchor else None,
                suggested_text=replacement,
            )
        )
    return tuple(findings)


def _insert_space_at(text: str, index: int) -> str:
    """Return an in-memory suggestion with one boundary space inserted."""
    return f"{text[:index]} {text[index:]}"


def _token_window(text: str, boundary: int) -> tuple[int, int]:
    """Expand a suspicious boundary to a short human-readable token window."""
    start = boundary - 1
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    end = boundary
    while end < len(text) and not text[end].isspace():
        end += 1
    return start, end
