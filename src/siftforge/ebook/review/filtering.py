"""Reduce low-value local-OCR review noise without hiding provenance."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace

from .models import OcrPage, OcrWord, ReviewFinding, ReviewKind

_HIGH_RISK_ROLES = frozenset({"heading", "other", "unknown"})


@dataclass(frozen=True, slots=True)
class ReviewFilterConfig:
    """Thresholds used to keep OCR findings worth human attention."""

    enabled: bool = True
    minimum_ocr_confidence: float = 85.0
    minimum_heading_ocr_confidence: float = 92.0
    minimum_punctuation_ocr_confidence: float = 95.0
    minimum_short_ocr_confidence: float = 97.0

    def __post_init__(self) -> None:
        """Reject invalid confidence thresholds early."""
        for name, value in (
            ("minimum_ocr_confidence", self.minimum_ocr_confidence),
            ("minimum_heading_ocr_confidence", self.minimum_heading_ocr_confidence),
            (
                "minimum_punctuation_ocr_confidence",
                self.minimum_punctuation_ocr_confidence,
            ),
            ("minimum_short_ocr_confidence", self.minimum_short_ocr_confidence),
        ):
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} must be between 0 and 100")


def filter_ocr_findings(
    *,
    ocr: OcrPage,
    ocr_findings: tuple[ReviewFinding, ...],
    heuristic_findings: tuple[ReviewFinding, ...],
    config: ReviewFilterConfig,
) -> tuple[tuple[ReviewFinding, ...], tuple[ReviewFinding, ...]]:
    """Split OCR differences into actionable findings and suppressed noise.

    Heuristic findings are independent signals and are never suppressed here.
    OCR findings remain serialized even when hidden from the default HTML report.
    """
    kept: list[ReviewFinding] = []
    suppressed: list[ReviewFinding] = []
    for finding in ocr_findings:
        confidence = confidence_for_finding(ocr, finding)
        enriched = replace(finding, ocr_confidence=confidence)
        reason = _suppression_reason(enriched, heuristic_findings, config)
        if reason is None:
            kept.append(enriched)
        else:
            suppressed.append(replace(enriched, suppressed_reason=reason))
    return tuple(kept), tuple(suppressed)


def confidence_for_finding(ocr: OcrPage, finding: ReviewFinding) -> float | None:
    """Return conservative confidence from OCR words supporting one finding."""
    words = words_for_finding(ocr, finding)
    if not words:
        return None
    return min(word.confidence for word in words)


def words_for_finding(
    ocr: OcrPage,
    finding: ReviewFinding,
) -> tuple[OcrWord, ...]:
    """Return OCR words overlapping or immediately neighboring a diff range."""
    if finding.reference_start is None or finding.reference_end is None:
        return ()
    start = finding.reference_start
    end = finding.reference_end
    direct = tuple(
        word
        for word in ocr.words
        if word.end > start and word.start < max(end, start + 1)
    )
    if direct:
        return direct

    before = [word for word in ocr.words if word.end <= start]
    after = [word for word in ocr.words if word.start >= end]
    neighbors: list[OcrWord] = []
    if before:
        nearest_before = max(before, key=lambda word: word.end)
        if start - nearest_before.end <= 2:
            neighbors.append(nearest_before)
    if after:
        nearest_after = min(after, key=lambda word: word.start)
        if nearest_after.start - end <= 2:
            neighbors.append(nearest_after)
    return tuple(neighbors)


def _suppression_reason(
    finding: ReviewFinding,
    heuristic_findings: tuple[ReviewFinding, ...],
    config: ReviewFilterConfig,
) -> str | None:
    """Return an audit reason when an OCR finding is too noisy to show."""
    if not config.enabled:
        return None
    if any(_overlaps(finding, heuristic) for heuristic in heuristic_findings):
        return "covered_by_heuristic"
    if _looks_like_ocr_diacritic_loss(finding):
        return "ocr_diacritic_loss"
    confidence = finding.ocr_confidence
    if confidence is None:
        return None
    threshold = config.minimum_ocr_confidence
    if finding.block_role in _HIGH_RISK_ROLES:
        threshold = max(threshold, config.minimum_heading_ocr_confidence)
    if finding.kind is ReviewKind.PUNCTUATION:
        threshold = max(threshold, config.minimum_punctuation_ocr_confidence)
    if _is_short_difference(finding):
        threshold = max(threshold, config.minimum_short_ocr_confidence)
    if confidence < threshold:
        return f"ocr_confidence_below_{threshold:g}"
    return None


def _overlaps(first: ReviewFinding, second: ReviewFinding) -> bool:
    """Return whether two Gemini-side findings refer to the same local area."""
    if first.page_number != second.page_number:
        return False
    if first.block_id and second.block_id and first.block_id != second.block_id:
        return False
    first_start = first.gemini_start
    first_end = max(first.gemini_end, first_start + 1)
    second_start = second.gemini_start
    second_end = max(second.gemini_end, second_start + 1)
    return first_end > second_start and second_end > first_start


def _is_short_difference(finding: ReviewFinding) -> bool:
    """Return whether one OCR disagreement is only one or two characters."""
    longest = max(
        len(finding.gemini_text.strip()),
        len(finding.reference_text.strip()),
    )
    return longest <= 2


def _looks_like_ocr_diacritic_loss(finding: ReviewFinding) -> bool:
    """Suppress the common case where OCR drops accents Gemini preserved."""
    gemini = finding.gemini_text
    reference = finding.reference_text
    if not gemini or not reference:
        return False
    if _fold_diacritics(gemini) != _fold_diacritics(reference):
        return False
    return _diacritic_weight(gemini) > _diacritic_weight(reference)


def _fold_diacritics(value: str) -> str:
    """Fold accents for noise detection without changing persisted text."""
    normalized = unicodedata.normalize("NFD", value.casefold())
    folded = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return folded.replace("đ", "d")


def _diacritic_weight(value: str) -> int:
    """Count accent evidence, including Vietnamese đ/Đ."""
    decomposed = unicodedata.normalize("NFD", value)
    marks = sum(unicodedata.category(char) == "Mn" for char in decomposed)
    return marks + sum(char in "đĐ" for char in value)
