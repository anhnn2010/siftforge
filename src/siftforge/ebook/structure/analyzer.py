"""Deterministic first-pass structural analysis for ebook page evidence.

Milestone 1F-6 keeps the pass deterministic while resolving containers that
are explicit in page evidence: lists, quotation runs, verse runs, and figures.
Ambiguous higher-level structures such as embedded excerpts remain candidates
rather than being expanded from language-specific heuristics.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from siftforge.ebook.evidence import (
    BlockRoleHint,
    HeadingRoleHint,
    MarkerKind,
    PageBlockEvidence,
    PageExtraction,
    TextSpanEvidence,
)

from .models import (
    AttributionNode,
    BookDocument,
    CaptionNode,
    ContainerCandidateKind,
    ContainerResolutionCandidate,
    DocumentRelationship,
    DocumentTextSpan,
    FigureNode,
    FlowNode,
    FootnoteNode,
    HeadingNode,
    HeadingRole,
    ImageNode,
    InsetRole,
    ListItemNode,
    ListKind,
    ListNode,
    ParagraphNode,
    QuotationNode,
    RelationshipKind,
    SourceFragment,
    VerseLineNode,
    VerseNode,
)

_FURNITURE_ROLES = frozenset(
    {
        BlockRoleHint.PAGE_HEADER,
        BlockRoleHint.PAGE_FOOTER,
        BlockRoleHint.PAGE_NUMBER,
    }
)
_LIST_ROLES = frozenset({BlockRoleHint.LIST, BlockRoleHint.LIST_ITEM})
_CONTINUATION_ROLES = frozenset(
    {
        BlockRoleHint.PARAGRAPH,
        BlockRoleHint.LIST_ITEM,
        BlockRoleHint.QUOTE,
    }
)
_ORDERED_MARKERS = frozenset({MarkerKind.NUMERIC, MarkerKind.ALPHABETIC})
_TERMINAL_PUNCTUATION = frozenset({".", "!", "?", "…"})
_TRAILING_CLOSERS = frozenset({'"', "'", "”", "’", ")", "]", "}"})
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class RunningFurnitureOccurrence:
    """One page-furniture block excluded from logical body flow."""

    page_id: str
    block_id: str
    role_hint: BlockRoleHint
    raw_text: str
    normalized_text: str
    repeated: bool = False


@dataclass(frozen=True, slots=True)
class StructuralAnalysisResult:
    """Output of the conservative first-pass book structural analyzer."""

    document: BookDocument
    running_furniture: tuple[RunningFurnitureOccurrence, ...]
    unresolved_blocks: tuple[PageBlockEvidence, ...] = ()
    container_candidates: tuple[ContainerResolutionCandidate, ...] = ()

    @property
    def continuation_candidates(self) -> tuple[DocumentRelationship, ...]:
        """Return unresolved cross-page continuation relationships."""
        return tuple(
            relationship
            for relationship in self.document.relationships
            if relationship.kind is RelationshipKind.CONTINUES_TO
        )


@dataclass(frozen=True, slots=True)
class _EvidencePosition:
    """Internal ordered view of one non-furniture page-evidence block."""

    page_index: int
    page: PageExtraction
    block: PageBlockEvidence


class BookStructuralAnalyzer:
    """Build conservative logical structure from ordered page evidence.

    Explicit page-local container evidence is grouped without guessing hidden
    semantics. Running furniture is removed, likely continuations stay scored
    candidates, and incomplete inset evidence is surfaced for later resolution.
    """

    def analyze(self, pages: Sequence[PageExtraction]) -> StructuralAnalysisResult:
        """Analyze physical pages in caller-supplied reading order.

        Args:
            pages: Ordered page-level extraction evidence for one book segment.

        Returns:
            Logical nodes, running-furniture observations, unresolved evidence,
            and continuation candidates represented as document relationships.

        Raises:
            ValueError: If duplicate page identities are supplied.
        """
        self._validate_page_ids(pages)
        positions, furniture = self._partition_page_evidence(pages)
        nodes, node_ids_by_block, unresolved = self._build_nodes(positions)
        relationships = self._detect_continuations(
            pages,
            positions,
            node_ids_by_block,
        )
        container_candidates = self._detect_container_candidates(positions)
        normalized_furniture = self._mark_repeated_furniture(furniture)
        return StructuralAnalysisResult(
            document=BookDocument(
                nodes=tuple(nodes),
                relationships=relationships,
            ),
            running_furniture=normalized_furniture,
            unresolved_blocks=tuple(unresolved),
            container_candidates=container_candidates,
        )

    def _validate_page_ids(self, pages: Sequence[PageExtraction]) -> None:
        """Reject duplicate physical-page identities."""
        page_ids = [page.page_id for page in pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("page_id values must be unique within one analysis")

    def _partition_page_evidence(
        self,
        pages: Sequence[PageExtraction],
    ) -> tuple[list[_EvidencePosition], list[RunningFurnitureOccurrence]]:
        """Separate body evidence from page-local running furniture."""
        positions: list[_EvidencePosition] = []
        furniture: list[RunningFurnitureOccurrence] = []
        for page_index, page in enumerate(pages):
            for block in page.blocks:
                if block.role_hint in _FURNITURE_ROLES:
                    furniture.append(self._furniture_occurrence(page, block))
                    continue
                positions.append(
                    _EvidencePosition(
                        page_index=page_index,
                        page=page,
                        block=block,
                    )
                )
        return positions, furniture

    def _furniture_occurrence(
        self,
        page: PageExtraction,
        block: PageBlockEvidence,
    ) -> RunningFurnitureOccurrence:
        """Normalize one header/footer/page-number observation."""
        normalized_text = _collapse_whitespace(block.text)
        if block.role_hint is not BlockRoleHint.PAGE_NUMBER:
            normalized_text = _strip_printed_page_number(
                normalized_text,
                page.printed_page_number,
            )
        return RunningFurnitureOccurrence(
            page_id=page.page_id,
            block_id=block.block_id,
            role_hint=block.role_hint,
            raw_text=block.text,
            normalized_text=normalized_text,
        )

    def _mark_repeated_furniture(
        self,
        occurrences: Sequence[RunningFurnitureOccurrence],
    ) -> tuple[RunningFurnitureOccurrence, ...]:
        """Mark normalized header/footer text repeated on multiple pages."""
        pages_by_key: dict[tuple[BlockRoleHint, str], set[str]] = {}
        for occurrence in occurrences:
            if occurrence.role_hint is BlockRoleHint.PAGE_NUMBER:
                continue
            if not occurrence.normalized_text:
                continue
            key = (
                occurrence.role_hint,
                occurrence.normalized_text.casefold(),
            )
            pages_by_key.setdefault(key, set()).add(occurrence.page_id)

        return tuple(
            replace(
                occurrence,
                repeated=self._is_repeated_furniture(occurrence, pages_by_key),
            )
            for occurrence in occurrences
        )

    def _is_repeated_furniture(
        self,
        occurrence: RunningFurnitureOccurrence,
        pages_by_key: dict[tuple[BlockRoleHint, str], set[str]],
    ) -> bool:
        """Return whether a normalized furniture string recurs across pages."""
        if occurrence.role_hint is BlockRoleHint.PAGE_NUMBER:
            return False
        if not occurrence.normalized_text:
            return False
        key = (
            occurrence.role_hint,
            occurrence.normalized_text.casefold(),
        )
        return len(pages_by_key.get(key, set())) >= 2

    def _build_nodes(
        self,
        positions: Sequence[_EvidencePosition],
    ) -> tuple[list[FlowNode], dict[str, str], list[PageBlockEvidence]]:
        """Build supported logical nodes and resolve explicit containers."""
        nodes: list[FlowNode] = []
        node_ids_by_block: dict[str, str] = {}
        unresolved: list[PageBlockEvidence] = []
        index = 0

        while index < len(positions):
            position = positions[index]
            role = position.block.role_hint

            if role in _LIST_ROLES:
                run_end = self._list_run_end(positions, index)
                run = positions[index:run_end]
                list_node = self._list_node(run)
                nodes.append(list_node)
                for item, item_position in zip(
                    list_node.items, run, strict=True
                ):
                    node_ids_by_block[item_position.block.block_id] = item.node_id
                index = run_end
                continue

            if role is BlockRoleHint.QUOTE:
                run_end = self._same_role_run_end(
                    positions, index, BlockRoleHint.QUOTE
                )
                run = positions[index:run_end]
                quotation = self._quotation_node(run)
                nodes.append(quotation)
                for item_position in run:
                    node_ids_by_block[item_position.block.block_id] = (
                        quotation.node_id
                    )
                index = run_end
                continue

            if role is BlockRoleHint.VERSE:
                run_end = self._same_role_run_end(
                    positions, index, BlockRoleHint.VERSE
                )
                run = positions[index:run_end]
                verse = self._verse_group_node(run)
                nodes.append(verse)
                for item_position in run:
                    node_ids_by_block[item_position.block.block_id] = verse.node_id
                index = run_end
                continue

            if role is BlockRoleHint.IMAGE:
                caption_position = self._following_caption(positions, index)
                consumed = 2 if caption_position is not None else 1
                if position.block.region is None:
                    unresolved.append(position.block)
                    if caption_position is not None:
                        unresolved.append(caption_position.block)
                    index += consumed
                    continue
                figure = self._figure_node(position, caption_position)
                nodes.append(figure)
                node_ids_by_block[position.block.block_id] = figure.node_id
                if caption_position is not None:
                    node_ids_by_block[caption_position.block.block_id] = (
                        figure.node_id
                    )
                index += consumed
                continue

            if role is BlockRoleHint.CAPTION:
                unresolved.append(position.block)
                index += 1
                continue

            node = self._single_block_node(position)
            if node is None:
                unresolved.append(position.block)
            else:
                nodes.append(node)
                node_ids_by_block[position.block.block_id] = node.node_id
            index += 1

        return nodes, node_ids_by_block, unresolved

    def _same_role_run_end(
        self,
        positions: Sequence[_EvidencePosition],
        start: int,
        role: BlockRoleHint,
    ) -> int:
        """Return the end of a contiguous explicit container-role run."""
        index = start + 1
        start_page_index = positions[start].page_index
        while index < len(positions):
            current = positions[index]
            if current.page_index != start_page_index:
                break
            if current.block.role_hint is not role:
                break
            index += 1
        return index

    def _quotation_node(
        self,
        run: Sequence[_EvidencePosition],
    ) -> QuotationNode:
        """Group contiguous explicit quote evidence into one quotation."""
        children = tuple(
            ParagraphNode(
                node_id=_node_id(position.block.block_id, "quote-paragraph"),
                spans=_document_spans(position.page, position.block),
                provenance=(_source_fragment(position.page, position.block),),
            )
            for position in run
        )
        provenance = tuple(
            fragment
            for child in children
            for fragment in child.provenance
        )
        return QuotationNode(
            node_id=_node_id(run[0].block.block_id, "quotation"),
            children=children,
            provenance=provenance,
        )

    def _verse_group_node(
        self,
        run: Sequence[_EvidencePosition],
    ) -> VerseNode:
        """Group contiguous verse evidence while preserving semantic lines."""
        block_verses = tuple(
            _verse_node(position.page, position.block) for position in run
        )
        return VerseNode(
            node_id=_node_id(run[0].block.block_id, "verse"),
            lines=tuple(
                line
                for verse in block_verses
                for line in verse.lines
            ),
            provenance=tuple(
                fragment
                for verse in block_verses
                for fragment in verse.provenance
            ),
        )

    def _following_caption(
        self,
        positions: Sequence[_EvidencePosition],
        image_index: int,
    ) -> _EvidencePosition | None:
        """Return an immediately following same-page caption, if present."""
        next_index = image_index + 1
        if next_index >= len(positions):
            return None
        image = positions[image_index]
        candidate = positions[next_index]
        if candidate.page_index != image.page_index:
            return None
        if candidate.block.role_hint is not BlockRoleHint.CAPTION:
            return None
        return candidate

    def _figure_node(
        self,
        image_position: _EvidencePosition,
        caption_position: _EvidencePosition | None,
    ) -> FigureNode:
        """Resolve an image region and optional adjacent caption as a figure."""
        image_block = image_position.block
        if image_block.region is None:
            raise ValueError("figure image evidence requires a source region")
        image = ImageNode(
            node_id=_node_id(image_block.block_id, "image"),
            source_region=image_block.region,
            asset_id=None,
            provenance=(
                _source_fragment(image_position.page, image_block),
            ),
        )
        caption = None
        if caption_position is not None:
            caption_block = caption_position.block
            caption = CaptionNode(
                node_id=_node_id(caption_block.block_id, "caption"),
                spans=_document_spans(caption_position.page, caption_block),
                provenance=(
                    _source_fragment(caption_position.page, caption_block),
                ),
            )
        provenance = image.provenance + (
            caption.provenance if caption is not None else ()
        )
        return FigureNode(
            node_id=_node_id(image_block.block_id, "figure"),
            image=image,
            caption=caption,
            provenance=provenance,
        )

    def _list_run_end(
        self,
        positions: Sequence[_EvidencePosition],
        start: int,
    ) -> int:
        """Return the exclusive end of one compatible contiguous list run."""
        first = positions[start].block
        expected_kind = _list_kind(first)
        previous = first
        index = start + 1
        while index < len(positions):
            current_position = positions[index]
            if current_position.page_index > positions[index - 1].page_index + 1:
                break
            current = current_position.block
            if current.role_hint not in _LIST_ROLES:
                break
            if _list_kind(current) is not expected_kind:
                break
            if not _ordered_markers_are_compatible(previous, current):
                break
            previous = current
            index += 1
        return index

    def _list_node(self, run: Sequence[_EvidencePosition]) -> ListNode:
        """Build one list from a contiguous run of list-item evidence."""
        items = tuple(self._list_item_node(position) for position in run)
        provenance = tuple(
            fragment
            for item in items
            for fragment in item.provenance
        )
        return ListNode(
            node_id=_node_id(run[0].block.block_id, "list"),
            kind=_list_kind(run[0].block),
            items=items,
            provenance=provenance,
        )

    def _list_item_node(self, position: _EvidencePosition) -> ListItemNode:
        """Convert one explicit list-item evidence block into a logical item."""
        block = position.block
        return ListItemNode(
            node_id=_node_id(block.block_id, "list-item"),
            spans=_document_spans(position.page, block),
            marker=block.marker,
            ordinal=block.marker.ordinal if block.marker is not None else None,
            provenance=(_source_fragment(position.page, block),),
        )

    def _single_block_node(self, position: _EvidencePosition) -> FlowNode | None:
        """Convert one supported non-list evidence block into a logical node."""
        block = position.block
        provenance = (_source_fragment(position.page, block),)
        spans = _document_spans(position.page, block)

        if block.role_hint is BlockRoleHint.PARAGRAPH:
            return ParagraphNode(
                node_id=_node_id(block.block_id, "paragraph"),
                spans=spans,
                provenance=provenance,
            )
        if block.role_hint is BlockRoleHint.HEADING:
            return HeadingNode(
                node_id=_node_id(block.block_id, "heading"),
                spans=spans,
                role=_heading_role(block.heading_role_hint),
                level=block.heading_level_hint,
                provenance=provenance,
            )
        if block.role_hint is BlockRoleHint.FOOTNOTE:
            return FootnoteNode(
                node_id=_node_id(block.block_id, "footnote"),
                spans=spans,
                provenance=provenance,
            )
        if block.role_hint is BlockRoleHint.ATTRIBUTION:
            return AttributionNode(
                node_id=_node_id(block.block_id, "attribution"),
                spans=spans,
                provenance=provenance,
            )
        return None

    def _detect_container_candidates(
        self,
        positions: Sequence[_EvidencePosition],
    ) -> tuple[ContainerResolutionCandidate, ...]:
        """Record strong inset-opening evidence without guessing its extent."""
        candidates: list[ContainerResolutionCandidate] = []
        for index, position in enumerate(positions):
            block = position.block
            if block.role_hint is not BlockRoleHint.HEADING:
                continue
            if block.heading_role_hint is not HeadingRoleHint.GENRE_LABEL:
                continue

            source_block_ids = [block.block_id]
            reasons = ["genre-label heading suggests embedded material"]
            confidence = 0.75
            if index > 0:
                previous = positions[index - 1]
                if (
                    previous.page_index == position.page_index
                    and previous.block.role_hint is BlockRoleHint.HEADING
                ):
                    source_block_ids.insert(0, previous.block.block_id)
                    reasons.append(
                        "genre label is immediately preceded by a title-like heading"
                    )
                    confidence = 0.90

            candidates.append(
                ContainerResolutionCandidate(
                    candidate_id=(
                        f"{source_block_ids[0]}:candidate:inset"
                    ),
                    kind=ContainerCandidateKind.INSET,
                    role=InsetRole.UNKNOWN,
                    source_block_ids=tuple(source_block_ids),
                    confidence=confidence,
                    reasons=tuple(reasons),
                )
            )
        return tuple(candidates)

    def _detect_continuations(
        self,
        pages: Sequence[PageExtraction],
        positions: Sequence[_EvidencePosition],
        node_ids_by_block: dict[str, str],
    ) -> tuple[DocumentRelationship, ...]:
        """Emit conservative continuation candidates across adjacent pages."""
        body_by_page: dict[int, list[PageBlockEvidence]] = {
            page_index: [] for page_index in range(len(pages))
        }
        for position in positions:
            body_by_page[position.page_index].append(position.block)

        candidates: list[DocumentRelationship] = []
        for page_index in range(len(pages) - 1):
            left_blocks = body_by_page[page_index]
            right_blocks = body_by_page[page_index + 1]
            if not left_blocks or not right_blocks:
                continue
            left = left_blocks[-1]
            right = right_blocks[0]
            source_id = node_ids_by_block.get(left.block_id)
            target_id = node_ids_by_block.get(right.block_id)
            if source_id is None or target_id is None:
                continue
            if source_id == target_id:
                continue
            candidate = _continuation_relationship(
                left,
                right,
                source_id,
                target_id,
            )
            if candidate is not None:
                candidates.append(candidate)
        return tuple(candidates)


def _collapse_whitespace(text: str) -> str:
    """Collapse source whitespace for deterministic furniture comparison."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def _strip_printed_page_number(text: str, printed_page_number: str | None) -> str:
    """Strip a duplicated printed page number at either furniture edge."""
    if not text or not printed_page_number:
        return text
    number = re.escape(printed_page_number.strip())
    stripped = re.sub(rf"^(?:{number})(?:\s+|$)", "", text).strip()
    stripped = re.sub(rf"(?:\s+|^)(?:{number})$", "", stripped).strip()
    return stripped


