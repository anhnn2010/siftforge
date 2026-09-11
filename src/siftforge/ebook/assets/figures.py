"""Materialize logical figure regions into renderable image assets."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image

from siftforge.ebook.evidence import NormalizedRegion
from siftforge.ebook.structure import (
    BookDocument,
    FigureNode,
    FlowNode,
    InsetNode,
    QuotationNode,
)


@dataclass(frozen=True, slots=True)
class FigureSourcePage:
    """Source-page image associated with one physical page identity."""

    page_id: str
    image_path: Path


@dataclass(frozen=True, slots=True)
class FigureAsset:
    """One cropped figure image derived from a source-page region."""

    figure_node_id: str
    source_page_id: str
    asset_id: str
    path: Path
    pixel_box: tuple[int, int, int, int]
    width: int
    height: int


class FigureAssetMaterializer:
    """Crop source-page regions and attach deterministic figure asset IDs.

    Crops are saved as PNG so the derived asset does not introduce an extra
    lossy JPEG generation. Exact printed-page layout is not reproduced; the
    crop exists only to preserve the pixels belonging to the logical figure.
    """

    def materialize(
        self,
        document: BookDocument,
        source_pages: Mapping[str, FigureSourcePage],
        output_root: str | Path,
    ) -> tuple[BookDocument, tuple[FigureAsset, ...]]:
        """Materialize every figure reachable from a logical document.

        Args:
            document: Logical book structure containing source-backed figures.
            source_pages: Physical page images keyed by ``page_id``.
            output_root: Assembly directory owning the derived asset folder.

        Returns:
            Updated document whose figures reference derived assets, plus the
            complete materialized figure manifest.

        Raises:
            ValueError: If a figure lacks exactly one source page or that page
                has no available source image.
        """
        root = Path(output_root).expanduser().resolve()
        assets_dir = root / "assets" / "figures"
        assets_dir.mkdir(parents=True, exist_ok=True)

        assets: list[FigureAsset] = []
        nodes = tuple(
            self._materialize_node(node, source_pages, root, assets)
            for node in document.nodes
        )
        return (
            replace(document, nodes=nodes),
            tuple(assets),
        )

    def _materialize_node(
        self,
        node: FlowNode,
        source_pages: Mapping[str, FigureSourcePage],
        output_root: Path,
        assets: list[FigureAsset],
    ) -> FlowNode:
        """Recursively materialize figures while preserving container shape."""
        if isinstance(node, FigureNode):
            updated, asset = self._materialize_figure(
                node,
                source_pages,
                output_root,
            )
            assets.append(asset)
            return updated
        if isinstance(node, QuotationNode):
            return replace(
                node,
                children=tuple(
                    self._materialize_node(
                        child,
                        source_pages,
                        output_root,
                        assets,
                    )
                    for child in node.children
                ),
            )
        if isinstance(node, InsetNode):
            return replace(
                node,
                children=tuple(
                    self._materialize_node(
                        child,
                        source_pages,
                        output_root,
                        assets,
                    )
                    for child in node.children
                ),
            )
        return node

    def _materialize_figure(
        self,
        figure: FigureNode,
        source_pages: Mapping[str, FigureSourcePage],
        output_root: Path,
    ) -> tuple[FigureNode, FigureAsset]:
        """Crop one figure and return the updated immutable logical node."""
        page_ids = {fragment.page_id for fragment in figure.image.provenance}
        if len(page_ids) != 1:
            raise ValueError(
                f"figure {figure.node_id!r} must reference exactly one source page"
            )
        page_id = next(iter(page_ids))
        source_page = source_pages.get(page_id)
        if source_page is None:
            raise ValueError(
                f"missing source-page image for figure {figure.node_id!r}: {page_id}"
            )

        asset_name = _figure_asset_name(figure.node_id)
        asset_id = f"assets/figures/{asset_name}"
        destination = output_root / asset_id
        destination.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(source_page.image_path) as source_image:
            source_image.load()
            pixel_box = _pixel_box(
                width=source_image.width,
                height=source_image.height,
                region=figure.image.source_region,
            )
            crop = source_image.crop(pixel_box)
            temporary = destination.with_name(f".{destination.name}.tmp")
            crop.save(temporary, format="PNG", optimize=True)
            temporary.replace(destination)
            width, height = crop.size

        updated_image = replace(figure.image, asset_id=asset_id)
        return (
            replace(figure, image=updated_image),
            FigureAsset(
                figure_node_id=figure.node_id,
                source_page_id=page_id,
                asset_id=asset_id,
                path=destination,
                pixel_box=pixel_box,
                width=width,
                height=height,
            ),
        )


def _figure_asset_name(node_id: str) -> str:
    """Return a Windows-safe deterministic filename for one figure node."""
    digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:16]
    return f"figure-{digest}.png"


def _pixel_box(
    *, width: int, height: int, region: NormalizedRegion
) -> tuple[int, int, int, int]:
    """Convert a normalized source region into a clamped Pillow crop box."""
    x = region.x
    y = region.y
    region_width = region.width
    region_height = region.height

    left = max(0, min(width - 1, math.floor(x * width)))
    top = max(0, min(height - 1, math.floor(y * height)))
    right = max(left + 1, min(width, math.ceil((x + region_width) * width)))
    bottom = max(top + 1, min(height, math.ceil((y + region_height) * height)))
    return left, top, right, bottom
