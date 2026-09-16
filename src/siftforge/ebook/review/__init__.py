"""Text-fidelity review using local OCR and conservative heuristics."""

from .models import (
    OcrPage,
    OcrWord,
    PageReviewResult,
    ProjectedText,
    ReviewFinding,
    ReviewKind,
    ReviewSeverity,
    ReviewSource,
    TextAnchor,
    TextReviewRun,
)
from .ocr import LocalOcrError, TesseractOcrConfig, TesseractOcrEngine
from .service import EbookTextReviewService, TextReviewError

__all__: list[str] = [
    "EbookTextReviewService",
    "LocalOcrError",
    "OcrPage",
    "OcrWord",
    "PageReviewResult",
    "ProjectedText",
    "ReviewFinding",
    "ReviewKind",
    "ReviewSeverity",
    "ReviewSource",
    "TesseractOcrConfig",
    "TesseractOcrEngine",
    "TextAnchor",
    "TextReviewError",
    "TextReviewRun",
]
