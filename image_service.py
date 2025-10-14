from __future__ import annotations

from pathlib import Path
from typing import Union


class ImageService:
    """Utility class for working with generated image files.

    The service keeps track of a gallery directory and exposes helpers to
    resolve file paths within it safely.
    """

    def __init__(self, gallery_root: Union[str, Path] = Path("generated_images")) -> None:
        self._gallery_root = Path(gallery_root)

    @property
    def gallery_root(self) -> Path:
        """Return the root directory for generated images."""
        return self._gallery_root

    def _is_relative_to(self, path: Path, other: Path) -> bool:
        """Return True if *path* is within *other*, supporting Python < 3.9."""
        if hasattr(path, "is_relative_to"):
            return path.is_relative_to(other)  # type: ignore[attr-defined]
        try:
            path.relative_to(other)
            return True
        except ValueError:
            return False

    def ensure_within_gallery(self, path: Path) -> Path:
        """Ensure *path* is located within the gallery root.

        Raises ``ValueError`` if the resolved path escapes the gallery directory.
        """
        root = self._gallery_root.resolve()
        if not self._is_relative_to(path, root):
            raise ValueError("Path escapes generated images gallery")
        return path

    def get_image_path(self, relative_path: str) -> Path:
        """Return a resolved path for *relative_path* within the gallery.

        The method rejects absolute paths or traversal attempts that would escape
        the configured gallery directory.
        """
        if not relative_path:
            raise ValueError("Empty path is not allowed")
        rel_path = Path(relative_path)
        if rel_path.is_absolute():
            raise ValueError("Absolute paths are not allowed")
        candidate = (self._gallery_root / rel_path).resolve(strict=False)
        return self.ensure_within_gallery(candidate)

    def is_within_gallery(self, path: Path) -> bool:
        """Return True if *path* resides within the gallery directory."""
        try:
            self.ensure_within_gallery(path)
        except ValueError:
            return False
        return True
