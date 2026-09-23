"""Render EPUB-ready semantic content into reader-compatible XHTML assets."""

from __future__ import annotations

import html
import shutil
from dataclasses import dataclass
from pathlib import Path

from siftforge.ebook.semantic import (
    InlinePresentation,
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
    SemanticParagraph,
    SemanticQuotation,
    SemanticVerse,
)
from siftforge.ebook.structure import HeadingRole, ListKind, SemanticMark


@dataclass(frozen=True, slots=True)
class XhtmlRenderResult:
    """Files produced by the EPUB-ready XHTML renderer."""

    content_paths: tuple[Path, ...]
    stylesheet_path: Path
    copied_assets: tuple[Path, ...]
    endnotes_path: Path | None = None

    @property
    def content_path(self) -> Path:
        """Return the first content document for legacy single-file callers."""
        return self.content_paths[0]


@dataclass(frozen=True, slots=True)
class _RenderContext:
    """Cross-document link context used while rendering one XHTML file."""

    current_document: str
    document_language: str | None
    locator_by_id: dict[str, str]
    backlinks_by_target: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _ContentChunk:
    """One logical body chunk and its deterministic XHTML filename."""

    filename: str
    nodes: tuple[SemanticFlowNode, ...]


class EpubReadyXhtmlRenderer:
    """Render a semantic book into XHTML + CSS + copied assets.

    Logical headings form reader-sized spine documents. Footnotes are projected
    into a dedicated ``endnotes.xhtml`` document so references and backlinks use
    conventional cross-document EPUB links instead of reader-specific history.
    """

    def render(
        self,
        document: SemanticBookDocument,
        *,
        asset_root: str | Path,
        output_root: str | Path,
    ) -> XhtmlRenderResult:
        """Render semantic content and copy referenced figure assets."""
        source_root = Path(asset_root).expanduser().resolve()
        destination_root = Path(output_root).expanduser().resolve()
        text_dir = destination_root / "text"
        styles_dir = destination_root / "styles"
        text_dir.mkdir(parents=True, exist_ok=True)
        styles_dir.mkdir(parents=True, exist_ok=True)

        copied_assets = self._copy_assets(
            document,
            source_root=source_root,
            destination_root=destination_root,
        )
        stylesheet_path = styles_dir / "book.css"
        stylesheet_path.write_text(_DEFAULT_CSS, encoding="utf-8")

        body_nodes, footnotes = _partition_top_level_footnotes(document.nodes)
        chunks = _plan_content_chunks(body_nodes)
        locator_by_id = _build_locator(chunks, footnotes=footnotes)
        backlinks_by_target = _collect_footnote_backlinks(document.nodes)

        content_paths: list[Path] = []
        for chunk in chunks:
            content_path = text_dir / chunk.filename
            context = _RenderContext(
                current_document=chunk.filename,
                document_language=document.language,
                locator_by_id=locator_by_id,
                backlinks_by_target=backlinks_by_target,
            )
            content_path.write_text(
                self._render_document(
                    document,
                    nodes=chunk.nodes,
                    context=context,
                    body_type="bodymatter",
                ),
                encoding="utf-8",
            )
            content_paths.append(content_path)

        endnotes_path: Path | None = None
        if footnotes:
            endnotes_path = text_dir / "endnotes.xhtml"
            context = _RenderContext(
                current_document=endnotes_path.name,
                document_language=document.language,
                locator_by_id=locator_by_id,
                backlinks_by_target=backlinks_by_target,
            )
            endnotes_path.write_text(
                self._render_endnotes_document(
                    document,
                    footnotes=footnotes,
                    context=context,
                ),
                encoding="utf-8",
            )
            content_paths.append(endnotes_path)

        return XhtmlRenderResult(
            content_paths=tuple(content_paths),
            stylesheet_path=stylesheet_path,
            copied_assets=copied_assets,
            endnotes_path=endnotes_path,
        )

    def _render_document(
        self,
        document: SemanticBookDocument,
        *,
        nodes: tuple[SemanticFlowNode, ...],
        context: _RenderContext,
        body_type: str,
    ) -> str:
        """Render one complete XHTML spine document."""
        language = document.language or "und"
        body = self._render_nodes(nodes, 2, context=context)
        title = html.escape(document.title)
        language_attr = html.escape(language, quote=True)
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" '
            f'lang="{language_attr}" xml:lang="{language_attr}">\n'
            "  <head>\n"
            '    <meta charset="utf-8" />\n'
            f"    <title>{title}</title>\n"
            '    <link rel="stylesheet" type="text/css" '
            'href="../styles/book.css" />\n'
            "  </head>\n"
            f'  <body epub:type="{body_type}">\n'
            f"{body}\n"
            "  </body>\n"
            "</html>\n"
        )

    def _render_endnotes_document(
        self,
        document: SemanticBookDocument,
        *,
        footnotes: tuple[SemanticFootnote, ...],
        context: _RenderContext,
    ) -> str:
        """Render source footnotes as a dedicated EPUB endnotes document."""
        language = document.language or "und"
        language_attr = html.escape(language, quote=True)
        items = "\n".join(
            _render_endnote(note, "      ", context=context)
            for note in footnotes
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" '
            f'lang="{language_attr}" xml:lang="{language_attr}">\n'
            "  <head>\n"
            '    <meta charset="utf-8" />\n'
            "    <title>Notes</title>\n"
            '    <link rel="stylesheet" type="text/css" '
            'href="../styles/book.css" />\n'
            "  </head>\n"
            '  <body epub:type="backmatter">\n'
            '    <section id="endnotes" epub:type="endnotes">\n'
            "      <h1>Notes</h1>\n"
            '      <ol class="endnotes-list">\n'
            f"{items}\n"
            "      </ol>\n"
            "    </section>\n"
            "  </body>\n"
            "</html>\n"
        )

    def _render_nodes(
        self,
        nodes: tuple[SemanticFlowNode, ...],
        depth: int,
        *,
        context: _RenderContext,
    ) -> str:
        """Render a node sequence while preserving semantic heading groups."""
        rendered: list[str] = []
        index = 0
        while index < len(nodes):
            group = _heading_group_at(nodes, index)
            if group is not None:
                values, consumed = group
                rendered.append(
                    _render_heading_group(
                        values,
                        "  " * depth,
                        context=context,
                    )
                )
                index += consumed
                continue
            rendered.append(
                self._render_node(nodes[index], depth, context=context)
            )
            index += 1
        return "\n".join(rendered)

    def _render_node(
        self,
        node: SemanticFlowNode,
        depth: int,
        *,
        context: _RenderContext,
    ) -> str:
        """Render one semantic flow node recursively."""
        indent = "  " * depth
        if isinstance(node, SemanticParagraph):
            return _text_element(
                "p",
                node.node_id,
                node.content,
                indent=indent,
                context=context,
            )
        if isinstance(node, SemanticHeading):
            return _render_heading(node, indent, context=context)
        if isinstance(node, SemanticList):
            return _render_list(node, indent, context=context)
        if isinstance(node, SemanticVerse):
            return _render_verse(node, indent, context=context)
        if isinstance(node, SemanticQuotation):
            children = self._render_nodes(
                node.children,
                depth + 1,
                context=context,
            )
            return (
                f'{indent}<blockquote id="{_attr(node.node_id)}">\n'
                f"{children}\n"
                f"{indent}</blockquote>"
            )
        if isinstance(node, SemanticFigure):
            return _render_figure(node, indent, context=context)
        if isinstance(node, SemanticInset):
            children = self._render_nodes(
                node.children,
                depth + 1,
                context=context,
            )
            role = _css_token(node.role.value)
            return (
                f'{indent}<aside id="{_attr(node.node_id)}" '
                f'class="inset inset-{role}">\n'
                f"{children}\n"
                f"{indent}</aside>"
            )
        if isinstance(node, SemanticFootnote):
            raise ValueError("footnotes must be projected into endnotes.xhtml")
        if isinstance(node, SemanticAttribution):
            return _text_element(
                "p",
                node.node_id,
                node.content,
                indent=indent,
                class_name="attribution",
                context=context,
            )
        raise TypeError(f"unsupported semantic node: {type(node).__name__}")

    def _copy_assets(
        self,
        document: SemanticBookDocument,
        *,
        source_root: Path,
        destination_root: Path,
    ) -> tuple[Path, ...]:
        """Copy referenced assets while preventing path traversal."""
        copied: list[Path] = []
        for asset_id in sorted(set(_collect_asset_ids(document.nodes))):
            relative = Path(asset_id)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe semantic asset path: {asset_id!r}")
            source = (source_root / relative).resolve()
            try:
                source.relative_to(source_root)
            except ValueError as exc:
                raise ValueError(
                    f"semantic asset escapes source root: {asset_id!r}"
                ) from exc
            if not source.is_file():
                raise FileNotFoundError(f"missing semantic figure asset: {source}")
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(destination)
        return tuple(copied)


