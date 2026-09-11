"""Golden-fixture loading for ebook extraction and structural regression tests.

The harness consumes normalized page-evidence artifacts produced by SiftForge.
It intentionally revalidates each stored artifact through the active strict v5
normalizer so corrupted fixture IDs or incompatible normalized shapes fail fast.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siftforge.ebook.evidence import PageExtraction
from siftforge.ebook.extraction.evidence_normalizer import (
    EbookPageEvidenceNormalizer,
)
from siftforge.extraction.models import SourceRef

_CASE_KEYS = frozenset(
    {
        "case_id",
        "model",
        "prompt_version",
        "schema_version",
        "source_page_number",
        "tags",
    }
)
_ARTIFACT_KEYS = frozenset(
    {
        "page_id",
        "source",
        "page_kind_hint",
        "dominant_language",
        "printed_page_number",
        "blocks",
        "warnings",
    }
)
_SOURCE_KEYS = frozenset(
    {
        "source_id",
        "uri",
        "sha256",
        "media_type",
        "metadata",
    }
)
_BLOCK_ARTIFACT_KEYS = frozenset(
    {
        "block_id",
        "sequence_index",
        "role_hint",
        "content",
        "dominant_language",
        "heading_level_hint",
        "heading_role_hint",
        "marker",
        "region",
        "alignment",
    }
)
_SPAN_ARTIFACT_KEYS = frozenset(
    {
        "span_id",
        "text",
        "language",
        "source_typography",
        "semantic_line_break_after",
    }
)


class GoldenFixtureError(ValueError):
    """Raised when a stored golden fixture is malformed or self-inconsistent."""


@dataclass(frozen=True, slots=True)
class _GoldenCaseMetadata:
    """Validated metadata stored beside one golden page artifact."""

    case_id: str
    model: str
    prompt_version: str
    schema_version: str
    source_page_number: int
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoldenPageFixture:
    """One real-run page evidence fixture plus its extraction provenance."""

    case_id: str
    model: str
    prompt_version: str
    schema_version: str
    source_page_number: int
    tags: tuple[str, ...]
    page: PageExtraction


class GoldenPageFixtureLoader:
    """Load normalized page artifacts as strict immutable golden fixtures."""

    def __init__(self) -> None:
        """Create a loader backed by the active strict page normalizer."""
        self._normalizer = EbookPageEvidenceNormalizer()

    def load(self, fixture_dir: Path) -> GoldenPageFixture:
        """Load one fixture directory containing ``case.json`` and ``page.json``.

        Args:
            fixture_dir: Directory containing fixture metadata and normalized
                page evidence.

        Returns:
            Parsed fixture with a strictly validated ``PageExtraction``.

        Raises:
            GoldenFixtureError: If metadata, JSON, normalized shape, or stored
                deterministic IDs are invalid.
        """
        case_payload = self._load_json_object(fixture_dir / "case.json")
        page_payload = self._load_json_object(fixture_dir / "page.json")
        self._require_exact_keys(case_payload, _CASE_KEYS, "case")
        fixture = self._case_metadata(case_payload)
        page = self._page_from_artifact(page_payload)
        if _source_page_number(page) != fixture.source_page_number:
            raise GoldenFixtureError(
                "fixture source_page_number does not match page source metadata"
            )
        return GoldenPageFixture(
            case_id=fixture.case_id,
            model=fixture.model,
            prompt_version=fixture.prompt_version,
            schema_version=fixture.schema_version,
            source_page_number=fixture.source_page_number,
            tags=fixture.tags,
            page=page,
        )

    def discover(self, root: Path) -> tuple[GoldenPageFixture, ...]:
        """Load all direct child fixture directories in deterministic order."""
        fixture_dirs = sorted(
            path
            for path in root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )
        return tuple(self.load(path) for path in fixture_dirs)

    def _case_metadata(self, payload: Mapping[str, Any]) -> _GoldenCaseMetadata:
        """Validate fixture metadata before page evidence is loaded."""
        case_id = self._required_string(payload.get("case_id"), "case.case_id")
        model = self._required_string(payload.get("model"), "case.model")
        prompt_version = self._required_string(
            payload.get("prompt_version"),
            "case.prompt_version",
        )
        schema_version = self._required_string(
            payload.get("schema_version"),
            "case.schema_version",
        )
        source_page_number = payload.get("source_page_number")
        if isinstance(source_page_number, bool) or not isinstance(
            source_page_number, int
        ):
            raise GoldenFixtureError("case.source_page_number must be an integer")
        if source_page_number < 1:
            raise GoldenFixtureError("case.source_page_number must be positive")
        raw_tags = payload.get("tags")
        if not isinstance(raw_tags, list) or not all(
            isinstance(tag, str) and tag for tag in raw_tags
        ):
            raise GoldenFixtureError("case.tags must be a list of non-empty strings")
        return _GoldenCaseMetadata(
            case_id=case_id,
            model=model,
            prompt_version=prompt_version,
            schema_version=schema_version,
            source_page_number=source_page_number,
            tags=tuple(raw_tags),
        )

    def _page_from_artifact(self, payload: Mapping[str, Any]) -> PageExtraction:
        """Revalidate a normalized artifact through the strict v5 normalizer."""
        self._require_exact_keys(payload, _ARTIFACT_KEYS, "page artifact")
        page_id = self._required_string(payload.get("page_id"), "page.page_id")
        source = self._source_ref(payload.get("source"))
        provider_payload = {
            "page_kind_hint": payload.get("page_kind_hint"),
            "dominant_language": payload.get("dominant_language"),
            "printed_page_number": payload.get("printed_page_number"),
            "blocks": self._provider_blocks(payload.get("blocks"), page_id),
            "warnings": payload.get("warnings"),
        }
        page = self._normalizer.normalize(page_id, source, provider_payload)
        regenerated = self._normalizer.to_dict(page)
        if regenerated != dict(payload):
            raise GoldenFixtureError(
                "normalized page artifact is not canonical or has invalid IDs"
            )
        return page

    def _source_ref(self, payload: Any) -> SourceRef:
        """Parse source provenance stored in a normalized artifact."""
        source = self._require_mapping(payload, "page.source")
        self._require_exact_keys(source, _SOURCE_KEYS, "page.source")
        source_id = self._required_string(source.get("source_id"), "source.source_id")
        uri = self._required_string(source.get("uri"), "source.uri")
        sha256 = self._optional_string(source.get("sha256"), "source.sha256")
        media_type = self._optional_string(
            source.get("media_type"),
            "source.media_type",
        )
        metadata = source.get("metadata")
        if not isinstance(metadata, dict):
            raise GoldenFixtureError("source.metadata must be an object")
        return SourceRef(
            source_id=source_id,
            uri=uri,
            sha256=sha256,
            media_type=media_type,
            metadata=dict(metadata),
        )

    def _provider_blocks(self, payload: Any, page_id: str) -> list[dict[str, Any]]:
        """Strip normalized-only IDs after validating deterministic identities."""
        if not isinstance(payload, list):
            raise GoldenFixtureError("page.blocks must be a list")
        return [
            self._provider_block(block, page_id, block_index)
            for block_index, block in enumerate(payload)
        ]

    def _provider_block(
        self,
        payload: Any,
        page_id: str,
        block_index: int,
    ) -> dict[str, Any]:
        """Validate one stored block and return raw-contract-compatible data."""
        block = self._require_mapping(payload, f"blocks[{block_index}]")
        self._require_exact_keys(block, _BLOCK_ARTIFACT_KEYS, f"blocks[{block_index}]")
        expected_block_id = f"{page_id}:block:{block_index + 1:04d}"
        if block.get("block_id") != expected_block_id:
            raise GoldenFixtureError(
                f"blocks[{block_index}].block_id is not deterministic"
            )
        if block.get("sequence_index") != block_index:
            raise GoldenFixtureError(
                f"blocks[{block_index}].sequence_index does not match array order"
            )
        content = block.get("content")
        if not isinstance(content, list):
            raise GoldenFixtureError(f"blocks[{block_index}].content must be a list")
        provider_content = [
            self._provider_span(span, expected_block_id, block_index, span_index)
            for span_index, span in enumerate(content)
        ]
        return {
            "role_hint": block.get("role_hint"),
            "content": provider_content,
            "dominant_language": block.get("dominant_language"),
            "heading_level_hint": block.get("heading_level_hint"),
            "heading_role_hint": block.get("heading_role_hint"),
            "marker": block.get("marker"),
            "region": block.get("region"),
            "alignment": block.get("alignment"),
        }

    def _provider_span(
        self,
        payload: Any,
        block_id: str,
        block_index: int,
        span_index: int,
    ) -> dict[str, Any]:
        """Validate one stored span and strip its normalized-only identifier."""
        path = f"blocks[{block_index}].content[{span_index}]"
        span = self._require_mapping(payload, path)
        self._require_exact_keys(span, _SPAN_ARTIFACT_KEYS, path)
        expected_span_id = f"{block_id}:span:{span_index + 1:04d}"
        if span.get("span_id") != expected_span_id:
            raise GoldenFixtureError(f"{path}.span_id is not deterministic")
        return {
            "text": span.get("text"),
            "language": span.get("language"),
            "source_typography": span.get("source_typography"),
            "semantic_line_break_after": span.get("semantic_line_break_after"),
        }

    def _load_json_object(self, path: Path) -> dict[str, Any]:
        """Read one UTF-8 JSON object with a fixture-specific error."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            message = f"cannot load golden fixture JSON: {path}"
            raise GoldenFixtureError(message) from exc
        if not isinstance(payload, dict):
            raise GoldenFixtureError(f"golden fixture JSON must be an object: {path}")
        return payload

    def _require_mapping(self, payload: Any, path: str) -> Mapping[str, Any]:
        """Require a JSON object-like mapping."""
        if not isinstance(payload, Mapping):
            raise GoldenFixtureError(f"{path} must be an object")
        return payload

    def _require_exact_keys(
        self,
        payload: Mapping[str, Any],
        expected: frozenset[str],
        path: str,
    ) -> None:
        """Reject fixture drift caused by missing or unknown fields."""
        actual = frozenset(payload)
        if actual == expected:
            return
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise GoldenFixtureError(
            f"{path} keys mismatch: missing={missing}, extra={extra}"
        )

    def _required_string(self, payload: Any, path: str) -> str:
        """Return one required non-empty string."""
        if not isinstance(payload, str) or not payload:
            raise GoldenFixtureError(f"{path} must be a non-empty string")
        return payload

    def _optional_string(self, payload: Any, path: str) -> str | None:
        """Return one optional string field."""
        if payload is None:
            return None
        if not isinstance(payload, str):
            raise GoldenFixtureError(f"{path} must be a string or null")
        return payload


def _source_page_number(page: PageExtraction) -> int | None:
    """Return integer source page number when stored in fixture metadata."""
    page_number = page.source.metadata.get("page_number")
    if isinstance(page_number, bool) or not isinstance(page_number, int):
        return None
    return page_number
