"""Core domain-independent data models used by extraction pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class TaskStatus(StrEnum):
    """Lifecycle states for a unit of extraction work."""

    PENDING = "pending"
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    VALIDATED = "validated"
    DONE = "done"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"


class ValidationStatus(StrEnum):
    """Possible outcomes produced by an extraction validator."""

    PASS = "pass"
    REVIEW_REQUIRED = "review_required"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Logical reference to one independently processable source item.

    Attributes:
        source_id: Stable logical identity within the source domain.
        uri: Human-readable provenance URI for the source item.
        sha256: Optional content fingerprint for caching and change detection.
        media_type: Media type of the logical source item.
        metadata: Source-specific provenance and discovery metadata.
    """

    source_id: str
    uri: str
    sha256: str | None = None
    media_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MaterializedAsset:
    """Local binary asset produced from a logical source reference.

    This model is the boundary between source-specific acquisition and downstream
    extraction. Providers consume the asset without needing to understand PDF
    internals, archives, remote storage, or other source containers.

    Attributes:
        source: Logical source item from which the asset was produced.
        path: Local filesystem path containing the materialized bytes.
        media_type: Concrete media type of the local asset.
        sha256: SHA-256 hash of the materialized bytes.
        byte_size: Size of the materialized asset in bytes.
        metadata: Materialization-specific provenance metadata.
    """

    source: SourceRef
    path: Path
    media_type: str
    sha256: str
    byte_size: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtractionTask:
    """Provider-independent description of one extraction request."""

    source: SourceRef
    capability: str
    schema_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Attempt:
    """Record one parser, OCR, or AI attempt made for an extraction task."""

    mechanism: str
    provider: str | None
    status: str
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Raw and optionally normalized output produced for an extraction task."""

    task: ExtractionTask
    raw_data: Any
    normalized_data: Any | None = None
    attempts: tuple[Attempt, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Independent quality assessment of an extraction result."""

    status: ValidationStatus
    reasons: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
