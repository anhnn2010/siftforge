"""Tests for free-first generic extraction routing and Gemini classification."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from siftforge.ebook.extraction import EBOOK_PAGE_PROMPT_V4, EBOOK_PAGE_SCHEMA_V4
from siftforge.extraction.models import (
    Attempt,
    ExtractionResult,
    ExtractionTask,
    SourceRef,
)
from siftforge.extraction.providers import (
    GeminiRequestError,
    InvalidGeminiResponseError,
)
from siftforge.extraction.runtime import (
    CostTier,
    ExtractionRoute,
    ExtractionRoutingError,
    FailureKind,
    FreeFirstRouter,
    GeminiFailureClassifier,
    RoutingPolicy,
)


@dataclass
class ScriptedExtractor:
    """Return or raise scripted outcomes while counting calls."""

    outcomes: list[ExtractionResult | Exception]
    calls: int = 0

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Consume one scripted outcome."""
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ExtractionResult(
            task=task,
            raw_data=outcome.raw_data,
            normalized_data=outcome.normalized_data,
            attempts=outcome.attempts,
        )


def _task() -> ExtractionTask:
    """Create a minimal provider-independent extraction task."""
    return ExtractionTask(
        source=SourceRef(
            source_id="fixture:page:0001",
            uri="fixture://page/1",
        ),
        capability="document_transcription",
        prompt=EBOOK_PAGE_PROMPT_V4,
        schema=EBOOK_PAGE_SCHEMA_V4,
    )


def _success(profile: str, tier: CostTier) -> ExtractionResult:
    """Create a successful result carrying one provider attempt."""
    task = _task()
    return ExtractionResult(
        task=task,
        raw_data='{"ok": true}',
        normalized_data={"ok": True},
        attempts=(
            Attempt(
                mechanism="ai",
                provider="gemini",
                status="success",
                metadata={"profile": profile, "cost_tier": tier.value},
            ),
        ),
    )


def _route(
    name: str,
    extractor: ScriptedExtractor,
    tier: CostTier,
    *,
    max_attempts: int = 1,
) -> ExtractionRoute:
    """Build one Gemini-classified extraction route for tests."""
    return ExtractionRoute(
        name=name,
        extractor=extractor,
        classifier=GeminiFailureClassifier(),
        provider="gemini",
        cost_tier=tier,
        max_attempts=max_attempts,
    )


def test_free_success_never_calls_paid_route() -> None:
    """A successful free attempt must stop routing before any paid mechanism."""
    free = ScriptedExtractor([_success("free", CostTier.FREE)])
    paid = ScriptedExtractor([_success("paid", CostTier.PAID)])
    router = FreeFirstRouter(
        (_route("free", free, CostTier.FREE), _route("paid", paid, CostTier.PAID)),
        policy=RoutingPolicy.FREE_THEN_PAID,
        sleep=lambda _: None,
    )

    result = router.extract(_task())

    assert free.calls == 1
    assert paid.calls == 0
    assert result.attempts[-1].metadata["profile"] == "free"


def test_transient_free_failure_retries_before_paid() -> None:
    """Transient free failures should consume configured free retries first."""
    free = ScriptedExtractor(
        [
            GeminiRequestError("server busy", status_code=503),
            GeminiRequestError("server busy", status_code=503),
            _success("free", CostTier.FREE),
        ]
    )
    paid = ScriptedExtractor([_success("paid", CostTier.PAID)])
    delays: list[float] = []
    router = FreeFirstRouter(
        (
            _route("free", free, CostTier.FREE, max_attempts=3),
            _route("paid", paid, CostTier.PAID),
        ),
        policy=RoutingPolicy.FREE_THEN_PAID,
        base_backoff_seconds=1.0,
        max_backoff_seconds=8.0,
        sleep=delays.append,
    )

    result = router.extract(_task())

    assert free.calls == 3
    assert paid.calls == 0
    assert delays == [1.0, 2.0]
    assert [attempt.reason for attempt in result.attempts[:-1]] == [
        FailureKind.TRANSIENT.value,
        FailureKind.TRANSIENT.value,
    ]


