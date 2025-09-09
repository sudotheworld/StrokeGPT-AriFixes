import json
import os
import pathlib

"""Helper to load user secrets from a config file in the user's profile.

This will look for a JSON file in a platform-specific location and, if found,
load keys for HANDY_KEY and ELEVENLABS_API_KEY into os.environ (unless already set).
"""

def _user_secret_paths():
    """Return potential paths where a secrets JSON file may reside."""
    paths = []
    if os.name == "nt":
        # On Windows, prefer APPDATA\StrokeGPT\secrets.json
        appdata = os.environ.get("APPDATA") or str(pathlib.Path.home() / "AppData" / "Roaming")
        paths.append(pathlib.Path(appdata) / "StrokeGPT" / "secrets.json")
    else:
        # On Unix-like systems, use ~/.config/strokegpt/secrets.json
        paths.append(pathlib.Path.home() / ".config" / "strokegpt" / "secrets.json")
    return paths


def load_user_secrets() -> bool:
    """Load user secrets from the first existing secrets file.

    Returns True if a file was found and secrets were loaded, otherwise False.
    """
    for path in _user_secret_paths():
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Only map known keys to environment variables
                for key in ("HANDY_KEY", "ELEVENLABS_API_KEY"):
                    val = data.get(key)
                    if val and os.getenv(key) in (None, ""):
                        os.environ[key] = val
                return True
        except Exception:
            # Ignore any errors reading/parsing the secrets file
            pass
    return False