"""Build EPUB-ready semantic XHTML from an assembled ``BookDocument``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    warnings: tuple[str, ...]
    render: XhtmlRenderResult
    output_dir: Path


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
        title: str,
        language: str | None = None,
        author: str | None = None,
    ) -> EbookEpubReadyRun:
        """Build EPUB-ready semantic artifacts from a persisted assembly."""
        assembly = Path(assembly_root).expanduser().resolve()
        output = Path(output_root).expanduser().resolve()
        if not assembly.is_dir():
            raise EbookEpubReadyError(
                f"assembly root is not a directory: {assembly}"
            )
        if not title.strip():
            raise EbookEpubReadyError("book title must not be empty")

        payload = _load_json_object(assembly / "structure" / "book.json")
        try:
            structural_document = book_document_from_dict(payload)
            projection = self._projector.project(
                structural_document,
                title=title,
                language=language,
                author=author,
            )
            render = self._renderer.render(
                projection.document,
                asset_root=assembly,
                output_root=output,
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
        store.write_json(
            "manifest.json",
            {
                "format": "epub-ready-xhtml",
                "source_assembly": assembly.name,
                "title": title,
                "language": language,
                "author": author,
                "content": render.content_path.relative_to(output).as_posix(),
                "contents": [
                    path.relative_to(output).as_posix()
                    for path in render.content_paths
                ],
                "endnotes": (
                    render.endnotes_path.relative_to(output).as_posix()
                    if render.endnotes_path is not None
                    else None
                ),
                "stylesheet": render.stylesheet_path.relative_to(
                    output
                ).as_posix(),
                "assets": [
                    path.relative_to(output).as_posix()
                    for path in render.copied_assets
                ],
                "warnings": list(projection.warnings),
            },
        )
        return EbookEpubReadyRun(
            document=projection.document,
            warnings=projection.warnings,
            render=render,
            output_dir=output,
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