def test_free_only_policy_never_calls_configured_paid_route() -> None:
    """Free-only mode should fail safely instead of silently spending money."""
    free = ScriptedExtractor(
        [GeminiRequestError("daily requests per day exhausted", status_code=429)]
    )
    paid = ScriptedExtractor([_success("paid", CostTier.PAID)])
    router = FreeFirstRouter(
        (_route("free", free, CostTier.FREE), _route("paid", paid, CostTier.PAID)),
        policy=RoutingPolicy.FREE_ONLY,
        sleep=lambda _: None,
    )

    with pytest.raises(ExtractionRoutingError) as caught:
        router.extract(_task())

    assert free.calls == 1
    assert paid.calls == 0
    assert caught.value.attempts[0].reason == FailureKind.QUOTA_EXHAUSTED.value


def test_paid_fallback_runs_after_exhausted_free_quota() -> None:
    """Explicit free-then-paid mode should fall back after free quota exhaustion."""
    free = ScriptedExtractor(
        [GeminiRequestError("daily requests per day exhausted", status_code=429)]
    )
    paid = ScriptedExtractor([_success("paid", CostTier.PAID)])
    router = FreeFirstRouter(
        (_route("free", free, CostTier.FREE), _route("paid", paid, CostTier.PAID)),
        policy=RoutingPolicy.FREE_THEN_PAID,
        sleep=lambda _: None,
    )

    result = router.extract(_task())

    assert free.calls == 1
    assert paid.calls == 1
    assert result.attempts[0].status == "failed"
    assert result.attempts[0].reason == FailureKind.QUOTA_EXHAUSTED.value
    assert result.attempts[1].metadata["profile"] == "paid"


def test_invalid_request_aborts_without_paid_fallback() -> None:
    """A task-level bad request should not be repeated through paid routes."""
    free = ScriptedExtractor([GeminiRequestError("bad request", status_code=400)])
    paid = ScriptedExtractor([_success("paid", CostTier.PAID)])
    router = FreeFirstRouter(
        (_route("free", free, CostTier.FREE), _route("paid", paid, CostTier.PAID)),
        policy=RoutingPolicy.FREE_THEN_PAID,
        sleep=lambda _: None,
    )

    with pytest.raises(ExtractionRoutingError) as caught:
        router.extract(_task())

    assert paid.calls == 0
    assert caught.value.attempts[0].reason == FailureKind.INVALID_REQUEST.value


def test_invalid_output_can_retry_and_fallback() -> None:
    """Malformed structured output should be retryable before route escalation."""
    free = ScriptedExtractor(
        [
            InvalidGeminiResponseError("bad json"),
            InvalidGeminiResponseError("bad json"),
        ]
    )
    paid = ScriptedExtractor([_success("paid", CostTier.PAID)])
    router = FreeFirstRouter(
        (
            _route("free", free, CostTier.FREE, max_attempts=2),
            _route("paid", paid, CostTier.PAID),
        ),
        policy=RoutingPolicy.FREE_THEN_PAID,
        sleep=lambda _: None,
    )

    result = router.extract(_task())

    assert free.calls == 2
    assert paid.calls == 1
    assert [attempt.reason for attempt in result.attempts[:2]] == [
        FailureKind.INVALID_OUTPUT.value,
        FailureKind.INVALID_OUTPUT.value,
    ]


def test_router_rejects_free_route_after_paid_route() -> None:
    """Free-first configuration should make accidental paid-first order invalid."""
    free = ScriptedExtractor([_success("free", CostTier.FREE)])
    paid = ScriptedExtractor([_success("paid", CostTier.PAID)])

    with pytest.raises(ValueError, match="free routes must appear before paid routes"):
        FreeFirstRouter(
            (_route("paid", paid, CostTier.PAID), _route("free", free, CostTier.FREE))
        )


def test_rate_limit_classifier_preserves_retry_hint() -> None:
    """429 rate limits should remain retryable and preserve retry-after hints."""
    decision = GeminiFailureClassifier().classify(
        GeminiRequestError(
            "rate limit exceeded",
            status_code=429,
            retry_after_seconds=2.5,
        )
    )

    assert decision.kind is FailureKind.RATE_LIMIT
    assert decision.retryable is True
    assert decision.continue_routing is True
    assert decision.retry_after_seconds == 2.5


def test_free_only_router_rejects_paid_only_configuration() -> None:
    """Generic free-only policy must never silently run a paid-only route set."""
    paid = ScriptedExtractor([_success("paid", CostTier.PAID)])

    with pytest.raises(ValueError, match="requires at least one free route"):
        FreeFirstRouter(
            (_route("paid", paid, CostTier.PAID),),
            policy=RoutingPolicy.FREE_ONLY,
        )
