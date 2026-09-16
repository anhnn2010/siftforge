"""Incremental cache helpers for local-OCR text review."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from siftforge.ebook.pipeline.book_assembly import EbookPageRunArtifact

from .filtering import ReviewFilterConfig
from .models import (
    TEXT_REVIEW_MODEL,
    OcrPage,
    OcrWord,
    PageReviewResult,
    ProjectedText,
    ReviewFinding,
    ReviewKind,
    ReviewSeverity,
    ReviewSource,
)


def build_review_input_fingerprint(
    *,
    page_run: EbookPageRunArtifact,
    projection: ProjectedText,
    output_dir: Path,
    ocr_cache_key: str,
    filter_config: ReviewFilterConfig,
) -> str:
    """Hash every input that can materially change a page review result."""
    digest = hashlib.sha256()
    _update(digest, TEXT_REVIEW_MODEL)
    _update(digest, ocr_cache_key)
    _update(digest, output_dir.resolve().as_posix())
    _update(
        digest,
        json.dumps(asdict(filter_config), sort_keys=True, separators=(",", ":")),
    )

    normalized = page_run.run_dir / "normalized" / "page.json"
    if normalized.is_file():
        _update_bytes(digest, normalized.read_bytes())
    else:
        _update(digest, projection.text)
        for anchor in projection.anchors:
            if anchor is None:
                _update(digest, "-")
                continue
            _update(
                digest,
                "|".join(
                    (
                        anchor.page_id,
                        anchor.block_id,
                        anchor.span_id,
                        str(anchor.span_offset),
                        anchor.block_role,
                    )
                ),
            )

    _update_bytes(digest, page_run.source_image.read_bytes())
    return digest.hexdigest()


def load_cached_page_review(
    *,
    page_run: EbookPageRunArtifact,
    projection: ProjectedText,
    expected_fingerprint: str,
) -> PageReviewResult | None:
    """Reload a current page review, or return ``None`` when it is stale."""
    review_dir = page_run.run_dir / "review"
    findings_path = review_dir / "findings.json"
    ocr_path = review_dir / "ocr.json"
    if not findings_path.is_file() or not ocr_path.is_file():
        return None
    try:
        findings_payload = _load_object(findings_path)
        ocr_payload = _load_object(ocr_path)
        if findings_payload.get("review_model") != TEXT_REVIEW_MODEL:
            return None
        if findings_payload.get("input_fingerprint") != expected_fingerprint:
            return None
        if ocr_payload.get("input_fingerprint") != expected_fingerprint:
            return None
        if findings_payload.get("page_id") != page_run.page.page_id:
            return None
        ocr = _parse_ocr(ocr_payload)
        findings = _parse_findings(findings_payload.get("findings"))
        suppressed = _parse_findings(findings_payload.get("suppressed_findings"))
        similarity = findings_payload.get("ocr_similarity")
        if isinstance(similarity, bool) or not isinstance(similarity, (int, float)):
            return None
        return PageReviewResult(
            page_id=page_run.page.page_id,
            page_number=page_run.page_number,
            gemini_text=projection.text,
            ocr_text=ocr.text,
            ocr_similarity=float(similarity),
            findings=findings,
            suppressed_findings=suppressed,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def review_cache_metadata(
    *,
    input_fingerprint: str,
    ocr_cache_key: str,
    filter_config: ReviewFilterConfig,
) -> dict[str, Any]:
    """Return auditable cache metadata shared by page review artifacts."""
    return {
        "review_model": TEXT_REVIEW_MODEL,
        "input_fingerprint": input_fingerprint,
        "ocr_cache_key": ocr_cache_key,
        "filter_config": asdict(filter_config),
    }


def _parse_ocr(payload: dict[str, Any]) -> OcrPage:
    """Deserialize persisted local OCR evidence for report regeneration."""
    text = payload.get("text")
    engine = payload.get("engine")
    language = payload.get("language")
    raw_words = payload.get("words")
    if not all(isinstance(item, str) for item in (text, engine, language)):
        raise ValueError("cached OCR header is invalid")
    if not isinstance(raw_words, list):
        raise ValueError("cached OCR words must be a list")
    words: list[OcrWord] = []
    for item in raw_words:
        if not isinstance(item, dict):
            raise ValueError("cached OCR word must be an object")
        box = item.get("box")
        text_range = item.get("range")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("cached OCR box is invalid")
        if not isinstance(text_range, list) or len(text_range) != 2:
            raise ValueError("cached OCR range is invalid")
        word_text = item.get("text")
        confidence = item.get("confidence")
        if not isinstance(word_text, str):
            raise ValueError("cached OCR text is invalid")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("cached OCR confidence is invalid")
        integers = (*box, *text_range)
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in integers
        ):
            raise ValueError("cached OCR coordinates are invalid")
        words.append(
            OcrWord(
                text=word_text,
                confidence=float(confidence),
                left=box[0],
                top=box[1],
                width=box[2],
                height=box[3],
                start=text_range[0],
                end=text_range[1],
            )
        )
    return OcrPage(
        text=text,
        words=tuple(words),
        engine=engine,
        language=language,
    )


def _parse_findings(value: Any) -> tuple[ReviewFinding, ...]:
    """Deserialize finding snapshots retained by the page review cache."""
    if not isinstance(value, list):
        raise ValueError("cached findings must be a list")
    return tuple(_parse_finding(item) for item in value)


def _parse_finding(value: Any) -> ReviewFinding:
    """Deserialize one review finding with strict enum and range checks."""
    if not isinstance(value, dict):
        raise ValueError("cached finding must be an object")
    gemini_range = _pair(value.get("gemini_range"), "gemini_range")
    reference_raw = value.get("reference_range")
    reference_range = (
        None if reference_raw is None else _pair(reference_raw, "reference_range")
    )
    page_number = value.get("page_number")
    if isinstance(page_number, bool) or not isinstance(page_number, int):
        raise ValueError("cached finding page_number is invalid")
    confidence = value.get("ocr_confidence")
    if confidence is not None and (
        isinstance(confidence, bool) or not isinstance(confidence, (int, float))
    ):
        raise ValueError("cached finding OCR confidence is invalid")
    return ReviewFinding(
        finding_id=_string(value, "finding_id"),
        page_id=_string(value, "page_id"),
        page_number=page_number,
        source=ReviewSource(_string(value, "source")),
        kind=ReviewKind(_string(value, "kind")),
        severity=ReviewSeverity(_string(value, "severity")),
        gemini_start=gemini_range[0],
        gemini_end=gemini_range[1],
        reference_start=(reference_range[0] if reference_range else None),
        reference_end=(reference_range[1] if reference_range else None),
        gemini_text=_string(value, "gemini_text", allow_empty=True),
        reference_text=_string(value, "reference_text", allow_empty=True),
        block_id=_optional_string(value.get("block_id")),
        span_id=_optional_string(value.get("span_id")),
        block_role=_optional_string(value.get("block_role")),
        suggested_text=_optional_string(value.get("suggested_text"), allow_empty=True),
        crop_path=_optional_string(value.get("crop_path")),
        ocr_confidence=(float(confidence) if confidence is not None else None),
        suppressed_reason=_optional_string(value.get("suppressed_reason")),
    )


def _load_object(path: Path) -> dict[str, Any]:
    """Load one cached JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"cached artifact must be an object: {path}")
    return payload


def _pair(value: Any, name: str) -> tuple[int, int]:
    """Return one two-integer range."""
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"cached finding {name} is invalid")
    start, end = value
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ValueError(f"cached finding {name} is invalid")
    if start < 0 or end < start:
        raise ValueError(f"cached finding {name} is invalid")
    return start, end


def _string(payload: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    """Return a required cached string."""
    value = payload.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"cached finding {key} is invalid")
    return value


def _optional_string(value: Any, *, allow_empty: bool = False) -> str | None:
    """Return an optional cached string."""
    if value is None:
        return None
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError("cached optional string is invalid")
    return value


def _update(digest: Any, value: str) -> None:
    """Add a length-delimited UTF-8 value to a SHA-256 digest."""
    _update_bytes(digest, value.encode("utf-8"))


def _update_bytes(digest: Any, value: bytes) -> None:
    """Add length-delimited bytes to avoid accidental concatenation aliases."""
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)
