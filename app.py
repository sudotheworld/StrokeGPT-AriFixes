import os
import sys
import io
import re
import json
import atexit
import queue
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict
from flask import Flask, request, jsonify, render_template_string, send_file, send_from_directory
from config import Config

from settings_manager import SettingsManager
from handy_controller import HandyController
from memory_manager import MemoryManager
from llm_service import LLMService
from audio_service import AudioService
from background_modes import AutoModeThread, auto_mode_logic, milking_mode_logic, edging_mode_logic
from funscript_utils import compute_metrics, compute_segments, hash_funscript, load_actions_from_bytes
from image_service import ImageService

# ─── INITIALIZATION ───────────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
# Removed static LLM_URL; defaults are provided via Config.
settings = SettingsManager(settings_file_path="my_settings.json")
settings.load()
if not settings.image_api_url and Config.IMAGE_API_URL:
    settings.image_api_url = Config.IMAGE_API_URL
if not settings.image_prompt_prefix and Config.IMAGE_PROMPT_PREFIX:
    settings.image_prompt_prefix = Config.IMAGE_PROMPT_PREFIX
if not settings.image_negative_prompt and Config.IMAGE_NEGATIVE_PROMPT:
    settings.image_negative_prompt = Config.IMAGE_NEGATIVE_PROMPT
if not settings.image_steps:
    settings.image_steps = Config.IMAGE_STEPS
if not settings.image_cfg_scale:
    settings.image_cfg_scale = Config.IMAGE_CFG_SCALE
if not settings.image_sampler:
    settings.image_sampler = Config.IMAGE_SAMPLER
if not settings.image_clip_skip:
    settings.image_clip_skip = Config.IMAGE_CLIP_SKIP
if not settings.image_width:
    settings.image_width = Config.IMAGE_WIDTH
if not settings.image_height:
    settings.image_height = Config.IMAGE_HEIGHT
settings.save()

handy = HandyController(settings.handy_key)
handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)

llm = LLMService()
audio = AudioService()
if settings.elevenlabs_api_key:
    if audio.set_api_key(settings.elevenlabs_api_key):
        audio.fetch_available_voices()
        audio.configure_voice(settings.elevenlabs_voice_id, True)

image_service = ImageService(output_dir="generated_images")
_image_job_queue = queue.Queue()
_image_jobs: Dict[str, Dict[str, Any]] = {}
_image_jobs_lock = threading.Lock()
_image_worker_threads: list[threading.Thread] = []

# In-Memory State
chat_history = deque(maxlen=20)
messages_for_ui = deque()
auto_mode_active_task = None
current_mood = "Curious"
use_long_term_memory = True
calibration_pos_mm = 0.0
user_signal_event = threading.Event()
mode_message_queue = deque(maxlen=5)
edging_start_time = None

# -------------------------------------------------------------------------
# Memory manager
#
# A global instance of MemoryManager is created here.  It is used to
# store events from the persona and recall context when building prompts.
mem = MemoryManager()

# -------------------------------------------------------------------------
# Feedback and A/B state persistence
#
# FEEDBACK_LOG: appends one JSON line per feedback submission (score/note/time).
# STATE_FILE: stores the current A/B mode choice so it can persist across restarts.
FEEDBACK_LOG = "feedback.log"
STATE_FILE = "session_state.json"

# Easter Egg State
special_persona_mode = None
special_persona_interactions_left = 0

SNAKE_ASCII = """
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⠟⠛⠛⠋⠉⠛⠟⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⡏⠉⠹⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⠀⢸⣧⡀⠀⠰⣦⡀⠀⠀⢀⠀⠀⠈⣻⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⡇⢨⣿⣿⣖⡀⢡⠉⠄⣀⢀⣀⡀⠀⠼⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⠀⠀⠘⠋⢏⢀⣰⣖⣿⣿⣿⠟⡡⠀⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣯⠁⢀⠂⡆⠉⠘⠛⠿⣿⢿⠟⢁⣬⡶⢠⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⡯⠀⢀⡀⠝⠀⠀⠀⠀⢀⠠⣩⣤⣠⣆⣾⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⡅⠀⠊⠇⢈⣴⣦⣤⣆⠈⢀⠋⠹⣿⣇⣻⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⡄⠥⡇⠀⠀⠚⠺⠯⠀⠀⠒⠛⠒⢪⢿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⡿⠿⠛⠋⠀⠘⣿⡄⠀⠀⠀⠋⠉⡉⠙⠂⢰⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿
⠀⠈⠉⠀⠀⠀⠀⠀⠀⠀⠙⠷⢐⠀⠀⠀⠀⢀⢴⣿⠊⠀⠉⠉⠉⠈⠙⠉⠛⠿
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠰⣖⣴⣾⡃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠁⠀⠀⠀⠀⠀⢀⠀⠀⠀⠀⠁⠀⠨
"""

