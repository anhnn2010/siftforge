"""Render EPUB-ready semantic content into standalone XHTML assets."""

from __future__ import annotations

import html
import shutil
from dataclasses import dataclass
from pathlib import Path

from siftforge.ebook.semantic import (
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
from siftforge.ebook.structure import ListKind, SemanticMark


@dataclass(frozen=True, slots=True)
class XhtmlRenderResult:
    """Files produced by the EPUB-ready XHTML renderer."""

    content_path: Path
    stylesheet_path: Path
    copied_assets: tuple[Path, ...]


class EpubReadyXhtmlRenderer:
    """Render one semantic book document into XHTML + CSS + copied assets.

    This is deliberately not a complete EPUB package yet. It emits content in
    the same XHTML vocabulary used by EPUB so later packaging can add OPF, nav,
    mimetype, and container metadata without changing content semantics.
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
        content_path = text_dir / "content.xhtml"
        content_path.write_text(
            self._render_document(document),
            encoding="utf-8",
        )
        return XhtmlRenderResult(
            content_path=content_path,
            stylesheet_path=stylesheet_path,
            copied_assets=copied_assets,
        )

    def _render_document(self, document: SemanticBookDocument) -> str:
        """Render one complete XHTML document."""
        language = document.language or "und"
        body = "\n".join(self._render_node(node, 2) for node in document.nodes)
        title = html.escape(document.title)
        language_attr = html.escape(language, quote=True)
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" '
            f'lang="{language_attr}" xml:lang="{language_attr}">\n'
            "  <head>\n"
            "    <meta charset=\"utf-8\" />\n"
            f"    <title>{title}</title>\n"
            '    <link rel="stylesheet" type="text/css" '
            'href="../styles/book.css" />\n'
            "  </head>\n"
            "  <body>\n"
            f"{body}\n"
            "  </body>\n"
            "</html>\n"
        )

    def _render_node(self, node: SemanticFlowNode, depth: int) -> str:
        """Render one semantic flow node recursively."""
        indent = "  " * depth
        if isinstance(node, SemanticParagraph):
            return _text_element(
                "p",
                node.node_id,
                node.content,
                indent=indent,
            )
        if isinstance(node, SemanticHeading):
            return _render_heading(node, indent)
        if isinstance(node, SemanticList):
            return _render_list(node, indent)
        if isinstance(node, SemanticVerse):
            lines = "\n".join(
                f'{indent}  <div class="verse-line" id="{_attr(line.node_id)}">'
                f"{_render_inlines(line.content)}</div>"
                for line in node.lines
            )
            return (
                f'{indent}<div class="verse" id="{_attr(node.node_id)}">\n'
                f"{lines}\n"
                f"{indent}</div>"
            )
        if isinstance(node, SemanticQuotation):
            children = "\n".join(
                self._render_node(child, depth + 1) for child in node.children
            )
            return (
                f'{indent}<blockquote id="{_attr(node.node_id)}">\n'
                f"{children}\n"
                f"{indent}</blockquote>"
            )
        if isinstance(node, SemanticFigure):
            return _render_figure(node, indent)
        if isinstance(node, SemanticInset):
            children = "\n".join(
                self._render_node(child, depth + 1) for child in node.children
            )
            role = _css_token(node.role.value)
            return (
                f'{indent}<aside id="{_attr(node.node_id)}" '
                f'class="inset inset-{role}">\n'
                f"{children}\n"
                f"{indent}</aside>"
            )
        if isinstance(node, SemanticFootnote):
            label = (
                f'<span class="footnote-label">{html.escape(node.label)}</span> '
                if node.label
                else ""
            )
            return (
                f'{indent}<aside id="{_attr(node.node_id)}" '
                'class="footnote" epub:type="footnote">'
                f"{label}{_render_inlines(node.content)}</aside>"
            )
        if isinstance(node, SemanticAttribution):
            return _text_element(
                "p",
                node.node_id,
                node.content,
                indent=indent,
                class_name="attribution",
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


def _render_heading(node: SemanticHeading, indent: str) -> str:
    """Render a heading or non-hierarchical heading-like label."""
    role = _css_token(node.role.value)
    if node.level is None:
        return _text_element(
            "div",
            node.node_id,
            node.content,
            indent=indent,
            class_name=f"heading-label role-{role}",
        )
    level = min(6, max(1, node.level))
    return _text_element(
        f"h{level}",
        node.node_id,
        node.content,
        indent=indent,
        class_name=f"role-{role}",
    )


def _render_list(node: SemanticList, indent: str) -> str:
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
            f"{_render_inlines(item.content)}</li>"
        )
    return (
        f'{indent}<{tag} id="{_attr(node.node_id)}"{start_attribute}>\n'
        + "\n".join(items)
        + f"\n{indent}</{tag}>"
    )


def _render_figure(node: SemanticFigure, indent: str) -> str:
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
            f"{indent}  <figcaption>{_render_inlines(node.caption)}</figcaption>"
        )
    lines.append(f"{indent}</figure>")
    return "\n".join(lines)


def _text_element(
    tag: str,
    node_id: str,
    content: tuple[SemanticInline, ...],
    *,
    indent: str,
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
        f"{_render_inlines(content)}</{tag}>"
    )


def _render_inlines(values: tuple[SemanticInline, ...]) -> str:
    """Render semantic inline fragments without consulting source typography."""
    return "".join(_render_inline(value) for value in values)


def _render_inline(value: SemanticInline) -> str:
    """Render one inline with semantic marks, language, and note links."""
    rendered = html.escape(value.text)
    if SemanticMark.STRONG in value.marks:
        rendered = f"<strong>{rendered}</strong>"
    if SemanticMark.EMPHASIS in value.marks:
        rendered = f"<em>{rendered}</em>"
    if value.language is not None:
        language = html.escape(value.language, quote=True)
        rendered = (
            f'<span lang="{language}" xml:lang="{language}">{rendered}</span>'
        )
    if value.role is InlineRole.FOOTNOTE_REF:
        if value.target_id is None:
            raise ValueError("footnote reference has no target")
        source_id = (
            f' id="{_attr(value.source_span_id)}"'
            if value.source_span_id is not None
            else ""
        )
        rendered = (
            '<sup class="noteref">'
            f'<a{source_id} epub:type="noteref" '
            f'href="#{_attr(value.target_id)}">{rendered}</a>'
            "</sup>"
        )
    return rendered


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
  display: block;
}
.inset {
  margin: 1.5em 0;
}
.footnote {
  font-size: 0.9em;
}
"""