def _partition_top_level_footnotes(
    nodes: tuple[SemanticFlowNode, ...],
) -> tuple[tuple[SemanticFlowNode, ...], tuple[SemanticFootnote, ...]]:
    """Separate top-level note bodies from normal reading flow."""
    body: list[SemanticFlowNode] = []
    footnotes: list[SemanticFootnote] = []
    for node in nodes:
        if isinstance(node, SemanticFootnote):
            footnotes.append(node)
        else:
            body.append(node)
    return tuple(body), tuple(footnotes)


def _plan_content_chunks(
    nodes: tuple[SemanticFlowNode, ...],
) -> tuple[_ContentChunk, ...]:
    """Split logical body flow and assign semantic deterministic filenames."""
    raw_chunks = _split_content_chunks(nodes)
    filenames = _semantic_content_names(raw_chunks)
    return tuple(
        _ContentChunk(filename=name, nodes=chunk)
        for name, chunk in zip(filenames, raw_chunks, strict=True)
    )


def _split_content_chunks(
    nodes: tuple[SemanticFlowNode, ...],
) -> tuple[tuple[SemanticFlowNode, ...], ...]:
    """Split top-level flow at logical document starts while preserving labels."""
    chunks: list[tuple[SemanticFlowNode, ...]] = []
    current: list[SemanticFlowNode] = []
    for node in nodes:
        if isinstance(node, SemanticHeading) and _is_leading_heading_label(node):
            if current:
                chunks.append(tuple(current))
                current = []
            current.append(node)
            continue
        if _starts_new_document(node) and current:
            if not _contains_only_leading_heading_labels(current):
                chunks.append(tuple(current))
                current = []
        current.append(node)
    if current:
        chunks.append(tuple(current))
    if not chunks:
        chunks.append(())
    return tuple(chunks)


