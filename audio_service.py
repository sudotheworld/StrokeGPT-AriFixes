import os
import tempfile
from collections import deque
from typing import Deque, Dict, Optional, Tuple

try:  # Optional import; we handle missing ElevenLabs gracefully.
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings
except Exception:  # pragma: no cover - missing dependency paths are expected.
    ElevenLabs = None  # type: ignore
    VoiceSettings = None  # type: ignore


class LocalTTSClient:
    """Wrapper around a local/offline TTS engine (Coqui TTS by default)."""

    def __init__(self, model_name: Optional[str] = None, speaker: Optional[str] = None):
        self.model_name = model_name or os.getenv("LOCAL_TTS_MODEL", "tts_models/en/vctk/vits")
        self.speaker = speaker or os.getenv("LOCAL_TTS_SPEAKER")
        self._engine = None
        self._load_error: Optional[str] = None
        self._initialise_engine()

    def _initialise_engine(self) -> None:
        try:
            from TTS.api import TTS  # type: ignore
        except ModuleNotFoundError:
            self._load_error = (
                "Local TTS requires the 'TTS' package from Coqui. Install it with `pip install TTS`"
            )
            return
        except Exception as exc:  # pragma: no cover - defensive logging
            self._load_error = f"Failed to initialise local TTS: {exc}"
            return

        try:
            self._engine = TTS(model_name=self.model_name, progress_bar=False, gpu=False)
        except Exception as exc:
            self._load_error = f"Failed to load local TTS model '{self.model_name}': {exc}"

    def is_ready(self) -> bool:
        return self._engine is not None

    def get_error_message(self) -> str:
        return self._load_error or ""

    def set_speaker(self, speaker: Optional[str]) -> None:
        self.speaker = speaker

    def synthesize(self, text: str) -> bytes:
        if not self.is_ready():
            raise RuntimeError(self.get_error_message() or "Local TTS engine is not initialised.")

        temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_file.close()
        try:
            kwargs: Dict[str, str] = {}
            if self.speaker:
                kwargs["speaker"] = self.speaker
            self._engine.tts_to_file(text=text, file_path=temp_file.name, **kwargs)  # type: ignore[arg-type]
            with open(temp_file.name, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass


AudioChunk = Tuple[bytes, str]


class AudioService:
    SUPPORTED_MODES = ("elevenlabs_cloud", "local_tts")

    def __init__(self):
        self.api_key = ""
        self.voice_id = ""
        self.is_on = False
        self.client: Optional[ElevenLabs] = None  # type: ignore[assignment]
        self.local_client: Optional[LocalTTSClient] = None
        self.tts_mode: str = "elevenlabs_cloud"
        self.available_voices: Dict[str, str] = {}
        self.audio_output_queue: Deque[AudioChunk] = deque()
        self.last_error: str = ""

    def set_mode(self, mode: str) -> Tuple[bool, str]:
        if mode not in self.SUPPORTED_MODES:
            return False, "Unsupported TTS mode requested."

        previous_mode = self.tts_mode
        self.tts_mode = mode
        if mode == "local_tts":
            if not self.local_client:
                self.local_client = LocalTTSClient()
            if not self.local_client.is_ready():
                self.is_on = False
                self.last_error = self.local_client.get_error_message() or "Local TTS engine unavailable."
                self.tts_mode = previous_mode
                return False, self.last_error
            self.last_error = ""
            return True, "Local TTS mode ready."

        # ElevenLabs mode: ensure client exists if an API key is present.
        if self.api_key and not self.client:
            if not self.set_api_key(self.api_key):
                self.tts_mode = previous_mode
                return False, self.last_error or "Failed to initialise ElevenLabs client."
        self.last_error = ""
        return True, "ElevenLabs cloud mode selected."

    def set_api_key(self, api_key: str) -> bool:
        self.api_key = api_key
        if ElevenLabs is None:
            self.client = None
            self.last_error = "The 'elevenlabs' package is not installed."
            print(f"🔥 Failed to initialise ElevenLabs client: {self.last_error}")
            return False
        try:
            self.client = ElevenLabs(api_key=self.api_key)
            self.last_error = ""
            return True
        except Exception as e:
            print(f"🔥 Failed to initialise ElevenLabs client: {e}")
            self.client = None
            self.last_error = str(e)
            return False

    def fetch_available_voices(self):
        if not self.client:
            return {"status": "error", "message": "API key not set or invalid."}

        try:
            voices_list = self.client.voices.get_all()
            self.available_voices = {voice.name: voice.voice_id for voice in voices_list.voices}
            print(f"✅ ElevenLabs key set. Found {len(self.available_voices)} voices.")
            return {"status": "success", "voices": self.available_voices}
        except Exception as e:
            return {"status": "error", "message": f"Couldn't fetch voices: {e}"}

    def configure_voice(self, voice_id: Optional[str], enabled: bool) -> Tuple[bool, str]:
        if self.tts_mode == "elevenlabs_cloud":
            if enabled and not self.client:
                if self.api_key and not self.client:
                    if not self.set_api_key(self.api_key):
                        return False, self.last_error or "Invalid ElevenLabs API key."
                else:
                    return False, "Set an ElevenLabs API key before enabling audio."

            if voice_id:
                self.voice_id = voice_id

            if enabled and not self.voice_id:
                return False, "A voice must be selected to enable audio."

            self.is_on = bool(enabled)
            status_message = "ON" if self.is_on else "OFF"
            if self.voice_id:
                voice_name = next((name for name, v_id in self.available_voices.items() if v_id == self.voice_id), self.voice_id)
                print(f"🎤 Voice set to '{voice_name}'. Audio is now {status_message}.")
            else:
                print(f"🎤 Audio is now {status_message}.")
            return True, "ElevenLabs audio settings updated."

        # Local mode
        if not self.local_client:
            self.local_client = LocalTTSClient()

        if voice_id:
            self.local_client.set_speaker(voice_id)

        if enabled and not self.local_client.is_ready():
            self.is_on = False
            message = self.local_client.get_error_message() or "Local TTS engine unavailable."
            self.last_error = message
            print(f"🔥 {message}")
            return False, message

        self.is_on = bool(enabled)
        status_message = "ON" if self.is_on else "OFF"
        print(f"🎤 Local TTS audio is now {status_message}.")
        self.last_error = ""
        return True, "Local audio settings updated."

    def generate_audio_for_text(self, text_to_speak: str) -> None:
        if not self.is_on:
            return

        if not text_to_speak or text_to_speak.strip().startswith(("(", "[")):
            return

        try:
            print(f"🎙️ Generating audio: '{text_to_speak[:50]}...'")
            if self.tts_mode == "elevenlabs_cloud":
                if not self.client or not self.voice_id:
                    return
                if VoiceSettings is None:
                    raise RuntimeError("elevenlabs VoiceSettings unavailable; install the ElevenLabs SDK.")
                audio_stream = self.client.text_to_speech.convert(
                    voice_id=self.voice_id,
                    text=text_to_speak,
                    model_id="eleven_multilingual_v2",
                    voice_settings=VoiceSettings(stability=0.4, similarity_boost=0.7, style=0.1, use_speaker_boost=True)  # type: ignore[arg-type]
                )
                audio_bytes_data = b"".join(audio_stream)
                self.audio_output_queue.append((audio_bytes_data, "audio/mpeg"))
            else:
                if not self.local_client:
                    self.local_client = LocalTTSClient()
                if not self.local_client.is_ready():
                    message = self.local_client.get_error_message() or "Local TTS engine unavailable."
                    print(f"🔥 {message}")
                    self.last_error = message
                    return
                audio_bytes_data = self.local_client.synthesize(text_to_speak)
                self.audio_output_queue.append((audio_bytes_data, "audio/wav"))
            print("✅ Audio ready.")

        except Exception as e:
            self.last_error = str(e)
            print(f"🔥 Audio generation error: {e}")

    def get_next_audio_chunk(self) -> Optional[AudioChunk]:
        if self.audio_output_queue:
            return self.audio_output_queue.popleft()
        return None

    def get_last_error(self) -> str:
        return self.last_error