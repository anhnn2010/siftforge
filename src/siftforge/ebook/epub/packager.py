"""Create and validate deterministic EPUB 3 package archives."""

from __future__ import annotations

import hashlib
import html
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from siftforge.ebook.metadata import (
    BookMetadata,
    BookMetadataError,
    book_metadata_from_dict,
    book_metadata_to_dict,
)

_EPUB_MIMETYPE = b"application/epub+zip"
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_MODIFIED_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class EpubPackageError(ValueError):
    """Raised when EPUB-ready artifacts cannot form a valid EPUB package."""


@dataclass(frozen=True, slots=True)
class EpubTocEntry:
    """One flat navigation entry derived from a semantic heading."""

    label: str
    target_id: str


@dataclass(frozen=True, slots=True)
class _ResolvedTocEntry:
    """One navigation entry bound to the XHTML file containing its target."""

    label: str
    target_id: str
    content_relative: PurePosixPath


@dataclass(frozen=True, slots=True)
class EpubPackageResult:
    """Metadata describing one successfully built EPUB archive."""

    epub_path: Path
    identifier: str
    modified: str
    manifest_item_count: int
    toc_entry_count: int


class EpubPackageBuilder:
    """Package EPUB-ready XHTML artifacts into a validated EPUB 3 archive."""

    def build(
        self,
        epub_ready_root: str | Path,
        output_path: str | Path,
        *,
        identifier: str | None = None,
        modified: str | None = None,
    ) -> EpubPackageResult:
        """Build one EPUB archive from a persisted EPUB-ready directory.

        Args:
            epub_ready_root: Root produced by ``render-xhtml``.
            output_path: Destination ``.epub`` file.
            identifier: Optional publication identifier. A stable UUID URN is
                derived from package inputs when omitted.
            modified: Optional EPUB 3 ``dcterms:modified`` timestamp in UTC
                ``YYYY-MM-DDTHH:MM:SSZ`` form. Current UTC time is used when
                omitted.

        Returns:
            Result describing the generated EPUB archive.

        Raises:
            EpubPackageError: If source artifacts or package metadata are invalid.
        """
        root = Path(epub_ready_root).expanduser().resolve()
        destination = Path(output_path).expanduser().resolve()
        if not root.is_dir():
            raise EpubPackageError(
                f"EPUB-ready root is not a directory: {root}"
            )
        if destination.suffix.lower() != ".epub":
            raise EpubPackageError("EPUB output path must end with .epub")

        manifest = _load_json_object(root / "manifest.json")
        if manifest.get("format") != "epub-ready-xhtml":
            raise EpubPackageError(
                "EPUB-ready manifest has unsupported or missing format"
            )
        metadata = _manifest_metadata(manifest)
        if metadata.title is None:
            raise EpubPackageError("publication metadata title must not be empty")
        title = metadata.title
        language = metadata.language or "und"
        content_relatives = _manifest_content_paths(manifest)
        cover_image_relative, cover_content_relative = _manifest_cover_paths(
            manifest,
            content_relatives=content_relatives,
        )
        endnotes_relative = _manifest_endnotes_path(
            manifest,
            content_relatives=content_relatives,
        )
        stylesheet_relative = _safe_relative_path(
            _required_nonempty_string(manifest, "stylesheet")
        )
        asset_relatives = _manifest_asset_paths(manifest)
        if (
            cover_image_relative is not None
            and cover_image_relative not in asset_relatives
        ):
            raise EpubPackageError(
                "manifest cover image must also appear in 'assets'"
            )
        package_paths = (
            *content_relatives,
            stylesheet_relative,
            *asset_relatives,
        )
        if len(set(package_paths)) != len(package_paths):
            raise EpubPackageError(
                "EPUB-ready manifest paths must not overlap"
            )

        content_sources = tuple(
            (relative, _require_file(root, relative))
            for relative in content_relatives
        )
        stylesheet_source = _require_file(root, stylesheet_relative)
        asset_sources = tuple(
            (relative, _require_file(root, relative))
            for relative in asset_relatives
        )
        semantic_payload = _load_json_object(root / "semantic" / "document.json")
        toc_entries = _collect_toc_entries(semantic_payload)
        content_id_index = _content_id_index(content_sources)
        resolved_toc_entries = _resolve_toc_entries(
            toc_entries,
            content_id_index=content_id_index,
        )

        resolved_identifier = identifier or _derive_identifier(
            root=root,
            metadata=metadata,
            language=language,
            content_relatives=content_relatives,
            stylesheet_relative=stylesheet_relative,
            asset_relatives=asset_relatives,
        )
        if not resolved_identifier.strip():
            raise EpubPackageError("publication identifier must not be empty")
        resolved_modified = _normalize_modified(modified)

        package_items, spine_item_ids = _build_manifest_items(
            content_relatives=content_relatives,
            stylesheet_relative=stylesheet_relative,
            asset_relatives=asset_relatives,
            cover_content_relative=cover_content_relative,
            cover_image_relative=cover_image_relative,
        )
        package_opf = _render_package_opf(
            metadata=metadata,
            language=language,
            identifier=resolved_identifier,
            modified=resolved_modified,
            items=package_items,
            spine_item_ids=spine_item_ids,
        )
        default_content = next(
            (
                relative
                for relative in content_relatives
                if relative != cover_content_relative
                and relative != endnotes_relative
            ),
            content_relatives[0],
        )
        nav_xhtml = _render_nav_xhtml(
            title=title,
            language=language,
            default_content=default_content,
            cover_content=cover_content_relative,
            endnotes_content=endnotes_relative,
            entries=resolved_toc_entries,
        )
        container_xml = _render_container_xml()

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            with zipfile.ZipFile(temporary, "w") as archive:
                _write_zip_bytes(
                    archive,
                    "mimetype",
                    _EPUB_MIMETYPE,
                    compression=zipfile.ZIP_STORED,
                )
                _write_zip_text(
                    archive,
                    "META-INF/container.xml",
                    container_xml,
                )
                _write_zip_text(archive, "EPUB/package.opf", package_opf)
                _write_zip_text(archive, "EPUB/nav.xhtml", nav_xhtml)
                for relative, source in content_sources:
                    _write_zip_bytes(
                        archive,
                        f"EPUB/{relative.as_posix()}",
                        source.read_bytes(),
                    )
                _write_zip_bytes(
                    archive,
                    f"EPUB/{stylesheet_relative.as_posix()}",
                    stylesheet_source.read_bytes(),
                )
                for relative, source in asset_sources:
                    _write_zip_bytes(
                        archive,
                        f"EPUB/{relative.as_posix()}",
                        source.read_bytes(),
                    )
            _validate_epub_archive(temporary)
            temporary.replace(destination)
        except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            temporary.unlink(missing_ok=True)
            raise EpubPackageError(f"EPUB package build failed: {exc}") from exc
        except EpubPackageError:
            temporary.unlink(missing_ok=True)
            raise

        return EpubPackageResult(
            epub_path=destination,
            identifier=resolved_identifier,
            modified=resolved_modified,
            manifest_item_count=len(package_items) + 1,
            toc_entry_count=len(toc_entries),
        )


