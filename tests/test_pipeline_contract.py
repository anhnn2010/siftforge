"""Contract tests for provider-independent pipeline orchestration."""

from siftforge.extraction.models import (
    Attempt,
    ExtractionResult,
    ExtractionSchema,
    ExtractionTask,
    PromptSpec,
    SourceRef,
    ValidationResult,
    ValidationStatus,
)
from siftforge.extraction.runtime import Pipeline


class FakeExtractor:
    """Deterministic extractor used to verify provider independence."""

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Return a predictable result without calling an external provider."""
        return ExtractionResult(
            task=task,
            raw_data={"text": "hello"},
            normalized_data={"text": "hello"},
            attempts=(Attempt(mechanism="fake", provider=None, status="success"),),
        )


class FakeValidator:
    """Validator used to verify the pipeline contract."""

    def validate(self, result: ExtractionResult) -> ValidationResult:
        """Accept the deterministic fixture result."""
        assert result.normalized_data == {"text": "hello"}
        return ValidationResult(status=ValidationStatus.PASS)


def test_pipeline_does_not_depend_on_real_provider() -> None:
    """Pipeline should work with any contract-compatible provider."""
    task = ExtractionTask(
        source=SourceRef(source_id="page-1", uri="fixture://page-1"),
        capability="document_transcription",
        prompt=PromptSpec(name="fixture", version="1", text="Extract."),
        schema=ExtractionSchema(
            name="fixture",
            version="1",
            json_schema={"type": "object"},
        ),
    )

    outcome = Pipeline(FakeExtractor(), FakeValidator()).run(task)

    assert outcome.validation.status is ValidationStatus.PASS
    assert outcome.extraction.task is task