def _is_leading_heading_label(node: SemanticHeading) -> bool:
    """Return whether a label conventionally belongs to the following title."""
    return node.role in {
        HeadingRole.CHAPTER_LABEL,
        HeadingRole.GENRE_LABEL,
        HeadingRole.SCENARIO_LABEL,
    }


def _contains_only_leading_heading_labels(nodes: list[SemanticFlowNode]) -> bool:
    """Return whether a pending chunk contains only title-leading labels."""
    return bool(nodes) and all(
        isinstance(node, SemanticHeading) and _is_leading_heading_label(node)
        for node in nodes
    )


def _starts_new_document(node: SemanticFlowNode) -> bool:
    """Return whether one top-level node should begin a new spine document."""
    if not isinstance(node, SemanticHeading):
        return False
    return node.role not in {
        HeadingRole.CHAPTER_LABEL,
        HeadingRole.SUBTITLE,
        HeadingRole.GENRE_LABEL,
        HeadingRole.SCENARIO_LABEL,
    }


def _semantic_content_names(
    chunks: tuple[tuple[SemanticFlowNode, ...], ...],
) -> tuple[str, ...]:
    """Return semantic filenames while retaining stable fallback section names."""
    if len(chunks) == 1 and _chunk_filename_stem(chunks[0]) is None:
        return ("content.xhtml",)

    counters: dict[str, int] = {}
    names: list[str] = []
    for chunk in chunks:
        stem = _chunk_filename_stem(chunk) or "section"
        counters[stem] = counters.get(stem, 0) + 1
        names.append(f"{stem}-{counters[stem]:04d}.xhtml")
    return tuple(names)


