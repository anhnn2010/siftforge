"""Versioned extraction contracts and normalization for the ebook application."""

from .contracts import (
    EBOOK_PAGE_PROMPT,
    EBOOK_PAGE_PROMPT_V4,
    EBOOK_PAGE_PROMPT_V5,
    EBOOK_PAGE_PROMPT_V5_R1,
    EBOOK_PAGE_PROMPT_V5_R2,
    EBOOK_PAGE_SCHEMA,
    EBOOK_PAGE_SCHEMA_V4,
    EBOOK_PAGE_SCHEMA_V5,
)
from .evidence_normalizer import EbookPageEvidenceNormalizer
from .normalizer import EbookPageNormalizationError, EbookPageNormalizer

__all__: list[str] = [
    "EBOOK_PAGE_PROMPT",
    "EBOOK_PAGE_PROMPT_V4",
    "EBOOK_PAGE_PROMPT_V5",
    "EBOOK_PAGE_PROMPT_V5_R1",
    "EBOOK_PAGE_PROMPT_V5_R2",
    "EBOOK_PAGE_SCHEMA",
    "EBOOK_PAGE_SCHEMA_V4",
    "EBOOK_PAGE_SCHEMA_V5",
    "EbookPageEvidenceNormalizer",
    "EbookPageNormalizationError",
    "EbookPageNormalizer",
]
