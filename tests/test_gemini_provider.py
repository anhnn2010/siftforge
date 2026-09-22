"""Tests for the Gemini provider boundary without network access."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from siftforge.ebook.extraction import (
    EBOOK_PAGE_PROMPT_V4,
    EBOOK_PAGE_SCHEMA_V4,
)
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
from siftforge.extraction.providers.gemini import (
    _extract_response_diagnostics,
    _extract_response_text,
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
        prompt=EBOOK_PAGE_PROMPT_V4,
        schema=EBOOK_PAGE_SCHEMA_V4,
        assets=(asset,),
    )


def test_gemini_provider_passes_explicit_typography_schema(
    tmp_path: Path,
) -> None:
    """Gemini should receive the generic task's explicit typography contract."""
    response_text = (
        '{"page_kind":"text","language":"vi","printed_page_number":"1",'
        '"blocks":[{"type":"paragraph","content":[{"text":"Xin chào",'
        '"typography":{"posture":"roman","weight":"normal",'
        '"vertical_position":"baseline","caps_style":"normal",'
        '"decorations":[]}}],"language":"vi","level":null,'
        '"alignment":"justify"}],"warnings":[]}'
    )
    transport = FakeGeminiTransport(response_text)
    provider = GeminiProvider(
        GeminiProviderConfig(
            model="test-model",
            profile_name="gemini-free",
            cost_tier="free",
        ),
        transport=transport,
    )

    result = provider.extract(_make_task(tmp_path))

    typography = result.normalized_data["blocks"][0]["content"][0]["typography"]
    assert typography["posture"] == "roman"
    assert result.attempts[0].metadata["prompt_version"] == "4"
    assert result.attempts[0].metadata["schema_version"] == "4"
    assert result.attempts[0].metadata["profile"] == "gemini-free"
    assert result.attempts[0].metadata["cost_tier"] == "free"

    assert transport.last_call is not None
    assert (
        transport.last_call["response_json_schema"]
        == EBOOK_PAGE_SCHEMA_V4.json_schema
    )


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


def test_gemini_provider_reports_empty_response_diagnostics(tmp_path: Path) -> None:
    """Empty output should explain finish/block metadata without raw content."""

    class EmptyDiagnosticTransport:
        def generate(self, **_: Any) -> GeminiTransportResponse:
            return GeminiTransportResponse(
                text="",
                diagnostics={
                    "candidate_count": 1,
                    "finish_reasons": ("MAX_TOKENS",),
                    "candidate_part_counts": (0,),
                    "prompt_block_reason": "BLOCK_REASON_UNSPECIFIED",
                },
            )

    provider = GeminiProvider(
        GeminiProviderConfig(model="test-model"),
        transport=EmptyDiagnosticTransport(),
    )

    with pytest.raises(InvalidGeminiResponseError) as caught:
        provider.extract(_make_task(tmp_path))

    message = str(caught.value)
    assert "Gemini returned an empty response" in message
    assert "candidate_count=1" in message
    assert "finish_reasons=MAX_TOKENS" in message
    assert "candidate_part_counts=0" in message
    assert "prompt_block_reason=BLOCK_REASON_UNSPECIFIED" in message


def test_response_text_falls_back_to_candidate_parts() -> None:
    """Recover text parts when the SDK convenience text is empty."""
    response = SimpleNamespace(
        text="",
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text='{"page_kind":"text"}')]
                )
            )
        ],
    )

    assert _extract_response_text(response) == '{"page_kind":"text"}'


def test_response_diagnostics_extracts_finish_and_prompt_feedback() -> None:
    """SDK generation metadata should be reduced to provider-safe diagnostics."""
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                finish_reason="MAX_TOKENS",
                content=SimpleNamespace(parts=[]),
                safety_ratings=[],
            )
        ],
        prompt_feedback=SimpleNamespace(
            block_reason="BLOCK_REASON_UNSPECIFIED",
            block_reason_message=None,
            safety_ratings=[],
        ),
    )

    diagnostics = _extract_response_diagnostics(response)

    assert diagnostics["candidate_count"] == 1
    assert diagnostics["finish_reasons"] == ("MAX_TOKENS",)
    assert diagnostics["candidate_part_counts"] == (0,)
    assert diagnostics["prompt_block_reason"] == "BLOCK_REASON_UNSPECIFIED"


def test_empty_response_exposes_recitation_finish_reason(tmp_path: Path) -> None:
    """Structured empty-output errors should retain RECITATION diagnostics."""

    class RecitationTransport:
        def generate(self, **_: Any) -> GeminiTransportResponse:
            return GeminiTransportResponse(
                text="",
                diagnostics={"finish_reasons": ("RECITATION",)},
            )

    provider = GeminiProvider(
        GeminiProviderConfig(model="test-model"),
        transport=RecitationTransport(),
    )

    with pytest.raises(InvalidGeminiResponseError) as caught:
        provider.extract(_make_task(tmp_path))

    assert caught.value.finish_reasons == ("RECITATION",)
    assert caught.value.is_recitation is True
