"""Project structural ebook data into EPUB-ready semantic content."""

from __future__ import annotations

from dataclasses import dataclass

from siftforge.ebook.structure import (
    AttributionNode,
    BookDocument,
    CaptionNode,
    DocumentRelationship,
    DocumentTextSpan,
    FigureNode,
    FlowNode,
    FootnoteNode,
    HeadingNode,
    HeadingRole,
    InsetNode,
    ListItemNode,
    ListNode,
    ParagraphNode,
    QuotationNode,
    RelationshipKind,
    VerseLineNode,
    VerseNode,
)

from .models import (
    InlineRole,
    SemanticAttribution,
    SemanticBookDocument,
    SemanticFigure,
    SemanticFlowNode,
    SemanticFootnote,
    SemanticHeading,
    SemanticInline,
    SemanticInset,
    SemanticList,
    SemanticListItem,
    SemanticParagraph,
    SemanticQuotation,
    SemanticRelationship,
    SemanticVerse,
    SemanticVerseLine,
)


class SemanticProjectionError(ValueError):
    """Raised when logical structure is not safe to project into ebook markup."""


@dataclass(frozen=True, slots=True)
class SemanticProjectionResult:
    """Projected semantic document plus conservative unresolved warnings."""

    document: SemanticBookDocument
    warnings: tuple[str, ...] = ()


class EbookSemanticProjector:
    """Convert ``BookDocument`` into semantics safe for reflowable XHTML.

    Source typography is intentionally ignored. Only explicit ``SemanticMark``
    values may become ``em``/``strong`` markup downstream. This prevents an
    italic base typeface from being misrepresented as semantic emphasis.
    """

    def project(
        self,
        document: BookDocument,
        *,
        title: str,
        language: str | None = None,
        author: str | None = None,
    ) -> SemanticProjectionResult:
        """Project one logical document without inferring new book semantics."""
        footnote_refs = _footnote_reference_map(document.relationships)
        nodes = tuple(
            self._project_node(node, footnote_refs) for node in document.nodes
        )
        relationships = tuple(
            SemanticRelationship(
                kind=relationship.kind.value,
                source_id=relationship.source_id,
                target_id=relationship.target_id,
            )
            for relationship in document.relationships
            if relationship.kind
            in {
                RelationshipKind.ATTRIBUTION_OF,
                RelationshipKind.TRANSLATION_OF,
            }
        )
        warnings = tuple(
            f"unresolved continuation: {item.source_id} -> {item.target_id}"
            for item in document.relationships
            if item.kind is RelationshipKind.CONTINUES_TO
        )
        return SemanticProjectionResult(
            document=SemanticBookDocument(
                title=title,
                language=language,
                author=author,
                nodes=nodes,
                relationships=relationships,
            ),
            warnings=warnings,
        )

    def _project_node(
        self,
        node: FlowNode,
        footnote_refs: dict[str, str],
    ) -> SemanticFlowNode:
        """Project one structural node recursively."""
        if isinstance(node, ParagraphNode):
            return SemanticParagraph(
                node_id=node.node_id,
                content=_project_spans(node.spans, footnote_refs),
            )
        if isinstance(node, HeadingNode):
            return SemanticHeading(
                node_id=node.node_id,
                content=_project_spans(node.spans, footnote_refs),
                role=node.role,
                level=_resolved_heading_level(node),
            )
        if isinstance(node, ListNode):
            return SemanticList(
                node_id=node.node_id,
                kind=node.kind,
                items=tuple(
                    _project_list_item(item, footnote_refs)
                    for item in node.items
                ),
            )
        if isinstance(node, VerseNode):
            return SemanticVerse(
                node_id=node.node_id,
                lines=tuple(
                    _project_verse_line(line, footnote_refs)
                    for line in node.lines
                ),
            )
        if isinstance(node, QuotationNode):
            return SemanticQuotation(
                node_id=node.node_id,
                children=tuple(
                    self._project_node(child, footnote_refs)
                    for child in node.children
                ),
            )
        if isinstance(node, FigureNode):
            return _project_figure(node, footnote_refs)
        if isinstance(node, InsetNode):
            return SemanticInset(
                node_id=node.node_id,
                role=node.role,
                children=tuple(
                    self._project_node(child, footnote_refs)
                    for child in node.children
                ),
            )
        if isinstance(node, FootnoteNode):
            return SemanticFootnote(
                node_id=node.node_id,
                content=_project_spans(node.spans, footnote_refs),
                label=node.label,
            )
        if isinstance(node, AttributionNode):
            return SemanticAttribution(
                node_id=node.node_id,
                content=_project_spans(node.spans, footnote_refs),
            )
        raise TypeError(f"unsupported structural node: {type(node).__name__}")