def _chunk_filename_stem(nodes: tuple[SemanticFlowNode, ...]) -> str | None:
    """Choose a readable filename stem from the first meaningful heading role."""
    for node in nodes:
        if not isinstance(node, SemanticHeading):
            return None
        role_to_stem = {
            HeadingRole.CHAPTER_TITLE: "chapter",
            HeadingRole.SECTION_TITLE: "section",
            HeadingRole.SUBSECTION_TITLE: "subsection",
            HeadingRole.SCENARIO_TITLE: "scenario",
        }
        stem = role_to_stem.get(node.role)
        if stem is not None:
            return stem
        if node.role not in {
            HeadingRole.CHAPTER_LABEL,
            HeadingRole.GENRE_LABEL,
            HeadingRole.SCENARIO_LABEL,
        }:
            return None
    return None


def _build_locator(
    chunks: tuple[_ContentChunk, ...],
    *,
    footnotes: tuple[SemanticFootnote, ...],
) -> dict[str, str]:
    """Map every rendered linkable ID to its owning XHTML document."""
    locator: dict[str, str] = {}
    for chunk in chunks:
        for link_id in _collect_linkable_ids(chunk.nodes):
            _register_locator(locator, link_id, chunk.filename)
    for footnote in footnotes:
        _register_locator(locator, footnote.node_id, "endnotes.xhtml")
    return locator


def _register_locator(locator: dict[str, str], link_id: str, name: str) -> None:
    """Register one XHTML ID and reject cross-document duplicates."""
    existing = locator.get(link_id)
    if existing is not None and existing != name:
        raise ValueError(f"duplicate rendered XHTML id: {link_id}")
    locator[link_id] = name


def _collect_linkable_ids(nodes: tuple[SemanticFlowNode, ...]) -> tuple[str, ...]:
    """Collect element and noteref IDs that are emitted into XHTML."""
    result: list[str] = []
    for node in nodes:
        result.append(node.node_id)
        result.extend(_inline_reference_ids(_node_inline_groups(node)))
        if isinstance(node, SemanticList):
            result.extend(item.node_id for item in node.items)
        elif isinstance(node, SemanticVerse):
            result.extend(line.node_id for line in node.lines)
        elif isinstance(node, SemanticQuotation | SemanticInset):
            result.extend(_collect_linkable_ids(node.children))
    return tuple(result)


def _inline_reference_ids(
    groups: tuple[tuple[SemanticInline, ...], ...],
) -> tuple[str, ...]:
    """Collect IDs emitted on footnote reference anchors."""
    result: list[str] = []
    for values in groups:
        for value in values:
            if (
                value.role is InlineRole.FOOTNOTE_REF
                and value.source_span_id is not None
            ):
                result.append(value.source_span_id)
    return tuple(result)


def _collect_footnote_backlinks(
    nodes: tuple[SemanticFlowNode, ...],
) -> dict[str, tuple[str, ...]]:
    """Map each footnote target to the rendered reference IDs that point to it."""
    mutable: dict[str, list[str]] = {}
    for node in nodes:
        for values in _node_inline_groups(node):
            for value in values:
                if (
                    value.role is InlineRole.FOOTNOTE_REF
                    and value.target_id is not None
                    and value.source_span_id is not None
                ):
                    mutable.setdefault(value.target_id, []).append(
                        value.source_span_id
                    )
        if isinstance(node, SemanticQuotation | SemanticInset):
            nested = _collect_footnote_backlinks(node.children)
            for target_id, source_ids in nested.items():
                mutable.setdefault(target_id, []).extend(source_ids)
    return {key: tuple(values) for key, values in mutable.items()}


