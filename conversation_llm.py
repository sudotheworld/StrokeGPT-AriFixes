"""Text-only Ollama adapter; separate from persona and motion generation."""
import requests
from config import Config


def text_reply(messages):
    response = requests.post(
        f"{Config.OLLAMA_URL.rstrip('/')}/api/chat",
        json={'model': Config.OLLAMA_MODEL, 'stream': False, 'messages': messages},
        timeout=(Config.CONNECT_TIMEOUT, Config.READ_TIMEOUT),
    )
    response.raise_for_status()
    return response.json()['message']['content']
