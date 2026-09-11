"""Tests for rendering source-backed figure regions into derived assets."""

from pathlib import Path

from PIL import Image

from siftforge.ebook.assets import FigureAssetMaterializer, FigureSourcePage
from siftforge.ebook.evidence import NormalizedRegion
from siftforge.ebook.structure import (
    BookDocument,
    FigureNode,
    ImageNode,
    SourceFragment,
)


def test_figure_materializer_crops_region_as_lossless_png(tmp_path: Path) -> None:
    """Normalized figure bounds should produce deterministic decoded pixels."""
    page_image = tmp_path / "page.jpg"
    Image.new("RGB", (100, 80), (240, 240, 240)).save(page_image, format="JPEG")
    fragment = SourceFragment(page_id="page-0116", block_id="block-image")
    figure = FigureNode(
        node_id="page-0116:block:0001:figure",
        image=ImageNode(
            node_id="page-0116:block:0001:image",
            source_region=NormalizedRegion(
                x=0.10,
                y=0.25,
                width=0.30,
                height=0.50,
            ),
            provenance=(fragment,),
        ),
        provenance=(fragment,),
    )
    document = BookDocument(nodes=(figure,))

    updated, assets = FigureAssetMaterializer().materialize(
        document,
        {
            "page-0116": FigureSourcePage(
                page_id="page-0116",
                image_path=page_image,
            )
        },
        tmp_path / "assembly",
    )

    assert len(assets) == 1
    asset = assets[0]
    assert asset.pixel_box == (10, 20, 40, 60)
    assert (asset.width, asset.height) == (30, 40)
    assert asset.path.suffix == ".png"
    assert asset.path.is_file()
    with Image.open(asset.path) as crop:
        assert crop.size == (30, 40)

    updated_figure = updated.nodes[0]
    assert isinstance(updated_figure, FigureNode)
    assert updated_figure.image.asset_id == asset.asset_id
    assert asset.asset_id.startswith("assets/figures/figure-")


def test_figure_asset_name_is_repeatable(tmp_path: Path) -> None:
    """Repeated materialization should retain the same logical asset identity."""
    page_image = tmp_path / "page.jpg"
    Image.new("RGB", (20, 20)).save(page_image, format="JPEG")
    fragment = SourceFragment(page_id="page-1", block_id="block-1")
    figure = FigureNode(
        node_id="stable:figure:id",
        image=ImageNode(
            node_id="stable:image:id",
            source_region=NormalizedRegion(x=0, y=0, width=1, height=1),
            provenance=(fragment,),
        ),
        provenance=(fragment,),
    )
    document = BookDocument(nodes=(figure,))
    pages = {
        "page-1": FigureSourcePage(page_id="page-1", image_path=page_image)
    }
    materializer = FigureAssetMaterializer()

    _, first = materializer.materialize(document, pages, tmp_path / "first")
    _, second = materializer.materialize(document, pages, tmp_path / "second")

    assert first[0].asset_id == second[0].asset_id
