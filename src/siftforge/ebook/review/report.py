"""Persist machine-readable and human-readable text-review reports."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .models import PageReviewResult, ReviewFinding


def write_review_artifacts(
    *,
    output_dir: Path,
    pages: tuple[PageReviewResult, ...],
    context_chars: int = 70,
) -> tuple[Path, Path]:
    """Write summary JSON and a standalone HTML review report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.html"
    payload = _summary_payload(pages)
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        _render_html(pages, payload, context_chars=context_chars),
        encoding="utf-8",
    )
    return summary_path, report_path


def finding_to_dict(finding: ReviewFinding) -> dict[str, Any]:
    """Serialize one finding without mutating source extraction artifacts."""
    return {
        "finding_id": finding.finding_id,
        "page_id": finding.page_id,
        "page_number": finding.page_number,
        "source": finding.source.value,
        "kind": finding.kind.value,
        "severity": finding.severity.value,
        "gemini_range": [finding.gemini_start, finding.gemini_end],
        "reference_range": (
            [finding.reference_start, finding.reference_end]
            if finding.reference_start is not None
            and finding.reference_end is not None
            else None
        ),
        "gemini_text": finding.gemini_text,
        "reference_text": finding.reference_text,
        "suggested_text": finding.suggested_text,
        "block_id": finding.block_id,
        "span_id": finding.span_id,
        "block_role": finding.block_role,
        "crop_path": finding.crop_path,
        "ocr_confidence": finding.ocr_confidence,
        "suppressed_reason": finding.suppressed_reason,
    }


def _summary_payload(pages: tuple[PageReviewResult, ...]) -> dict[str, Any]:
    """Build the stable whole-run review summary payload."""
    findings = [finding for page in pages for finding in page.findings]
    suppressed = [
        finding for page in pages for finding in page.suppressed_findings
    ]
    return {
        "review_model": "TextFidelityReview-v2",
        "pages_reviewed": len(pages),
        "pages_with_findings": sum(bool(page.findings) for page in pages),
        "findings_total": len(findings),
        "suppressed_total": len(suppressed),
        "raw_candidates_total": len(findings) + len(suppressed),
        "findings_by_source": {
            source: sum(finding.source.value == source for finding in findings)
            for source in ("local_ocr", "heuristic")
        },
        "suppressed_by_reason": _count_suppression_reasons(suppressed),
        "pages": [
            {
                "page_id": page.page_id,
                "page_number": page.page_number,
                "ocr_similarity": round(page.ocr_similarity, 6),
                "findings": [finding_to_dict(item) for item in page.findings],
                "suppressed_findings": [
                    finding_to_dict(item) for item in page.suppressed_findings
                ],
            }
            for page in pages
        ],
    }


def _count_suppression_reasons(
    findings: list[ReviewFinding],
) -> dict[str, int]:
    """Return stable counts for audit-only suppressed OCR candidates."""
    reasons = sorted(
        {finding.suppressed_reason for finding in findings if finding.suppressed_reason}
    )
    return {
        reason: sum(finding.suppressed_reason == reason for finding in findings)
        for reason in reasons
    }


def _render_html(
    pages: tuple[PageReviewResult, ...],
    payload: dict[str, Any],
    *,
    context_chars: int,
) -> str:
    """Render one self-contained report optimized for visual review."""
    finding_pages = tuple(page for page in pages if page.findings)
    cards = "\n".join(
        _render_page(page, context_chars=context_chars) for page in finding_pages
    )
    if not cards:
        cards = '<div class="empty">No actionable review findings.</div>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SiftForge text review</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #202124; }}
