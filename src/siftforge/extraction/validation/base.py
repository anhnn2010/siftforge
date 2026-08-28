from __future__ import annotations

from typing import Protocol

from siftforge.extraction.models import ExtractionResult, ValidationResult


class Validator(Protocol):
    """Evaluates whether an extraction result is usable."""

    def validate(self, result: ExtractionResult) -> ValidationResult:
        ...
