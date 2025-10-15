import os
from dataclasses import dataclass

"""
Central configuration loader for StrokeGPT.

This module loads configuration values from multiple sources in the following order of precedence:

1. Process environment variables (highest priority)
2. A local `.env` file in the project root (optional)
3. A user‑level secrets file stored outside the repository

The user‑level secrets file can live in `%APPDATA%/StrokeGPT/secrets.json` on Windows
or `~/.config/strokegpt/secrets.json` on Linux/macOS.  It should contain JSON with
keys like `HANDY_KEY` and `ELEVENLABS_API_KEY`.  These are only loaded if the same
keys are not already set via environment variables.
"""

# ---------------------------------------------------------------------------
# Utilities to load environment variables from a `.env` file.  We use the
# python‑dotenv package if available; otherwise we fall back to a simple parser.

def _load_dotenv_if_available() -> None:
    """Load variables from a .env file using python-dotenv or a fallback."""
    try:
        # Try to use python-dotenv if installed
        from dotenv import find_dotenv, load_dotenv  # type: ignore
        load_dotenv(find_dotenv())
    except Exception:
        # Fallback: parse a .env file in the current working directory
        path = ".env"
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    # don't override existing environment variables
                    os.environ.setdefault(key.strip(), val.strip())
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Secrets bootstrap loader

def _load_user_secrets() -> bool:
    """Attempt to load secrets from a user‑level JSON file.

    Returns True if a secrets file was found and processed, False otherwise.
    """
    import json
    import pathlib

    # Determine candidate secret file locations
    candidates = []
    if os.name == "nt":  # Windows
        appdata = os.environ.get("APPDATA") or str(pathlib.Path.home() / "AppData/Roaming")
        candidates.append(pathlib.Path(appdata) / "StrokeGPT" / "secrets.json")
    else:
        candidates.append(pathlib.Path.home() / ".config" / "strokegpt" / "secrets.json")

    for p in candidates:
        try:
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Only set known keys if they are unset in the environment
                for key in ("HANDY_KEY", "ELEVENLABS_API_KEY"):
                    val = data.get(key)
                    if val and not os.environ.get(key):
                        os.environ[key] = str(val)
                return True
        except Exception:
            # Swallow errors silently
            pass
    return False


# Immediately load .env variables and then user secrets on module import
_load_dotenv_if_available()
_load_user_secrets()


@dataclass
class Config:
    """Central configuration loaded from environment variables and defaults."""

    # Server configuration
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "5000"))

    # Ollama connection
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3:8b-instruct-q4_K_M")
    CONNECT_TIMEOUT: float = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "5"))
    READ_TIMEOUT: float = float(os.getenv("READ_TIMEOUT_SECONDS", "180"))

    # API keys
    HANDY_KEY: str = os.getenv("HANDY_KEY", "")
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")

    # Image generation defaults (SillyTavern Extras compatible)
    IMAGE_API_URL: str = os.getenv("IMAGE_API_URL", "http://127.0.0.1:5100/api/image")
    IMAGE_API_KEY: str = os.getenv("IMAGE_API_KEY", "")
    IMAGE_PROMPT_PREFIX: str = os.getenv("IMAGE_PROMPT_PREFIX", "")
    IMAGE_NEGATIVE_PROMPT: str = os.getenv("IMAGE_NEGATIVE_PROMPT", "")
    IMAGE_WIDTH: int = int(os.getenv("IMAGE_WIDTH", "512"))
    IMAGE_HEIGHT: int = int(os.getenv("IMAGE_HEIGHT", "512"))
    IMAGE_STEPS: int = int(os.getenv("IMAGE_STEPS", "30"))
    IMAGE_CFG_SCALE: float = float(os.getenv("IMAGE_CFG_SCALE", "6"))
    IMAGE_SAMPLER: str = os.getenv("IMAGE_SAMPLER", "DDIM")
    IMAGE_CLIP_SKIP: int = int(os.getenv("IMAGE_CLIP_SKIP", "1"))
    IMAGE_RESTORE_FACES: bool = os.getenv("IMAGE_RESTORE_FACES", "false").lower() in {"1", "true", "yes", "on"}
    IMAGE_WORKER_COUNT: int = int(os.getenv("IMAGE_WORKER_COUNT", "2"))
    IMAGE_REQUEST_TIMEOUT: float = float(os.getenv("IMAGE_REQUEST_TIMEOUT", "120"))

    # Optional room pin for gating the UI (empty string means no pin)
    ROOM_PIN: str = os.getenv("ROOM_PIN", "")