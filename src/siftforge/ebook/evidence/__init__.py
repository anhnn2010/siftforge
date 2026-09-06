"""Page-local ebook extraction evidence and compatibility adapters."""

from .adapter import page_content_to_evidence
from .identity import build_block_id, build_span_id
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
    "build_block_id",
    "build_span_id",
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
