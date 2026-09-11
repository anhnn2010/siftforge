"""Regression tests backed by real v5 ebook page-extraction artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from siftforge.ebook.evaluation import (
    GoldenFixtureError,
    GoldenPageFixture,
    GoldenPageFixtureLoader,
)
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
    VerseNode,
)

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "ebook" / "golden" / "v5"
_LOADER = GoldenPageFixtureLoader()


def _fixture(page_number: int) -> GoldenPageFixture:
    """Load one numbered real-run golden fixture."""
    return _LOADER.load(_FIXTURE_ROOT / f"page-{page_number:04d}")


def _block_with_text(
    fixture: GoldenPageFixture,
    text: str,
) -> PageBlockEvidence:
    """Return the unique block whose concatenated text exactly matches text."""
    matches = [block for block in fixture.page.blocks if block.text == text]
    assert len(matches) == 1
    return matches[0]


def test_golden_fixture_suite_discovers_real_v5_cases() -> None:
    """The checked-in suite should expose all accepted real v5 regression pages."""
    fixtures = _LOADER.discover(_FIXTURE_ROOT)

    assert [fixture.source_page_number for fixture in fixtures] == [
        18,
        68,
        116,
        152,
        378,
        397,
        398,
        402,
        412,
    ]
    assert {fixture.model for fixture in fixtures} == {"gemini-3.6-flash"}
    assert {fixture.schema_version for fixture in fixtures} == {"5"}
    assert {fixture.prompt_version for fixture in fixtures} == {"5", "5.1"}
    assert all(
        fixture.page.source.uri.startswith("fixture://") for fixture in fixtures
    )


def test_golden_fixture_loader_rejects_corrupted_deterministic_ids(
    tmp_path: Path,
) -> None:
    """Golden fixtures should fail fast if stored normalized IDs drift."""
    fixture_dir = _FIXTURE_ROOT / "page-0018"
    case_payload = json.loads((fixture_dir / "case.json").read_text(encoding="utf-8"))
    page_payload = json.loads((fixture_dir / "page.json").read_text(encoding="utf-8"))
    page_payload["blocks"][0]["block_id"] = "corrupted:block:id"

    target = tmp_path / "page-0018"
    target.mkdir()
    (target / "case.json").write_text(
        json.dumps(case_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (target / "page.json").write_text(
        json.dumps(page_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(GoldenFixtureError, match="block_id is not deterministic"):
        _LOADER.load(target)


def test_page_18_preserves_typography_boundary_and_superscript() -> None:
    """Page 18 guards the roman label between surrounding italic content."""
    fixture = _fixture(18)
    label = _block_with_text(fixture, "Nguyên văn bản tiếng Anh:")

    assert len(label.spans) == 1
    assert label.spans[0].source_typography.posture is FontPosture.ROMAN

    date_block = next(
        block
        for block in fixture.page.blocks
        if block.text == "December 13th, 2014"
    )
    superscript = next(span for span in date_block.spans if span.text == "th")
    assert superscript.source_typography.posture is FontPosture.ITALIC
    assert (
        superscript.source_typography.vertical_position
        is VerticalPosition.SUPERSCRIPT
    )

    page_number = next(
        block
        for block in fixture.page.blocks
        if block.role_hint is BlockRoleHint.PAGE_NUMBER
    )
    assert page_number.spans[0].language is None


def test_page_68_preserves_four_semantic_verse_lines() -> None:
    """Page 68 should keep verse lines while ending the final line explicitly."""
    fixture = _fixture(68)
    verse_evidence = next(
        block
        for block in fixture.page.blocks
        if block.role_hint is BlockRoleHint.VERSE
    )
    assert [span.semantic_line_break_after for span in verse_evidence.spans] == [
        True,
        True,
        True,
        False,
    ]

    result = BookStructuralAnalyzer().analyze((fixture.page,))
    verse_nodes = [
        node for node in result.document.nodes if isinstance(node, VerseNode)
    ]
    assert len(verse_nodes) == 1
    assert len(verse_nodes[0].lines) == 4


def test_page_116_builds_two_source_backed_figures() -> None:
    """Page 116 should resolve two image/caption pairs without losing regions."""
    fixture = _fixture(116)
    result = BookStructuralAnalyzer().analyze((fixture.page,))
    figures = [node for node in result.document.nodes if isinstance(node, FigureNode)]

    assert len(figures) == 2
    assert figures[0].image.source_region.x == pytest.approx(0.125)
    assert figures[0].image.source_region.y == pytest.approx(0.080)
    assert figures[1].image.source_region.x == pytest.approx(0.122)
    assert figures[1].image.source_region.y == pytest.approx(0.505)
    assert figures[0].caption is not None
    assert figures[1].caption is not None
    assert figures[0].caption.spans[0].text.startswith("Kỷ niệm Minh Khuê")
    assert figures[1].caption.spans[0].text == "Tháng 10 năm 1999"
    assert result.unresolved_blocks == ()


def test_page_152_separates_heading_wrap_verse_lines_and_list_markers() -> None:
    """Page 152 guards three v5 behaviors on the same real source page."""
    fixture = _fixture(152)
    heading = next(
        block
        for block in fixture.page.blocks
        if block.role_hint is BlockRoleHint.HEADING
    )
    assert heading.heading_role_hint is HeadingRoleHint.SECTION_TITLE
    assert len(heading.spans) == 1
    assert heading.spans[0].semantic_line_break_after is False

    result = BookStructuralAnalyzer().analyze((fixture.page,))
    verses = [node for node in result.document.nodes if isinstance(node, VerseNode)]
    lists = [node for node in result.document.nodes if isinstance(node, ListNode)]
    assert len(verses) == 1
    assert len(verses[0].lines) == 2
    assert len(lists) == 1
    assert len(lists[0].items) == 2
    assert all(
        item.marker is not None and item.marker.kind is MarkerKind.GRAPHIC
        for item in lists[0].items
    )
    assert all("♥" not in item.spans[0].text for item in lists[0].items)


def test_page_378_recovers_ordered_list_without_absorbing_leading_prose() -> None:
    """Page 378 should keep leading continuation prose outside items 10-17."""
    fixture = _fixture(378)
    result = BookStructuralAnalyzer().analyze((fixture.page,))

    assert len(result.document.nodes) == 2
    assert isinstance(result.document.nodes[0], ParagraphNode)
    assert isinstance(result.document.nodes[1], ListNode)
    ordered = result.document.nodes[1]
    assert [item.ordinal for item in ordered.items] == list(range(10, 18))


def test_page_397_dash_dialogue_does_not_become_a_list() -> None:
    """Page 397 is the negative control for dash-prefixed list recovery."""
    fixture = _fixture(397)
    result = BookStructuralAnalyzer().analyze((fixture.page,))

    assert not any(isinstance(node, ListNode) for node in result.document.nodes)
    dialogue = [
        node
        for node in result.document.nodes
        if isinstance(node, ParagraphNode)
        and node.spans
        and node.spans[0].text.startswith("–")
    ]
    assert len(dialogue) == 4


def test_page_398_preserves_italic_author_transition() -> None:
    """Page 398 guards the local roman-to-italic-to-roman boundary."""
    fixture = _fixture(398)
    transition = _block_with_text(fixture, "Và đây là cách ứng xử của tôi:")

    assert len(transition.spans) == 1
    assert transition.spans[0].source_typography.posture is FontPosture.ITALIC
    result = BookStructuralAnalyzer().analyze((fixture.page,))
    assert not any(isinstance(node, ListNode) for node in result.document.nodes)


def test_page_402_preserves_scenario_label_title_and_graphic_marker() -> None:
    """Page 402 should keep graphic evidence separate from readable heading text."""
    fixture = _fixture(402)
    label = _block_with_text(fixture, "TÌNH HUỐNG")
    title = _block_with_text(fixture, "Bật lại!")

    assert label.heading_role_hint is HeadingRoleHint.SCENARIO_LABEL
    assert label.marker is not None
    assert label.marker.kind is MarkerKind.GRAPHIC
    assert label.marker.raw_text is None
    assert title.heading_role_hint is HeadingRoleHint.SCENARIO_TITLE
    assert "\uf8ff" not in label.text
    assert "☛" not in label.text


def test_page_412_keeps_graphic_marked_dialogue_as_paragraphs() -> None:
    """Page 412 guards visual-list formatting that is semantically dialogue."""
    fixture = _fixture(412)
    label = _block_with_text(fixture, "TÌNH HUỐNG")
    assert label.heading_role_hint is HeadingRoleHint.SCENARIO_LABEL

    marked_dialogue = [
        block
        for block in fixture.page.blocks
        if block.role_hint is BlockRoleHint.PARAGRAPH
        and block.marker is not None
        and block.marker.kind is MarkerKind.GRAPHIC
    ]
    assert len(marked_dialogue) == 8

    result = BookStructuralAnalyzer().analyze((fixture.page,))
    assert not any(isinstance(node, ListNode) for node in result.document.nodes)
