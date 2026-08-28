"""Minimal provider-independent pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from siftforge.extraction.models import (
    ExtractionResult,
    ExtractionTask,
    ValidationResult,
)
from siftforge.extraction.providers import Extractor
from siftforge.extraction.validation import Validator


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """Combined extraction and validation results for one task."""

    extraction: ExtractionResult
    validation: ValidationResult


class Pipeline:
    """Run one extractor followed by one independent validator."""

    def __init__(self, extractor: Extractor, validator: Validator) -> None:
        """Create a minimal pipeline from mechanism and validator contracts."""
        self._extractor: Extractor = extractor
        self._validator: Validator = validator

    def run(self, task: ExtractionTask) -> PipelineOutcome:
        """Execute extraction and validation for one task."""
        extraction: ExtractionResult = self._extractor.extract(task)
        validation: ValidationResult = self._validator.validate(extraction)
        return PipelineOutcome(extraction=extraction, validation=validation)