def _node_id(block_id: str, kind: str) -> str:
    """Build a stable logical-node identifier from source evidence identity."""
    return f"{block_id}:node:{kind}"


def _source_fragment(
    page: PageExtraction,
    block: PageBlockEvidence,
) -> SourceFragment:
    """Build provenance for one logical node derived from one page block."""
    return SourceFragment(
        page_id=page.page_id,
        block_id=block.block_id,
        span_ids=tuple(span.span_id for span in block.spans),
    )


def _document_spans(
    page: PageExtraction,
    block: PageBlockEvidence,
) -> tuple[DocumentTextSpan, ...]:
    """Copy source spans into logical text without inferring semantic marks."""
    return tuple(
        DocumentTextSpan(
            span_id=span.span_id,
            text=span.text,
            language=span.language,
            source_typography=span.source_typography,
            semantic_marks=(),
            provenance=(
                SourceFragment(
                    page_id=page.page_id,
                    block_id=block.block_id,
                    span_ids=(span.span_id,),
                ),
            ),
        )
        for span in block.spans
    )


def _heading_role(role_hint: HeadingRoleHint) -> HeadingRole:
    """Map page-local heading-role evidence to the matching logical enum."""
    try:
        return HeadingRole(role_hint.value)
    except ValueError:
        return HeadingRole.UNKNOWN


