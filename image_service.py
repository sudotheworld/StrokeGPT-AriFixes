"""Utility for generating persona portraits via an external image API."""

from __future__ import annotations

import base64
from typing import Any, Dict

import requests
from requests.adapters import HTTPAdapter, Retry

from config import Config


def _create_session() -> requests.Session:
    """Create a shared requests session with retry behaviour."""

    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


class ImageService:
    """Simple wrapper around a text-to-image HTTP API."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self._session = session or _create_session()
        self.api_key = api_key or Config.IMAGE_API_KEY
        self.endpoint = endpoint or Config.IMAGE_API_URL
        self.model = model or Config.IMAGE_MODEL

    def set_api_key(self, api_key: str | None) -> bool:
        """Update the API key used for future requests."""

        self.api_key = api_key or ""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def generate_persona_image(self, traits: Dict[str, str]) -> str:
        """Generate a base64 image given persona traits.

        Raises
        ------
        ValueError
            If the service is not configured correctly or the API returns an
            unexpected response.
        """

        if not self.endpoint:
            raise ValueError("Image generation endpoint is not configured.")
        if not self.api_key and not Config.IMAGE_API_KEY:
            raise ValueError("Image API key is missing. Provide one in settings.")

        prompt = self._build_prompt(traits)
        headers = {
            "Authorization": f"Bearer {self.api_key or Config.IMAGE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "size": Config.IMAGE_SIZE,
            "response_format": "b64_json",
            "n": 1,
        }

        try:
            response = self._session.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=(Config.CONNECT_TIMEOUT, Config.READ_TIMEOUT),
            )
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise ValueError(f"Image API request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError("Image API returned invalid JSON.") from exc

        images = data.get("data")
        if not images:
            message = data.get("error") or "Image API returned no data."
            raise ValueError(message)

        b64_value = images[0].get("b64_json") if isinstance(images, list) else None
        if not b64_value:
            raise ValueError("Image API response missing base64 payload.")

        # Normalise to a str in case bytes are returned.
        if isinstance(b64_value, bytes):
            b64_value = b64_value.decode("utf-8")

        # Ensure the payload is valid base64; this raises if not.
        try:
            base64.b64decode(b64_value)
        except Exception as exc:
            raise ValueError("Image API returned malformed base64 data.") from exc

        return b64_value

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_prompt(self, traits: Dict[str, str]) -> str:
        """Compose a descriptive prompt for the persona portrait."""

        name = traits.get("name") or "Unnamed persona"
        role = traits.get("role")
        body_type = traits.get("body_type")
        description = traits.get("description")
        goal = traits.get("goal")

        parts = [f"Highly detailed portrait of {name}."]
        if role:
            parts.append(f"Character archetype: {role}.")
        if body_type:
            parts.append(f"Body type: {body_type.replace('-', ' ')}.")
        if description:
            parts.append(description)
        if goal:
            parts.append(f"Primary objective or vibe: {goal}.")

        parts.extend(
            [
                "Digital art, vibrant lighting, neon cyberpunk styling.",
                "Portrait orientation, upper body focus, expressive gaze.",
            ]
        )

        return " \n".join(part.strip() for part in parts if part)


__all__ = ["ImageService"]

