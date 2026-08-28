"""Protocols implemented by result-quality validators."""

from __future__ import annotations

from typing import Protocol

from siftforge.extraction.models import ExtractionResult, ValidationResult


class Validator(Protocol):
    """Evaluate extraction quality independently of the extraction provider."""

    def validate(self, result: ExtractionResult) -> ValidationResult:
        """Return an independent quality assessment for an extraction result."""
        ...
