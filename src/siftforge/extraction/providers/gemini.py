"""Gemini implementation of the generic structured-extraction provider contract."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from siftforge.extraction.models import (
    Attempt,
    ExtractionResult,
    ExtractionTask,
    MaterializedAsset,
)


class GeminiProviderError(RuntimeError):
    """Base error raised by the Gemini provider boundary."""


class MissingMaterializedAssetError(GeminiProviderError):
    """Raised when a Gemini extraction task contains no local input asset."""


class InvalidGeminiResponseError(GeminiProviderError):
    """Raised when Gemini does not return valid JSON for a structured task.

    Provider-safe generation diagnostics are retained so routing and recovery
    layers can distinguish generic malformed output from terminal generation
    reasons such as ``RECITATION`` without parsing exception strings.
    """

    def __init__(
        self,
        message: str,
        *,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        """Store provider-safe generation diagnostics alongside the message."""
        super().__init__(message)
        self.diagnostics: dict[str, object] = dict(diagnostics or {})

    @property
    def finish_reasons(self) -> tuple[str, ...]:
        """Return normalized Gemini finish reasons attached to this failure."""
        value = self.diagnostics.get("finish_reasons")
        if isinstance(value, tuple):
            return tuple(str(item) for item in value)
        if isinstance(value, list):
            return tuple(str(item) for item in value)
        if value is None:
            return ()
        return (str(value),)

    @property
    def is_recitation(self) -> bool:
        """Return whether Gemini stopped generation for recitation filtering."""
        return any(reason.upper() == "RECITATION" for reason in self.finish_reasons)


class GeminiRequestError(GeminiProviderError):
    """Normalized transport error raised by the Google Gemini SDK boundary."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Store routing-relevant request metadata without provider secrets."""
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class GeminiProviderConfig:
    """Configuration for one Gemini extraction mechanism.

    Attributes:
        model: Explicit Gemini model identifier selected by caller policy/config.
        temperature: Generation temperature. Extraction defaults to deterministic.
        api_key: Optional API key. When omitted, the Google SDK may use its normal
            environment-based credential discovery.
        profile_name: Safe route/profile label persisted in attempt provenance.
        cost_tier: Safe cost classification such as ``free`` or ``paid``.
    """

    model: str
    temperature: float = 0.0
    api_key: str | None = field(default=None, repr=False)
    profile_name: str = "default"
    cost_tier: str = "unspecified"


@dataclass(frozen=True, slots=True)
class GeminiTransportResponse:
    """Provider-agnostic subset of a Gemini SDK response used by SiftForge.

    ``diagnostics`` contains only provider-safe generation metadata used to explain
    empty structured responses. It must never contain credentials, prompts, or raw
    user content.
    """

    text: str
    usage: dict[str, int | float | str | None] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)


class GeminiTransport(Protocol):
    """Small transport boundary that keeps the Google SDK out of provider tests."""

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        assets: tuple[MaterializedAsset, ...],
        response_json_schema: dict[str, Any],
        temperature: float,
    ) -> GeminiTransportResponse:
        """Generate one structured response from Gemini."""
        ...


