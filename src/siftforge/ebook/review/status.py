"""Review-completeness status and strict build gating."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from siftforge.ebook.pipeline.book_assembly import (
    EbookPageRunArtifact,
    EbookPageRunLoader,
)

from .projection import project_page_text


class ReviewPageState(StrEnum):
    """Human-review state for one canonical page run."""

    NOT_REVIEWED = "not_reviewed"
    PASS = "pass"
    NEEDS_REVIEW = "needs_review"
    RESOLVED = "resolved"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class ReviewPageStatus:
    """Review status for one physical page."""

    page_id: str
    page_number: int
    state: ReviewPageState
    finding_count: int
    resolved_count: int
    unresolved_count: int
    stale_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewStatus:
    """Whole-book review completeness summary."""

    runs_root: Path
    pages: tuple[ReviewPageStatus, ...]

    @property
    def total_pages(self) -> int:
        """Return canonical page count."""
        return len(self.pages)

    @property
    def complete(self) -> bool:
        """Return whether every page was reviewed and every finding resolved."""
        return all(
            page.state in {ReviewPageState.PASS, ReviewPageState.RESOLVED}
            for page in self.pages
        )

    def count(self, state: ReviewPageState) -> int:
        """Count pages in one review state."""
        return sum(page.state is state for page in self.pages)

    @property
    def finding_count(self) -> int:
        """Return all actionable findings in current review artifacts."""
        return sum(page.finding_count for page in self.pages)

    @property
    def unresolved_count(self) -> int:
        """Return actionable findings without human decisions."""
        return sum(page.unresolved_count for page in self.pages)


class PageRunLoader(Protocol):
    """Small loader contract used by the status service and tests."""

    def discover(
        self,
        runs_root: str | Path,
    ) -> tuple[EbookPageRunArtifact, ...]:
        """Load canonical page runs."""
        ...


class ReviewStatusError(ValueError):
    """Raised when review artifacts are malformed or inconsistent."""


class ReviewStatusService:
    """Inspect additive review artifacts without changing page evidence."""

    def __init__(self, loader: PageRunLoader | None = None) -> None:
        """Initialize with the canonical page-run loader by default."""
        self._loader = loader or EbookPageRunLoader()

    def inspect(self, runs_root: str | Path) -> ReviewStatus:
        """Return page-level review status and detect stale review snapshots."""
        root = Path(runs_root).expanduser().resolve()
        page_runs = self._loader.discover(root)
        pages = tuple(self._inspect_page(page_run) for page_run in page_runs)
        return ReviewStatus(runs_root=root, pages=pages)

    def require_complete(self, runs_root: str | Path) -> ReviewStatus:
        """Fail when any canonical page still lacks a complete current review."""
        status = self.inspect(runs_root)
        if status.complete:
            return status
        counts = ", ".join(
            f"{state.value}={status.count(state)}"
            for state in ReviewPageState
            if status.count(state)
        )
        raise ReviewStatusError(
            "text review is incomplete; run review-text, resolve findings, and "
            f"import-review before strict build ({counts})"
        )

    def _inspect_page(self, page_run: EbookPageRunArtifact) -> ReviewPageStatus:
        """Inspect one page's findings and human resolutions."""
        review_dir = page_run.run_dir / "review"
        findings_path = review_dir / "findings.json"
        if not findings_path.is_file():
            return ReviewPageStatus(
                page_id=page_run.page.page_id,
                page_number=page_run.page_number,
                state=ReviewPageState.NOT_REVIEWED,
                finding_count=0,
                resolved_count=0,
                unresolved_count=0,
            )

        findings_payload = _load_object(findings_path)
        findings = _object_list(findings_payload, "findings", findings_path)
        stale = _stale_finding_reason(page_run, findings)
        if stale is not None:
            return ReviewPageStatus(
                page_id=page_run.page.page_id,
                page_number=page_run.page_number,
                state=ReviewPageState.STALE,
                finding_count=len(findings),
                resolved_count=0,
                unresolved_count=len(findings),
                stale_reason=stale,
            )
        if not findings:
            return ReviewPageStatus(
                page_id=page_run.page.page_id,
                page_number=page_run.page_number,
                state=ReviewPageState.PASS,
                finding_count=0,
                resolved_count=0,
                unresolved_count=0,
            )

        finding_ids = {_required_id(item, findings_path) for item in findings}
        resolutions_path = review_dir / "resolutions.json"
        resolved_ids: set[str] = set()
        if resolutions_path.is_file():
            payload = _load_object(resolutions_path)
            resolutions = _object_list(payload, "resolutions", resolutions_path)
            for item in resolutions:
                finding_id = _required_id(item, resolutions_path)
                if finding_id not in finding_ids:
                    return ReviewPageStatus(
                        page_id=page_run.page.page_id,
                        page_number=page_run.page_number,
                        state=ReviewPageState.STALE,
                        finding_count=len(findings),
                        resolved_count=0,
                        unresolved_count=len(findings),
                        stale_reason=(
                            "resolution references a finding that is no longer "
                            f"actionable: {finding_id}"
                        ),
                    )
                resolved_ids.add(finding_id)

        unresolved = finding_ids - resolved_ids
        state = (
            ReviewPageState.RESOLVED
            if not unresolved
            else ReviewPageState.NEEDS_REVIEW
        )
        return ReviewPageStatus(
            page_id=page_run.page.page_id,
            page_number=page_run.page_number,
            state=state,
            finding_count=len(findings),
            resolved_count=len(resolved_ids),
            unresolved_count=len(unresolved),
        )