def _load_json_object(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object with packaging-specific errors."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EpubPackageError(f"missing EPUB-ready artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EpubPackageError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise EpubPackageError(f"JSON artifact must be an object: {path}")
    return payload


def _required_nonempty_string(payload: dict[str, Any], key: str) -> str:
    """Return one required non-empty string field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EpubPackageError(f"manifest field {key!r} must be a non-empty string")
    return value.strip()


def _optional_nonempty_string(
    payload: dict[str, Any], key: str
) -> str | None:
    """Return one optional non-empty string field."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EpubPackageError(
            f"manifest field {key!r} must be null or a non-empty string"
        )
    return value.strip()


def _manifest_metadata(payload: dict[str, Any]) -> BookMetadata:
    """Load rich metadata while remaining compatible with legacy manifests."""
    value = payload.get("metadata")
    if value is None:
        legacy = {
            "title": _required_nonempty_string(payload, "title"),
            "language": _optional_nonempty_string(payload, "language"),
            "authors": (
                [_optional_nonempty_string(payload, "author")]
                if _optional_nonempty_string(payload, "author") is not None
                else []
            ),
        }
        try:
            return book_metadata_from_dict(legacy)
        except BookMetadataError as exc:
            raise EpubPackageError(str(exc)) from exc
    if not isinstance(value, dict):
        raise EpubPackageError("manifest field 'metadata' must be an object")
    try:
        metadata = book_metadata_from_dict(value)
    except BookMetadataError as exc:
        raise EpubPackageError(str(exc)) from exc
    if metadata.title is None:
        raise EpubPackageError("manifest metadata title must not be empty")
    return metadata


