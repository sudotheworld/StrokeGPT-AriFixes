"""Image generation service utilities.

This module provides the :class:`ImageService` which coordinates image
requests to a remote API and persists the returned images to disk.  The
service keeps a gallery index on disk so the UI can show recently
generated images without re-reading the filesystem every time.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests


@dataclass(slots=True)
class GalleryEntry:
    """Metadata describing a generated image."""

    filename: str
    prompt: str
    metadata: Dict[str, Any]


class ImageService:
    """Generate and persist images returned by a remote API.

    Parameters
    ----------
    output_dir:
        Directory where image files are persisted.  Created on demand.
    index_file:
        JSON file that stores the gallery metadata.  Defaults to
        ``<output_dir>/index.json`` if not supplied.
    session_factory:
        Callable returning a fresh :class:`requests.Session`.  A new
        session is lazily constructed per worker thread to avoid
        cross-thread reuse which is not supported by ``requests``.
    uuid_factory:
        Callable returning a UUID.  Primarily useful for deterministic
        testing when a predictable filename is required.
    """

    def __init__(
        self,
        output_dir: str | Path = "generated_images",
        index_file: str | Path | None = None,
        *,
        session_factory: Callable[[], requests.Session] | None = None,
        uuid_factory: Callable[[], uuid.UUID] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = Path(index_file) if index_file else self.output_dir / "index.json"

        self._gallery: List[GalleryEntry] = []
        self._gallery_lock = threading.Lock()

        self._uuid_factory = uuid_factory or uuid.uuid4
        self._session_factory = session_factory or requests.Session
        self._session_local = threading.local()

        self._load_gallery()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load_gallery(self) -> None:
        """Populate ``_gallery`` from the JSON index if it exists."""

        try:
            if not self.index_file.exists():
                return
            with open(self.index_file, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, Iterable):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    filename = item.get("filename")
                    prompt = item.get("prompt", "")
                    metadata = {k: v for k, v in item.items() if k not in {"filename", "prompt"}}
                    if filename:
                        self._gallery.append(GalleryEntry(filename, prompt, metadata))
        except Exception:
            # Corrupt index files should not crash the service; start with
            # an empty gallery instead.
            self._gallery.clear()

    def _write_gallery_index_locked(self) -> None:
        """Write the gallery index to disk.

        Callers *must* hold ``_gallery_lock`` while invoking this method.
        Using a temporary file avoids partially written JSON if the
        process crashes mid-write.
        """

        tmp_path = self.index_file.with_suffix(self.index_file.suffix + ".tmp")
        payload = [
            {"filename": entry.filename, "prompt": entry.prompt, **entry.metadata}
            for entry in self._gallery
        ]
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.index_file)

    def _generate_filename_locked(self, suffix: str = ".png") -> str:
        """Return a collision-resistant filename for a new image."""

        suffix = suffix if suffix.startswith(".") else f".{suffix}"
        while True:
            candidate = f"{self._uuid_factory().hex}{suffix}"
            if not (self.output_dir / candidate).exists():
                return candidate

    def _get_session(self) -> requests.Session:
        """Return the thread-local :class:`requests.Session`."""

        session = getattr(self._session_local, "session", None)
        if session is None:
            session = self._session_factory()
            self._session_local.session = session
        return session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_gallery(self) -> List[GalleryEntry]:
        """Return a copy of the gallery metadata."""

        with self._gallery_lock:
            return list(self._gallery)

    def clear_gallery(self) -> None:
        """Remove all gallery entries and delete stored images."""

        with self._gallery_lock:
            for entry in self._gallery:
                try:
                    (self.output_dir / entry.filename).unlink(missing_ok=True)
                except Exception:
                    pass
            self._gallery.clear()
            if self.index_file.exists():
                try:
                    self.index_file.unlink()
                except Exception:
                    pass

    def save_image_bytes(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        suffix: str = ".png",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GalleryEntry:
        """Persist ``image_bytes`` and append a gallery entry.

        The filename generation, gallery mutation, and index write are
        all performed while holding ``_gallery_lock`` to guarantee
        thread-safety when multiple workers finish at the same time.
        """

        if not isinstance(image_bytes, (bytes, bytearray)):
            raise TypeError("image_bytes must be bytes-like")

        with self._gallery_lock:
            filename = self._generate_filename_locked(suffix)
            path = self.output_dir / filename
            path.write_bytes(bytes(image_bytes))

            entry = GalleryEntry(filename=filename, prompt=prompt, metadata=metadata or {})
            self._gallery.append(entry)
            self._write_gallery_index_locked()
        return entry

    def save_image_base64(
        self,
        image_b64: str,
        prompt: str,
        *,
        suffix: str = ".png",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GalleryEntry:
        """Decode a base64 string and persist the resulting image."""

        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception as exc:  # pragma: no cover - defensive branch
            raise ValueError("Invalid base64 image payload") from exc
        return self.save_image_bytes(image_bytes, prompt, suffix=suffix, metadata=metadata)

    def request_image(
        self,
        url: str,
        payload: Dict[str, Any],
        *,
        prompt: str,
        suffix: str = ".png",
        metadata: Optional[Dict[str, Any]] = None,
        timeout: tuple[float, float] | float | None = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> GalleryEntry:
        """Send ``payload`` to ``url`` and store the returned image.

        The response is expected to be JSON with an ``"image"`` field
        containing base64 encoded image data.  Worker threads obtain a
        dedicated ``requests.Session`` by calling ``_get_session`` which
        ensures thread-local connections.

        Parameters
        ----------
        timeout:
            Optional timeout forwarded to :meth:`requests.Session.post`.
        headers:
            Optional mapping of HTTP headers included with the request.
            This allows callers to provide bearer tokens or custom auth
            headers required by remote services.
        """

        session = self._get_session()
        response = session.post(url, json=payload, timeout=timeout, headers=headers)
        response.raise_for_status()
        data = response.json()
        image_b64 = data.get("image")
        if not isinstance(image_b64, str):
            raise ValueError("Response missing base64 image data")

        combined_metadata = dict(metadata or {})
        combined_metadata.setdefault("response", data)
        return self.save_image_base64(image_b64, prompt, suffix=suffix, metadata=combined_metadata)


__all__ = ["ImageService", "GalleryEntry"]