def review_status_to_dict(status: ReviewStatus) -> dict[str, Any]:
    """Serialize review status for CI, scripts, and retained artifacts."""
    return {
        "runs_root": str(status.runs_root),
        "complete": status.complete,
        "total_pages": status.total_pages,
        "findings": status.finding_count,
        "unresolved": status.unresolved_count,
        "counts": {
            state.value: status.count(state)
            for state in ReviewPageState
        },
        "pages": [
            {
                "page_id": page.page_id,
                "page_number": page.page_number,
                "state": page.state.value,
                "findings": page.finding_count,
                "resolved": page.resolved_count,
                "unresolved": page.unresolved_count,
                "stale_reason": page.stale_reason,
            }
            for page in status.pages
        ],
    }


def _stale_finding_reason(
    page_run: EbookPageRunArtifact,
    findings: list[dict[str, Any]],
) -> str | None:
    """Return a reason when finding snapshots no longer match normalized text."""
    projection = project_page_text(page_run.page)
    for finding in findings:
        finding_id = _required_id(finding, page_run.run_dir)
        raw_range = finding.get("gemini_range")
        if not isinstance(raw_range, list) or len(raw_range) != 2:
            return f"finding {finding_id} has invalid gemini_range"
        start, end = raw_range
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
            or end > len(projection.text)
        ):
            return f"finding {finding_id} has stale gemini_range"
        expected = finding.get("gemini_text")
        if not isinstance(expected, str):
            return f"finding {finding_id} has invalid gemini_text"
        if projection.text[start:end] != expected:
            return f"finding {finding_id} no longer matches normalized page text"
    return None


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object with review-specific diagnostics."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewStatusError(f"cannot read review artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReviewStatusError(f"review artifact must be a JSON object: {path}")
    return payload


def _object_list(
    payload: dict[str, Any],
    key: str,
    path: Path,
) -> list[dict[str, Any]]:
    """Read one required list of JSON objects."""
    value = payload.get(key)
    if not isinstance(value, list):
        raise ReviewStatusError(f"{key} must be a list: {path}")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ReviewStatusError(f"{key} items must be objects: {path}")
        result.append(item)
    return result


def _required_id(item: dict[str, Any], path: Path) -> str:
    """Return one required non-empty finding identifier."""
    value = item.get("finding_id")
    if not isinstance(value, str) or not value:
        raise ReviewStatusError(f"finding_id is invalid: {path}")
    return value
