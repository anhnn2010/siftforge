"""Deterministic first-pass structural analysis for ebook page evidence.

The current pass stays deterministic while resolving explicit containers,
evidence-backed semantic relationships, and only high-confidence cross-page
prose continuations. Lower-confidence or non-prose continuation evidence remains
scored instead of being guessed from language-specific content.
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
from siftforge.ebook.models import VerticalPosition

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
    InsetNode,
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
    resolved_continuations: tuple[DocumentRelationship, ...] = ()

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
    semantics. Running furniture is removed, only high-confidence paragraph
    continuations are resolved, and ambiguous continuation/inset evidence stays
    visible for later resolution.
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
        continuation_relationships = self._detect_continuations(
            pages,
            positions,
            node_ids_by_block,
        )
        resolved_nodes, unresolved_continuations, resolved_continuations = (
            self._resolve_high_confidence_continuations(
                nodes,
                continuation_relationships,
            )
        )
        semantic_relationships = self._resolve_semantic_relationships(
            positions,
            nodes,
            node_ids_by_block,
        )
        relationships = unresolved_continuations + semantic_relationships
        container_candidates = self._detect_container_candidates(positions)
        normalized_furniture = self._mark_repeated_furniture(furniture)
        return StructuralAnalysisResult(
            document=BookDocument(
                nodes=resolved_nodes,
                relationships=relationships,
            ),
            running_furniture=normalized_furniture,
            unresolved_blocks=tuple(unresolved),
            container_candidates=container_candidates,
            resolved_continuations=resolved_continuations,
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
                run_end = self._quotation_run_end(positions, index)
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

    def _quotation_run_end(
        self,
        positions: Sequence[_EvidencePosition],
        start: int,
    ) -> int:
        """Return the end of one same-language quotation run on one page.

        Known language changes split adjacent quote evidence so a later
        relationship pass can retain bilingual original/translation pairs as
        separate logical quotation containers. Unknown language does not force
        a split.
        """
        index = start + 1
        start_page_index = positions[start].page_index
        previous_language = positions[start].block.dominant_language
        while index < len(positions):
            current = positions[index]
            if current.page_index != start_page_index:
                break
            if current.block.role_hint is not BlockRoleHint.QUOTE:
                break
            current_language = current.block.dominant_language
            if (
                previous_language is not None
                and current_language is not None
                and previous_language != current_language
            ):
                break
            if current_language is not None:
                previous_language = current_language
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
            previous_position = positions[index - 1]
            if not _positions_are_same_or_consecutive(
                previous_position, current_position
            ):
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
                label=_footnote_body_label(block),
                provenance=provenance,
            )
        if block.role_hint is BlockRoleHint.ATTRIBUTION:
            return AttributionNode(
                node_id=_node_id(block.block_id, "attribution"),
                spans=spans,
                provenance=provenance,
            )
        return None

    def _resolve_semantic_relationships(
        self,
        positions: Sequence[_EvidencePosition],
        nodes: Sequence[FlowNode],
        node_ids_by_block: dict[str, str],
    ) -> tuple[DocumentRelationship, ...]:
        """Resolve relationships supported by explicit page-local evidence."""
        relationships: list[DocumentRelationship] = []
        relationships.extend(
            self._resolve_footnote_references(positions, node_ids_by_block)
        )
        relationships.extend(self._resolve_attributions(nodes))
        relationships.extend(self._resolve_translation_pairs(nodes))
        return tuple(relationships)

    def _resolve_footnote_references(
        self,
        positions: Sequence[_EvidencePosition],
        node_ids_by_block: dict[str, str],
    ) -> tuple[DocumentRelationship, ...]:
        """Link matching superscript references to same-page footnote bodies."""
        targets: dict[tuple[str, str], list[str]] = {}
        for position in positions:
            block = position.block
            if block.role_hint is not BlockRoleHint.FOOTNOTE:
                continue
            label = _footnote_body_label(block)
            target_id = node_ids_by_block.get(block.block_id)
            if label is None or target_id is None:
                continue
            key = (position.page.page_id, label.casefold())
            targets.setdefault(key, []).append(target_id)

        relationships: list[DocumentRelationship] = []
        for position in positions:
            block = position.block
            if block.role_hint is BlockRoleHint.FOOTNOTE:
                continue
            for span in block.spans:
                label = _footnote_reference_label(span)
                if label is None:
                    continue
                key = (position.page.page_id, label.casefold())
                matching_targets = targets.get(key, [])
                if len(matching_targets) != 1:
                    continue
                target_id = matching_targets[0]
                relationships.append(
                    DocumentRelationship(
                        relationship_id=(
                            f"{span.span_id}:relationship:footnote-ref:"
                            f"{target_id}"
                        ),
                        kind=RelationshipKind.FOOTNOTE_REF,
                        source_id=span.span_id,
                        target_id=target_id,
                        confidence=1.0,
                        reasons=(
                            "superscript reference label matches a unique "
                            "same-page footnote label",
                        ),
                    )
                )
        return tuple(relationships)

    def _resolve_attributions(
        self,
        nodes: Sequence[FlowNode],
    ) -> tuple[DocumentRelationship, ...]:
        """Link explicit attribution nodes to one unambiguous adjacent work."""
        relationships: list[DocumentRelationship] = []
        for index, node in enumerate(nodes):
            if not isinstance(node, AttributionNode):
                continue
            candidates: list[FlowNode] = []
            if index > 0:
                previous = nodes[index - 1]
                if _is_attributable_neighbor(node, previous):
                    candidates.append(previous)
            if index + 1 < len(nodes):
                following = nodes[index + 1]
                if _is_attributable_neighbor(node, following):
                    candidates.append(following)
            if len(candidates) != 1:
                continue
            target = candidates[0]
            relationships.append(
                DocumentRelationship(
                    relationship_id=(
                        f"{node.node_id}:relationship:attribution-of:"
                        f"{target.node_id}"
                    ),
                    kind=RelationshipKind.ATTRIBUTION_OF,
                    source_id=node.node_id,
                    target_id=target.node_id,
                    confidence=0.95,
                    reasons=(
                        "explicit attribution is adjacent to one "
                        "attributable same-page container",
                    ),
                )
            )
        return tuple(relationships)

    def _resolve_translation_pairs(
        self,
        nodes: Sequence[FlowNode],
    ) -> tuple[DocumentRelationship, ...]:
        """Emit conservative translation candidates for bilingual quote pairs."""
        relationships: list[DocumentRelationship] = []
        for index in range(1, len(nodes)):
            original = nodes[index - 1]
            translated = nodes[index]
            if not isinstance(original, QuotationNode):
                continue
            if not isinstance(translated, QuotationNode):
                continue
            if not _nodes_share_one_page(original, translated):
                continue
            original_language = _logical_node_language(original)
            translated_language = _logical_node_language(translated)
            if original_language is None or translated_language is None:
                continue
            if original_language == translated_language:
                continue
            if not _translation_lengths_are_plausible(original, translated):
                continue
            confidence = 0.80
            reasons = [
                "adjacent quotation containers use different known languages",
                "both quotations occur on the same physical page",
            ]
            if _pair_has_adjacent_attribution(nodes, index - 1, index):
                confidence = 0.90
                reasons.append("quotation pair shares adjacent attribution context")
            relationships.append(
                DocumentRelationship(
                    relationship_id=(
                        f"{translated.node_id}:relationship:translation-of:"
                        f"{original.node_id}"
                    ),
                    kind=RelationshipKind.TRANSLATION_OF,
                    source_id=translated.node_id,
                    target_id=original.node_id,
                    confidence=confidence,
                    reasons=tuple(reasons),
                )
            )
        return tuple(relationships)

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

    def _resolve_high_confidence_continuations(
        self,
        nodes: Sequence[FlowNode],
        relationships: Sequence[DocumentRelationship],
    ) -> tuple[
        tuple[FlowNode, ...],
        tuple[DocumentRelationship, ...],
        tuple[DocumentRelationship, ...],
    ]:
        """Merge only unambiguous adjacent paragraph continuation chains.

        The continuation detector deliberately emits candidates for a broader
        set of leaf roles. Automatic resolution is narrower: both logical
        nodes must be top-level paragraphs, they must be adjacent in logical
        flow, and the candidate must contain every strong boundary signal used
        by the current scorer (confidence ``0.99``).

        Consumed relationships are returned separately so diagnostics retain
        the evidence that justified the merge without leaving dangling
        ``CONTINUES_TO`` links in ``BookDocument``.
        """
        resolvable = {
            (relationship.source_id, relationship.target_id): relationship
            for relationship in relationships
            if relationship.kind is RelationshipKind.CONTINUES_TO
            and relationship.confidence is not None
            and relationship.confidence >= 0.99
        }
        resolved: list[DocumentRelationship] = []
        merged_nodes: list[FlowNode] = []
        index = 0

        while index < len(nodes):
            current = nodes[index]
            if not isinstance(current, ParagraphNode):
                merged_nodes.append(current)
                index += 1
                continue

            merged = current
            chain_index = index
            while chain_index + 1 < len(nodes):
                left = nodes[chain_index]
                right = nodes[chain_index + 1]
                if not isinstance(left, ParagraphNode) or not isinstance(
                    right, ParagraphNode
                ):
                    break
                relationship = resolvable.get((left.node_id, right.node_id))
                if relationship is None:
                    break
                merged = _merge_paragraph_nodes(merged, right)
                resolved.append(relationship)
                chain_index += 1

            merged_nodes.append(merged)
            index = chain_index + 1

        resolved_ids = {item.relationship_id for item in resolved}
        unresolved = tuple(
            relationship
            for relationship in relationships
            if relationship.relationship_id not in resolved_ids
        )
        return tuple(merged_nodes), unresolved, tuple(resolved)

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
            if not _pages_are_consecutive(
                pages[page_index], pages[page_index + 1]
            ):
                continue
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


def _positions_are_same_or_consecutive(
    left: _EvidencePosition,
    right: _EvidencePosition,
) -> bool:
    """Return whether evidence positions can belong to one cross-page run."""
    if left.page_index == right.page_index:
        return True
    return _pages_are_consecutive(left.page, right.page)


def _pages_are_consecutive(
    left: PageExtraction,
    right: PageExtraction,
) -> bool:
    """Require known consecutive physical pages before cross-page inference."""
    left_number = _physical_page_number(left)
    right_number = _physical_page_number(right)
    if left_number is None or right_number is None:
        return False
    return right_number == left_number + 1


def _physical_page_number(page: PageExtraction) -> int | None:
    """Return the physical PDF page number from source provenance when known."""
    value = page.source.metadata.get("page_number")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    printed = page.printed_page_number
    if printed is not None and printed.isascii() and printed.isdigit():
        parsed = int(printed)
        return parsed if parsed > 0 else None
    return None


_FOOTNOTE_LABEL_RE = re.compile(r"^(?:\d{1,3}|[A-Za-z]|[*†‡]+)$")


def _normalize_footnote_label(text: str) -> str | None:
    """Return a compact footnote label when text is label-shaped."""
    label = text.strip().strip("()[]{}")
    label = label.rstrip(".").strip()
    if not label or _FOOTNOTE_LABEL_RE.fullmatch(label) is None:
        return None
    return label


def _footnote_body_label(block: PageBlockEvidence) -> str | None:
    """Extract an explicit superscript label at the start of a footnote body."""
    for span in block.spans:
        if not span.text.strip():
            continue
        if span.source_typography.vertical_position is not VerticalPosition.SUPERSCRIPT:
            return None
        return _normalize_footnote_label(span.text)
    return None


def _footnote_reference_label(span: TextSpanEvidence) -> str | None:
    """Return a candidate inline footnote label from superscript evidence."""
    if span.source_typography.vertical_position is not VerticalPosition.SUPERSCRIPT:
        return None
    return _normalize_footnote_label(span.text)


def _is_attributable_neighbor(
    attribution: AttributionNode,
    target: FlowNode,
) -> bool:
    """Return whether an adjacent node is a supported same-page attribution target."""
    if not isinstance(target, QuotationNode | VerseNode | InsetNode):
        return False
    return _nodes_share_one_page(attribution, target)


def _node_page_ids(node: FlowNode) -> frozenset[str]:
    """Return physical page identities represented by one logical node."""
    return frozenset(fragment.page_id for fragment in node.provenance)


def _nodes_share_one_page(left: FlowNode, right: FlowNode) -> bool:
    """Return whether both nodes are sourced from the same single page."""
    left_pages = _node_page_ids(left)
    right_pages = _node_page_ids(right)
    return len(left_pages) == 1 and left_pages == right_pages


def _logical_node_language(node: QuotationNode) -> str | None:
    """Return one unambiguous non-null language for a quotation container."""
    languages = {
        span.language
        for child in node.children
        for span in child.spans
        if span.language is not None
    }
    if len(languages) != 1:
        return None
    return next(iter(languages))


def _logical_node_text(node: QuotationNode) -> str:
    """Return normalized readable text for a quotation container."""
    return _collapse_whitespace(
        " ".join(span.text for child in node.children for span in child.spans)
    )


def _translation_lengths_are_plausible(
    original: QuotationNode,
    translated: QuotationNode,
) -> bool:
    """Reject extreme-length adjacent quotes unlikely to be translations."""
    original_length = len(_logical_node_text(original))
    translated_length = len(_logical_node_text(translated))
    if original_length == 0 or translated_length == 0:
        return False
    ratio = translated_length / original_length
    return 0.4 <= ratio <= 2.5


def _pair_has_adjacent_attribution(
    nodes: Sequence[FlowNode],
    original_index: int,
    translated_index: int,
) -> bool:
    """Return whether a bilingual quotation pair touches an attribution node."""
    if original_index > 0 and isinstance(
        nodes[original_index - 1], AttributionNode
    ):
        return True
    return (
        translated_index + 1 < len(nodes)
        and isinstance(nodes[translated_index + 1], AttributionNode)
    )


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


def _merge_paragraph_nodes(
    left: ParagraphNode,
    right: ParagraphNode,
) -> ParagraphNode:
    """Merge adjacent logical prose while preserving source provenance.

    A synthetic unprovenanced space is inserted only when the page boundary
    itself removed ordinary inter-word whitespace. Source spans remain
    otherwise unchanged and keep their original page/block provenance.
    """
    spans = list(left.spans)
    if _paragraphs_need_joining_space(left, right):
        spans.append(_continuation_join_span(left, right))
    spans.extend(right.spans)
    return ParagraphNode(
        node_id=left.node_id,
        spans=tuple(spans),
        provenance=left.provenance + right.provenance,
    )


def _paragraphs_need_joining_space(
    left: ParagraphNode,
    right: ParagraphNode,
) -> bool:
    """Return whether one synthetic space is needed at a merged page break."""
    left_text = "".join(span.text for span in left.spans)
    right_text = "".join(span.text for span in right.spans)
    if not left_text or not right_text:
        return False
    if left_text[-1].isspace() or right_text[0].isspace():
        return False
    if left_text[-1] in {"-", "‐", "‑", "\u00ad"}:
        return False
    if right_text[0] in {",", ".", ";", ":", "!", "?", ")", "]", "}"}:
        return False
    return True


def _continuation_join_span(
    left: ParagraphNode,
    right: ParagraphNode,
) -> DocumentTextSpan:
    """Create synthetic whitespace introduced by logical paragraph stitching."""
    if not left.spans or not right.spans:
        raise ValueError("continuation join requires non-empty paragraph spans")
    left_span = left.spans[-1]
    right_span = right.spans[0]
    return DocumentTextSpan(
        span_id=f"{left.node_id}:join:{right.node_id}",
        text=" ",
        language=(
            left_span.language
            if left_span.language == right_span.language
            else None
        ),
        source_typography=left_span.source_typography,
        semantic_marks=(),
        provenance=(),
    )


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
