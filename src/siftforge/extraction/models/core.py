from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    VALIDATED = "validated"
    DONE = "done"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"


class ValidationStatus(StrEnum):
    PASS = "pass"
    REVIEW_REQUIRED = "review_required"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: str
    uri: str
    sha256: str | None = None
    media_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtractionTask:
    source: SourceRef
    capability: str
    schema_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Attempt:
    mechanism: str
    provider: str | None
    status: str
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    task: ExtractionTask
    raw_data: Any
    normalized_data: Any | None = None
    attempts: tuple[Attempt, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: ValidationStatus
    reasons: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
