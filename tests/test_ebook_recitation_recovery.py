"""Tests for conservative local OCR recovery after Gemini RECITATION."""

from __future__ import annotations

import json
from pathlib import Path

from siftforge.ebook.pipeline.recitation_recovery import (
    _nearby_tesseract_language,
    _split_ocr_paragraphs,
)


def test_auto_language_reads_nearby_page_from_staging_run(tmp_path: Path) -> None:
    """Full-book staging names should still infer Vietnamese as Tesseract vie."""
    sibling = tmp_path / "page-0031" / "normalized"
    sibling.mkdir(parents=True)
    (sibling / "page.json").write_text(
        json.dumps({"dominant_language": "vi"}),
        encoding="utf-8",
    )
    staging = tmp_path / ".page-0032.extracting"
    staging.mkdir()

    assert _nearby_tesseract_language(staging) == "vie"


def test_plain_ocr_recovery_preserves_paragraph_groups() -> None:
    """Blank-line groups should remain separate recovery blocks."""
    text = "Dòng một\nDòng hai\n\nĐoạn kế tiếp\n"

    assert _split_ocr_paragraphs(text) == (
        "Dòng một Dòng hai",
        "Đoạn kế tiếp",
    )
