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
                for key in (
                    "HANDY_KEY",
                    "ELEVENLABS_API_KEY",
                    "DEVICE_TYPE",
                    "LOVENSE_TOKEN",
                    "LOVENSE_DOMAIN",
                    "LOVENSE_PORT",
                    "LOVENSE_SECURE",
                ):
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

    # Device configuration
    DEVICE_TYPE: str = os.getenv("DEVICE_TYPE", "handy").lower()
    LOVENSE_TOKEN: str = os.getenv("LOVENSE_TOKEN", "")
    LOVENSE_DOMAIN: str = os.getenv("LOVENSE_DOMAIN", "127.0.0.1")
    LOVENSE_PORT: int = int(os.getenv("LOVENSE_PORT", "20010"))
    LOVENSE_SECURE: bool = os.getenv("LOVENSE_SECURE", "false").lower() in {"1", "true", "yes"}

    # Optional room pin for gating the UI (empty string means no pin)
    ROOM_PIN: str = os.getenv("ROOM_PIN", "")