"""Tests for byte-preserving PDF-page materialization."""

import base64
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NumberObject,
)

from siftforge.extraction.materializers import PDFPageMaterializer
from siftforge.extraction.sources import PDFSource

_JPEG_BYTES: bytes = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQE"
    "BQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/"
    "2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFB"
    "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAACAAIDASIAAhEBAxEB"
    "/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIE"
    "AwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2Jy"
    "ggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlq"
    "c3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLD"
    "xMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEB"
    "AQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3"
    "AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcY"
    "GRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6"
    "goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK"
    "0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD9U6KK"
    "KAP/2Q=="
)


def _make_single_jpeg_page_pdf(path: Path) -> None:
    """Create one PDF page containing one exact `/DCTDecode` JPEG stream."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)

    image = EncodedStreamObject()
    image._data = _JPEG_BYTES
    image[NameObject("/Type")] = NameObject("/XObject")
    image[NameObject("/Subtype")] = NameObject("/Image")
    image[NameObject("/Width")] = NumberObject(2)
    image[NameObject("/Height")] = NumberObject(2)
    image[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
    image[NameObject("/BitsPerComponent")] = NumberObject(8)
    image[NameObject("/Filter")] = NameObject("/DCTDecode")
    image_reference = writer._add_object(image)

    xobjects = DictionaryObject()
    xobjects[NameObject("/Im0")] = image_reference
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = xobjects
    page[NameObject("/Resources")] = resources

    contents = DecodedStreamObject()
    contents.set_data(b"q 100 0 0 100 0 0 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(contents)

    with path.open("wb") as handle:
        writer.write(handle)


def test_pdf_materializer_preserves_embedded_jpeg_bytes(tmp_path: Path) -> None:
    """Materializer should write the original JPEG without re-encoding it."""
    pdf_path = tmp_path / "fixture.pdf"
    _make_single_jpeg_page_pdf(pdf_path)

    page_ref = next(PDFSource(pdf_path).iter_items())
    materializer = PDFPageMaterializer(pdf_path)
    asset = materializer.materialize(page_ref, tmp_path / "materialized")

    assert asset.media_type == "image/jpeg"
    assert asset.path.name == "page-0001.jpg"
    assert asset.path.read_bytes() == _JPEG_BYTES
    assert asset.byte_size == len(_JPEG_BYTES)
    assert asset.metadata["preserved_encoded_source"] is True
    assert asset.metadata["reused_existing_file"] is False


def test_pdf_materializer_reuses_matching_existing_file(tmp_path: Path) -> None:
    """Repeated materialization should reuse an unchanged local asset."""
    pdf_path = tmp_path / "fixture.pdf"
    _make_single_jpeg_page_pdf(pdf_path)

    page_ref = next(PDFSource(pdf_path).iter_items())
    materializer = PDFPageMaterializer(pdf_path)
    output_dir = tmp_path / "materialized"

    first = materializer.materialize(page_ref, output_dir)
    second = materializer.materialize(page_ref, output_dir)

    assert first.path == second.path
    assert second.metadata["reused_existing_file"] is True
    assert second.path.read_bytes() == _JPEG_BYTES
