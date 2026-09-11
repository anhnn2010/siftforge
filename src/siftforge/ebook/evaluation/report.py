"""Human-readable golden evaluation reports for ebook regression evidence.

The report layer turns the real-run golden fixtures into named feature checks.
It complements pytest: failures are grouped by capability and token usage is
reported alongside quality so future provider and prompt comparisons can use
one stable evaluation surface.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from siftforge.ebook.evidence import (
    BlockRoleHint,
    HeadingRoleHint,
    MarkerKind,
    PageBlockEvidence,
)
from siftforge.ebook.models import FontPosture, VerticalPosition
from siftforge.ebook.structure import (
    BookStructuralAnalyzer,
    FigureNode,
    ListNode,
    ParagraphNode,
    StructuralAnalysisResult,
    VerseNode,
)

from .golden import GoldenPageFixture, GoldenPageFixtureLoader, TokenUsage


class EvaluationCategory(StrEnum):
    """Stable quality dimensions surfaced by golden evaluation reports."""

    TEXT = "text"
    LANGUAGE = "language"
    TYPOGRAPHY = "typography"
    STRUCTURE = "structure"
    MARKER = "marker"
    FIGURE = "figure"
    ROLE = "role"


@dataclass(frozen=True, slots=True)
class EvaluationCheckResult:
    """Outcome of one named golden expectation."""

    name: str
    category: EvaluationCategory
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class GoldenCaseEvaluation:
    """Evaluation result for one real-run golden page fixture."""

    case_id: str
    source_page_number: int
    model: str
    prompt_version: str
    schema_version: str
    tags: tuple[str, ...]
    usage: TokenUsage
    checks: tuple[EvaluationCheckResult, ...]

    @property
    def passed(self) -> bool:
        """Return whether all expectations for this page passed."""
        return all(check.passed for check in self.checks)


@dataclass(frozen=True, slots=True)
class AggregateTokenUsage:
    """Token totals across evaluated real extraction runs."""

    prompt_token_count: int
    candidates_token_count: int
    thoughts_token_count: int
    total_token_count: int
    cached_content_token_count: int | None


@dataclass(frozen=True, slots=True)
class GoldenEvaluationReport:
    """Named feature results and usage totals for one golden suite run."""

    cases: tuple[GoldenCaseEvaluation, ...]

    @property
    def passed(self) -> bool:
        """Return whether every case and check passed."""
        return all(case.passed for case in self.cases)

    @property
    def total_checks(self) -> int:
        """Return the number of evaluated feature expectations."""
        return sum(len(case.checks) for case in self.cases)

    @property
    def passed_checks(self) -> int:
        """Return the number of passing feature expectations."""
        return sum(
            check.passed
            for case in self.cases
            for check in case.checks
        )

    @property
    def token_usage(self) -> AggregateTokenUsage:
        """Aggregate provider token usage from all real-run fixtures."""
        cached_values = [
            case.usage.cached_content_token_count
            for case in self.cases
            if case.usage.cached_content_token_count is not None
        ]
        cached_total = sum(cached_values) if cached_values else None
        return AggregateTokenUsage(
            prompt_token_count=sum(
                case.usage.prompt_token_count for case in self.cases
            ),
            candidates_token_count=sum(
                case.usage.candidates_token_count for case in self.cases
            ),
            thoughts_token_count=sum(
                case.usage.thoughts_token_count for case in self.cases
            ),
            total_token_count=sum(
                case.usage.total_token_count for case in self.cases
            ),
            cached_content_token_count=cached_total,
        )

    def category_counts(self) -> dict[EvaluationCategory, tuple[int, int]]:
        """Return ``category -> (passed, total)`` in enum order."""
        passed: Counter[EvaluationCategory] = Counter()
        total: Counter[EvaluationCategory] = Counter()
        for case in self.cases:
            for check in case.checks:
                total[check.category] += 1
                if check.passed:
                    passed[check.category] += 1
        return {
            category: (passed[category], total[category])
            for category in EvaluationCategory
            if total[category]
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to deterministic JSON-compatible data."""
        usage = self.token_usage
        categories = self.category_counts()
        return {
            "passed": self.passed,
            "summary": {
                "cases_passed": sum(case.passed for case in self.cases),
                "cases_total": len(self.cases),
                "checks_passed": self.passed_checks,
                "checks_total": self.total_checks,
            },
            "token_usage": {
                "prompt_token_count": usage.prompt_token_count,
                "candidates_token_count": usage.candidates_token_count,
                "thoughts_token_count": usage.thoughts_token_count,
                "total_token_count": usage.total_token_count,
                "cached_content_token_count": (
                    usage.cached_content_token_count
                ),
            },
            "categories": {
                category.value: {"passed": values[0], "total": values[1]}
                for category, values in categories.items()
            },
            "cases": [self._case_to_dict(case) for case in self.cases],
        }

    def to_json(self) -> str:
        """Render deterministic pretty JSON suitable for CI artifacts."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    def to_text(self) -> str:
        """Render a compact human-readable evaluation summary."""
        case_passed = sum(case.passed for case in self.cases)
        usage = self.token_usage
        lines = [
            "SiftForge ebook golden evaluation",
            f"result: {'PASS' if self.passed else 'FAIL'}",
            f"cases:  {case_passed}/{len(self.cases)} passed",
            f"checks: {self.passed_checks}/{self.total_checks} passed",
            (
                "tokens: "
                f"total={usage.total_token_count:,} "
                f"prompt={usage.prompt_token_count:,} "
                f"candidate={usage.candidates_token_count:,} "
                f"thoughts={usage.thoughts_token_count:,}"
            ),
            "categories:",
        ]
        for category, (passed, total) in self.category_counts().items():
            lines.append(f"  {category.value:<10} {passed}/{total}")
        lines.append("cases:")
        for case in self.cases:
            status = "PASS" if case.passed else "FAIL"
            check_passed = sum(check.passed for check in case.checks)
            lines.append(
                f"  {status} {case.case_id} "
                f"{check_passed}/{len(case.checks)} "
                f"tokens={case.usage.total_token_count:,}"
            )
            for check in case.checks:
                if not check.passed:
                    lines.append(
                        f"    FAIL [{check.category.value}] "
                        f"{check.name}: {check.detail}"
                    )
        return "\n".join(lines) + "\n"

    def _case_to_dict(self, case: GoldenCaseEvaluation) -> dict[str, Any]:
        """Serialize one evaluated case."""
        return {
            "case_id": case.case_id,
            "source_page_number": case.source_page_number,
            "model": case.model,
            "prompt_version": case.prompt_version,
            "schema_version": case.schema_version,
            "tags": list(case.tags),
            "passed": case.passed,
            "usage": {
                "prompt_token_count": case.usage.prompt_token_count,
                "candidates_token_count": case.usage.candidates_token_count,
                "thoughts_token_count": case.usage.thoughts_token_count,
                "total_token_count": case.usage.total_token_count,
                "cached_content_token_count": (
                    case.usage.cached_content_token_count
                ),
            },
            "checks": [
                {
                    "name": check.name,
                    "category": check.category.value,
                    "passed": check.passed,
                    "detail": check.detail,
                }
                for check in case.checks
            ],
        }


@dataclass(frozen=True, slots=True)
class _EvaluationContext:
    """One page fixture plus deterministic structural analysis."""

    fixture: GoldenPageFixture
    structure: StructuralAnalysisResult


@dataclass(frozen=True, slots=True)
class _CheckSpec:
    """Named executable expectation used by the report evaluator."""

    name: str
    category: EvaluationCategory
    evaluate: Callable[[_EvaluationContext], tuple[bool, str]]


class GoldenRegressionEvaluator:
    """Evaluate real-run golden pages as named capability checks."""

    def __init__(self) -> None:
        """Create an evaluator using the deterministic structural analyzer."""
        self._analyzer = BookStructuralAnalyzer()

    def evaluate_root(self, root: Path) -> GoldenEvaluationReport:
        """Load and evaluate every fixture beneath one golden root."""
        fixtures = GoldenPageFixtureLoader().discover(root)
        return self.evaluate(fixtures)

    def evaluate(
        self,
        fixtures: Sequence[GoldenPageFixture],
    ) -> GoldenEvaluationReport:
        """Evaluate fixtures in supplied order and return one report."""
        cases = tuple(self._evaluate_case(fixture) for fixture in fixtures)
        return GoldenEvaluationReport(cases=cases)

    def _evaluate_case(self, fixture: GoldenPageFixture) -> GoldenCaseEvaluation:
        """Evaluate all expectations registered for one fixture."""
        specs = _CHECKS_BY_CASE.get(fixture.case_id)
        if specs is None:
            specs = (
                _CheckSpec(
                    name="fixture_normalizes",
                    category=EvaluationCategory.STRUCTURE,
                    evaluate=_fixture_normalizes,
                ),
            )
        context = _EvaluationContext(
            fixture=fixture,
            structure=self._analyzer.analyze((fixture.page,)),
        )
        checks = tuple(
            self._run_check(spec, context)
            for spec in specs
        )
        return GoldenCaseEvaluation(
            case_id=fixture.case_id,
            source_page_number=fixture.source_page_number,
            model=fixture.model,
            prompt_version=fixture.prompt_version,
            schema_version=fixture.schema_version,
            tags=fixture.tags,
            usage=fixture.usage,
            checks=checks,
        )

    def _run_check(
        self,
        spec: _CheckSpec,
        context: _EvaluationContext,
    ) -> EvaluationCheckResult:
        """Run one check without hiding assertion or lookup failures."""
        try:
            passed, detail = spec.evaluate(context)
        except (LookupError, StopIteration, ValueError) as exc:
            passed = False
            detail = str(exc)
        return EvaluationCheckResult(
            name=spec.name,
            category=spec.category,
            passed=passed,
            detail=detail,
        )


def _fixture_normalizes(context: _EvaluationContext) -> tuple[bool, str]:
    """Fallback expectation for newly added fixtures without custom checks."""
    block_count = len(context.fixture.page.blocks)
    return True, f"strict fixture loaded with {block_count} blocks"


def _block_with_text(
    context: _EvaluationContext,
    text: str,
) -> PageBlockEvidence:
    """Return the unique page block whose plain text equals ``text``."""
    matches = [
        block for block in context.fixture.page.blocks if block.text == text
    ]
    if len(matches) != 1:
        raise LookupError(f"expected one block with text {text!r}, got {len(matches)}")
    return matches[0]


def _page_18_label_roman(context: _EvaluationContext) -> tuple[bool, str]:
    block = _block_with_text(context, "Nguyên văn bản tiếng Anh:")
    actual = block.spans[0].source_typography.posture
    expected = FontPosture.ROMAN
    return actual is expected, f"posture={actual.value}, expected={expected.value}"


def _page_18_superscript(context: _EvaluationContext) -> tuple[bool, str]:
    block = _block_with_text(context, "December 13th, 2014")
    span = next((item for item in block.spans if item.text == "th"), None)
    if span is None:
        return False, "missing superscript span 'th'"
    typography = span.source_typography
    passed = (
        typography.posture is FontPosture.ITALIC
        and typography.vertical_position is VerticalPosition.SUPERSCRIPT
    )
    return passed, (
        f"posture={typography.posture.value}, "
        f"vertical={typography.vertical_position.value}"
    )


def _page_18_page_number_language(context: _EvaluationContext) -> tuple[bool, str]:
    block = next(
        item
        for item in context.fixture.page.blocks
        if item.role_hint is BlockRoleHint.PAGE_NUMBER
    )
    language = block.spans[0].language
    return language is None, f"language={language!r}, expected=None"


def _page_68_verse_breaks(context: _EvaluationContext) -> tuple[bool, str]:
    block = next(
        item
        for item in context.fixture.page.blocks
        if item.role_hint is BlockRoleHint.VERSE
    )
    actual = [span.semantic_line_break_after for span in block.spans]
    expected = [True, True, True, False]
    return actual == expected, f"breaks={actual}, expected={expected}"


def _page_68_verse_structure(context: _EvaluationContext) -> tuple[bool, str]:
    verses = [
        node
        for node in context.structure.document.nodes
        if isinstance(node, VerseNode)
    ]
    line_counts = [len(node.lines) for node in verses]
    return line_counts == [4], f"verse_line_counts={line_counts}, expected=[4]"


def _page_116_figure_count(context: _EvaluationContext) -> tuple[bool, str]:
    figures = _figures(context)
    return len(figures) == 2, f"figures={len(figures)}, expected=2"


def _page_116_regions(context: _EvaluationContext) -> tuple[bool, str]:
    figures = _figures(context)
    if len(figures) != 2:
        return False, f"cannot check regions with {len(figures)} figures"
    actual = [
        (
            round(figure.image.source_region.x, 3),
            round(figure.image.source_region.y, 3),
        )
        for figure in figures
    ]
    expected = [(0.125, 0.080), (0.122, 0.505)]
    return actual == expected, f"region_origins={actual}, expected={expected}"


def _page_116_captions(context: _EvaluationContext) -> tuple[bool, str]:
    figures = _figures(context)
    actual = [
        "".join(span.text for span in figure.caption.spans)
        if figure.caption is not None
        else None
        for figure in figures
    ]
    passed = (
        len(actual) == 2
        and actual[0] is not None
        and actual[0].startswith("Kỷ niệm Minh Khuê")
        and actual[1] == "Tháng 10 năm 1999"
    )
    return passed, f"captions={actual!r}"


def _figures(context: _EvaluationContext) -> list[FigureNode]:
    """Return all resolved figure nodes in document order."""
    return [
        node
        for node in context.structure.document.nodes
        if isinstance(node, FigureNode)
    ]


def _page_152_heading_wrap(context: _EvaluationContext) -> tuple[bool, str]:
    heading = next(
        block
        for block in context.fixture.page.blocks
        if block.role_hint is BlockRoleHint.HEADING
    )
    breaks = [span.semantic_line_break_after for span in heading.spans]
    passed = len(heading.spans) == 1 and breaks == [False]
    return passed, f"spans={len(heading.spans)}, breaks={breaks}"


def _page_152_verse(context: _EvaluationContext) -> tuple[bool, str]:
    verses = [
        node
        for node in context.structure.document.nodes
        if isinstance(node, VerseNode)
    ]
    counts = [len(verse.lines) for verse in verses]
    return counts == [2], f"verse_line_counts={counts}, expected=[2]"


def _page_152_list_markers(context: _EvaluationContext) -> tuple[bool, str]:
    lists = [
        node
        for node in context.structure.document.nodes
        if isinstance(node, ListNode)
    ]
    if len(lists) != 1:
        return False, f"lists={len(lists)}, expected=1"
    items = lists[0].items
    passed = len(items) == 2 and all(
        item.marker is not None
        and item.marker.kind is MarkerKind.GRAPHIC
        and all("♥" not in span.text for span in item.spans)
        for item in items
    )
    return passed, f"items={len(items)}, graphic_markers={passed}"


def _page_378_ordinals(context: _EvaluationContext) -> tuple[bool, str]:
    lists = [
        node
        for node in context.structure.document.nodes
        if isinstance(node, ListNode)
    ]
    actual = [item.ordinal for item in lists[0].items] if len(lists) == 1 else []
    expected = list(range(10, 18))
    return actual == expected, f"ordinals={actual}, expected={expected}"


def _page_378_leading_prose(context: _EvaluationContext) -> tuple[bool, str]:
    nodes = context.structure.document.nodes
    passed = (
        len(nodes) == 2
        and isinstance(nodes[0], ParagraphNode)
        and isinstance(nodes[1], ListNode)
    )
    types = [type(node).__name__ for node in nodes]
    return passed, f"node_types={types}"


def _page_397_no_list(context: _EvaluationContext) -> tuple[bool, str]:
    list_count = sum(
        isinstance(node, ListNode) for node in context.structure.document.nodes
    )
    return list_count == 0, f"lists={list_count}, expected=0"


def _page_397_dialogue_count(context: _EvaluationContext) -> tuple[bool, str]:
    dialogue = [
        node
        for node in context.structure.document.nodes
        if isinstance(node, ParagraphNode)
        and node.spans
        and node.spans[0].text.startswith("–")
    ]
    return len(dialogue) == 4, f"dash_dialogue={len(dialogue)}, expected=4"


def _page_398_transition(context: _EvaluationContext) -> tuple[bool, str]:
    block = _block_with_text(context, "Và đây là cách ứng xử của tôi:")
    posture = block.spans[0].source_typography.posture
    return posture is FontPosture.ITALIC, f"posture={posture.value}, expected=italic"


def _page_398_no_list(context: _EvaluationContext) -> tuple[bool, str]:
    return _page_397_no_list(context)


def _page_402_roles(context: _EvaluationContext) -> tuple[bool, str]:
    label = _block_with_text(context, "TÌNH HUỐNG")
    title = _block_with_text(context, "Bật lại!")
    passed = (
        label.heading_role_hint is HeadingRoleHint.SCENARIO_LABEL
        and title.heading_role_hint is HeadingRoleHint.SCENARIO_TITLE
    )
    return passed, (
        f"label={label.heading_role_hint.value}, "
        f"title={title.heading_role_hint.value}"
    )


def _page_402_marker(context: _EvaluationContext) -> tuple[bool, str]:
    label = _block_with_text(context, "TÌNH HUỐNG")
    marker = label.marker
    passed = (
        marker is not None
        and marker.kind is MarkerKind.GRAPHIC
        and marker.raw_text is None
        and "\uf8ff" not in label.text
        and "☛" not in label.text
    )
    return passed, f"marker={marker!r}, text={label.text!r}"


def _page_412_role(context: _EvaluationContext) -> tuple[bool, str]:
    label = _block_with_text(context, "TÌNH HUỐNG")
    role = label.heading_role_hint
    return (
        role is HeadingRoleHint.SCENARIO_LABEL,
        f"role={role.value}, expected=scenario_label",
    )


def _page_412_marked_dialogue(context: _EvaluationContext) -> tuple[bool, str]:
    blocks = [
        block
        for block in context.fixture.page.blocks
        if block.role_hint is BlockRoleHint.PARAGRAPH
        and block.marker is not None
        and block.marker.kind is MarkerKind.GRAPHIC
    ]
    return len(blocks) == 8, f"graphic_paragraphs={len(blocks)}, expected=8"


def _page_412_no_list(context: _EvaluationContext) -> tuple[bool, str]:
    return _page_397_no_list(context)


_CHECKS_BY_CASE: dict[str, tuple[_CheckSpec, ...]] = {
    "page-0018": (
        _CheckSpec(
            "roman_language_label",
            EvaluationCategory.TYPOGRAPHY,
            _page_18_label_roman,
        ),
        _CheckSpec(
            "italic_superscript_th",
            EvaluationCategory.TYPOGRAPHY,
            _page_18_superscript,
        ),
        _CheckSpec(
            "page_number_language_neutral",
            EvaluationCategory.LANGUAGE,
            _page_18_page_number_language,
        ),
    ),
    "page-0068": (
        _CheckSpec(
            "four_semantic_verse_breaks",
            EvaluationCategory.STRUCTURE,
            _page_68_verse_breaks,
        ),
        _CheckSpec(
            "four_line_verse_node",
            EvaluationCategory.STRUCTURE,
            _page_68_verse_structure,
        ),
    ),
    "page-0116": (
        _CheckSpec(
            "two_figures",
            EvaluationCategory.FIGURE,
            _page_116_figure_count,
        ),
        _CheckSpec(
            "figure_regions",
            EvaluationCategory.FIGURE,
            _page_116_regions,
        ),
        _CheckSpec(
            "figure_captions",
            EvaluationCategory.FIGURE,
            _page_116_captions,
        ),
    ),
    "page-0152": (
        _CheckSpec(
            "heading_wrap_collapsed",
            EvaluationCategory.STRUCTURE,
            _page_152_heading_wrap,
        ),
        _CheckSpec(
            "two_line_verse",
            EvaluationCategory.STRUCTURE,
            _page_152_verse,
        ),
        _CheckSpec(
            "graphic_list_markers_separated",
            EvaluationCategory.MARKER,
            _page_152_list_markers,
        ),
    ),
    "page-0378": (
        _CheckSpec(
            "ordered_list_10_to_17",
            EvaluationCategory.STRUCTURE,
            _page_378_ordinals,
        ),
        _CheckSpec(
            "leading_prose_outside_list",
            EvaluationCategory.STRUCTURE,
            _page_378_leading_prose,
        ),
    ),
    "page-0397": (
        _CheckSpec(
            "dash_dialogue_not_list",
            EvaluationCategory.STRUCTURE,
            _page_397_no_list,
        ),
        _CheckSpec(
            "four_dash_dialogue_paragraphs",
            EvaluationCategory.STRUCTURE,
            _page_397_dialogue_count,
        ),
    ),
    "page-0398": (
        _CheckSpec(
            "italic_author_transition",
            EvaluationCategory.TYPOGRAPHY,
            _page_398_transition,
        ),
        _CheckSpec(
            "dialogue_not_list",
            EvaluationCategory.STRUCTURE,
            _page_398_no_list,
        ),
    ),
    "page-0402": (
        _CheckSpec(
            "scenario_label_and_title_roles",
            EvaluationCategory.ROLE,
            _page_402_roles,
        ),
        _CheckSpec(
            "graphic_marker_not_unicode_text",
            EvaluationCategory.MARKER,
            _page_402_marker,
        ),
    ),
    "page-0412": (
        _CheckSpec(
            "scenario_label_role",
            EvaluationCategory.ROLE,
            _page_412_role,
        ),
        _CheckSpec(
            "eight_graphic_marked_dialogue_turns",
            EvaluationCategory.MARKER,
            _page_412_marked_dialogue,
        ),
        _CheckSpec(
            "graphic_dialogue_not_list",
            EvaluationCategory.STRUCTURE,
            _page_412_no_list,
        ),
    ),
}
