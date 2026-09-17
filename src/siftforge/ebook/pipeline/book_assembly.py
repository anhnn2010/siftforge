"""Assemble existing v5 page runs into logical multi-page ebook structure."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from siftforge.ebook.assets import (
    FigureAsset,
    FigureAssetMaterializer,
    FigureSourcePage,
)
from siftforge.ebook.evidence import (
    PageExtraction,
    TextCorrectionError,
    apply_text_corrections,
)
from siftforge.ebook.extraction import EbookPageEvidenceNormalizer
from siftforge.ebook.structure import (
    BookDocument,
    BookStructuralAnalyzer,
    StructuralAnalysisResult,
    book_document_to_dict,
)
from siftforge.extraction.artifacts import FilesystemArtifactStore


class EbookBookAssemblyError(ValueError):
    """Raised when persisted page runs cannot form a valid book assembly."""


@dataclass(frozen=True, slots=True)
class EbookPageRunArtifact:
    """One persisted v5 page run loaded without calling the AI provider again."""

    run_dir: Path
    page_number: int
    page: PageExtraction
    source_image: Path
    source_media_type: str


@dataclass(frozen=True, slots=True)
class EbookBookAssemblyRun:
    """Artifacts and typed structure produced by multi-page book assembly."""

    page_runs: tuple[EbookPageRunArtifact, ...]
    analysis: StructuralAnalysisResult
    document: BookDocument
    figure_assets: tuple[FigureAsset, ...]
    output_dir: Path


class EbookPageRunLoader:
    """Load canonical v5 page run directories produced by ``extract-page``."""

    def __init__(self) -> None:
        """Initialize the loader with the strict canonical page normalizer."""
        self._normalizer = EbookPageEvidenceNormalizer()

    def discover(self, runs_root: str | Path) -> tuple[EbookPageRunArtifact, ...]:
        """Load direct page-run children and order them by physical page number."""
        root = Path(runs_root).expanduser().resolve()
        if not root.is_dir():
            raise EbookBookAssemblyError(
                f"page-runs root is not a directory: {root}"
            )
        run_dirs = sorted(
            path
            for path in root.iterdir()
            if path.is_dir()
            and (path / "manifest.json").is_file()
            and (path / "normalized" / "page.json").is_file()
        )
        if not run_dirs:
            raise EbookBookAssemblyError(
                f"no v5 page runs found below: {root}"
            )
        runs = tuple(self.load(path) for path in run_dirs)
        ordered = tuple(sorted(runs, key=lambda item: item.page_number))
        page_numbers = [item.page_number for item in ordered]
        if len(page_numbers) != len(set(page_numbers)):
            raise EbookBookAssemblyError(
                "page-run root contains duplicate physical page numbers"
            )
        return ordered

    def load(self, run_dir: str | Path) -> EbookPageRunArtifact:
        """Load and validate one v5 page-run artifact directory."""
        root = Path(run_dir).expanduser().resolve()
        page_payload = _load_json_object(root / "normalized" / "page.json")
        try:
            page = self._normalizer.from_dict(page_payload)
        except ValueError as exc:
            raise EbookBookAssemblyError(
                f"invalid normalized page artifact in {root}: {exc}"
            ) from exc

        manifest = _load_json_object(root / "manifest.json")
        page_number = _positive_int(
            _nested_value(manifest, "source", "page_number"),
            "manifest.source.page_number",
        )
        source_page_number = page.source.metadata.get("page_number")
        if source_page_number is not None and source_page_number != page_number:
            raise EbookBookAssemblyError(
                f"manifest/page source page mismatch in {root}"
            )

        asset_path_value = _nested_value(manifest, "asset", "path")
        if not isinstance(asset_path_value, str) or not asset_path_value:
            raise EbookBookAssemblyError(
                "manifest.asset.path must be a non-empty string"
            )
        source_image = (root / asset_path_value).resolve()
        if root not in source_image.parents:
            raise EbookBookAssemblyError(
                f"manifest asset escapes page run directory: {asset_path_value!r}"
            )
        if not source_image.is_file():
            raise EbookBookAssemblyError(
                f"page source image does not exist: {source_image}"
            )
        source_media_type = _nested_value(manifest, "asset", "media_type")
        if not isinstance(source_media_type, str) or not source_media_type:
            raise EbookBookAssemblyError(
                "manifest.asset.media_type must be a non-empty string"
            )
        return EbookPageRunArtifact(
            run_dir=root,
            page_number=page_number,
            page=page,
            source_image=source_image,
            source_media_type=source_media_type,
        )


class EbookBookAssemblyService:
    """Build logical book structure and renderable figure assets from page runs."""

    def __init__(
        self,
        analyzer: BookStructuralAnalyzer | None = None,
        figure_materializer: FigureAssetMaterializer | None = None,
        loader: EbookPageRunLoader | None = None,
    ) -> None:
        """Initialize deterministic assembly collaborators."""
        self._analyzer = analyzer or BookStructuralAnalyzer()
        self._figure_materializer = (
            figure_materializer or FigureAssetMaterializer()
        )
        self._loader = loader or EbookPageRunLoader()

    def assemble(
        self,
        runs_root: str | Path,
        output_dir: str | Path,
    ) -> EbookBookAssemblyRun:
        """Assemble persisted page runs without making any provider calls."""
        raw_page_runs = self._loader.discover(runs_root)
        try:
            page_runs = tuple(
                replace(
                    page_run,
                    page=_load_effective_page(page_run),
                )
                for page_run in raw_page_runs
            )
        except (OSError, ValueError, TextCorrectionError) as exc:
            raise EbookBookAssemblyError(
                f"review correction overlay failed: {exc}"
            ) from exc
        output = Path(output_dir).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)

        analysis = self._analyzer.analyze(
            tuple(page_run.page for page_run in page_runs)
        )
        source_pages = {
            page_run.page.page_id: FigureSourcePage(
                page_id=page_run.page.page_id,
                image_path=page_run.source_image,
            )
            for page_run in page_runs
        }
        try:
            document, figure_assets = self._figure_materializer.materialize(
                analysis.document,
                source_pages,
                output,
            )
        except (OSError, ValueError) as exc:
            raise EbookBookAssemblyError(
                f"figure materialization failed: {exc}"
            ) from exc
        updated_analysis = replace(analysis, document=document)
        self._write_artifacts(
            output=output,
            page_runs=page_runs,
            analysis=updated_analysis,
            figure_assets=figure_assets,
        )
        return EbookBookAssemblyRun(
            page_runs=page_runs,
            analysis=updated_analysis,
            document=document,
            figure_assets=figure_assets,
            output_dir=output,
        )

    def _write_artifacts(
        self,
        *,
        output: Path,
        page_runs: Sequence[EbookPageRunArtifact],
        analysis: StructuralAnalysisResult,
        figure_assets: Sequence[FigureAsset],
    ) -> None:
        """Persist inspectable logical structure and assembly provenance."""
        store = FilesystemArtifactStore(output)
        store.write_json(
            "structure/book.json",
            book_document_to_dict(analysis.document),
        )
        store.write_json(
            "structure/analysis.json",
            {
                "running_furniture": [
                    {
                        "page_id": item.page_id,
                        "block_id": item.block_id,
                        "role_hint": item.role_hint.value,
                        "raw_text": item.raw_text,
                        "normalized_text": item.normalized_text,
                        "repeated": item.repeated,
                    }
                    for item in analysis.running_furniture
                ],
                "unresolved_block_ids": [
                    block.block_id for block in analysis.unresolved_blocks
                ],
                "container_candidates": [
                    {
                        "candidate_id": item.candidate_id,
                        "kind": item.kind.value,
                        "role": item.role.value,
                        "source_block_ids": list(item.source_block_ids),
                        "confidence": item.confidence,
                        "reasons": list(item.reasons),
                    }
                    for item in analysis.container_candidates
                ],
                "resolved_continuations": [
                    {
                        "relationship_id": item.relationship_id,
                        "source_id": item.source_id,
                        "target_id": item.target_id,
                        "confidence": item.confidence,
                        "reasons": list(item.reasons),
                    }
                    for item in analysis.resolved_continuations
                ],
            },
        )
        store.write_json(
            "manifest.json",
            {
                "assembly_model": "BookDocument",
                "pages": [
                    {
                        "page_number": item.page_number,
                        "page_id": item.page.page_id,
                        "source_run": item.run_dir.name,
                        "source_asset": item.source_image.relative_to(
                            item.run_dir
                        ).as_posix(),
                    }
                    for item in page_runs
                ],
                "figure_assets": [
                    {
                        "figure_node_id": item.figure_node_id,
                        "source_page_id": item.source_page_id,
                        "asset_id": item.asset_id,
                        "pixel_box": list(item.pixel_box),
                        "width": item.width,
                        "height": item.height,
                    }
                    for item in figure_assets
                ],
            },
        )


def _load_effective_page(page_run: EbookPageRunArtifact) -> PageExtraction:
    """Overlay reviewed corrections while keeping normalized evidence immutable."""
    path = page_run.run_dir / "review" / "corrections.json"
    if not path.is_file():
        return page_run.page
    payload = _load_json_object(path)
    return apply_text_corrections(page_run.page, payload)


def _load_json_object(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object with assembly-specific error reporting."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EbookBookAssemblyError(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EbookBookAssemblyError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise EbookBookAssemblyError(f"JSON artifact must be an object: {path}")
    return payload


def _nested_value(payload: dict[str, Any], *keys: str) -> Any:
    """Return a required nested manifest value without silently defaulting."""
    value: Any = payload
    traversed: list[str] = []
    for key in keys:
        traversed.append(key)
        if not isinstance(value, dict) or key not in value:
            path = ".".join(traversed)
            raise EbookBookAssemblyError(f"manifest is missing {path}")
        value = value[key]
    return value


def _positive_int(value: Any, path: str) -> int:
    """Validate one positive integer without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EbookBookAssemblyError(f"{path} must be a positive integer")
    return value
