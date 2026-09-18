"""Build EPUB-ready semantic XHTML from an assembled ``BookDocument``."""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siftforge.ebook.metadata import (
    BookMetadata,
    BookMetadataError,
    book_metadata_to_dict,
    resolve_book_metadata,
    resolve_metadata_cover,
)
from siftforge.ebook.renderers import EpubReadyXhtmlRenderer, XhtmlRenderResult
from siftforge.ebook.semantic import (
    EbookSemanticProjector,
    SemanticBookDocument,
    semantic_book_to_dict,
)
from siftforge.ebook.structure import book_document_from_dict
from siftforge.extraction.artifacts import FilesystemArtifactStore


class EbookEpubReadyError(ValueError):
    """Raised when an assembled book cannot produce EPUB-ready XHTML."""


@dataclass(frozen=True, slots=True)
class EbookEpubReadyRun:
    """Artifacts produced by semantic projection and XHTML rendering."""

    document: SemanticBookDocument
    metadata: BookMetadata
    warnings: tuple[str, ...]
    render: XhtmlRenderResult
    output_dir: Path
    cover_image_path: Path | None = None
    cover_content_path: Path | None = None

    @property
    def asset_count(self) -> int:
        """Return the total copied figure and cover asset count."""
        return len(self.render.copied_assets) + int(self.cover_image_path is not None)


class EbookEpubReadyService:
    """Project one book assembly into semantic XHTML without provider access."""

    def __init__(self) -> None:
        """Initialize deterministic projection and rendering components."""
        self._projector = EbookSemanticProjector()
        self._renderer = EpubReadyXhtmlRenderer()

    def build(
        self,
        assembly_root: str | Path,
        output_root: str | Path,
        *,
        title: str | None = None,
        language: str | None = None,
        author: str | None = None,
        metadata_path: str | Path | None = None,
        cover_path: str | Path | None = None,
    ) -> EbookEpubReadyRun:
        """Build EPUB-ready semantic artifacts from a persisted assembly.

        Explicit ``title``, ``language``, and ``author`` values override the
        corresponding values in ``metadata_path``. An explicit ``cover_path``
        overrides a cover declared in metadata JSON.
        """
        assembly = Path(assembly_root).expanduser().resolve()
        output = Path(output_root).expanduser().resolve()
        if not assembly.is_dir():
            raise EbookEpubReadyError(
                f"assembly root is not a directory: {assembly}"
            )
        metadata_source = (
            Path(metadata_path).expanduser().resolve()
            if metadata_path is not None
            else None
        )
        try:
            metadata = resolve_book_metadata(
                metadata_path=metadata_source,
                title=title,
                language=language,
                author=author,
            )
            metadata_cover = resolve_metadata_cover(
                metadata,
                metadata_path=metadata_source,
            )
            resolved_cover = (
                Path(cover_path).expanduser().resolve()
                if cover_path is not None
                else metadata_cover
            )
        except BookMetadataError as exc:
            raise EbookEpubReadyError(str(exc)) from exc

        payload = _load_json_object(assembly / "structure" / "book.json")
        try:
            structural_document = book_document_from_dict(payload)
            projection = self._projector.project(
                structural_document,
                title=metadata.title,
                language=metadata.language,
                author=metadata.primary_author,
            )
            render = self._renderer.render(
                projection.document,
                asset_root=assembly,
                output_root=output,
            )
            cover_image, cover_content = _prepare_cover(
                output,
                title=metadata.title,
                language=metadata.language,
                cover_path=resolved_cover,
            )
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise EbookEpubReadyError(
                f"EPUB-ready projection failed: {exc}"
            ) from exc

        store = FilesystemArtifactStore(output)
        store.write_json(
            "semantic/document.json",
            semantic_book_to_dict(projection.document),
        )
        content_paths = (
            ((cover_content,) if cover_content is not None else ())
            + render.content_paths
        )
        asset_paths = render.copied_assets + (
            (cover_image,) if cover_image is not None else ()
        )
        store.write_json(
            "metadata.json",
            book_metadata_to_dict(metadata),
        )
        store.write_json(
            "manifest.json",
            {
                "format": "epub-ready-xhtml",
                "source_assembly": assembly.name,
                "title": metadata.title,
                "language": metadata.language,
                "author": metadata.primary_author,
                "metadata": book_metadata_to_dict(metadata),
                "content": render.content_path.relative_to(output).as_posix(),
                "contents": [
                    path.relative_to(output).as_posix()
                    for path in content_paths
                ],
                "cover": (
                    {
                        "image": cover_image.relative_to(output).as_posix(),
                        "content": cover_content.relative_to(output).as_posix(),
                    }
                    if cover_image is not None and cover_content is not None
                    else None
                ),
                "endnotes": (
                    render.endnotes_path.relative_to(output).as_posix()
                    if render.endnotes_path is not None
                    else None
                ),
                "stylesheet": render.stylesheet_path.relative_to(
                    output
                ).as_posix(),
                "assets": [
                    path.relative_to(output).as_posix() for path in asset_paths
                ],
                "warnings": list(projection.warnings),
            },
        )
        return EbookEpubReadyRun(
            document=projection.document,
            metadata=metadata,
            warnings=projection.warnings,
            render=render,
            output_dir=output,
            cover_image_path=cover_image,
            cover_content_path=cover_content,
        )


def _load_json_object(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object with pipeline-specific errors."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EbookEpubReadyError(f"missing assembly artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EbookEpubReadyError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise EbookEpubReadyError(f"JSON artifact must be an object: {path}")
    return payload


_COVER_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


def _prepare_cover(
    output_root: Path,
    *,
    title: str,
    language: str | None,
    cover_path: Path | None,
) -> tuple[Path | None, Path | None]:
    """Copy an optional cover and create its dedicated XHTML spine document."""
    if cover_path is None:
        return None, None
    if not cover_path.is_file():
        raise EbookEpubReadyError(f"cover image does not exist: {cover_path}")
    suffix = cover_path.suffix.lower()
    if suffix not in _COVER_MEDIA_TYPES:
        raise EbookEpubReadyError(
            f"unsupported cover image type: {cover_path.suffix or '<none>'}"
        )

    assets = output_root / "assets"
    text = output_root / "text"
    assets.mkdir(parents=True, exist_ok=True)
    text.mkdir(parents=True, exist_ok=True)
    image = assets / f"cover{suffix}"
    shutil.copyfile(cover_path, image)
    content = text / "cover.xhtml"
    content.write_text(
        _render_cover_xhtml(
            title=title,
            language=language or "und",
            image_filename=image.name,
        ),
        encoding="utf-8",
    )
    return image, content


def _render_cover_xhtml(
    *,
    title: str,
    language: str,
    image_filename: str,
) -> str:
    """Render a reader-compatible EPUB cover document."""
    title_text = html.escape(title)
    title_attr = html.escape(title, quote=True)
    language_attr = html.escape(language, quote=True)
    image_attr = html.escape(image_filename, quote=True)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'lang="{language_attr}" xml:lang="{language_attr}">\n'
        '  <head>\n'
        '    <meta charset="utf-8" />\n'
        f'    <title>{title_text}</title>\n'
        '    <link rel="stylesheet" type="text/css" '
        'href="../styles/book.css" />\n'
        '  </head>\n'
        '  <body epub:type="cover" class="cover-body">\n'
        '    <section epub:type="cover" class="cover-page">\n'
        f'      <img class="book-cover" src="../assets/{image_attr}" '
        f'alt="{title_attr}" />\n'
        '    </section>\n'
        '  </body>\n'
        '</html>\n'
    )