def _list_kind(block: PageBlockEvidence) -> ListKind:
    """Infer only ordered-vs-unordered behavior from explicit marker evidence."""
    if block.marker is not None and block.marker.kind in _ORDERED_MARKERS:
        return ListKind.ORDERED
    return ListKind.UNORDERED


def _ordered_markers_are_compatible(
    previous: PageBlockEvidence,
    current: PageBlockEvidence,
) -> bool:
    """Avoid grouping explicit ordered items whose ordinals conflict."""
    if _list_kind(previous) is not ListKind.ORDERED:
        return True
    previous_ordinal = previous.marker.ordinal if previous.marker is not None else None
    current_ordinal = current.marker.ordinal if current.marker is not None else None
    if previous_ordinal is None or current_ordinal is None:
        return True
    return current_ordinal == previous_ordinal + 1


def _verse_node(page: PageExtraction, block: PageBlockEvidence) -> VerseNode:
    """Build a verse container from explicit semantic line-break evidence."""
    line_spans: list[DocumentTextSpan] = []
    lines: list[VerseLineNode] = []
    line_number = 1
    for source_span in block.spans:
        line_spans.append(_document_span(page, block, source_span))
        if source_span.semantic_line_break_after:
            lines.append(
                VerseLineNode(
                    node_id=_verse_line_id(block.block_id, line_number),
                    spans=tuple(line_spans),
                    provenance=(_source_fragment(page, block),),
                )
            )
            line_number += 1
            line_spans = []
    if line_spans or not lines:
        lines.append(
            VerseLineNode(
                node_id=_verse_line_id(block.block_id, line_number),
                spans=tuple(line_spans),
                provenance=(_source_fragment(page, block),),
            )
        )
    return VerseNode(
        node_id=_node_id(block.block_id, "verse"),
        lines=tuple(lines),
        provenance=(_source_fragment(page, block),),
    )


