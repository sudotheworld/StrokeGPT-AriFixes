import os
from dataclasses import dataclass

# Attempt to import python-dotenv. If it's unavailable, define a no-op loader
try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    def load_dotenv(path: str | None = None):
        """Simple fallback to read key=value pairs from a .env file into os.environ.

        This will only parse lines with a single '=' and skip comments/blank lines.
        """
        filename = path or ".env"
        if not os.path.exists(filename):
            return
        with open(filename) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

# Load variables from .env file if present
load_dotenv()

@dataclass
class Config:
    """Central configuration loaded from environment variables."""
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "5000"))
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3:8b-instruct-q4_K_M")
    CONNECT_TIMEOUT: float = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "5"))
    READ_TIMEOUT: float = float(os.getenv("READ_TIMEOUT_SECONDS", "180"))
    HANDY_KEY: str = os.getenv("HANDY_KEY", "")
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")