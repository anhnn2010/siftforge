from __future__ import annotations

from typing import Protocol

from siftforge.extraction.models import ExtractionResult, ExtractionTask


class Extractor(Protocol):
    """Executes one extraction mechanism/provider."""

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        ...
