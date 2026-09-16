"""Import human review decisions and compile safe text-correction overlays."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from siftforge.ebook.pipeline.book_assembly import EbookPageRunLoader

from .models import ProjectedText
from .projection import project_page_text

_RESOLUTION_FORMAT = "siftforge-text-review-resolutions"
_RESOLUTION_VERSION = 1
_RESOLUTION_MODEL = "TextFidelityResolution-v1"
_CORRECTION_MODEL = "TextCorrectionOverlay-v1"


class ReviewDecision(StrEnum):
    """Human decision for one actionable review finding."""

    KEEP_SOURCE = "keep_source"
    USE_OCR = "use_ocr"
    USE_SUGGESTION = "use_suggestion"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ReviewImportResult:
    """Persisted result of importing one exported browser review file."""

    runs_root: Path
    source_path: Path
    aggregate_path: Path
    resolved_count: int
    correction_count: int
    pages_touched: int


class ReviewResolutionError(ValueError):
    """Raised when human review decisions are invalid or stale."""


def import_review_resolutions(
    runs_root: str | Path,
    source_path: str | Path,
) -> ReviewImportResult:
    """Validate browser-exported review decisions and persist page overlays."""
    root = Path(runs_root).expanduser().resolve()
    source = Path(source_path).expanduser().resolve()
    payload = _load_object(source)
    _validate_export_header(payload)
    raw_resolutions = payload.get("resolutions")
    if not isinstance(raw_resolutions, list):
        raise ReviewResolutionError("resolutions must be a list")

    page_runs = EbookPageRunLoader().discover(root)
    run_by_page_id = {item.page.page_id: item for item in page_runs}
    finding_index = _load_finding_index(page_runs)

    canonical: list[dict[str, Any]] = []
    page_resolutions: dict[str, list[dict[str, Any]]] = {}
    page_corrections: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()

    for index, raw in enumerate(raw_resolutions):
        if not isinstance(raw, dict):
            raise ReviewResolutionError(f"resolutions[{index}] must be an object")
        finding_id = _required_string(raw, "finding_id", index)
        if finding_id in seen:
            raise ReviewResolutionError(f"duplicate finding_id: {finding_id}")
        seen.add(finding_id)
        finding = finding_index.get(finding_id)
        if finding is None:
            raise ReviewResolutionError(
                f"resolution references unknown or non-actionable finding: {finding_id}"
            )
        page_id = _required_string(finding, "page_id", index)
        page_run = run_by_page_id.get(page_id)
        if page_run is None:
            raise ReviewResolutionError(
                f"finding {finding_id} references unknown page_id {page_id!r}"
            )
        decision = _decision(raw.get("decision"), finding_id)
        replacement = _replacement_text(raw, finding, decision)
        gemini_range = _range_pair(finding.get("gemini_range"), finding_id)
        projection = project_page_text(page_run.page)
        _validate_finding_snapshot(projection, finding, gemini_range, finding_id)
        target = _span_target(projection, gemini_range, finding_id)

        canonical_item = {
            "finding_id": finding_id,
            "page_id": page_id,
            "page_number": finding.get("page_number"),
            "decision": decision.value,
            "gemini_range": list(gemini_range),
            "gemini_text": finding.get("gemini_text"),
            "replacement_text": replacement,
            "block_id": finding.get("block_id"),
            "span_id": target[0] if target is not None else finding.get("span_id"),
        }
        canonical.append(canonical_item)
        page_resolutions.setdefault(page_id, []).append(canonical_item)

        if decision is ReviewDecision.KEEP_SOURCE:
            continue
        if target is None:
            raise ReviewResolutionError(
                f"finding {finding_id} cannot be mapped to one editable text span"
            )
        span_id, span_start, span_end = target
        original_text = _required_finding_text(finding, finding_id)
        page_corrections.setdefault(page_id, []).append(
            {
                "finding_id": finding_id,
                "decision": decision.value,
                "span_id": span_id,
                "span_start": span_start,
                "span_end": span_end,
                "original_text": original_text,
                "replacement_text": replacement,
            }
        )

    # Treat each imported file as the authoritative decision set. Clearing
    # older page-local overlays prevents aggregate provenance from drifting
    # away from what later EPUB builds actually apply.
    for page_run in page_runs:
        for name in ("resolutions.json", "corrections.json"):
            stale = page_run.run_dir / "review" / name
            if stale.is_file():
                stale.unlink()

    review_root = root / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    aggregate_path = review_root / "resolutions.json"
    aggregate_payload = {
        "resolution_model": _RESOLUTION_MODEL,
        "source_format": _RESOLUTION_FORMAT,
        "source_version": _RESOLUTION_VERSION,
        "resolutions": canonical,
    }
    _write_json(aggregate_path, aggregate_payload)

    touched = 0
    for page_run in page_runs:
        page_id = page_run.page.page_id
        resolutions = page_resolutions.get(page_id)
        corrections = page_corrections.get(page_id)
        review_dir = page_run.run_dir / "review"
        resolutions_path = review_dir / "resolutions.json"
        corrections_path = review_dir / "corrections.json"
        if resolutions is None:
            continue
        review_dir.mkdir(parents=True, exist_ok=True)
        touched += 1
        _write_json(
            resolutions_path,
            {
                "resolution_model": _RESOLUTION_MODEL,
                "page_id": page_id,
                "page_number": page_run.page_number,
                "resolutions": resolutions,
            },
        )
        _write_json(
            corrections_path,
            {
                "correction_model": _CORRECTION_MODEL,
                "page_id": page_id,
                "page_number": page_run.page_number,
                "corrections": corrections or [],
            },
        )

    return ReviewImportResult(
        runs_root=root,
        source_path=source,
        aggregate_path=aggregate_path,
        resolved_count=len(canonical),
        correction_count=sum(len(items) for items in page_corrections.values()),
        pages_touched=touched,
    )


def _load_finding_index(page_runs: tuple[Any, ...]) -> dict[str, dict[str, Any]]:
    """Load actionable finding snapshots from canonical page review artifacts."""
    findings: dict[str, dict[str, Any]] = {}
    for page_run in page_runs:
        path = page_run.run_dir / "review" / "findings.json"
        if not path.is_file():
            continue
        payload = _load_object(path)
        raw_findings = payload.get("findings")
        if not isinstance(raw_findings, list):
            raise ReviewResolutionError(f"findings must be a list: {path}")
        for item in raw_findings:
            if not isinstance(item, dict):
                raise ReviewResolutionError(f"finding must be an object: {path}")
            finding_id = item.get("finding_id")
            if not isinstance(finding_id, str) or not finding_id:
                raise ReviewResolutionError(f"finding_id is invalid: {path}")
            if finding_id in findings:
                raise ReviewResolutionError(f"duplicate finding_id: {finding_id}")
            findings[finding_id] = item
    return findings


def _validate_export_header(payload: dict[str, Any]) -> None:
    """Validate the small browser-export contract before reading decisions."""
    if payload.get("format") != _RESOLUTION_FORMAT:
        raise ReviewResolutionError(
            f"unsupported resolution format: {payload.get('format')!r}"
        )
    if payload.get("version") != _RESOLUTION_VERSION:
        raise ReviewResolutionError(
            f"unsupported resolution version: {payload.get('version')!r}"
        )


def _validate_finding_snapshot(
    projection: ProjectedText,
    finding: dict[str, Any],
    gemini_range: tuple[int, int],
    finding_id: str,
) -> None:
    """Fail if a resolution was exported for different normalized page text."""
    start, end = gemini_range
    if end > len(projection.text):
        raise ReviewResolutionError(f"stale range for finding {finding_id}")
    observed = projection.text[start:end]
    expected = _required_finding_text(finding, finding_id)
    if observed != expected:
        raise ReviewResolutionError(
            f"stale finding {finding_id}: expected {expected!r}, found {observed!r}"
        )


def _span_target(
    projection: ProjectedText,
    gemini_range: tuple[int, int],
    finding_id: str,
) -> tuple[str, int, int] | None:
    """Map one projected range back to one deterministic normalized text span."""
    start, end = gemini_range
    if start == end:
        next_anchor = (
            projection.anchors[start]
            if start < len(projection.anchors)
            else None
        )
        if next_anchor is not None:
            return next_anchor.span_id, next_anchor.span_offset, next_anchor.span_offset
        previous_anchor = (
            projection.anchors[start - 1]
            if start > 0 and start - 1 < len(projection.anchors)
            else None
        )
        if previous_anchor is not None:
            offset = previous_anchor.span_offset + 1
            return previous_anchor.span_id, offset, offset
        return None

    anchors = [
        anchor
        for anchor in projection.anchors[start:end]
        if anchor is not None
    ]
    if not anchors:
        return None
    span_ids = {anchor.span_id for anchor in anchors}
    if len(span_ids) != 1:
        return None
    offsets = [anchor.span_offset for anchor in anchors]
    low = min(offsets)
    high = max(offsets) + 1
    expected_offsets = set(range(low, high))
    if set(offsets) != expected_offsets:
        raise ReviewResolutionError(
            f"finding {finding_id} maps to a non-contiguous source span"
        )
    return anchors[0].span_id, low, high


def _replacement_text(
    raw: dict[str, Any],
    finding: dict[str, Any],
    decision: ReviewDecision,
) -> str:
    """Resolve one explicit human decision to its final replacement string."""
    if decision is ReviewDecision.KEEP_SOURCE:
        return _required_finding_text(finding, str(finding.get("finding_id")))
    if decision is ReviewDecision.USE_OCR:
        value = finding.get("reference_text")
        if not isinstance(value, str):
            raise ReviewResolutionError("OCR replacement is unavailable")
        if finding.get("source") != "local_ocr":
            raise ReviewResolutionError("use_ocr requires a local_ocr finding")
        return value
    if decision is ReviewDecision.USE_SUGGESTION:
        value = finding.get("suggested_text")
        if not isinstance(value, str):
            raise ReviewResolutionError("heuristic suggestion is unavailable")
        return value
    value = raw.get("replacement_text")
    if not isinstance(value, str):
        raise ReviewResolutionError(
            "manual decisions require a string replacement_text"
        )
    return value


def _decision(value: Any, finding_id: str) -> ReviewDecision:
    """Parse one review decision with finding-specific diagnostics."""
    try:
        return ReviewDecision(value)
    except (TypeError, ValueError) as exc:
        raise ReviewResolutionError(
            f"finding {finding_id} has invalid decision {value!r}"
        ) from exc


def _range_pair(value: Any, finding_id: str) -> tuple[int, int]:
    """Parse one serialized Gemini projected-text range."""
    if not isinstance(value, list) or len(value) != 2:
        raise ReviewResolutionError(f"finding {finding_id} has invalid gemini_range")
    start, end = value
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end < start
    ):
        raise ReviewResolutionError(f"finding {finding_id} has invalid gemini_range")
    return start, end


def _required_finding_text(finding: dict[str, Any], finding_id: str) -> str:
    """Return the exact projected source slice stored with one finding."""
    value = finding.get("gemini_text")
    if not isinstance(value, str):
        raise ReviewResolutionError(f"finding {finding_id} has invalid gemini_text")
    return value


def _required_string(payload: dict[str, Any], key: str, index: int) -> str:
    """Return one required non-empty string from an exported resolution."""
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ReviewResolutionError(
            f"resolutions[{index}].{key} must be a non-empty string"
        )
    return value


def _load_object(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object with review-specific error reporting."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReviewResolutionError(f"missing review artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewResolutionError(f"invalid JSON review artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise ReviewResolutionError(f"review artifact must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist deterministic UTF-8 JSON with a trailing newline."""
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
