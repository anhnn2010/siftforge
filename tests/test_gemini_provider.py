"""Tests for the Gemini provider boundary without network access."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from siftforge.ebook.extraction import EBOOK_PAGE_PROMPT, EBOOK_PAGE_SCHEMA
from siftforge.extraction.models import (
    ExtractionTask,
    MaterializedAsset,
    SourceRef,
)
from siftforge.extraction.providers import (
    GeminiProvider,
    GeminiProviderConfig,
    GeminiTransportResponse,
    InvalidGeminiResponseError,
    MissingMaterializedAssetError,
)


class FakeGeminiTransport:
    """Capture provider inputs and return deterministic structured JSON."""

    def __init__(self, response_text: str) -> None:
        """Initialize the transport with one canned response."""
        self.response_text: str = response_text
        self.last_call: dict[str, Any] | None = None

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        assets: tuple[MaterializedAsset, ...],
        response_json_schema: dict[str, Any],
        temperature: float,
    ) -> GeminiTransportResponse:
        """Capture the request and return the configured response."""
        self.last_call = {
            "model": model,
            "prompt": prompt,
            "assets": assets,
            "response_json_schema": response_json_schema,
            "temperature": temperature,
        }
        return GeminiTransportResponse(
            text=self.response_text,
            usage={"total_token_count": 123},
        )


def _make_task(tmp_path: Path) -> ExtractionTask:
    """Create an ebook page extraction task with one materialized JPEG asset."""
    image_path = tmp_path / "page-0001.jpg"
    data = b"fake-jpeg-fixture"
    image_path.write_bytes(data)

    source = SourceRef(
        source_id="pdf:fixture:page:0001",
        uri="fixture://book.pdf#page=1",
    )
    asset = MaterializedAsset(
        source=source,
        path=image_path,
        media_type="image/jpeg",
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    )
    return ExtractionTask(
        source=source,
        capability="document_transcription",
        prompt=EBOOK_PAGE_PROMPT,
        schema=EBOOK_PAGE_SCHEMA,
        assets=(asset,),
    )


def test_gemini_provider_keeps_domain_contract_outside_provider(
    tmp_path: Path,
) -> None:
    """Gemini should consume generic prompt/schema/assets supplied by the task."""
    response_text = (
        '{"page_kind":"text","language":"vi","printed_page_number":"1",'
        '"blocks":[{"type":"paragraph","text":"Xin chào.","level":null}],'
        '"warnings":[]}'
    )
    transport = FakeGeminiTransport(response_text)
    provider = GeminiProvider(
        GeminiProviderConfig(model="test-model"),
        transport=transport,
    )
    task = _make_task(tmp_path)

    result = provider.extract(task)

    assert result.normalized_data["page_kind"] == "text"
    assert result.normalized_data["blocks"][0]["text"] == "Xin chào."
    assert result.attempts[0].provider == "gemini"
    assert result.attempts[0].metadata["model"] == "test-model"
    assert result.attempts[0].metadata["prompt_version"] == "1"
    assert result.attempts[0].metadata["schema_version"] == "1"

    assert transport.last_call is not None
    assert transport.last_call["prompt"] == EBOOK_PAGE_PROMPT.text
    assert transport.last_call["response_json_schema"] == EBOOK_PAGE_SCHEMA.json_schema
    assert transport.last_call["temperature"] == 0.0


def test_gemini_provider_rejects_task_without_asset(tmp_path: Path) -> None:
    """Gemini should fail explicitly when materialization was skipped."""
    task_with_asset = _make_task(tmp_path)
    task = ExtractionTask(
        source=task_with_asset.source,
        capability=task_with_asset.capability,
        prompt=task_with_asset.prompt,
        schema=task_with_asset.schema,
    )
    provider = GeminiProvider(
        GeminiProviderConfig(model="test-model"),
        transport=FakeGeminiTransport("{}"),
    )

    with pytest.raises(MissingMaterializedAssetError):
        provider.extract(task)


def test_gemini_provider_rejects_malformed_json(tmp_path: Path) -> None:
    """Structured extraction should not silently accept malformed JSON."""
    provider = GeminiProvider(
        GeminiProviderConfig(model="test-model"),
        transport=FakeGeminiTransport("not-json"),
    )

    with pytest.raises(InvalidGeminiResponseError):
        provider.extract(_make_task(tmp_path))
