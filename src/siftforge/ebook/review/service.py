"""Whole-run local OCR comparison and review-report orchestration."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Protocol

from PIL import Image

from siftforge.ebook.pipeline.book_assembly import EbookPageRunLoader

from .cache import (
    build_review_input_fingerprint,
    load_cached_page_review,
    review_cache_metadata,
)
from .comparison import compare_with_ocr
from .filtering import ReviewFilterConfig, filter_ocr_findings, words_for_finding
from .heuristics import find_suspicious_boundaries
from .models import (
    TEXT_REVIEW_MODEL,
    OcrPage,
    PageReviewResult,
    ReviewFinding,
    TextReviewRun,
)
from .projection import project_page_text
from .report import finding_to_dict, write_review_artifacts


class TextReviewError(RuntimeError):
    """Raised when text review cannot consume or persist page-run artifacts."""


class LocalOcrEngine(Protocol):
    """Minimal local OCR capability required by the review service."""

    def extract(self, image_path: str | Path) -> OcrPage:
        """Extract independent text evidence from one page image."""
        ...


class EbookTextReviewService:
    """Compare Gemini page text with local OCR and suspicious-text heuristics."""

    def __init__(
        self,
        ocr_engine: LocalOcrEngine,
        loader: EbookPageRunLoader | None = None,
        filter_config: ReviewFilterConfig | None = None,
    ) -> None:
        """Initialize review collaborators without provider dependencies."""
        self._ocr = ocr_engine
        self._loader = loader or EbookPageRunLoader()
        self._filter_config = filter_config or ReviewFilterConfig()

    def review(
        self,
        runs_root: str | Path,
        output_dir: str | Path | None = None,
        *,
        start_page: int = 1,
        end_page: int | None = None,
        force: bool = False,
    ) -> TextReviewRun:
        """Review canonical page runs without modifying normalized extraction."""
        root = Path(runs_root).expanduser().resolve()
        output = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else (root / "review").resolve()
        )
        page_runs = tuple(
            item
            for item in self._loader.discover(root)
            if item.page_number >= start_page
            and (end_page is None or item.page_number <= end_page)
        )
        if not page_runs:
            raise TextReviewError("selected review range contains no page runs")

        output.mkdir(parents=True, exist_ok=True)
        pages: list[PageReviewResult] = []
        processed_pages = 0
        reused_pages = 0
        ocr_cache_key = self._ocr_cache_key()
        for page_run in page_runs:
            projection = project_page_text(page_run.page)
            fingerprint = build_review_input_fingerprint(
                page_run=page_run,
                projection=projection,
                output_dir=output,
                ocr_cache_key=ocr_cache_key,
                filter_config=self._filter_config,
            )
            cached = None
            if not force:
                cached = load_cached_page_review(
                    page_run=page_run,
                    projection=projection,
                    expected_fingerprint=fingerprint,
                )
            if cached is not None:
                pages.append(cached)
                reused_pages += 1
                continue

            try:
                ocr = self._ocr.extract(page_run.source_image)
            except Exception as exc:
                raise TextReviewError(
                    f"local OCR failed for page {page_run.page_number:04d}: {exc}"
                ) from exc
            similarity, raw_ocr_findings = compare_with_ocr(
                page_number=page_run.page_number,
                projection=projection,
                ocr=ocr,
            )
            heuristic_findings = find_suspicious_boundaries(
                page_number=page_run.page_number,
                projection=projection,
            )
            ocr_findings, suppressed = filter_ocr_findings(
                ocr=ocr,
                ocr_findings=raw_ocr_findings,
                heuristic_findings=heuristic_findings,
                config=self._filter_config,
            )
            findings = self._attach_crops(
                page_run.source_image,
                output,
                ocr,
                heuristic_findings + ocr_findings,
            )
            result = PageReviewResult(
                page_id=page_run.page.page_id,
                page_number=page_run.page_number,
                gemini_text=projection.text,
                ocr_text=ocr.text,
                ocr_similarity=similarity,
                findings=findings,
                suppressed_findings=suppressed,
            )
            pages.append(result)
            processed_pages += 1
            self._write_page_artifacts(
                run_dir=page_run.run_dir,
                ocr=ocr,
                result=result,
                input_fingerprint=fingerprint,
                ocr_cache_key=ocr_cache_key,
            )

        page_tuple = tuple(pages)
        summary_path, report_path = write_review_artifacts(
            output_dir=output,
            pages=page_tuple,
        )
        manifest_path = output / "run.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "review_model": TEXT_REVIEW_MODEL,
                    "runs_root": str(root),
                    "output_dir": str(output),
                    "start_page": start_page,
                    "end_page": end_page,
                    "selected_pages": len(page_tuple),
                    "processed_pages": processed_pages,
                    "reused_pages": reused_pages,
                    "force": force,
                    "ocr_cache_key": ocr_cache_key,
                    "filter_config": asdict(self._filter_config),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return TextReviewRun(
            runs_root=root,
            output_dir=output,
            pages=page_tuple,
            report_path=report_path,
            summary_path=summary_path,
            manifest_path=manifest_path,
            processed_pages=processed_pages,
            reused_pages=reused_pages,
        )

    def _ocr_cache_key(self) -> str:
        """Return a stable OCR configuration key without requiring OCR work."""
        cache_key = getattr(self._ocr, "cache_key", None)
        if callable(cache_key):
            value = cache_key()
            if isinstance(value, str) and value:
                return value
        cls = type(self._ocr)
        return f"{cls.__module__}.{cls.__qualname__}"

    def _write_page_artifacts(
        self,
        *,
        run_dir: Path,
        ocr: OcrPage,
        result: PageReviewResult,
        input_fingerprint: str,
        ocr_cache_key: str,
    ) -> None:
        """Persist independent OCR and findings beside immutable page evidence."""
        review_dir = run_dir / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        metadata = review_cache_metadata(
            input_fingerprint=input_fingerprint,
            ocr_cache_key=ocr_cache_key,
            filter_config=self._filter_config,
        )
        (review_dir / "ocr.json").write_text(
            json.dumps(
                {
                    **metadata,
                    "engine": ocr.engine,
                    "language": ocr.language,
                    "text": ocr.text,
                    "words": [
                        {
                            "text": word.text,
                            "confidence": word.confidence,
                            "box": [word.left, word.top, word.width, word.height],
                            "range": [word.start, word.end],
                        }
                        for word in ocr.words
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (review_dir / "findings.json").write_text(
            json.dumps(
                {
                    **metadata,
                    "page_id": result.page_id,
                    "page_number": result.page_number,
                    "ocr_similarity": result.ocr_similarity,
                    "findings": [
                        finding_to_dict(finding) for finding in result.findings
                    ],
                    "suppressed_findings": [
                        finding_to_dict(finding)
                        for finding in result.suppressed_findings
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _attach_crops(
        self,
        source_image: Path,
        output_dir: Path,
        ocr: OcrPage,
        findings: tuple[ReviewFinding, ...],
    ) -> tuple[ReviewFinding, ...]:
        """Crop source evidence around OCR words when a location is available."""
        crops_dir = output_dir / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)
        updated: list[ReviewFinding] = []
        with Image.open(source_image) as image:
            for finding in findings:
                words = words_for_finding(ocr, finding)
                if not words:
                    token = finding.gemini_text.strip()
                    words = tuple(word for word in ocr.words if word.text == token)[:1]
                if not words:
                    updated.append(finding)
                    continue
                left = min(word.left for word in words)
                top = min(word.top for word in words)
                right = max(word.left + word.width for word in words)
                bottom = max(word.top + word.height for word in words)
                pad_x = max(20, (right - left) // 2)
                pad_y = max(16, (bottom - top) * 2)
                box = (
                    max(0, left - pad_x),
                    max(0, top - pad_y),
                    min(image.width, right + pad_x),
                    min(image.height, bottom + pad_y),
                )
                crop_name = f"{finding.finding_id}.png"
                crop_path = crops_dir / crop_name
                image.crop(box).save(crop_path, format="PNG")
                relative = crop_path.relative_to(output_dir).as_posix()
                updated.append(replace(finding, crop_path=relative))
        return tuple(updated)