def _node_inline_groups(
    node: SemanticFlowNode,
) -> tuple[tuple[SemanticInline, ...], ...]:
    """Return direct inline groups carried by one flow node."""
    if isinstance(
        node,
        SemanticParagraph | SemanticHeading | SemanticFootnote | SemanticAttribution,
    ):
        return (node.content,)
    if isinstance(node, SemanticList):
        return tuple(item.content for item in node.items)
    if isinstance(node, SemanticVerse):
        return tuple(line.content for line in node.lines)
    if isinstance(node, SemanticFigure):
        return (node.caption,)
    return ()


def _heading_group_at(
    nodes: tuple[SemanticFlowNode, ...],
    start: int,
) -> tuple[tuple[SemanticHeading, ...], int] | None:
    """Return a title/label/subtitle heading group beginning at ``start``."""
    first = nodes[start]
    if not isinstance(first, SemanticHeading):
        return None

    values: list[SemanticHeading] = []
    primary_count = 0
    index = start
    while index < len(nodes) and isinstance(nodes[index], SemanticHeading):
        heading = nodes[index]
        assert isinstance(heading, SemanticHeading)
        if heading.level is not None:
            primary_count += 1
            if primary_count > 1:
                break
        elif heading.role not in {
            HeadingRole.CHAPTER_LABEL,
            HeadingRole.SUBTITLE,
            HeadingRole.GENRE_LABEL,
            HeadingRole.SCENARIO_LABEL,
        }:
            break
        values.append(heading)
        index += 1

    if primary_count != 1 or len(values) < 2:
        return None
    return tuple(values), len(values)


def _render_heading_group(
    headings: tuple[SemanticHeading, ...],
    indent: str,
    *,
    context: _RenderContext,
) -> str:
    """Render one semantic title group using HTML ``hgroup``."""
    children = "\n".join(
        _render_heading(
            heading,
            f"{indent}  ",
            context=context,
            supporting_tag="p",
        )
        for heading in headings
    )
    return f'{indent}<hgroup class="heading-group">\n{children}\n{indent}</hgroup>'


def _render_heading(
    node: SemanticHeading,
    indent: str,
    *,
    context: _RenderContext,
    supporting_tag: str = "p",
) -> str:
    """Render a hierarchical heading or non-hierarchical heading label."""
    role = _css_token(node.role.value)
    if node.level is None:
        return _text_element(
            supporting_tag,
            node.node_id,
            node.content,
            indent=indent,
            class_name=f"heading-label role-{role}",
            context=context,
        )
    level = min(6, max(1, node.level))
    return _text_element(
        f"h{level}",
        node.node_id,
        node.content,
        indent=indent,
        class_name=f"role-{role}",
        context=context,
    )


def _render_list(
    node: SemanticList,
    indent: str,
    *,
    context: _RenderContext,
) -> str:
    """Render ordered/unordered lists without source marker glyphs in text."""
    tag = "ol" if node.kind is ListKind.ORDERED else "ul"
    start_attribute = ""
    expected: int | None = None
    if node.kind is ListKind.ORDERED and node.items:
        first_ordinal = node.items[0].ordinal
        if first_ordinal is not None:
            expected = first_ordinal
            if first_ordinal != 1:
                start_attribute = f' start="{first_ordinal}"'
    items: list[str] = []
    for item in node.items:
        value_attribute = ""
        if node.kind is ListKind.ORDERED and item.ordinal is not None:
            if expected is not None and item.ordinal != expected:
                value_attribute = f' value="{item.ordinal}"'
            expected = item.ordinal + 1
        elif expected is not None:
            expected += 1
        items.append(
            f'{indent}  <li id="{_attr(item.node_id)}"{value_attribute}>'
            f"{_render_inlines(item.content, context=context)}</li>"
        )
    return (
        f'{indent}<{tag} id="{_attr(node.node_id)}"{start_attribute}>\n'
        + "\n".join(items)
        + f"\n{indent}</{tag}>"
    )


