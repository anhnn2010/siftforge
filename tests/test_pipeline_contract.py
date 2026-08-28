from siftforge.extraction.models import (
    Attempt,
    ExtractionResult,
    ExtractionTask,
    SourceRef,
    ValidationResult,
    ValidationStatus,
)
from siftforge.extraction.runtime import Pipeline


class FakeExtractor:
    def extract(self, task: ExtractionTask) -> ExtractionResult:
        return ExtractionResult(
            task=task,
            raw_data={"text": "hello"},
            normalized_data={"text": "hello"},
            attempts=(
                Attempt(
                    mechanism="fake",
                    provider=None,
                    status="success",
                ),
            ),
        )


class FakeValidator:
    def validate(self, result: ExtractionResult) -> ValidationResult:
        assert result.normalized_data == {"text": "hello"}
        return ValidationResult(status=ValidationStatus.PASS)


def test_pipeline_does_not_depend_on_real_provider() -> None:
    task = ExtractionTask(
        source=SourceRef(
            source_id="page-1",
            uri="fixture://page-1",
        ),
        capability="document_transcription",
        schema_name="PageContent",
    )

    outcome = Pipeline(FakeExtractor(), FakeValidator()).run(task)

    assert outcome.validation.status is ValidationStatus.PASS
    assert outcome.extraction.task is task