def _document_span(
    page: PageExtraction,
    block: PageBlockEvidence,
    span: TextSpanEvidence,
) -> DocumentTextSpan:
    """Copy one evidence span into a logical span without semantic inference."""
    return DocumentTextSpan(
        span_id=span.span_id,
        text=span.text,
        language=span.language,
        source_typography=span.source_typography,
        semantic_marks=(),
        provenance=(
            SourceFragment(
                page_id=page.page_id,
                block_id=block.block_id,
                span_ids=(span.span_id,),
            ),
        ),
    )


def _verse_line_id(block_id: str, line_number: int) -> str:
    """Build a stable line identifier inside one verse evidence block."""
    return f"{block_id}:node:verse-line:{line_number:04d}"


def _continuation_relationship(
    left: PageBlockEvidence,
    right: PageBlockEvidence,
    source_id: str,
    target_id: str,
) -> DocumentRelationship | None:
    """Score a conservative cross-page continuation hypothesis."""
    if not _continuation_roles_are_compatible(left.role_hint, right.role_hint):
        return None
    left_text = left.text.strip()
    right_text = right.text.strip()
    if not left_text or not right_text:
        return None

    reasons: list[str] = []
    confidence = 0.40
    if not _has_terminal_punctuation(left_text):
        confidence += 0.30
        reasons.append("previous page ends without terminal punctuation")
    if _starts_with_lowercase_letter(right_text):
        confidence += 0.20
        reasons.append("next page starts with a lowercase letter")
    if _same_language(left, right):
        confidence += 0.05
        reasons.append("adjacent blocks use the same language")
    if _boundary_typography_is_compatible(left, right):
        confidence += 0.05
        reasons.append("boundary typography is compatible")

    if confidence < 0.65:
        return None
    confidence = min(confidence, 0.99)
    return DocumentRelationship(
        relationship_id=(
            f"{source_id}:relationship:continues-to:{target_id}"
        ),
        kind=RelationshipKind.CONTINUES_TO,
        source_id=source_id,
        target_id=target_id,
        confidence=confidence,
        reasons=tuple(reasons),
    )


