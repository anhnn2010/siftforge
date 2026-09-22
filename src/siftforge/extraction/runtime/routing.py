"""Cost-aware extraction routing with retry and fallback provenance."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from siftforge.extraction.models import Attempt, ExtractionResult, ExtractionTask
from siftforge.extraction.providers import Extractor


class CostTier(StrEnum):
    """Relative billing tier associated with one extraction route."""

    FREE = "free"
    PAID = "paid"
    UNSPECIFIED = "unspecified"


class FailureKind(StrEnum):
    """Stable failure categories used by routing policy decisions."""

    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    INVALID_OUTPUT = "invalid_output"
    RECITATION = "recitation"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    INVALID_REQUEST = "invalid_request"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FailureDecision:
    """Classification result for one failed extraction attempt.

    Attributes:
        kind: Stable reason category persisted in attempt provenance.
        retryable: Whether the same route may be attempted again.
        continue_routing: Whether a later fallback route may still help.
        retry_after_seconds: Optional provider-supplied minimum delay.
    """

    kind: FailureKind
    retryable: bool
    continue_routing: bool
    retry_after_seconds: float | None = None


class FailureClassifier(Protocol):
    """Classify mechanism exceptions for retry and fallback policy."""

    def classify(self, error: Exception) -> FailureDecision:
        """Return routing behavior for one extraction exception."""
        ...


@dataclass(frozen=True, slots=True)
class ExtractionRoute:
    """One ordered extraction mechanism available to the router.

    Attributes:
        name: Stable human-readable route/profile name.
        extractor: Concrete mechanism used for the route.
        classifier: Provider-aware error classifier for the mechanism.
        provider: Provider name stored in failed-attempt provenance.
        cost_tier: Free/paid classification used by free-first policy.
        max_attempts: Maximum calls made on this route for one task.
    """

    name: str
    extractor: Extractor
    classifier: FailureClassifier
    provider: str | None
    cost_tier: CostTier
    max_attempts: int = 1

    def __post_init__(self) -> None:
        """Reject invalid route configuration before any provider call."""
        if not self.name.strip():
            raise ValueError("extraction route name must not be empty")
        if self.max_attempts < 1:
            raise ValueError("extraction route max_attempts must be at least 1")


class RoutingPolicy(StrEnum):
    """Supported cost policies for ordered extraction routes."""

    FREE_ONLY = "free-only"
    FREE_THEN_PAID = "free-then-paid"


class ExtractionRoutingError(RuntimeError):
    """Raised after routing cannot produce one successful extraction result."""

    def __init__(
        self,
        message: str,
        *,
        attempts: Sequence[Attempt],
        last_error: Exception,
    ) -> None:
        """Store safe attempt provenance and the final mechanism exception."""
        super().__init__(message)
        self.attempts: tuple[Attempt, ...] = tuple(attempts)
        self.last_error: Exception = last_error


SleepFunction = Callable[[float], None]


class FreeFirstRouter:
    """Try free extraction routes before optional paid fallbacks.

    Routes are evaluated in the order supplied, but configuration is validated so
    a free route can never appear after a paid route. This makes the cost policy
    explicit and prevents a future caller from accidentally paying before all
    configured free mechanisms have been attempted.

    Args:
        routes: Ordered free-first extraction routes.
        policy: Whether paid routes are allowed after free routes fail.
        base_backoff_seconds: Initial exponential retry delay.
        max_backoff_seconds: Upper bound for one retry delay.
        sleep: Injectable sleep function used by tests.
    """

    def __init__(
        self,
        routes: Sequence[ExtractionRoute],
        *,
        policy: RoutingPolicy = RoutingPolicy.FREE_ONLY,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 8.0,
        sleep: SleepFunction = time.sleep,
    ) -> None:
        """Validate and store free-first routing configuration."""
        if not routes:
            raise ValueError("free-first router requires at least one route")
        if base_backoff_seconds < 0:
            raise ValueError("base backoff must not be negative")
        if max_backoff_seconds < base_backoff_seconds:
            raise ValueError("max backoff must be at least base backoff")

        seen_paid = False
        for route in routes:
            if route.cost_tier is CostTier.PAID:
                seen_paid = True
            elif route.cost_tier is CostTier.FREE and seen_paid:
                raise ValueError("free routes must appear before paid routes")

        if policy is RoutingPolicy.FREE_ONLY and not any(
            route.cost_tier is CostTier.FREE for route in routes
        ):
            raise ValueError("free-only routing requires at least one free route")

        self._routes: tuple[ExtractionRoute, ...] = tuple(routes)
        self._policy: RoutingPolicy = policy
        self._base_backoff_seconds = base_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._sleep: SleepFunction = sleep

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Run one task through retryable free-first routes.

        Failed route attempts are prepended to the successful provider attempt
        history. If all permitted routes fail, ``ExtractionRoutingError`` exposes
        the same provenance so higher-level checkpointing can persist it.
        """
        failed_attempts: list[Attempt] = []
        last_error: Exception | None = None

        for route in self._eligible_routes():
            for attempt_number in range(1, route.max_attempts + 1):
                try:
                    result = route.extractor.extract(task)
                except Exception as error:
                    last_error = error
                    decision = route.classifier.classify(error)
                    failed_attempts.append(
                        _failed_attempt(
                            route=route,
                            attempt_number=attempt_number,
                            error=error,
                            decision=decision,
                        )
                    )

                    if decision.retryable and attempt_number < route.max_attempts:
                        self._sleep(
                            self._retry_delay(
                                attempt_number=attempt_number,
                                minimum=decision.retry_after_seconds,
                            )
                        )
                        continue

                    if decision.continue_routing:
                        break
                    raise ExtractionRoutingError(
                        _failure_message(task, route, decision),
                        attempts=failed_attempts,
                        last_error=error,
                    ) from error

                return ExtractionResult(
                    task=result.task,
                    raw_data=result.raw_data,
                    normalized_data=result.normalized_data,
                    attempts=tuple(failed_attempts) + result.attempts,
                )

        if last_error is None:
            raise RuntimeError("routing ended without executing an eligible route")
        raise ExtractionRoutingError(
            f"all permitted extraction routes failed for {task.source.source_id!r}",
            attempts=failed_attempts,
            last_error=last_error,
        ) from last_error

    def _eligible_routes(self) -> tuple[ExtractionRoute, ...]:
        """Return routes allowed by the configured cost policy."""
        if self._policy is RoutingPolicy.FREE_THEN_PAID:
            return self._routes
        return tuple(
            route for route in self._routes if route.cost_tier is CostTier.FREE
        )

    def _retry_delay(
        self,
        *,
        attempt_number: int,
        minimum: float | None,
    ) -> float:
        """Return bounded exponential delay honoring provider retry hints."""
        delay = min(
            self._base_backoff_seconds * (2 ** (attempt_number - 1)),
            self._max_backoff_seconds,
        )
        if minimum is not None:
            return max(delay, minimum)
        return delay


def _failed_attempt(
    *,
    route: ExtractionRoute,
    attempt_number: int,
    error: Exception,
    decision: FailureDecision,
) -> Attempt:
    """Build sanitized provenance for one failed route call."""
    metadata: dict[str, object] = {
        "route": route.name,
        "cost_tier": route.cost_tier.value,
        "attempt_number": attempt_number,
        "max_attempts": route.max_attempts,
        "error_type": type(error).__name__,
        "retryable": decision.retryable,
        "continue_routing": decision.continue_routing,
    }
    if decision.retry_after_seconds is not None:
        metadata["retry_after_seconds"] = decision.retry_after_seconds
    return Attempt(
        mechanism="ai",
        provider=route.provider,
        status="failed",
        reason=decision.kind.value,
        metadata=metadata,
    )


def _failure_message(
    task: ExtractionTask,
    route: ExtractionRoute,
    decision: FailureDecision,
) -> str:
    """Return a compact routing failure message without credentials."""
    return (
        f"extraction route {route.name!r} failed for "
        f"{task.source.source_id!r}: {decision.kind.value}"
    )