def _manifest_cover_paths(
    payload: dict[str, Any],
    *,
    content_relatives: tuple[PurePosixPath, ...],
) -> tuple[PurePosixPath | None, PurePosixPath | None]:
    """Load optional cover image/content paths from the ready manifest."""
    value = payload.get("cover")
    if value is None:
        return None, None
    if not isinstance(value, dict):
        raise EpubPackageError("manifest field 'cover' must be null or an object")
    image = value.get("image")
    content = value.get("content")
    if not isinstance(image, str) or not image.strip():
        raise EpubPackageError("manifest cover image must be a non-empty string")
    if not isinstance(content, str) or not content.strip():
        raise EpubPackageError("manifest cover content must be a non-empty string")
    image_relative = _safe_relative_path(image)
    content_relative = _safe_relative_path(content)
    if content_relative not in content_relatives:
        raise EpubPackageError(
            "manifest cover content must also appear in 'contents'"
        )
    return image_relative, content_relative


def _manifest_content_paths(payload: dict[str, Any]) -> tuple[PurePosixPath, ...]:
    """Load ordered XHTML spine paths from an EPUB-ready manifest."""
    values = payload.get("contents")
    if values is None:
        return (
            _safe_relative_path(_required_nonempty_string(payload, "content")),
        )
    if not isinstance(values, list) or not values:
        raise EpubPackageError(
            "manifest field 'contents' must be a non-empty list"
        )
    result: list[PurePosixPath] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise EpubPackageError(
                "manifest contents must be non-empty strings"
            )
        result.append(_safe_relative_path(value))
    if len(set(result)) != len(result):
        raise EpubPackageError("manifest contents must not contain duplicates")
    return tuple(result)


def _manifest_endnotes_path(
    payload: dict[str, Any],
    *,
    content_relatives: tuple[PurePosixPath, ...],
) -> PurePosixPath | None:
    """Load an optional dedicated endnotes XHTML path from the manifest."""
    value = payload.get("endnotes")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EpubPackageError(
            "manifest field 'endnotes' must be null or a non-empty string"
        )
    relative = _safe_relative_path(value)
    if relative not in content_relatives:
        raise EpubPackageError(
            "manifest endnotes path must also appear in 'contents'"
        )
    return relative


def _manifest_asset_paths(payload: dict[str, Any]) -> tuple[PurePosixPath, ...]:
    """Load and validate persisted asset paths from an EPUB-ready manifest."""
    values = payload.get("assets")
    if not isinstance(values, list):
        raise EpubPackageError("manifest field 'assets' must be a list")
    result: list[PurePosixPath] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise EpubPackageError("manifest assets must be non-empty strings")
        result.append(_safe_relative_path(value))
    if len(set(result)) != len(result):
        raise EpubPackageError("manifest assets must not contain duplicates")
    return tuple(result)


def _safe_relative_path(value: str) -> PurePosixPath:
    """Validate one package-relative POSIX path."""
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts:
        raise EpubPackageError(f"unsafe EPUB-ready path: {value!r}")
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise EpubPackageError(f"unsafe EPUB-ready path: {value!r}")
    return relative


def _require_file(root: Path, relative: PurePosixPath) -> Path:
    """Resolve one safe source file beneath an EPUB-ready root."""
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise EpubPackageError(
            f"EPUB-ready artifact escapes root: {relative.as_posix()}"
        ) from exc
    if not candidate.is_file():
        raise EpubPackageError(f"missing EPUB-ready artifact: {candidate}")
    return candidate