# Command Keywords
STOP_COMMANDS = {"stop", "hold", "halt", "pause", "freeze", "wait"}
AUTO_ON_WORDS = {"take over", "you drive", "auto mode"}
AUTO_OFF_WORDS = {"manual", "my turn", "stop auto"}
MILKING_CUES = {"i'm close", "make me cum", "finish me"}
EDGING_CUES = {"edge me", "start edging", "tease and deny"}

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────────────────────────────

def get_current_context():
    global edging_start_time, special_persona_mode
    context = {
        'persona_desc': settings.persona_desc, 'current_mood': current_mood,
        'user_profile': settings.user_profile, 'patterns': settings.patterns,
        'rules': settings.rules, 'last_stroke_speed': handy.last_relative_speed,
        'last_depth_pos': handy.last_depth_pos, 'use_long_term_memory': use_long_term_memory,
        'edging_elapsed_time': None, 'special_persona_mode': special_persona_mode
    }
    if edging_start_time:
        elapsed_seconds = int(time.time() - edging_start_time)
        minutes, seconds = divmod(elapsed_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            context['edging_elapsed_time'] = f"{hours}h {minutes}m {seconds}s"
        else:
            context['edging_elapsed_time'] = f"{minutes}m {seconds}s"

    insights = []
    for entry in settings.list_funscripts()[:3]:
        analysis = entry.get("analysis") or {}
        summary = analysis.get("summary")
        if not summary:
            continue
        tags = analysis.get("style_tags") or []
        tag_text = f" ({', '.join(tags[:3])})" if tags else ""
        move_label = None
        moves = analysis.get("signature_moves") or []
        if moves:
            move_label = moves[0].get("label")
        snippet = f"{entry.get('name', 'FunScript')} – {summary}{tag_text}"
        if move_label:
            snippet += f" | Signature move: {move_label}"
        insights.append(snippet)
    if insights:
        context['funscript_insights'] = insights

    return context

def add_message_to_queue(text, add_to_history=True):
    messages_for_ui.append(text)
    if add_to_history:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text: chat_history.append({"role": "assistant", "content": clean_text})
    threading.Thread(target=audio.generate_audio_for_text, args=(text,)).start()


def _update_image_job(job_id: str, updates: Dict[str, Any]) -> None:
    with _image_jobs_lock:
        job = _image_jobs.get(job_id)
        if not job:
            return
        job.update(updates)


def _image_worker() -> None:
    while True:
        item = _image_job_queue.get()
        if item is None:
            _image_job_queue.task_done()
            return

        job_id, task = item
        _update_image_job(job_id, {"status": "running", "started_at": time.time()})
        try:
            entry = image_service.request_image(
                task["url"],
                task["payload"],
                prompt=task["prompt"],
                suffix=task.get("suffix", ".jpg"),
                metadata=task.get("metadata"),
                timeout=task.get("timeout"),
                headers=task.get("headers"),
            )
            _update_image_job(
                job_id,
                {
                    "status": "finished",
                    "finished_at": time.time(),
                    "filename": entry.filename,
                    "gallery_entry": {
                        "filename": entry.filename,
                        "prompt": entry.prompt,
                        "metadata": entry.metadata,
                    },
                },
            )
        except Exception as exc:  # pragma: no cover - defensive branch
            _update_image_job(
                job_id,
                {
                    "status": "error",
                    "finished_at": time.time(),
                    "error": str(exc),
                },
            )
        finally:
            _image_job_queue.task_done()


def _start_image_workers(count: int) -> None:
    for idx in range(max(1, count)):
        worker = threading.Thread(target=_image_worker, name=f"image-worker-{idx}", daemon=True)
        worker.start()
        _image_worker_threads.append(worker)


def _shutdown_image_workers() -> None:
    for _ in _image_worker_threads:
        _image_job_queue.put(None)
    for worker in _image_worker_threads:
        worker.join(timeout=1)


def _coerce_int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def _coerce_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc


def _queue_image_generation(prompt: str, *, overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Queue an image generation job for asynchronous processing."""

    if not prompt or not prompt.strip():
        raise ValueError("Prompt is required")

    overrides = overrides or {}

    url = overrides.get("url") or settings.image_api_url or Config.IMAGE_API_URL
    if not url:
        raise RuntimeError("Image generator URL is not configured")

    api_key = overrides.get("api_key") or settings.image_api_key or Config.IMAGE_API_KEY
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers.setdefault("X-API-Key", api_key)

    prompt_prefix = overrides.get("prompt_prefix")
    if prompt_prefix is None:
        prompt_prefix = settings.image_prompt_prefix or Config.IMAGE_PROMPT_PREFIX

    negative_prompt = overrides.get("negative_prompt")
    if negative_prompt is None:
        negative_prompt = settings.image_negative_prompt or Config.IMAGE_NEGATIVE_PROMPT

    steps = overrides.get("steps", settings.image_steps or Config.IMAGE_STEPS)
    scale = overrides.get("scale", settings.image_cfg_scale or Config.IMAGE_CFG_SCALE)
    sampler = overrides.get("sampler", settings.image_sampler or Config.IMAGE_SAMPLER)
    width = overrides.get("width", settings.image_width or Config.IMAGE_WIDTH)
    height = overrides.get("height", settings.image_height or Config.IMAGE_HEIGHT)
    clip_skip = overrides.get("clip_skip", settings.image_clip_skip or Config.IMAGE_CLIP_SKIP)
    restore_faces = overrides.get("restore_faces")
    if restore_faces is None:
        restore_faces = settings.image_restore_faces or Config.IMAGE_RESTORE_FACES

    enable_hr = bool(overrides.get("enable_hr", False))
    seed = overrides.get("seed", -1)

    if not isinstance(restore_faces, bool):
        restore_faces = str(restore_faces).lower() in {"true", "1", "yes", "on"}

    try:
        steps = _coerce_int(steps, "steps")
        width = _coerce_int(width, "width")
        height = _coerce_int(height, "height")
        clip_skip = _coerce_int(clip_skip, "clip_skip")
        seed = _coerce_int(seed, "seed")
        scale = _coerce_float(scale, "scale")
    except ValueError:
        raise

    payload = {
        "prompt": prompt,
        "steps": steps,
        "scale": scale,
        "sampler": sampler,
        "width": width,
        "height": height,
        "restore_faces": restore_faces,
        "enable_hr": enable_hr,
        "prompt_prefix": prompt_prefix or "",
        "negative_prompt": negative_prompt or "",
        "seed": seed,
        "clip_skip": clip_skip,
    }

    metadata = {
        "request_payload": payload,
        "url": url,
    }
    job_id = uuid.uuid4().hex
    job_info = {
        "id": job_id,
        "status": "queued",
        "created_at": time.time(),
        "prompt": prompt,
    }
    with _image_jobs_lock:
        _image_jobs[job_id] = job_info

    task = {
        "url": url,
        "payload": payload,
        "prompt": prompt,
        "metadata": metadata,
        "timeout": Config.IMAGE_REQUEST_TIMEOUT,
        "headers": headers or None,
        "suffix": overrides.get("suffix", ".jpg"),
    }
    _image_job_queue.put((job_id, task))
    return job_info


_start_image_workers(Config.IMAGE_WORKER_COUNT)
atexit.register(_shutdown_image_workers)

def start_background_mode(mode_logic, initial_message, mode_name):
    global auto_mode_active_task, edging_start_time
    if auto_mode_active_task:
        auto_mode_active_task.stop()
        auto_mode_active_task.join(timeout=5)
    
    user_signal_event.clear()
    mode_message_queue.clear()
    if mode_name == 'edging':
        edging_start_time = time.time()
    
    def on_stop():
        global auto_mode_active_task, edging_start_time
        auto_mode_active_task = None
        edging_start_time = None

    def update_mood(m): global current_mood; current_mood = m
    def get_timings(n):
        return {
            'auto': (settings.auto_min_time, settings.auto_max_time),
            'milking': (settings.milking_min_time, settings.milking_max_time),
            'edging': (settings.edging_min_time, settings.edging_max_time)
        }.get(n, (3, 5))

    services = {'llm': llm, 'handy': handy}
    callbacks = {
        'send_message': add_message_to_queue, 'get_context': get_current_context,
        'get_timings': get_timings, 'on_stop': on_stop, 'update_mood': update_mood,
        'user_signal_event': user_signal_event,
        'message_queue': mode_message_queue
    }
    auto_mode_active_task = AutoModeThread(mode_logic, initial_message, services, callbacks, mode_name=mode_name)
    auto_mode_active_task.start()

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────────────────────────────────
@app.route('/')
def home_page():
    # Optional room pin gate: if a ROOM_PIN is set in config, require ?pin=ROOM_PIN
    pin = request.args.get('pin', '')
    if Config.ROOM_PIN and pin != Config.ROOM_PIN:
        return "Room locked. Append ?pin=<PIN> to the URL.", 401
    base_path = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_path, 'index.html'), 'r', encoding='utf-8') as f:
        return render_template_string(f.read())

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

# Simple healthcheck route to verify connectivity and configuration.
@app.get("/health")
def health():
    return jsonify({
        "server": "ok",
        "ollama_url": Config.OLLAMA_URL,
        "handy_key_set": bool(handy.handy_key),
    })

# -------------------------------------------------------------------------
# Feedback and A/B choice helpers and endpoints

def _load_state() -> dict:
    """Load the session state from STATE_FILE or return defaults."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    # Default state: A mode
    return {"ab_choice": "A"}


def _save_state(state: dict) -> None:
    """Persist the session state to STATE_FILE."""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f)
    except Exception:
        pass


@app.post("/api/feedback")
def api_feedback():
    """Record a feedback score and optional note sent from the UI."""
    data = request.get_json(silent=True) or {}
    try:
        score = int(data.get("score", 0))
    except Exception:
        score = 0
    note = str(data.get("note", ""))[:300]
    rec = {
        "ts": time.time(),
        "score": score,
        "note": note,
    }
    try:
        with open(FEEDBACK_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass
    return jsonify({"ok": True})


@app.post("/api/ab")
def api_ab():
    """Set the current A/B mode choice. Accepts 'A' or 'B'."""
    data = request.get_json(silent=True) or {}
    choice = str(data.get("choice", "A")).upper()
    if choice not in ("A", "B"):
        return jsonify({"ok": False, "error": "choice must be A or B"}), 400
    state = _load_state()
    state["ab_choice"] = choice
    _save_state(state)
    return jsonify({"ok": True, "choice": choice})


@app.get("/api/state")
def api_state():
    """Return the persisted session state."""
    return jsonify(_load_state())

# -------------------------------------------------------------------------
# Memory and invite endpoints
#
@app.post("/api/memory/add")
def api_memory_add():
    """Record a freeform note into the persona memory.

    The payload should be a JSON object with optional fields:
      - ``user``: identifier for the note author.  Defaults to the
        requester's IP address.
      - ``text``: the content of the note.  Empty strings will result
        in a no-op error response.
      - ``tags``: optional list of strings tagging the note.

    Returns a JSON object indicating success and echoing the recorded
    event.
    """
    data = request.get_json(silent=True) or {}
    user = (data.get('user') or request.remote_addr or 'room')
    text = data.get('text', '')
    tags = data.get('tags') or []
    return jsonify(mem.add_event(user, text, tags))


@app.get("/api/memory/recent")
def api_memory_recent():
    """Return the last `n` memory events.

    Query parameter:
      - ``n`` (int): maximum number of events to return (default 25).
    """
    try:
        n = int(request.args.get('n', '25'))
    except Exception:
        n = 25
    items = mem.recent(n)
    return jsonify({"items": items})


@app.post("/api/memory/summarise")
def api_memory_summarise():
    """Generate and persist a YAML‑like summary of the persona memory.

    The POST body may include an optional ``user`` field to label the
    summary.  The summary is written to disk and returned to the
    caller.
    """
    data = request.get_json(silent=True) or {}
    user = data.get('user') or 'room'
    persona_yaml = mem.summarise(user)
    return jsonify({"ok": True, "persona_yaml": persona_yaml})


@app.get("/api/invite")
def api_invite():
    """Return a sharable URL for the current session.

    This endpoint bases the URL on the host used for the request.  If
    a ROOM_PIN is configured, it appends ``?pin=<PIN>`` to the
    returned link.  When accessed via a Cloudflare or ngrok tunnel the
    appropriate public host is reflected automatically in
    ``request.host_url``.
    """
    base = request.host_url.rstrip('/')  # e.g. https://abc.trycloudflare.com
    url = f"{base}/"
    if Config.ROOM_PIN:
        url = f"{url}?pin={Config.ROOM_PIN}"
        # If the base URL already contains a query string, append with &
    return jsonify({"url": url})

def _konami_code_action():
    def pattern_thread():
        handy.move(speed=100, depth=50, stroke_range=100)
        time.sleep(5)
        handy.stop()
    threading.Thread(target=pattern_thread).start()
    message = f"Kept you waiting, huh?<pre>{SNAKE_ASCII}</pre>"
    add_message_to_queue(message)

def _handle_chat_commands(text):
    if any(cmd in text for cmd in STOP_COMMANDS):
        if auto_mode_active_task: auto_mode_active_task.stop()
        handy.stop()
        add_message_to_queue("Stopping.", add_to_history=False)
        return True, jsonify({"status": "stopped"})
    if "up up down down left right left right b a" in text:
        _konami_code_action()
        return True, jsonify({"status": "konami_code_activated"})
    if any(cmd in text for cmd in AUTO_ON_WORDS) and not auto_mode_active_task:
        start_background_mode(auto_mode_logic, "Okay, I'll take over...", mode_name='auto')
        return True, jsonify({"status": "auto_started"})
    if any(cmd in text for cmd in AUTO_OFF_WORDS) and auto_mode_active_task:
        auto_mode_active_task.stop()
        return True, jsonify({"status": "auto_stopped"})
    if any(cmd in text for cmd in EDGING_CUES):
        start_background_mode(edging_mode_logic, "Let's play an edging game...", mode_name='edging')
        return True, jsonify({"status": "edging_started"})
    if any(cmd in text for cmd in MILKING_CUES):
        start_background_mode(milking_mode_logic, "You're so close... I'm taking over completely now.", mode_name='milking')
        return True, jsonify({"status": "milking_started"})
    return False, None

@app.route('/send_message', methods=['POST'])
def handle_user_message():
    global special_persona_mode, special_persona_interactions_left
    data = request.json
    user_input = data.get('message', '').strip()

    if (p := data.get('persona_desc')) and p != settings.persona_desc:
        settings.persona_desc = p; settings.save()
    if (k := data.get('key')) and k != settings.handy_key:
        handy.set_api_key(k); settings.handy_key = k; settings.save()
    
    if not handy.handy_key: return jsonify({"status": "no_key_set"})
    if not user_input: return jsonify({"status": "empty_message"})

    chat_history.append({"role": "user", "content": user_input})
    
    handled, response = _handle_chat_commands(user_input.lower())
    if handled: return response

    if auto_mode_active_task:
        mode_message_queue.append(user_input)
        return jsonify({"status": "message_relayed_to_active_mode"})
    
    # Retrieve a rolling memory context for this user and supply it to the LLM via the context dict.
    user_id = request.remote_addr or "room"
    ctx = get_current_context()
    # Inject persona memory into the context if available.  The LLM will
    # incorporate this under a dedicated section in the system prompt.
    mem_block = mem.context(user_id)
    if mem_block:
        ctx['persona_memory'] = mem_block
    else:
        ctx.pop('persona_memory', None)
    llm_response = llm.get_chat_response(chat_history, ctx)
    
    if special_persona_mode is not None:
        special_persona_interactions_left -= 1
        if special_persona_interactions_left <= 0:
            special_persona_mode = None
            add_message_to_queue("(Personality core reverted to standard operation.)", add_to_history=False)

    if chat_text := llm_response.get("chat"): add_message_to_queue(chat_text)
    if new_mood := llm_response.get("new_mood"): global current_mood; current_mood = new_mood
    if not auto_mode_active_task and (move := llm_response.get("move")):
        handy.move(move.get("sp"), move.get("dp"), move.get("rng"))
    return jsonify({"status": "ok"})

@app.route('/check_settings')
def check_settings_route():
    if settings.handy_key and settings.min_depth < settings.max_depth:
        return jsonify({
            "configured": True, "persona": settings.persona_desc, "handy_key": settings.handy_key,
            "ai_name": settings.ai_name, "elevenlabs_key": settings.elevenlabs_api_key,
            "pfp": settings.profile_picture_b64,
            "timings": { "auto_min": settings.auto_min_time, "auto_max": settings.auto_max_time, "milking_min": settings.milking_min_time, "milking_max": settings.milking_max_time, "edging_min": settings.edging_min_time, "edging_max": settings.edging_max_time }
        ,
            "image": {
                "url": settings.image_api_url or Config.IMAGE_API_URL,
                "has_key": bool(settings.image_api_key or Config.IMAGE_API_KEY),
                "defaults": {
                    "width": settings.image_width,
                    "height": settings.image_height,
                    "steps": settings.image_steps,
                    "scale": settings.image_cfg_scale,
                    "sampler": settings.image_sampler,
                },
            },
        })
    return jsonify({"configured": False})

@app.route('/set_ai_name', methods=['POST'])
def set_ai_name_route():
    global special_persona_mode, special_persona_interactions_left
    name = request.json.get('name', 'BOT').strip();
    if not name: name = 'BOT'
    
    if name.lower() == 'glados':
        special_persona_mode = "GLaDOS"
        special_persona_interactions_left = 5
        settings.ai_name = "GLaDOS"
        settings.save()
        return jsonify({"status": "special_persona_activated", "persona": "GLaDOS", "message": "Oh, it's *you*."})

    settings.ai_name = name; settings.save()
    return jsonify({"status": "success", "name": name})

@app.route('/signal_edge', methods=['POST'])
def signal_edge_route():
    if auto_mode_active_task and auto_mode_active_task.name == 'edging':
        user_signal_event.set()
        return jsonify({"status": "signaled"})
    return jsonify({"status": "ignored", "message": "Edging mode not active."}), 400

@app.route('/set_profile_picture', methods=['POST'])
def set_pfp_route():
    b64_data = request.json.get('pfp_b64')
    if not b64_data: return jsonify({"status": "error", "message": "Missing image data"}), 400
    settings.profile_picture_b64 = b64_data; settings.save()
    return jsonify({"status": "success"})

@app.route('/set_handy_key', methods=['POST'])
def set_handy_key_route():
    key = request.json.get('key')
    if not key: return jsonify({"status": "error", "message": "Key is missing"}), 400
    handy.set_api_key(key); settings.handy_key = key; settings.save()
    return jsonify({"status": "success"})

@app.route('/nudge', methods=['POST'])
def nudge_route():
    global calibration_pos_mm
    if calibration_pos_mm == 0.0 and (pos := handy.get_position_mm()):
        calibration_pos_mm = pos
    direction = request.json.get('direction')
    calibration_pos_mm = handy.nudge(direction, 0, 100, calibration_pos_mm)
    return jsonify({"status": "ok", "depth_percent": handy.mm_to_percent(calibration_pos_mm)})

@app.route('/setup_elevenlabs', methods=['POST'])
def elevenlabs_setup_route():
    api_key = request.json.get('api_key')
    if not api_key or not audio.set_api_key(api_key): return jsonify({"status": "error"}), 400
    settings.elevenlabs_api_key = api_key; settings.save()
    return jsonify(audio.fetch_available_voices())

@app.route('/set_elevenlabs_voice', methods=['POST'])
def set_elevenlabs_voice_route():
    voice_id, enabled = request.json.get('voice_id'), request.json.get('enabled', False)
    ok, message = audio.configure_voice(voice_id, enabled)
    if ok: settings.elevenlabs_voice_id = voice_id; settings.save()
    return jsonify({"status": "ok" if ok else "error", "message": message})


@app.route('/setup_image_generator', methods=['POST'])
def setup_image_generator_route():
    data = request.get_json(force=True, silent=True) or {}

    updates: Dict[str, Any] = {}
    errors = []

    if 'url' in data:
        url = (data.get('url') or '').strip()
        if url:
            settings.image_api_url = url
            updates['url'] = url
        else:
            errors.append('Image generator URL cannot be empty')

    if 'api_key' in data:
        key = (data.get('api_key') or '').strip()
        settings.image_api_key = key
        updates['api_key'] = bool(key)

    if 'prompt_prefix' in data:
        settings.image_prompt_prefix = data.get('prompt_prefix') or ''
        updates['prompt_prefix'] = settings.image_prompt_prefix

    if 'negative_prompt' in data:
        settings.image_negative_prompt = data.get('negative_prompt') or ''
        updates['negative_prompt'] = settings.image_negative_prompt

    def _maybe_set_numeric(field: str, attr: str, caster, label: str) -> None:
        if field in data:
            try:
                setattr(settings, attr, caster(data[field]))
                updates[field] = getattr(settings, attr)
            except (TypeError, ValueError):
                errors.append(f"Invalid {label}")

    _maybe_set_numeric('width', 'image_width', int, 'width')
    _maybe_set_numeric('height', 'image_height', int, 'height')
    _maybe_set_numeric('steps', 'image_steps', int, 'steps')
    _maybe_set_numeric('scale', 'image_cfg_scale', float, 'scale')
    _maybe_set_numeric('clip_skip', 'image_clip_skip', int, 'clip skip')

    if 'sampler' in data:
        settings.image_sampler = str(data['sampler']) or settings.image_sampler
        updates['sampler'] = settings.image_sampler

    if 'restore_faces' in data:
        val = data['restore_faces']
        settings.image_restore_faces = bool(val) if isinstance(val, bool) else str(val).lower() in {"true", "1", "yes", "on"}
        updates['restore_faces'] = settings.image_restore_faces

    if errors:
        return jsonify({"status": "error", "message": "; ".join(errors)}), 400

    if not settings.image_api_url:
        return jsonify({"status": "error", "message": "Image generator URL is not configured"}), 400

    settings.save()
    return jsonify({
        "status": "success",
        "image": {
            "url": settings.image_api_url,
            "has_key": bool(settings.image_api_key),
            "defaults": {
                "width": settings.image_width,
                "height": settings.image_height,
                "steps": settings.image_steps,
                "scale": settings.image_cfg_scale,
                "sampler": settings.image_sampler,
                "clip_skip": settings.image_clip_skip,
                "restore_faces": settings.image_restore_faces,
            },
        },
        "updates": updates,
    })


@app.post('/api/image/generate')
def api_image_generate_route():
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({"status": "error", "message": "Prompt is required"}), 400

    overrides = {k: v for k, v in data.items() if k != 'prompt'}
    try:
        job = _queue_image_generation(prompt, overrides=overrides)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({"status": "queued", "job": dict(job), "job_id": job['id']})


@app.get('/api/image/jobs/<job_id>')
def api_image_job_status(job_id: str):
    with _image_jobs_lock:
        job = _image_jobs.get(job_id)
        if job:
            job = dict(job)
    if not job:
        return jsonify({"status": "error", "message": "Job not found"}), 404

    if job.get('filename'):
        job.setdefault('image_url', f"/generated_images/{job['filename']}")
    return jsonify(job)


@app.get('/api/image/gallery')
def api_image_gallery():
    entries = [
        {
            "filename": entry.filename,
            "prompt": entry.prompt,
            "metadata": entry.metadata,
            "image_url": f"/generated_images/{entry.filename}",
        }
        for entry in image_service.list_gallery()
    ]
    return jsonify({"gallery": entries})


@app.delete('/api/image/gallery')
def api_image_gallery_clear():
    image_service.clear_gallery()
    with _image_jobs_lock:
        _image_jobs.clear()
    return jsonify({"status": "cleared"})


@app.get('/generated_images/<path:filename>')
def serve_generated_image(filename: str):
    return send_from_directory(str(image_service.output_dir), filename)

@app.route('/get_updates')
def get_ui_updates_route():
    messages = [messages_for_ui.popleft() for _ in range(len(messages_for_ui))]
    if audio_chunk := audio.get_next_audio_chunk():
        return send_file(io.BytesIO(audio_chunk), mimetype='audio/mpeg')
    return jsonify({"messages": messages})

@app.route('/get_status')
def get_status_route():
    return jsonify({"mood": current_mood, "speed": handy.last_stroke_speed, "depth": handy.last_depth_pos})

@app.get('/api/funscripts')
def get_funscripts_route():
    return jsonify({"catalog": settings.list_funscripts()})


@app.post('/api/funscripts')
def upload_funscripts_route():
    if 'files' not in request.files:
        return jsonify({"status": "error", "message": "No files provided"}), 400

    uploaded_files = request.files.getlist('files')
    if not uploaded_files:
        return jsonify({"status": "error", "message": "No files provided"}), 400

    processed = []
    errors = []

    for fs in uploaded_files:
        filename = fs.filename or "FunScript"
        raw = fs.read()
        if not raw:
            errors.append({"file": filename, "message": "Empty file"})
            continue

        digest = hash_funscript(raw)
        try:
            actions = load_actions_from_bytes(raw)
        except ValueError:
            errors.append({"file": filename, "message": "Invalid FunScript JSON"})
            continue

        metrics = compute_metrics(actions)
        segments = compute_segments(actions)
        truncated_segments = segments[:12]

        existing = settings.get_funscript_by_hash(digest)
        entry = dict(existing) if existing else {}
        entry.update({
            "id": entry.get("id", digest),
            "sha1": digest,
            "name": filename,
            "metrics": metrics,
            "segments": truncated_segments,
            "uploaded_at": time.time(),
        })

        if not entry.get("analysis"):
            analysis = llm.analyze_funscript_patterns(metrics, truncated_segments)
            entry["analysis"] = analysis

        settings.update_funscript_entry(entry)
        processed.append(entry)

    status_code = 207 if errors and processed else (400 if errors else 200)
    return jsonify({
        "status": "ok" if processed else "error",
        "catalog": settings.list_funscripts(),
        "processed": processed,
        "errors": errors,
    }), status_code


@app.route('/set_depth_limits', methods=['POST'])
def set_depth_limits_route():
    depth1 = int(request.json.get('min_depth', 5)); depth2 = int(request.json.get('max_depth', 100))
    settings.min_depth = min(depth1, depth2); settings.max_depth = max(depth1, depth2)
    handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
    settings.save()
    return jsonify({"status": "success"})

@app.route('/set_speed_limits', methods=['POST'])
def set_speed_limits_route():
    settings.min_speed = int(request.json.get('min_speed', 10)); settings.max_speed = int(request.json.get('max_speed', 80))
    handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
    settings.save()
    return jsonify({"status": "success"})

@app.route('/like_last_move', methods=['POST'])
def like_last_move_route():
    last_speed = handy.last_relative_speed; last_depth = handy.last_depth_pos
    pattern_name = llm.name_this_move(last_speed, last_depth, current_mood)
    sp_range = [max(0, last_speed - 5), min(100, last_speed + 5)]; dp_range = [max(0, last_depth - 5), min(100, last_depth + 5)]
    new_pattern = {"name": pattern_name, "sp_range": [int(p) for p in sp_range], "dp_range": [int(p) for p in dp_range], "moods": [current_mood], "score": 1}
    settings.session_liked_patterns.append(new_pattern)
    add_message_to_queue(f"(I'll remember that you like '{pattern_name}')", add_to_history=False)
    return jsonify({"status": "boosted", "name": pattern_name})

@app.route('/start_edging_mode', methods=['POST'])
def start_edging_route():
    start_background_mode(edging_mode_logic, "Let's play an edging game...", mode_name='edging')
    return jsonify({"status": "edging_started"})

@app.route('/start_milking_mode', methods=['POST'])
def start_milking_route():
    start_background_mode(milking_mode_logic, "You're so close... I'm taking over completely now.", mode_name='milking')
    return jsonify({"status": "milking_started"})

@app.route('/stop_auto_mode', methods=['POST'])
def stop_auto_route():
    if auto_mode_active_task: auto_mode_active_task.stop()
    return jsonify({"status": "auto_mode_stopped"})

# ─── APP STARTUP ───────────────────────────────────────────────────────────────────────────────────
def on_exit():
    print("⏳ Saving settings on exit...")
    settings.save(llm, chat_history)
    print("✅ Settings saved.")

if __name__ == '__main__':
    atexit.register(on_exit)
    print(f"🚀 Starting Handy AI app at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
    # Run using configured host and port; threaded=True allows concurrent requests while the LLM computes.
    app.run(host=Config.HOST, port=Config.PORT, threaded=True)