def _render_verse(
    node: SemanticVerse,
    indent: str,
    *,
    context: _RenderContext,
) -> str:
    """Render each verse line as its own paragraph for natural TTS pauses."""
    lines = [
        (
            f'{indent}  <p class="verse-line" '
            f'id="{_attr(line.node_id)}">'
            f"{_render_inlines(line.content, context=context)}</p>"
        )
        for line in node.lines
    ]
    return (
        f'{indent}<div class="verse" id="{_attr(node.node_id)}">\n'
        + "\n".join(lines)
        + f"\n{indent}</div>"
    )


def _render_figure(
    node: SemanticFigure,
    indent: str,
    *,
    context: _RenderContext,
) -> str:
    """Render one figure with a source-backed image and optional caption."""
    caption_text = "".join(value.text for value in node.caption).strip()
    alt = html.escape(caption_text, quote=True)
    source = html.escape(f"../{node.asset_id}", quote=True)
    lines = [
        f'{indent}<figure id="{_attr(node.node_id)}">',
        f'{indent}  <img src="{source}" alt="{alt}" />',
    ]
    if node.caption:
        lines.append(
            f"{indent}  <figcaption>"
            f"{_render_inlines(node.caption, context=context)}</figcaption>"
        )
    lines.append(f"{indent}</figure>")
    return "\n".join(lines)


def _render_endnote(
    node: SemanticFootnote,
    indent: str,
    *,
    context: _RenderContext,
) -> str:
    """Render one note in the dedicated endnotes list."""
    label = (
        f'<span class="endnote-label">{html.escape(node.label)}</span> '
        if node.label
        else ""
    )
    content = _render_inlines(node.content, context=context)
    backlinks = _render_backlinks(node.node_id, context=context)
    suffix = f" {backlinks}" if backlinks else ""
    return (
        f'{indent}<li id="{_attr(node.node_id)}" epub:type="endnote">\n'
        f"{indent}  <p>{label}{content}{suffix}</p>\n"
        f"{indent}</li>"
    )


def _render_backlinks(note_id: str, *, context: _RenderContext) -> str:
    """Render explicit semantic links from a note back to its references."""
    source_ids = context.backlinks_by_target.get(note_id, ())
    links: list[str] = []
    for index, source_id in enumerate(source_ids, start=1):
        source_document = context.locator_by_id.get(source_id)
        if source_document is None:
            continue
        href = f"{source_document}#{_attr(source_id)}"
        label = (
            "Back to reference"
            if len(source_ids) == 1
            else f"Back to reference {index}"
        )
        links.append(
            '<a class="footnote-backlink" epub:type="backlink" '
            f'href="{href}" aria-label="{html.escape(label, quote=True)}">'
            "↩</a>"
        )
    return " ".join(links)


def _text_element(
    tag: str,
    node_id: str,
    content: tuple[SemanticInline, ...],
    *,
    indent: str,
    context: _RenderContext,
    class_name: str | None = None,
) -> str:
    """Render one text-bearing XHTML element."""
    class_attribute = (
        f' class="{html.escape(class_name, quote=True)}"'
        if class_name is not None
        else ""
    )
    return (
        f'{indent}<{tag} id="{_attr(node_id)}"{class_attribute}>'
        f"{_render_inlines(content, context=context)}</{tag}>"
    )


def _render_inlines(
    values: tuple[SemanticInline, ...],
    *,
    context: _RenderContext,
) -> str:
    """Render semantic inline fragments plus explicit presentation hints."""
    return "".join(_render_inline(value, context=context) for value in values)


