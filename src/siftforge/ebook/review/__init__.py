"""Text-fidelity review using local OCR and conservative heuristics."""

from .filtering import ReviewFilterConfig
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
from .resolution import (
    ReviewDecision,
    ReviewImportResult,
    ReviewResolutionError,
    import_review_resolutions,
)
from .service import EbookTextReviewService, TextReviewError

__all__: list[str] = [
    "EbookTextReviewService",
    "LocalOcrError",
    "OcrPage",
    "OcrWord",
    "PageReviewResult",
    "ProjectedText",
    "ReviewDecision",
    "ReviewFilterConfig",
    "ReviewImportResult",
    "ReviewFinding",
    "ReviewKind",
    "ReviewSeverity",
    "ReviewResolutionError",
    "ReviewSource",
    "TesseractOcrConfig",
    "TesseractOcrEngine",
    "TextAnchor",
    "TextReviewError",
    "TextReviewRun",
    "import_review_resolutions",
]
