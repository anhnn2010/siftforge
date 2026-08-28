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
    extraction: ExtractionResult
    validation: ValidationResult


class Pipeline:
    """Minimal orchestration contract for the first vertical slice."""

    def __init__(self, extractor: Extractor, validator: Validator) -> None:
        self._extractor = extractor
        self._validator = validator

    def run(self, task: ExtractionTask) -> PipelineOutcome:
        extraction = self._extractor.extract(task)
        validation = self._validator.validate(extraction)
        return PipelineOutcome(
            extraction=extraction,
            validation=validation,
        )
