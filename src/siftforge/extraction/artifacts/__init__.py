"""Artifact-storage interfaces and local implementations."""

from .base import ArtifactStore
from .filesystem import FilesystemArtifactStore

__all__: list[str] = ["ArtifactStore", "FilesystemArtifactStore"]