def _footnote_reference_map(
    relationships: tuple[DocumentRelationship, ...],
) -> dict[str, str]:
    """Return exact source-span to footnote-node links."""
    return {
        relationship.source_id: relationship.target_id
        for relationship in relationships
        if relationship.kind is RelationshipKind.FOOTNOTE_REF
    }


def _project_spans(
    spans: tuple[DocumentTextSpan, ...],
    footnote_refs: dict[str, str],
) -> tuple[SemanticInline, ...]:
    """Project text spans without inferring semantics from source typography."""
    projected: list[SemanticInline] = []
    for span in spans:
        target_id = footnote_refs.get(span.span_id)
        projected.append(
            SemanticInline(
                text=span.text,
                language=span.language,
                marks=span.semantic_marks,
                role=(
                    InlineRole.FOOTNOTE_REF
                    if target_id is not None
                    else InlineRole.TEXT
                ),
                target_id=target_id,
                source_span_id=span.span_id,
            )
        )
    return tuple(projected)


def _project_list_item(
    item: ListItemNode,
    footnote_refs: dict[str, str],
) -> SemanticListItem:
    """Project one list item while keeping markers out of readable text."""
    return SemanticListItem(
        node_id=item.node_id,
        content=_project_spans(item.spans, footnote_refs),
        ordinal=item.ordinal,
    )


def _project_verse_line(
    line: VerseLineNode,
    footnote_refs: dict[str, str],
) -> SemanticVerseLine:
    """Project one semantic verse line."""
    return SemanticVerseLine(
        node_id=line.node_id,
        content=_project_spans(line.spans, footnote_refs),
    )


def _project_figure(
    figure: FigureNode,
    footnote_refs: dict[str, str],
) -> SemanticFigure:
    """Project one figure only after its image has a materialized asset."""
    asset_id = figure.image.asset_id
    if asset_id is None:
        raise SemanticProjectionError(
            f"figure {figure.node_id!r} has no materialized image asset"
        )
    caption = (
        _project_caption(figure.caption, footnote_refs)
        if figure.caption is not None
        else ()
    )
    return SemanticFigure(
        node_id=figure.node_id,
        asset_id=asset_id,
        caption=caption,
    )


def _project_caption(
    caption: CaptionNode,
    footnote_refs: dict[str, str],
) -> tuple[SemanticInline, ...]:
    """Project figure caption text."""
    return _project_spans(caption.spans, footnote_refs)


def _resolved_heading_level(node: HeadingNode) -> int | None:
    """Resolve safe heading levels without treating labels as hierarchy."""
    if node.role in {
        HeadingRole.CHAPTER_LABEL,
        HeadingRole.SUBTITLE,
        HeadingRole.GENRE_LABEL,
        HeadingRole.SCENARIO_LABEL,
    }:
        return None
    if node.level is not None and 1 <= node.level <= 6:
        return node.level
    defaults = {
        HeadingRole.CHAPTER_TITLE: 1,
        HeadingRole.SECTION_TITLE: 2,
        HeadingRole.SUBSECTION_TITLE: 3,
        HeadingRole.SCENARIO_TITLE: 3,
        HeadingRole.UNKNOWN: 2,
    }
    return defaults[node.role]
