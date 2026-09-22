"""Gemini-specific failure classification for generic extraction routing."""

from __future__ import annotations

from siftforge.extraction.providers import (
    GeminiProviderError,
    GeminiRequestError,
    InvalidGeminiResponseError,
    MissingMaterializedAssetError,
)

from .routing import FailureDecision, FailureKind


class GeminiFailureClassifier:
    """Classify Gemini provider failures into retry and fallback decisions."""

    def classify(self, error: Exception) -> FailureDecision:
        """Return routing behavior for one Gemini extraction exception."""
        if isinstance(error, MissingMaterializedAssetError):
            return FailureDecision(
                kind=FailureKind.CONFIGURATION,
                retryable=False,
                continue_routing=False,
            )
        if isinstance(error, InvalidGeminiResponseError):
            if error.is_recitation:
                return FailureDecision(
                    kind=FailureKind.RECITATION,
                    retryable=False,
                    continue_routing=False,
                )
            return FailureDecision(
                kind=FailureKind.INVALID_OUTPUT,
                retryable=True,
                continue_routing=True,
            )
        if isinstance(error, GeminiRequestError):
            return _classify_request_error(error)
        if isinstance(error, GeminiProviderError):
            return FailureDecision(
                kind=FailureKind.CONFIGURATION,
                retryable=False,
                continue_routing=False,
            )
        return FailureDecision(
            kind=FailureKind.UNKNOWN,
            retryable=False,
            continue_routing=True,
        )


def _classify_request_error(error: GeminiRequestError) -> FailureDecision:
    """Classify one normalized Gemini request error by status and message."""
    status = error.status_code
    retry_after = error.retry_after_seconds
    message = str(error).lower()

    if status == 429:
        daily_quota = any(
            marker in message
            for marker in (
                "per day",
                "per-day",
                "daily",
                "requests_per_day",
                "requests per day",
                "requestsperday",
                "perdayperproject",
            )
        )
        if daily_quota:
            return FailureDecision(
                kind=FailureKind.QUOTA_EXHAUSTED,
                retryable=False,
                continue_routing=True,
                retry_after_seconds=retry_after,
            )
        return FailureDecision(
            kind=FailureKind.RATE_LIMIT,
            retryable=True,
            continue_routing=True,
            retry_after_seconds=retry_after,
        )

    if status in {408, 500, 502, 503, 504}:
        return FailureDecision(
            kind=FailureKind.TRANSIENT,
            retryable=True,
            continue_routing=True,
            retry_after_seconds=retry_after,
        )
    if status == 401:
        return FailureDecision(
            kind=FailureKind.AUTHENTICATION,
            retryable=False,
            continue_routing=True,
        )
    if status == 403:
        return FailureDecision(
            kind=FailureKind.PERMISSION,
            retryable=False,
            continue_routing=True,
        )
    if status == 400:
        return FailureDecision(
            kind=FailureKind.INVALID_REQUEST,
            retryable=False,
            continue_routing=False,
        )
    return FailureDecision(
        kind=FailureKind.UNKNOWN,
        retryable=False,
        continue_routing=True,
    )
