"""Page-local ebook extraction evidence and compatibility adapters."""

from .adapter import page_content_to_evidence
from .models import (
    BlockRoleHint,
    HeadingRoleHint,
    MarkerEvidence,
    MarkerKind,
    NormalizedRegion,
    PageBlockEvidence,
    PageExtraction,
    SourceTypography,
    TextSpanEvidence,
)

__all__: list[str] = [
    "BlockRoleHint",
    "HeadingRoleHint",
    "MarkerEvidence",
    "MarkerKind",
    "NormalizedRegion",
    "PageBlockEvidence",
    "PageExtraction",
    "SourceTypography",
    "TextSpanEvidence",
    "page_content_to_evidence",
]
