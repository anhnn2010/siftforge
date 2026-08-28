"""Public data models shared by generic extraction components."""

from .core import (
    Attempt,
    ExtractionResult,
    ExtractionTask,
    MaterializedAsset,
    SourceRef,
    TaskStatus,
    ValidationResult,
    ValidationStatus,
)

__all__: list[str] = [
    "Attempt",
    "ExtractionResult",
    "ExtractionTask",
    "MaterializedAsset",
    "SourceRef",
    "TaskStatus",
    "ValidationResult",
    "ValidationStatus",
]
