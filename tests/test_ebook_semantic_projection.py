"""Tests for EPUB-ready semantic projection."""

from pathlib import Path

import pytest

from siftforge.ebook.evidence import NormalizedRegion, SourceTypography
from siftforge.ebook.models import (
    CapsStyle,
    FontPosture,
    FontWeight,
    VerticalPosition,
)
from siftforge.ebook.semantic import (
    EbookSemanticProjector,
    InlineRole,
    SemanticFigure,
    SemanticHeading,
    SemanticParagraph,
    SemanticProjectionError,
)
from siftforge.ebook.structure import (
    BookDocument,
    DocumentRelationship,
    DocumentTextSpan,
    FigureNode,
    HeadingNode,
    HeadingRole,
    ImageNode,
    ParagraphNode,
    RelationshipKind,
    SemanticMark,
)


def _typography(posture: FontPosture = FontPosture.ROMAN) -> SourceTypography:
    """Return ordinary source typography for projector fixtures."""
    return SourceTypography(
        posture=posture,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.BASELINE,
        caps_style=CapsStyle.NORMAL,
    )


def _span(
    span_id: str,
    text: str,
    *,
    posture: FontPosture = FontPosture.ROMAN,
    marks: tuple[SemanticMark, ...] = (),
) -> DocumentTextSpan:
    """Build one logical text span."""
    return DocumentTextSpan(
        span_id=span_id,
        text=text,
        language="vi",
        source_typography=_typography(posture),
        semantic_marks=marks,
    )


def test_projection_does_not_infer_emphasis_from_source_italic() -> None:
    """Visual italic source text must not automatically become emphasis."""
    document = BookDocument(
        nodes=(
            ParagraphNode(
                node_id="p1",
                spans=(
                    _span("s1", "Nội dung", posture=FontPosture.ITALIC),
                ),
            ),
        )
    )

    result = EbookSemanticProjector().project(document, title="Book")

    paragraph = result.document.nodes[0]
    assert isinstance(paragraph, SemanticParagraph)
    assert paragraph.content[0].marks == ()


def test_projection_preserves_explicit_semantic_marks() -> None:
    """Only explicit semantic marks should reach the EPUB-ready layer."""
    document = BookDocument(
        nodes=(
            ParagraphNode(
                node_id="p1",
                spans=(
                    _span("s1", "nhấn mạnh", marks=(SemanticMark.EMPHASIS,)),
                ),
            ),
        )
    )

    result = EbookSemanticProjector().project(document, title="Book")

    paragraph = result.document.nodes[0]
    assert isinstance(paragraph, SemanticParagraph)
    assert paragraph.content[0].marks == (SemanticMark.EMPHASIS,)


def test_projection_turns_exact_footnote_span_into_note_reference() -> None:
    """Footnote relations should decorate only their exact source span."""
    document = BookDocument(
        nodes=(
            ParagraphNode(
                node_id="p1",
                spans=(_span("s1", "1"),),
            ),
        ),
        relationships=(
            DocumentRelationship(
                relationship_id="r1",
                kind=RelationshipKind.FOOTNOTE_REF,
                source_id="s1",
                target_id="footnote-1",
            ),
        ),
    )

    result = EbookSemanticProjector().project(document, title="Book")

    paragraph = result.document.nodes[0]
    assert isinstance(paragraph, SemanticParagraph)
    assert paragraph.content[0].role is InlineRole.FOOTNOTE_REF
    assert paragraph.content[0].target_id == "footnote-1"


def test_scenario_label_is_heading_like_but_not_hierarchy_level() -> None:
    """Scenario labels should not be forced into the heading hierarchy."""
    document = BookDocument(
        nodes=(
            HeadingNode(
                node_id="h1",
                spans=(_span("s1", "TÌNH HUỐNG"),),
                role=HeadingRole.SCENARIO_LABEL,
                level=2,
            ),
        )
    )

    result = EbookSemanticProjector().project(document, title="Book")

    heading = result.document.nodes[0]
    assert isinstance(heading, SemanticHeading)
    assert heading.level is None


def test_figure_requires_materialized_asset_before_projection() -> None:
    """EPUB-ready figures cannot reference only a source crop region."""
    document = BookDocument(
        nodes=(
            FigureNode(
                node_id="figure-1",
                image=ImageNode(
                    node_id="image-1",
                    source_region=NormalizedRegion(
                        x=0.1,
                        y=0.1,
                        width=0.5,
                        height=0.5,
                    ),
                    asset_id=None,
                ),
            ),
        )
    )

    with pytest.raises(SemanticProjectionError):
        EbookSemanticProjector().project(document, title="Book")


def test_materialized_figure_projects_asset_id(tmp_path: Path) -> None:
    """A materialized figure should pass its relative asset ID downstream."""
    del tmp_path
    document = BookDocument(
        nodes=(
            FigureNode(
                node_id="figure-1",
                image=ImageNode(
                    node_id="image-1",
                    source_region=NormalizedRegion(
                        x=0.1,
                        y=0.1,
                        width=0.5,
                        height=0.5,
                    ),
                    asset_id="assets/figures/figure.png",
                ),
            ),
        )
    )

    result = EbookSemanticProjector().project(document, title="Book")

    figure = result.document.nodes[0]
    assert isinstance(figure, SemanticFigure)
    assert figure.asset_id == "assets/figures/figure.png"