def _collect_toc_entries(payload: dict[str, Any]) -> tuple[EpubTocEntry, ...]:
    """Collect a flat TOC from semantic heading nodes in document order."""
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        raise EpubPackageError("semantic document field 'nodes' must be a list")
    entries: list[EpubTocEntry] = []
    _collect_heading_nodes(nodes, entries)
    return tuple(entries)


def _collect_heading_nodes(
    nodes: list[Any], entries: list[EpubTocEntry]
) -> None:
    """Recursively collect heading nodes from semantic containers."""
    for node in nodes:
        if not isinstance(node, dict):
            raise EpubPackageError("semantic document nodes must be objects")
        node_type = node.get("type")
        if node_type == "heading":
            node_id = node.get("node_id")
            content = node.get("content")
            role = node.get("role")
            if not isinstance(node_id, str) or not node_id:
                raise EpubPackageError("semantic heading has invalid node_id")
            if not isinstance(role, str):
                raise EpubPackageError("semantic heading has invalid role")
            if _heading_role_is_navigable(role):
                label = _semantic_navigation_text(content).strip()
                if label:
                    entries.append(EpubTocEntry(label=label, target_id=node_id))
        children = node.get("children")
        if children is not None:
            if not isinstance(children, list):
                raise EpubPackageError(
                    "semantic container children must be a list"
                )
            _collect_heading_nodes(children, entries)


def _heading_role_is_navigable(role: str) -> bool:
    """Return whether one semantic heading role belongs in the EPUB TOC.

    Supporting labels such as subtitles are rendered in the reading flow but do not
    represent navigation hierarchy by themselves.
    """
    return role not in {"chapter_label", "subtitle", "genre_label"}


def _semantic_navigation_text(value: Any) -> str:
    """Flatten heading text for navigation while omitting footnote references."""
    if not isinstance(value, list):
        raise EpubPackageError("semantic text content must be a list")
    parts: list[str] = []
    omitted_reference = False
    for inline in value:
        if not isinstance(inline, dict):
            raise EpubPackageError("semantic inline values must be objects")
        text = inline.get("text")
        role = inline.get("role")
        if not isinstance(text, str):
            raise EpubPackageError("semantic inline text must be a string")
        if not isinstance(role, str):
            raise EpubPackageError("semantic inline role must be a string")
        if role == "footnote_ref":
            omitted_reference = bool(text.strip()) or omitted_reference
            continue
        if omitted_reference and parts and _needs_navigation_separator(parts[-1], text):
            parts.append(" ")
        parts.append(text)
        omitted_reference = False
    return "".join(parts)


def _needs_navigation_separator(previous: str, current: str) -> bool:
    """Return whether text split by an omitted noteref needs a readable space."""
    if not previous or not current:
        return False
    if previous[-1].isspace() or current[0].isspace():
        return False
    if current[0] in ",.;:!?)]}»”’":
        return False
    if previous[-1] in "([{«“‘/-":
        return False
    return True


def _content_id_index(
    content_sources: tuple[tuple[PurePosixPath, Path], ...],
) -> dict[str, PurePosixPath]:
    """Map rendered XHTML IDs to their owning spine document."""
    result: dict[str, PurePosixPath] = {}
    for relative, source in content_sources:
        try:
            root = ElementTree.fromstring(source.read_bytes())
        except ElementTree.ParseError as exc:
            raise EpubPackageError(
                f"invalid XHTML artifact: {relative.as_posix()}"
            ) from exc
        for element in root.iter():
            element_id = element.get("id")
            if element_id is None:
                continue
            existing = result.get(element_id)
            if existing is not None and existing != relative:
                raise EpubPackageError(
                    f"duplicate XHTML id across content documents: {element_id}"
                )
            result[element_id] = relative
    return result


def _resolve_toc_entries(
    entries: tuple[EpubTocEntry, ...],
    *,
    content_id_index: dict[str, PurePosixPath],
) -> tuple[_ResolvedTocEntry, ...]:
    """Bind semantic TOC targets to rendered XHTML documents."""
    resolved: list[_ResolvedTocEntry] = []
    for entry in entries:
        content_relative = content_id_index.get(entry.target_id)
        if content_relative is None:
            raise EpubPackageError(
                f"navigation target is not rendered: {entry.target_id}"
            )
        resolved.append(
            _ResolvedTocEntry(
                label=entry.label,
                target_id=entry.target_id,
                content_relative=content_relative,
            )
        )
    if not resolved:
        return ()
    return tuple(resolved)