header {{ margin-bottom: 2rem; }}
.summary {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
.metric {{ border: 1px solid #ddd; border-radius: 8px; padding: .7rem 1rem; }}
.page {{ border-top: 2px solid #ddd; padding-top: 1rem; margin-top: 2rem; }}
.finding {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem;
  margin: 1rem 0; }}
.meta {{ color: #666; font-size: .9rem; margin-bottom: .6rem; }}
.compare {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
pre {{ white-space: pre-wrap; word-break: break-word; background: #f7f7f7;
  padding: .8rem; border-radius: 6px; }}
mark {{ padding: 0 .1rem; }}
img.crop {{ max-width: 100%; border: 1px solid #ddd; margin-top: .8rem; }}
.empty {{ padding: 2rem; background: #f7f7f7; border-radius: 8px; }}
@media (max-width: 800px) {{ .compare {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<header>
<h1>SiftForge text-fidelity review</h1>
<div class="summary">
<div class="metric">Pages: {payload['pages_reviewed']}</div>
<div class="metric">Pages needing review: {payload['pages_with_findings']}</div>
<div class="metric">Actionable findings: {payload['findings_total']}</div>
<div class="metric">Suppressed OCR noise: {payload['suppressed_total']}</div>
</div>
<p class="meta">Low-confidence OCR differences are retained in JSON for audit,
but hidden from this report by default.</p>
</header>
{cards}
</body>
</html>
"""


def _render_page(page: PageReviewResult, *, context_chars: int) -> str:
    """Render all actionable findings for one page."""
    findings = "\n".join(
        _render_finding(page, finding, context_chars=context_chars)
        for finding in page.findings
    )
    return (
        f'<section class="page"><h2>Page {page.page_number:04d}</h2>'
        f'<div class="meta">OCR similarity: {page.ocr_similarity:.2%} · '
        f"actionable: {len(page.findings)} · "
        f"suppressed: {len(page.suppressed_findings)}</div>"
        f"{findings}</section>"
    )


def _render_finding(
    page: PageReviewResult,
    finding: ReviewFinding,
    *,
    context_chars: int,
) -> str:
    """Render one localized finding with side-by-side context."""
    gemini = _highlight(
        page.gemini_text,
        finding.gemini_start,
        finding.gemini_end,
        context_chars,
    )
    if finding.source.value == "local_ocr":
        reference = _highlight(
            page.ocr_text,
            finding.reference_start or 0,
            finding.reference_end or 0,
            context_chars,
        )
        reference_label = "Local OCR"
    else:
        reference = html.escape(finding.suggested_text or "")
        reference_label = "Heuristic suggestion"
    confidence = (
        f" · OCR confidence {finding.ocr_confidence:.1f}%"
        if finding.ocr_confidence is not None
        else ""
    )
    role = f" · {html.escape(finding.block_role)}" if finding.block_role else ""
    crop = (
        f'<img class="crop" src="{html.escape(finding.crop_path)}" '
        'alt="Source crop for this review finding" />'
        if finding.crop_path
        else ""
    )
    return f"""
<article class="finding" id="{html.escape(finding.finding_id)}">
<div class="meta">{html.escape(finding.source.value)} ·
{html.escape(finding.kind.value)} · {html.escape(finding.severity.value)}{role}
{confidence} · {html.escape(finding.block_id or 'unmapped')}</div>
<div class="compare">
<div><strong>Gemini</strong><pre>{gemini}</pre></div>
<div><strong>{reference_label}</strong><pre>{reference}</pre></div>
</div>
{crop}
</article>
"""


def _highlight(text: str, start: int, end: int, context: int) -> str:
    """HTML-escape a short context and highlight the differing span."""
    safe_start = max(0, min(start, len(text)))
    safe_end = max(safe_start, min(end, len(text)))
    left = max(0, safe_start - context)
    right = min(len(text), safe_end + context)
    prefix = "…" if left else ""
    suffix = "…" if right < len(text) else ""
    before = html.escape(text[left:safe_start])
    differing = html.escape(text[safe_start:safe_end]) or "∅"
    after = html.escape(text[safe_end:right])
    return f"{prefix}{before}<mark>{differing}</mark>{after}{suffix}"
