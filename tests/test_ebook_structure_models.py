"""Tests for pagination-independent structural ebook models."""

from siftforge.ebook.evidence import SourceTypography
from siftforge.ebook.models import (
    CapsStyle,
    FontPosture,
    FontWeight,
    VerticalPosition,
)
from siftforge.ebook.structure import (
    BookDocument,
    DocumentRelationship,
    DocumentTextSpan,
    HeadingNode,
    HeadingRole,
    ParagraphNode,
    RelationshipKind,
    SemanticMark,
    SourceFragment,
)


def _source_typography() -> SourceTypography:
    """Return ordinary source typography for structural fixtures."""
    return SourceTypography(
        posture=FontPosture.ITALIC,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.BASELINE,
        caps_style=CapsStyle.NORMAL,
    )


def test_source_typography_is_independent_from_semantic_marks() -> None:
    """Visual italic text must be representable without semantic emphasis."""
    span = DocumentTextSpan(
        span_id="node-1:span:0001",
        text="Ordinary prose printed in an italic base face.",
        language="en",
        source_typography=_source_typography(),
        semantic_marks=(),
    )

    assert span.source_typography.posture is FontPosture.ITALIC
    assert span.semantic_marks == ()


def test_semantic_emphasis_can_coexist_with_source_typography() -> None:
    """Semantic emphasis should be explicit instead of inferred from posture."""
    span = DocumentTextSpan(
        span_id="node-1:span:0001",
        text="emphasized",
        language="en",
        source_typography=_source_typography(),
        semantic_marks=(SemanticMark.EMPHASIS,),
    )

    assert span.semantic_marks == (SemanticMark.EMPHASIS,)


def test_logical_node_can_preserve_cross_page_provenance() -> None:
    """One logical paragraph may trace back to fragments on multiple pages."""
    first = SourceFragment(page_id="page-0397", block_id="block-a")
    second = SourceFragment(page_id="page-0398", block_id="block-b")
    paragraph = ParagraphNode(
        node_id="paragraph-1",
        spans=(),
        provenance=(first, second),
    )

    assert [fragment.page_id for fragment in paragraph.provenance] == [
        "page-0397",
        "page-0398",
    ]


def test_heading_role_is_independent_from_heading_level() -> None:
    """A subtitle may have a semantic role without forcing an HTML-like level."""
    heading = HeadingNode(
        node_id="heading-1",
        spans=(),
        role=HeadingRole.SUBTITLE,
        level=None,
    )

    assert heading.role is HeadingRole.SUBTITLE
    assert heading.level is None


def test_book_document_can_retain_unresolved_relationship_evidence() -> None:
    """Structural analysis may retain typed relations with confidence and reasons."""
    relationship = DocumentRelationship(
        relationship_id="relationship-1",
        kind=RelationshipKind.CONTINUES_TO,
        source_id="page-0397:block:0010",
        target_id="page-0398:block:0001",
        confidence=0.95,
        reasons=("next page starts mid-sentence",),
    )
    document = BookDocument(nodes=(), relationships=(relationship,))

    assert document.relationships[0].kind is RelationshipKind.CONTINUES_TO
    assert document.relationships[0].confidence == 0.95