def _derive_identifier(
    *,
    root: Path,
    metadata: BookMetadata,
    language: str,
    content_relatives: tuple[PurePosixPath, ...],
    stylesheet_relative: PurePosixPath,
    asset_relatives: tuple[PurePosixPath, ...],
) -> str:
    """Derive a stable UUID URN from publication metadata and content bytes."""
    digest = hashlib.sha256()
    metadata_payload = book_metadata_to_dict(metadata)
    metadata_payload["language"] = language
    digest.update(
        json.dumps(
            metadata_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\0")
    for relative in (
        *content_relatives,
        stylesheet_relative,
        *sorted(asset_relatives, key=lambda item: item.as_posix()),
    ):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_require_file(root, relative).read_bytes())
        digest.update(b"\0")
    stable_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"siftforge:{digest.hexdigest()}")
    return f"urn:uuid:{stable_uuid}"


def _normalize_modified(value: str | None) -> str:
    """Return an EPUB 3 UTC modification timestamp."""
    if value is None:
        return datetime.now(UTC).replace(microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    if not _MODIFIED_PATTERN.fullmatch(value):
        raise EpubPackageError(
            "modified must use UTC format YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise EpubPackageError(f"invalid modified timestamp: {value}") from exc
    return value


@dataclass(frozen=True, slots=True)
class _ManifestItem:
    """One OPF manifest item relative to ``EPUB/package.opf``."""

    item_id: str
    href: str
    media_type: str
    properties: tuple[str, ...] = ()


def _build_manifest_items(
    *,
    content_relatives: tuple[PurePosixPath, ...],
    stylesheet_relative: PurePosixPath,
    asset_relatives: tuple[PurePosixPath, ...],
    cover_content_relative: PurePosixPath | None,
    cover_image_relative: PurePosixPath | None,
) -> tuple[tuple[_ManifestItem, ...], tuple[str, ...]]:
    """Build deterministic OPF items and ordered spine item IDs."""
    items: list[_ManifestItem] = []
    spine_ids: list[str] = []
    body_index = 0
    body_count = len(content_relatives) - int(cover_content_relative is not None)
    for relative in content_relatives:
        if relative == cover_content_relative:
            item_id = "cover"
        else:
            body_index += 1
            item_id = (
                f"content-{body_index:04d}" if body_count > 1 else "content"
            )
        items.append(
            _ManifestItem(
                item_id=item_id,
                href=relative.as_posix(),
                media_type="application/xhtml+xml",
            )
        )
        spine_ids.append(item_id)
    items.append(
        _ManifestItem(
            item_id="css",
            href=stylesheet_relative.as_posix(),
            media_type="text/css",
        )
    )
    asset_index = 0
    for relative in sorted(asset_relatives, key=lambda item: item.as_posix()):
        if relative == cover_image_relative:
            item_id = "cover-image"
            properties = ("cover-image",)
        else:
            asset_index += 1
            item_id = f"asset-{asset_index:04d}"
            properties = ()
        items.append(
            _ManifestItem(
                item_id=item_id,
                href=relative.as_posix(),
                media_type=_asset_media_type(relative),
                properties=properties,
            )
        )
    return tuple(items), tuple(spine_ids)


def _asset_media_type(relative: PurePosixPath) -> str:
    """Return an EPUB-compatible media type for one referenced asset."""
    suffix = relative.suffix.lower()
    types = {
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".svg": "image/svg+xml",
    }
    try:
        return types[suffix]
    except KeyError as exc:
        raise EpubPackageError(
            f"unsupported EPUB asset type: {relative.as_posix()}"
        ) from exc


def _isbn_identifier(value: str) -> str:
    """Return an ISBN value in canonical EPUB identifier form."""
    cleaned = value.strip()
    if cleaned.lower().startswith("urn:isbn:"):
        return cleaned
    return f"urn:isbn:{cleaned}"


def _render_container_xml() -> str:
    """Render the mandatory EPUB container document."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        '    <rootfile full-path="EPUB/package.opf" '
        'media-type="application/oebps-package+xml" />\n'
        "  </rootfiles>\n"
        "</container>\n"
    )


def _render_package_opf(
    *,
    metadata: BookMetadata,
    language: str,
    identifier: str,
    modified: str,
    items: tuple[_ManifestItem, ...],
    spine_item_ids: tuple[str, ...],
) -> str:
    """Render an EPUB 3 package document with rich publication metadata."""
    if metadata.title is None:
        raise EpubPackageError("publication title must not be empty")
    metadata_lines = [
        f'    <dc:identifier id="pub-id">{_text(identifier)}</dc:identifier>',
        f'    <dc:title id="main-title">{_text(metadata.title)}</dc:title>',
        '    <meta refines="#main-title" property="title-type">main</meta>',
        f"    <dc:language>{_text(language)}</dc:language>",
    ]
    if metadata.subtitle is not None:
        metadata_lines.extend(
            [
                f'    <dc:title id="subtitle">{_text(metadata.subtitle)}</dc:title>',
                '    <meta refines="#subtitle" property="title-type">subtitle</meta>',
            ]
        )
    for index, author in enumerate(metadata.authors, start=1):
        metadata_lines.append(
            f'    <dc:creator id="creator-{index}">{_text(author)}</dc:creator>'
        )
    for contributor in metadata.contributors:
        metadata_lines.append(
            f"    <dc:contributor>{_text(contributor)}</dc:contributor>"
        )
    if metadata.publisher is not None:
        metadata_lines.append(
            f"    <dc:publisher>{_text(metadata.publisher)}</dc:publisher>"
        )
    if metadata.publication_date is not None:
        metadata_lines.append(
            f"    <dc:date>{_text(metadata.publication_date)}</dc:date>"
        )
    if metadata.isbn is not None:
        metadata_lines.append(
            "    <dc:identifier>"
            f"{_text(_isbn_identifier(metadata.isbn))}</dc:identifier>"
        )
    if metadata.description is not None:
        metadata_lines.append(
            f"    <dc:description>{_text(metadata.description)}</dc:description>"
        )
    for subject in metadata.subjects:
        metadata_lines.append(f"    <dc:subject>{_text(subject)}</dc:subject>")
    if metadata.rights is not None:
        metadata_lines.append(f"    <dc:rights>{_text(metadata.rights)}</dc:rights>")
    if metadata.series is not None:
        metadata_lines.extend(
            [
                '    <meta property="belongs-to-collection" id="series">'
                f"{_text(metadata.series)}</meta>",
                '    <meta refines="#series" property="collection-type">series</meta>',
            ]
        )
        if metadata.series_index is not None:
            metadata_lines.append(
                '    <meta refines="#series" property="group-position">'
                f"{_text(metadata.series_index)}</meta>"
            )
    metadata_lines.append(
        f'    <meta property="dcterms:modified">{_text(modified)}</meta>'
    )

    manifest_lines = [
        '    <item id="nav" href="nav.xhtml" '
        'media-type="application/xhtml+xml" properties="nav" />'
    ]
    for item in items:
        properties = (
            f' properties="{_attr(" ".join(item.properties))}"'
            if item.properties
            else ""
        )
        manifest_lines.append(
            f'    <item id="{_attr(item.item_id)}" href="{_attr(item.href)}" '
            f'media-type="{_attr(item.media_type)}"{properties} />'
        )
    spine_lines = [
        f'    <itemref idref="{_attr(item_id)}" />'
        for item_id in spine_item_ids
    ]
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" '
        'version="3.0" unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(metadata_lines)
        + "\n  </metadata>\n"
        + "  <manifest>\n"
        + "\n".join(manifest_lines)
        + "\n  </manifest>\n"
        + "  <spine>\n"
        + "\n".join(spine_lines)
        + "\n  </spine>\n"
        + "</package>\n"
    )


def _render_nav_xhtml(
    *,
    title: str,
    language: str,
    default_content: PurePosixPath,
    cover_content: PurePosixPath | None,
    endnotes_content: PurePosixPath | None,
    entries: tuple[_ResolvedTocEntry, ...],
) -> str:
    """Render EPUB 3 TOC plus semantic landmarks navigation."""
    items: list[str] = []
    if entries:
        for entry in entries:
            href = f"{entry.content_relative.as_posix()}#{entry.target_id}"
            items.append(
                f'        <li><a href="{_attr(href)}">'
                f"{_text(entry.label)}</a></li>"
            )
    else:
        items.append(
            f'        <li><a href="{_attr(default_content.as_posix())}">'
            f"{_text(title)}</a></li>"
        )

    landmarks: list[str] = []
    if cover_content is not None:
        landmarks.append(
            '        <li><a epub:type="cover" '
            f'href="{_attr(cover_content.as_posix())}">Cover</a></li>'
        )
    landmarks.append(
        '        <li><a epub:type="bodymatter" '
        f'href="{_attr(default_content.as_posix())}">Start of Content</a></li>'
    )
    if endnotes_content is not None:
        endnotes_href = f"{endnotes_content.as_posix()}#endnotes"
        landmarks.append(
            '        <li><a epub:type="endnotes" '
            f'href="{_attr(endnotes_href)}">Notes</a></li>'
        )

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'lang="{_attr(language)}" xml:lang="{_attr(language)}">\n'
        "  <head>\n"
        '    <meta charset="utf-8" />\n'
        f"    <title>{_text(title)}</title>\n"
        "  </head>\n"
        "  <body>\n"
        '    <nav epub:type="toc" id="toc">\n'
        f"      <h1>{_text(title)}</h1>\n"
        "      <ol>\n"
        + "\n".join(items)
        + "\n      </ol>\n"
        + "    </nav>\n"
        + '    <nav epub:type="landmarks" id="landmarks">\n'
        + "      <h2>Landmarks</h2>\n"
        + "      <ol>\n"
        + "\n".join(landmarks)
        + "\n      </ol>\n"
        + "    </nav>\n"
        + "  </body>\n"
        + "</html>\n"
    )


def _write_zip_text(
    archive: zipfile.ZipFile,
    member: str,
    text: str,
) -> None:
    """Write one UTF-8 text member with stable archive metadata."""
    _write_zip_bytes(archive, member, text.encode("utf-8"))


def _write_zip_bytes(
    archive: zipfile.ZipFile,
    member: str,
    data: bytes,
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> None:
    """Write one EPUB archive member with deterministic ZIP metadata."""
    info = zipfile.ZipInfo(member, date_time=_FIXED_ZIP_TIMESTAMP)
    info.compress_type = compression
    info.create_system = 0
    info.external_attr = 0o600 << 16
    archive.writestr(info, data)


def _validate_epub_archive(path: Path) -> None:
    """Perform deterministic structural and internal-link checks."""
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if not infos or infos[0].filename != "mimetype":
                raise EpubPackageError(
                    "EPUB mimetype must be the first ZIP member"
                )
            if infos[0].compress_type != zipfile.ZIP_STORED:
                raise EpubPackageError(
                    "EPUB mimetype must be stored uncompressed"
                )
            if archive.read("mimetype") != _EPUB_MIMETYPE:
                raise EpubPackageError("EPUB mimetype content is invalid")
            names = {info.filename for info in infos}
            required = {
                "META-INF/container.xml",
                "EPUB/package.opf",
                "EPUB/nav.xhtml",
            }
            missing = sorted(required - names)
            if missing:
                raise EpubPackageError(
                    f"EPUB archive is missing required members: {missing}"
                )
            for name in names:
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts:
                    raise EpubPackageError(f"unsafe EPUB member path: {name}")

            container = ElementTree.fromstring(
                archive.read("META-INF/container.xml")
            )
            rootfile = container.find(
                ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
            )
            if (
                rootfile is None
                or rootfile.get("full-path") != "EPUB/package.opf"
            ):
                raise EpubPackageError(
                    "container.xml does not reference package.opf"
                )

            package = ElementTree.fromstring(archive.read("EPUB/package.opf"))
            namespace = {"opf": "http://www.idpf.org/2007/opf"}
            manifest_items = package.findall(
                ".//opf:manifest/opf:item", namespace
            )
            manifest_by_id: dict[str, str] = {}
            for item in manifest_items:
                item_id = item.get("id")
                href = item.get("href")
                if item_id is None or href is None:
                    raise EpubPackageError(
                        "OPF manifest item is missing id or href"
                    )
                member = f"EPUB/{href}"
                if member not in names:
                    raise EpubPackageError(
                        f"OPF manifest references missing member: {member}"
                    )
                manifest_by_id[item_id] = href

            spine = package.findall(".//opf:spine/opf:itemref", namespace)
            if not spine:
                raise EpubPackageError("OPF spine must not be empty")
            content_hrefs: list[str] = []
            for itemref in spine:
                item_id = itemref.get("idref")
                if item_id is None or item_id not in manifest_by_id:
                    raise EpubPackageError(
                        "OPF spine references an unknown manifest item"
                    )
                content_hrefs.append(manifest_by_id[item_id])

            ids_by_content: dict[str, set[str]] = {}
            roots_by_content: dict[str, ElementTree.Element] = {}
            for href in content_hrefs:
                root = ElementTree.fromstring(archive.read(f"EPUB/{href}"))
                roots_by_content[href] = root
                ids_by_content[href] = {
                    element_id
                    for element in root.iter()
                    if (element_id := element.get("id")) is not None
                }

            nav = ElementTree.fromstring(archive.read("EPUB/nav.xhtml"))
            xhtml = {"xhtml": "http://www.w3.org/1999/xhtml"}
            for anchor in nav.findall(".//xhtml:a", xhtml):
                href = anchor.get("href")
                if href is None:
                    raise EpubPackageError("navigation anchor has no href")
                _validate_internal_href(
                    source_href="nav.xhtml",
                    href=href,
                    ids_by_content=ids_by_content,
                    require_content_target=True,
                )

            for source_href, root in roots_by_content.items():
                for anchor in root.findall(".//xhtml:a", xhtml):
                    href = anchor.get("href")
                    if href is None:
                        raise EpubPackageError(
                            f"content anchor has no href: {source_href}"
                        )
                    if _is_external_href(href):
                        continue
                    _validate_internal_href(
                        source_href=source_href,
                        href=href,
                        ids_by_content=ids_by_content,
                        require_content_target=False,
                    )
    except KeyError as exc:
        raise EpubPackageError(f"EPUB member is missing: {exc}") from exc


def _is_external_href(href: str) -> bool:
    """Return whether an XHTML hyperlink points outside the EPUB package."""
    lowered = href.lower()
    return lowered.startswith(("http:", "https:", "mailto:", "tel:"))


def _validate_internal_href(
    *,
    source_href: str,
    href: str,
    ids_by_content: dict[str, set[str]],
    require_content_target: bool,
) -> None:
    """Validate one relative XHTML link and optional fragment target."""
    target_path_text, separator, fragment = href.partition("#")
    source = PurePosixPath(source_href)
    if target_path_text:
        target = source.parent / PurePosixPath(target_path_text)
    else:
        target = source
    if target.is_absolute() or ".." in target.parts:
        raise EpubPackageError(f"unsafe internal EPUB link: {href}")
    target_href = target.as_posix()
    if require_content_target and target_href not in ids_by_content:
        raise EpubPackageError(
            f"navigation target document is not in spine: {target_href}"
        )
    if not separator:
        if require_content_target and target_href not in ids_by_content:
            raise EpubPackageError(
                f"navigation target document is not in spine: {target_href}"
            )
        return
    if target_href not in ids_by_content:
        raise EpubPackageError(
            f"internal link target document is not in spine: {target_href}"
        )
    if fragment not in ids_by_content[target_href]:
        raise EpubPackageError(
            f"internal link target does not exist: {target_href}#{fragment}"
        )


def _text(value: str) -> str:
    """Escape XML element text."""
    return html.escape(value, quote=False)


def _attr(value: str) -> str:
    """Escape XML attribute text."""
    return html.escape(value, quote=True)
