"""Evaluation helpers for ebook extraction and structural regression suites."""

from .golden import (
    GoldenFixtureError,
    GoldenPageFixture,
    GoldenPageFixtureLoader,
    TokenUsage,
)
from .report import (
    AggregateTokenUsage,
    EvaluationCategory,
    EvaluationCheckResult,
    GoldenCaseEvaluation,
    GoldenEvaluationReport,
    GoldenRegressionEvaluator,
)

__all__: list[str] = [
    "AggregateTokenUsage",
    "EvaluationCategory",
    "EvaluationCheckResult",
    "GoldenCaseEvaluation",
    "GoldenEvaluationReport",
    "GoldenFixtureError",
    "GoldenPageFixture",
    "GoldenPageFixtureLoader",
    "GoldenRegressionEvaluator",
    "TokenUsage",
]
