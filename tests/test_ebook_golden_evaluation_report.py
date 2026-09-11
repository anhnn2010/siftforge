"""Tests for human-readable golden evaluation and token-usage reports."""

from __future__ import annotations

import json
from pathlib import Path

from siftforge.ebook.evaluation import (
    EvaluationCategory,
    GoldenPageFixtureLoader,
    GoldenRegressionEvaluator,
)

_FIXTURE_ROOT = Path("tests/fixtures/ebook/golden/v5")


def test_golden_evaluation_report_passes_all_named_expectations() -> None:
    """The accepted v5 golden suite should pass every named capability check."""
    report = GoldenRegressionEvaluator().evaluate_root(_FIXTURE_ROOT)

    assert report.passed is True
    assert len(report.cases) == 9
    assert report.total_checks == 22
    assert report.passed_checks == 22
    assert report.category_counts() == {
        EvaluationCategory.LANGUAGE: (1, 1),
        EvaluationCategory.TYPOGRAPHY: (3, 3),
        EvaluationCategory.STRUCTURE: (10, 10),
        EvaluationCategory.MARKER: (3, 3),
        EvaluationCategory.FIGURE: (3, 3),
        EvaluationCategory.ROLE: (2, 2),
    }


def test_golden_evaluation_report_aggregates_real_run_token_usage() -> None:
    """Token totals should remain tied to the extraction runs behind fixtures."""
    report = GoldenRegressionEvaluator().evaluate_root(_FIXTURE_ROOT)
    usage = report.token_usage

    assert usage.prompt_token_count == 23177
    assert usage.candidates_token_count == 19379
    assert usage.thoughts_token_count == 20036
    assert usage.total_token_count == 62592
    assert usage.cached_content_token_count is None


def test_golden_evaluation_report_renders_text_and_json() -> None:
    """Both report formats should expose quality and usage without ambiguity."""
    report = GoldenRegressionEvaluator().evaluate_root(_FIXTURE_ROOT)

    text = report.to_text()
    assert "result: PASS" in text
    assert "cases:  9/9 passed" in text
    assert "checks: 22/22 passed" in text
    assert "total=62,592" in text

    payload = json.loads(report.to_json())
    assert payload["passed"] is True
    assert payload["summary"]["checks_total"] == 22
    assert payload["token_usage"]["total_token_count"] == 62592
    assert len(payload["cases"]) == 9


def test_golden_fixture_loader_exposes_per_case_usage() -> None:
    """Fixture metadata should retain usage required for cost-aware evaluation."""
    fixture = GoldenPageFixtureLoader().load(_FIXTURE_ROOT / "page-0116")

    assert fixture.usage.prompt_token_count == 2351
    assert fixture.usage.candidates_token_count == 662
    assert fixture.usage.thoughts_token_count == 1122
    assert fixture.usage.total_token_count == 4135