def _continuation_roles_are_compatible(
    left: BlockRoleHint,
    right: BlockRoleHint,
) -> bool:
    """Allow only leaf roles observed to plausibly continue across pages."""
    if left not in _CONTINUATION_ROLES or right not in _CONTINUATION_ROLES:
        return False
    if left is right:
        return True
    paragraph_like = frozenset({BlockRoleHint.PARAGRAPH, BlockRoleHint.LIST_ITEM})
    return left in paragraph_like and right in paragraph_like


def _has_terminal_punctuation(text: str) -> bool:
    """Return whether visible text ends in sentence-terminal punctuation."""
    stripped = text.rstrip()
    while stripped and stripped[-1] in _TRAILING_CLOSERS:
        stripped = stripped[:-1].rstrip()
    return bool(stripped) and stripped[-1] in _TERMINAL_PUNCTUATION


def _starts_with_lowercase_letter(text: str) -> bool:
    """Return whether the first alphabetic character is lowercase."""
    for character in text:
        if character.isalpha():
            return character.islower()
    return False


def _same_language(left: PageBlockEvidence, right: PageBlockEvidence) -> bool:
    """Return whether both blocks expose the same non-null dominant language."""
    return (
        left.dominant_language is not None
        and left.dominant_language == right.dominant_language
    )


def _boundary_typography_is_compatible(
    left: PageBlockEvidence,
    right: PageBlockEvidence,
) -> bool:
    """Compare only the source typography touching the physical page boundary."""
    if not left.spans or not right.spans:
        return False
    left_style = left.spans[-1].source_typography
    right_style = right.spans[0].source_typography
    return (
        left_style.posture is right_style.posture
        and left_style.weight is right_style.weight
        and left_style.vertical_position is right_style.vertical_position
        and left_style.caps_style is right_style.caps_style
    )
