"""Pytest configuration helpers for the StrokeGPT test suite."""

import os
import sys
from pathlib import Path

# Ensure the project root is importable when invoking ``pytest`` directly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Optionally load environment overrides from a local .env file so tests run
# with the same defaults as the application without requiring extra setup.
dotenv_path = ROOT / ".env"
if dotenv_path.exists():
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