class GeminiProvider:
    """Run structured multimodal extraction through Gemini.

    The provider knows how to call Gemini but does not know anything about books,
    invoices, websites, or other application domains. Routing, retries, free/paid
    escalation, and provider selection deliberately live elsewhere.

    Args:
        config: Explicit provider/model configuration.
        transport: Optional injected transport used by tests or alternative clients.
            When omitted, the official ``google-genai`` SDK transport is created
            lazily.
    """

    def __init__(
        self,
        config: GeminiProviderConfig,
        transport: GeminiTransport | None = None,
    ) -> None:
        """Initialize a Gemini mechanism without making any network request."""
        self._config: GeminiProviderConfig = config
        self._transport: GeminiTransport = transport or _GoogleGenAITransport(
            api_key=config.api_key
        )

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Execute one structured extraction task with Gemini.

        Args:
            task: Provider-independent task containing assets, prompt, and schema.

        Returns:
            Extraction result containing raw JSON text, parsed JSON data, and attempt
            provenance.

        Raises:
            MissingMaterializedAssetError: If the task has no local input asset.
            InvalidGeminiResponseError: If Gemini returns empty or malformed JSON.
            GeminiRequestError: If the Gemini SDK request fails.
        """
        if not task.assets:
            raise MissingMaterializedAssetError(
                f"task {task.source.source_id!r} has no materialized assets"
            )

        response = self._transport.generate(
            model=self._config.model,
            prompt=task.prompt.text,
            assets=task.assets,
            response_json_schema=task.schema.json_schema,
            temperature=self._config.temperature,
        )

        if not response.text.strip():
            detail = _format_empty_response_diagnostics(response.diagnostics)
            message = "Gemini returned an empty response"
            if detail:
                message = f"{message} ({detail})"
            raise InvalidGeminiResponseError(
                message,
                diagnostics=response.diagnostics,
            )

        try:
            normalized_data: Any = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise InvalidGeminiResponseError(
                "Gemini returned malformed JSON for a structured extraction task"
            ) from exc

        return ExtractionResult(
            task=task,
            raw_data=response.text,
            normalized_data=normalized_data,
            attempts=(
                Attempt(
                    mechanism="ai",
                    provider="gemini",
                    status="success",
                    metadata={
                        "model": self._config.model,
                        "temperature": self._config.temperature,
                        "profile": self._config.profile_name,
                        "cost_tier": self._config.cost_tier,
                        "prompt_name": task.prompt.name,
                        "prompt_version": task.prompt.version,
                        "schema_name": task.schema.name,
                        "schema_version": task.schema.version,
                        "usage": response.usage,
                    },
                ),
            ),
        )


class _GoogleGenAITransport:
    """Lazy adapter around the official Google Gen AI Python SDK."""

    def __init__(self, api_key: str | None) -> None:
        """Store credential configuration without importing the optional SDK yet."""
        self._api_key: str | None = api_key
        self._client: Any | None = None

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        assets: tuple[MaterializedAsset, ...],
        response_json_schema: dict[str, Any],
        temperature: float,
    ) -> GeminiTransportResponse:
        """Call ``google-genai`` with local assets and JSON structured output."""
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise GeminiProviderError(
                'Gemini support is not installed; run pip install -e ".[gemini]"'
            ) from exc

        if self._client is None:
            self._client = (
                genai.Client(api_key=self._api_key)
                if self._api_key
                else genai.Client()
            )

        parts: list[Any] = [prompt]
        parts.extend(
            types.Part.from_bytes(
                data=asset.path.read_bytes(),
                mime_type=asset.media_type,
            )
            for asset in assets
        )

        try:
            response = self._client.models.generate_content(
                model=model,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=response_json_schema,
                    temperature=temperature,
                ),
            )
        except Exception as exc:
            raise _normalize_request_error(exc) from exc

        text: str = _extract_response_text(response)
        usage: dict[str, int | float | str | None] = _extract_usage(response)
        diagnostics = _extract_response_diagnostics(response)
        for usage_key in (
            "candidates_token_count",
            "total_token_count",
            "thoughts_token_count",
        ):
            usage_value = usage.get(usage_key)
            if usage_value is not None:
                diagnostics[f"usage_{usage_key}"] = usage_value
        return GeminiTransportResponse(
            text=text,
            usage=usage,
            diagnostics=diagnostics,
        )



def _extract_response_text(response: Any) -> str:
    """Return generated text, with a conservative candidate-part fallback.

    The Google SDK normally exposes joined text through ``response.text``. A small
    manual fallback is useful for SDK edge cases where textual candidate parts are
    present but the convenience property is empty. Only literal text parts are
    joined; non-text parts are ignored.
    """
    try:
        text: Any = getattr(response, "text", None)
    except Exception:
        text = None
    if isinstance(text, str) and text.strip():
        return text

    recovered: list[str] = []
    candidates: Any = getattr(response, "candidates", None)
    if not isinstance(candidates, (list, tuple)):
        return text if isinstance(text, str) else ""

    for candidate in candidates:
        content: Any = getattr(candidate, "content", None)
        parts: Any = getattr(content, "parts", None)
        if not isinstance(parts, (list, tuple)):
            continue
        for part in parts:
            part_text: Any = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text:
                recovered.append(part_text)
    return "".join(recovered)


def _extract_response_diagnostics(response: Any) -> dict[str, object]:
    """Return provider-safe metadata that explains an empty Gemini response."""
    diagnostics: dict[str, object] = {}

    candidates: Any = getattr(response, "candidates", None)
    if isinstance(candidates, (list, tuple)):
        diagnostics["candidate_count"] = len(candidates)
        finish_reasons: list[str] = []
        part_counts: list[int] = []
        safety_summaries: list[str] = []
        for candidate in candidates:
            finish_reason = _diagnostic_scalar(
                getattr(candidate, "finish_reason", None)
            )
            if finish_reason is not None:
                finish_reasons.append(finish_reason)

            content: Any = getattr(candidate, "content", None)
            parts: Any = getattr(content, "parts", None)
            if isinstance(parts, (list, tuple)):
                part_counts.append(len(parts))

            ratings: Any = getattr(candidate, "safety_ratings", None)
            summary = _summarize_safety_ratings(ratings)
            if summary:
                safety_summaries.append(summary)

        if finish_reasons:
            diagnostics["finish_reasons"] = tuple(finish_reasons)
        if part_counts:
            diagnostics["candidate_part_counts"] = tuple(part_counts)
        if safety_summaries:
            diagnostics["candidate_safety"] = tuple(safety_summaries)

    prompt_feedback: Any = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        block_reason = _diagnostic_scalar(
            getattr(prompt_feedback, "block_reason", None)
        )
        if block_reason is not None:
            diagnostics["prompt_block_reason"] = block_reason

        block_reason_message = _diagnostic_scalar(
            getattr(prompt_feedback, "block_reason_message", None)
        )
        if block_reason_message is not None:
            diagnostics["prompt_block_message"] = block_reason_message

        prompt_safety = _summarize_safety_ratings(
            getattr(prompt_feedback, "safety_ratings", None)
        )
        if prompt_safety:
            diagnostics["prompt_safety"] = prompt_safety

    return diagnostics


def _summarize_safety_ratings(ratings: Any) -> str | None:
    """Return a compact category/probability summary without prompt content."""
    if not isinstance(ratings, (list, tuple)):
        return None
    items: list[str] = []
    for rating in ratings:
        category = _diagnostic_scalar(getattr(rating, "category", None))
        probability = _diagnostic_scalar(getattr(rating, "probability", None))
        blocked = getattr(rating, "blocked", None)
        if category is None and probability is None and not isinstance(blocked, bool):
            continue
        fields = [value for value in (category, probability) if value is not None]
        item = ":".join(fields) if fields else "safety"
        if isinstance(blocked, bool):
            item = f"{item}:blocked={str(blocked).lower()}"
        items.append(item)
    return ",".join(items) if items else None


def _diagnostic_scalar(value: Any) -> str | None:
    """Convert one SDK enum/scalar into a stable short diagnostic string."""
    if value is None:
        return None
    for attribute in ("value", "name"):
        nested = getattr(value, attribute, None)
        if isinstance(nested, (str, int, float)) and not isinstance(nested, bool):
            text = str(nested).strip()
            if text:
                return text
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    text = str(value).strip()
    return text or None


def _format_empty_response_diagnostics(diagnostics: dict[str, object]) -> str:
    """Format selected empty-response metadata for CLI-safe exception text."""
    if not diagnostics:
        return ""
    ordered_keys = (
        "candidate_count",
        "finish_reasons",
        "candidate_part_counts",
        "prompt_block_reason",
        "prompt_block_message",
        "candidate_safety",
        "prompt_safety",
        "usage_candidates_token_count",
        "usage_thoughts_token_count",
        "usage_total_token_count",
    )
    items: list[str] = []
    for key in ordered_keys:
        if key not in diagnostics:
            continue
        value = diagnostics[key]
        if isinstance(value, tuple):
            rendered = ",".join(str(item) for item in value)
        else:
            rendered = str(value)
        if rendered:
            items.append(f"{key}={rendered}")
    return "; ".join(items)


def _normalize_request_error(error: Exception) -> GeminiRequestError:
    """Normalize common SDK exception metadata for provider-agnostic routing."""
    status_code = _status_code(error)
    retry_after = _retry_after_seconds(error)
    message = str(error).strip() or type(error).__name__
    return GeminiRequestError(
        message,
        status_code=status_code,
        retry_after_seconds=retry_after,
    )


def _status_code(error: Exception) -> int | None:
    """Best-effort extraction of an HTTP status code from SDK exceptions."""
    for value in (
        getattr(error, "status_code", None),
        getattr(error, "code", None),
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            return value

    response: Any = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _retry_after_seconds(error: Exception) -> float | None:
    """Best-effort extraction of a provider retry hint from SDK exceptions."""
    value = getattr(error, "retry_after_seconds", None)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)

    response: Any = getattr(error, "response", None)
    headers: Any = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        raw_value: Any = headers.get("retry-after")
    except AttributeError:
        return None
    if isinstance(raw_value, str):
        try:
            parsed = float(raw_value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _extract_usage(response: Any) -> dict[str, int | float | str | None]:
    """Return a stable small usage dictionary from a Google SDK response."""
    metadata: Any = getattr(response, "usage_metadata", None)
    if metadata is None:
        return {}

    field_names: tuple[str, ...] = (
        "prompt_token_count",
        "candidates_token_count",
        "total_token_count",
        "cached_content_token_count",
        "thoughts_token_count",
    )
    usage: dict[str, int | float | str | None] = {}
    for field_name in field_names:
        value: Any = getattr(metadata, field_name, None)
        if isinstance(value, (int, float, str)) or value is None:
            usage[field_name] = value
    return usage
