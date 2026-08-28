"""Tests for filesystem-backed artifact persistence."""

from pathlib import Path

import pytest

from siftforge.extraction.artifacts import FilesystemArtifactStore


def test_filesystem_artifact_store_writes_utf8_json(tmp_path: Path) -> None:
    """Artifact store should preserve Unicode and create parent directories."""
    store = FilesystemArtifactStore(tmp_path / "run")

    store.write_json(
        "normalized/page.json",
        {"text": "Tiếng Việt"},
    )

    content = (store.root / "normalized" / "page.json").read_text(
        encoding="utf-8"
    )
    assert "Tiếng Việt" in content


def test_filesystem_artifact_store_rejects_path_traversal(tmp_path: Path) -> None:
    """Artifact writes must not escape the owning run directory."""
    store = FilesystemArtifactStore(tmp_path / "run")

    with pytest.raises(ValueError):
        store.write_text("../outside.txt", "unsafe")
