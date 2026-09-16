"""Project structured page evidence into comparable plain text."""

from __future__ import annotations

from siftforge.ebook.evidence import PageExtraction

from .models import ProjectedText, TextAnchor


def project_page_text(page: PageExtraction) -> ProjectedText:
    """Flatten readable page evidence while preserving source provenance.

    This projection exists only for review. It never replaces the structured
    normalized artifact used by the ebook pipeline.
    """
    characters: list[str] = []
    anchors: list[TextAnchor | None] = []

    for block_index, block in enumerate(page.blocks):
        if block_index and characters:
            characters.append(" ")
            anchors.append(None)
        for span in block.spans:
            for offset, character in enumerate(span.text):
                characters.append(character)
                anchors.append(
                    TextAnchor(
                        page_id=page.page_id,
                        block_id=block.block_id,
                        span_id=span.span_id,
                        span_offset=offset,
                    )
                )
            if span.semantic_line_break_after:
                characters.append(" ")
                anchors.append(None)

    return _collapse_whitespace(characters, anchors)


def _collapse_whitespace(
    characters: list[str],
    anchors: list[TextAnchor | None],
) -> ProjectedText:
    """Collapse layout whitespace without inventing token boundaries."""
    projected: list[str] = []
    projected_anchors: list[TextAnchor | None] = []
    pending_space = False
    pending_anchor: TextAnchor | None = None

    for character, anchor in zip(characters, anchors, strict=True):
        if character.isspace():
            if projected:
                pending_space = True
                if pending_anchor is None:
                    pending_anchor = anchor
            continue
        if pending_space:
            projected.append(" ")
            projected_anchors.append(pending_anchor)
            pending_space = False
            pending_anchor = None
        projected.append(character)
        projected_anchors.append(anchor)

    return ProjectedText(
        text="".join(projected),
        anchors=tuple(projected_anchors),
    )


def anchor_for_range(
    projection: ProjectedText,
    start: int,
    end: int,
) -> TextAnchor | None:
    """Return the nearest useful extraction anchor for one diff range."""
    safe_start = max(0, min(start, len(projection.anchors)))
    safe_end = max(safe_start, min(end, len(projection.anchors)))
    for anchor in projection.anchors[safe_start:safe_end]:
        if anchor is not None:
            return anchor
    for index in range(safe_start - 1, -1, -1):
        anchor = projection.anchors[index]
        if anchor is not None:
            return anchor
    for index in range(safe_end, len(projection.anchors)):
        anchor = projection.anchors[index]
        if anchor is not None:
            return anchor
    return None