def _render_inline(value: SemanticInline, *, context: _RenderContext) -> str:
    """Render one inline while avoiding redundant DOM boundaries.

    Inline language inherits from the document unless it actually changes. Source
    presentation and a differing language are collapsed into one ``span`` where
    possible so TTS engines do not see gratuitous nested/sibling wrappers.
    """
    text = _strip_redundant_markdown_style_markers(value)
    rendered = html.escape(text)
    if SemanticMark.STRONG in value.marks:
        rendered = f"<strong>{rendered}</strong>"
    if SemanticMark.EMPHASIS in value.marks:
        rendered = f"<em>{rendered}</em>"

    attributes: list[str] = []
    if InlinePresentation.ITALIC in value.presentations:
        attributes.append('class="source-italic"')
    if (
        value.language is not None
        and value.language != context.document_language
    ):
        language = html.escape(value.language, quote=True)
        attributes.extend((f'lang="{language}"', f'xml:lang="{language}"'))
    if attributes:
        rendered = f"<span {' '.join(attributes)}>{rendered}</span>"

    if value.role is InlineRole.FOOTNOTE_REF:
        if value.target_id is None:
            raise ValueError("footnote reference has no target")
        target_document = context.locator_by_id.get(value.target_id)
        if target_document is None:
            raise ValueError(
                f"footnote reference target is not rendered: {value.target_id}"
            )
        source_id = (
            f' id="{_attr(value.source_span_id)}"'
            if value.source_span_id is not None
            else ""
        )
        href = f"{target_document}#{_attr(value.target_id)}"
        rendered = (
            '<sup class="noteref">'
            f'<a{source_id} epub:type="noteref" href="{href}">{rendered}</a>'
            "</sup>"
        )
    return rendered


def _strip_redundant_markdown_style_markers(value: SemanticInline) -> str:
    """Remove whole-run Markdown style delimiters already represented structurally.

    Extraction providers can occasionally return text such as ``**Title**`` while
    the same span already carries source italic/bold information. Keeping those
    delimiters makes them literal ebook text and can also create audible TTS
    hesitation. Only balanced delimiters wrapping the complete styled run are
    removed; ordinary unstyled text is left untouched.
    """
    if not value.marks and not value.presentations:
        return value.text

    text = value.text
    for _ in range(2):
        stripped = False
        for marker in ("**", "__", "*", "_"):
            if (
                text.startswith(marker)
                and text.endswith(marker)
                and len(text) > 2 * len(marker)
            ):
                text = text[len(marker) : -len(marker)]
                stripped = True
                break
        if not stripped:
            break
    return text


def _collect_asset_ids(nodes: tuple[SemanticFlowNode, ...]) -> list[str]:
    """Collect recursively referenced figure asset IDs."""
    assets: list[str] = []
    for node in nodes:
        if isinstance(node, SemanticFigure):
            assets.append(node.asset_id)
        elif isinstance(node, SemanticQuotation | SemanticInset):
            assets.extend(_collect_asset_ids(node.children))
    return assets


def _attr(value: str | None) -> str:
    """Escape one XHTML attribute value."""
    if value is None:
        return ""
    return html.escape(value, quote=True)


def _css_token(value: str) -> str:
    """Return a stable ASCII-ish CSS token for known enum values."""
    return value.replace("_", "-")


_DEFAULT_CSS = """\
body {
  font-family: serif;
  line-height: 1.5;
  margin: 5%;
}
.cover-body {
  margin: 0;
  padding: 0;
  text-align: center;
}
.cover-page {
  height: 100vh;
  margin: 0;
  padding: 0;
}
.book-cover {
  height: 100%;
  max-height: 100vh;
  max-width: 100%;
  object-fit: contain;
  width: auto;
}
img {
  height: auto;
  max-width: 100%;
}
figure {
  margin: 1.5em 0;
  text-align: center;
}
figcaption,
.attribution {
  margin-top: 0.5em;
}
.source-italic {
  font-style: italic;
}
.heading-group {
  margin: 1em 0;
}
.heading-label {
  display: block;
  margin: 0.5em 0;
}
.noteref {
  font-size: 0.75em;
  line-height: 0;
  vertical-align: super;
}
.verse {
  margin: 1em 0 1em 2em;
}
.verse-line {
  margin: 0;
}
.inset {
  margin: 1.5em 0;
}
.endnotes-list {
  list-style: none;
  padding-left: 0;
}
.endnotes-list > li {
  margin: 0.75em 0;
}
.endnote-label {
  font-weight: normal;
}
.footnote-backlink {
  margin-left: 0.35em;
  text-decoration: none;
}
"""
