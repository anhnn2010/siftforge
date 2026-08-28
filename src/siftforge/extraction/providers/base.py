"""Protocols implemented by parser, OCR, and AI extraction mechanisms."""

from __future__ import annotations

from typing import Protocol

from siftforge.extraction.models import ExtractionResult, ExtractionTask


class Extractor(Protocol):
    """Execute one extraction mechanism without routing-policy decisions."""

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Execute the supplied extraction task and return its result."""
        ...
