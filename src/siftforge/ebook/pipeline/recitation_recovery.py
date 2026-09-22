"""Local OCR recovery for page extraction blocked by Gemini recitation filtering."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from siftforge.ebook.evidence import (
    BlockRoleHint,
    HeadingRoleHint,
    PageBlockEvidence,
    PageExtraction,
    SourceTypography,
    TextSpanEvidence,
    build_block_id,
    build_span_id,
)
from siftforge.ebook.models import (
    CapsStyle,
    FontPosture,
    FontWeight,
    PageKind,
    VerticalPosition,
)
from siftforge.extraction.models import Attempt, MaterializedAsset, SourceRef


class RecitationOcrRecoveryError(RuntimeError):
    """Raised when local OCR cannot recover a recitation-blocked page."""


@dataclass(frozen=True, slots=True)
class RecitationOcrRecoveryResult:
    """Typed page evidence and provenance produced by local OCR recovery."""

    page: PageExtraction
    raw_text: str
    language: str
    attempt: Attempt


_TESSERACT_LANGUAGE_BY_ISO: dict[str, str] = {
    "vi": "vie",
    "en": "eng",
    "fr": "fra",
    "de": "deu",
    "es": "spa",
    "pt": "por",
    "it": "ita",
    "ja": "jpn",
    "ko": "kor",
    "zh": "chi_sim",
}
_ISO_BY_TESSERACT_LANGUAGE: dict[str, str] = {
    value: key for key, value in _TESSERACT_LANGUAGE_BY_ISO.items()
}
_PAGE_DIR_RE = re.compile(r"^\.?page-(\d+)(?:\.extracting)?$")


class RecitationOcrRecovery:
    """Recover exact page text locally when Gemini stops with ``RECITATION``.

    Recovery is intentionally conservative: Tesseract provides the text, while
    semantic structure and typography are marked as uncertain. The resulting page
    remains buildable but carries explicit warnings that human proofreading is
    required.
    """

    def __init__(
        self,
        *,
        language: str = "auto",
        command: str = "tesseract",
        page_segmentation_mode: int = 3,
    ) -> None:
        """Configure local OCR without making any subprocess call yet."""
        if not language.strip():
            raise ValueError("recitation OCR language must not be empty")
        if page_segmentation_mode < 0:
            raise ValueError("Tesseract page segmentation mode must be non-negative")
        self._language = language.strip()
        self._command = command
        self._psm = page_segmentation_mode

    def recover(
        self,
        *,
        source: SourceRef,
        asset: MaterializedAsset,
        run_dir: Path,
    ) -> RecitationOcrRecoveryResult:
        """Run Tesseract and build conservative v5 page evidence from its text."""
        if shutil.which(self._command) is None:
            raise RecitationOcrRecoveryError(
                f"local OCR command is not available: {self._command}"
            )
        language = self._resolve_language(run_dir)
        command = [
            self._command,
            str(asset.path),
            "stdout",
            "-l",
            language,
            "--psm",
            str(self._psm),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except OSError as exc:
            raise RecitationOcrRecoveryError(
                f"failed to launch local OCR recovery: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or "unknown Tesseract failure"
            raise RecitationOcrRecoveryError(
                f"local OCR recovery failed with exit {result.returncode}: {detail}"
            )

        raw_text = result.stdout.strip()
        if not raw_text:
            raise RecitationOcrRecoveryError(
                "local OCR recovery returned no readable text"
            )
        page = _page_from_ocr_text(
            source=source,
            raw_text=raw_text,
            language=language,
        )
        attempt = Attempt(
            mechanism="ocr",
            provider="tesseract",
            status="success",
            reason="recitation_recovery",
            metadata={
                "profile": "local-ocr-recovery",
                "cost_tier": "local",
                "language": language,
                "page_segmentation_mode": self._psm,
                "needs_review": True,
            },
        )
        return RecitationOcrRecoveryResult(
            page=page,
            raw_text=raw_text,
            language=language,
            attempt=attempt,
        )

    def _resolve_language(self, run_dir: Path) -> str:
        """Resolve ``auto`` from nearby canonical pages and installed languages."""
        if self._language.lower() != "auto":
            return self._language

        available = _available_languages(self._command)
        inferred = _nearby_tesseract_language(run_dir)
        if inferred is not None and inferred in available:
            return inferred

        usable = sorted(language for language in available if language != "osd")
        if len(usable) == 1:
            return usable[0]
        if "eng" in available:
            return "eng"
        if usable:
            return usable[0]
        raise RecitationOcrRecoveryError(
            "no Tesseract language data is available for recitation recovery"
        )


def _page_from_ocr_text(
    *,
    source: SourceRef,
    raw_text: str,
    language: str,
) -> PageExtraction:
    """Build conservative page-local evidence from plain local OCR text."""
    normalized_paragraphs = _split_ocr_paragraphs(raw_text)
    if not normalized_paragraphs:
        raise RecitationOcrRecoveryError("local OCR produced only whitespace")

    iso_language = _ISO_BY_TESSERACT_LANGUAGE.get(language)
    typography = SourceTypography(
        posture=FontPosture.UNKNOWN,
        weight=FontWeight.UNKNOWN,
        vertical_position=VerticalPosition.UNKNOWN,
        caps_style=CapsStyle.UNKNOWN,
        decorations=(),
    )
    blocks: list[PageBlockEvidence] = []
    for block_index, text in enumerate(normalized_paragraphs):
        block_id = build_block_id(source.source_id, block_index)
        role = _recovery_role(text)
        blocks.append(
            PageBlockEvidence(
                block_id=block_id,
                sequence_index=block_index,
                role_hint=role,
                spans=(
                    TextSpanEvidence(
                        span_id=build_span_id(block_id, 0),
                        text=text,
                        language=iso_language,
                        source_typography=typography,
                        semantic_line_break_after=False,
                    ),
                ),
                dominant_language=iso_language,
                heading_level_hint=None,
                heading_role_hint=HeadingRoleHint.UNKNOWN,
                marker=None,
                region=None,
                alignment=None,
            )
        )

    return PageExtraction(
        page_id=source.source_id,
        source=source,
        page_kind_hint=PageKind.TEXT,
        dominant_language=iso_language,
        printed_page_number=None,
        blocks=tuple(blocks),
        warnings=(
            (
                "Recovered with local OCR after Gemini RECITATION; "
                "human review is required."
            ),
            (
                "OCR recovery preserves text conservatively; verify structure "
                "and typography against the source page."
            ),
        ),
    )


def _split_ocr_paragraphs(raw_text: str) -> tuple[str, ...]:
    """Normalize Tesseract paragraph groups without inventing missing content."""
    groups = re.split(r"\n\s*\n+", raw_text.strip())
    normalized: list[str] = []
    for group in groups:
        lines = [line.strip() for line in group.splitlines() if line.strip()]
        text = " ".join(lines).strip()
        if text:
            normalized.append(text)
    return tuple(normalized)


def _recovery_role(text: str) -> BlockRoleHint:
    """Recognize only the safest furniture case from plain OCR text."""
    stripped = text.strip()
    if stripped.isdigit() and len(stripped) <= 4:
        return BlockRoleHint.PAGE_NUMBER
    return BlockRoleHint.PARAGRAPH


def _available_languages(command: str) -> set[str]:
    """Return installed Tesseract language identifiers."""
    try:
        result = subprocess.run(
            [command, "--list-langs"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise RecitationOcrRecoveryError(
            f"failed to query Tesseract languages: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown Tesseract failure"
        raise RecitationOcrRecoveryError(
            f"failed to query Tesseract languages: {detail}"
        )
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.lower().startswith("list of available languages")
    }


def _nearby_tesseract_language(run_dir: Path) -> str | None:
    """Infer OCR language from the nearest already-normalized sibling page."""
    current = _page_number_from_dir(run_dir)
    if current is None or not run_dir.parent.is_dir():
        return None

    candidates: list[tuple[int, Path]] = []
    for sibling in run_dir.parent.iterdir():
        if not sibling.is_dir() or sibling == run_dir:
            continue
        page_number = _page_number_from_dir(sibling)
        normalized = sibling / "normalized" / "page.json"
        if page_number is None or not normalized.is_file():
            continue
        candidates.append((abs(page_number - current), normalized))

    for _, normalized in sorted(candidates, key=lambda item: item[0]):
        try:
            payload = json.loads(normalized.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        dominant = payload.get("dominant_language")
        if not isinstance(dominant, str):
            continue
        mapped = _TESSERACT_LANGUAGE_BY_ISO.get(dominant.lower())
        if mapped is not None:
            return mapped
    return None


def _page_number_from_dir(path: Path) -> int | None:
    """Parse the conventional ``page-NNNN`` run directory name."""
    match = _PAGE_DIR_RE.match(path.name)
    if match is None:
        return None
    return int(match.group(1))
