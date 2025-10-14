import os
import sys
import io
import re
import json
import atexit
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, send_file, send_from_directory
from werkzeug.utils import secure_filename
from config import Config

from settings_manager import SettingsManager
from handy_controller import HandyController
from memory_manager import MemoryManager
from llm_service import LLMService
from audio_service import AudioService
from background_modes import AutoModeThread, auto_mode_logic, milking_mode_logic, edging_mode_logic

# ─── INITIALIZATION ───────────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
FUNSCRIPT_DIR = BASE_DIR / "funscripts"
FUNSCRIPT_INDEX_FILE = FUNSCRIPT_DIR / "index.json"
ALLOWED_FUNSCRIPT_EXTENSIONS = {".funscript", ".json"}
# Removed static LLM_URL; defaults are provided via Config.
settings = SettingsManager(settings_file_path="my_settings.json")
settings.load()

FUNSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

handy = HandyController(settings.handy_key)
handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)

llm = LLMService()
audio = AudioService()
if settings.elevenlabs_api_key:
    if audio.set_api_key(settings.elevenlabs_api_key):
        audio.fetch_available_voices()
        audio.configure_voice(settings.elevenlabs_voice_id, True)

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
    return context

def add_message_to_queue(text, add_to_history=True):
    messages_for_ui.append(text)
    if add_to_history:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text: chat_history.append({"role": "assistant", "content": clean_text})
    threading.Thread(target=audio.generate_audio_for_text, args=(text,)).start()

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

def _load_funscript_index() -> list:
    """Return the stored FunScript metadata index."""
    try:
        if FUNSCRIPT_INDEX_FILE.exists():
            with open(FUNSCRIPT_INDEX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _save_funscript_index(entries: list) -> None:
    """Persist the FunScript index to disk."""
    try:
        FUNSCRIPT_INDEX_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _normalise_tags(raw_tags) -> list:
    """Convert tags supplied as comma-separated string or list into a cleaned list."""
    if isinstance(raw_tags, str):
        items = [t.strip() for t in raw_tags.split(",")]
    elif isinstance(raw_tags, (list, tuple, set)):
        items = [str(t).strip() for t in raw_tags]
    else:
        items = []
    return [t for t in items if t]


def _unique_funscript_filename(base_name: str) -> str:
    """Return a filename that does not collide with existing files on disk."""
    candidate = base_name
    stem = Path(base_name).stem
    suffix = Path(base_name).suffix
    counter = 1
    while (FUNSCRIPT_DIR / candidate).exists():
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate

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


@app.post("/funscripts")
def upload_funscripts():
    """Accept multipart uploads for FunScript files and persist metadata."""
    files = request.files.getlist("files")
    if not files:
        single = request.files.get("file")
        if single:
            files = [single]

    if not files:
        return jsonify({"error": "No files provided."}), 400

    metadata_map = {}
    metadata_raw = request.form.get("metadata")
    if metadata_raw:
        try:
            metadata_map = json.loads(metadata_raw) or {}
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid metadata payload."}), 400

    index = _load_funscript_index()
    uploaded_entries = []
    skipped_entries = []

    for storage in files:
        original_name = storage.filename or ""
        safe_name = secure_filename(original_name)
        if not safe_name:
            skipped_entries.append({"filename": original_name, "reason": "invalid_filename"})
            continue

        suffix = Path(safe_name).suffix.lower()
        if suffix not in ALLOWED_FUNSCRIPT_EXTENSIONS:
            skipped_entries.append({"filename": original_name or safe_name, "reason": "unsupported_extension"})
            continue

        final_name = _unique_funscript_filename(safe_name)
        file_path = FUNSCRIPT_DIR / final_name

        try:
            storage.save(file_path)
        except Exception:
            skipped_entries.append({"filename": original_name or safe_name, "reason": "save_failed"})
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception:
                    pass
            continue

        meta = metadata_map.get(original_name) or metadata_map.get(safe_name) or {}
        display_name = str(meta.get("name") or Path(original_name or final_name).stem)
        tags = _normalise_tags(meta.get("tags"))

        try:
            file_size = file_path.stat().st_size
        except OSError:
            file_size = None

        entry = {
            "name": display_name,
            "filename": final_name,
            "original_filename": original_name,
            "tags": tags,
            "uploaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        if file_size is not None:
            entry["size"] = file_size

        index = [item for item in index if isinstance(item, dict) and item.get("filename") != final_name]
        index.append(entry)
        uploaded_entries.append(entry)

    if uploaded_entries:
        index.sort(key=lambda item: (item.get("name") or item.get("filename") or "").lower())
        _save_funscript_index(index)

    response = {"uploaded": uploaded_entries}
    if skipped_entries:
        response["skipped"] = skipped_entries

    if not uploaded_entries:
        response.setdefault("error", "No valid FunScript files were uploaded.")
        return jsonify(response), 400

    return jsonify(response)


@app.get("/funscripts")
def list_funscripts():
    """Return the available FunScript metadata."""
    stored_entries = _load_funscript_index()
    filtered_entries = []
    changed = False

    for entry in stored_entries:
        if not isinstance(entry, dict):
            changed = True
            continue
        filename = entry.get("filename")
        if not filename:
            changed = True
            continue
        file_path = FUNSCRIPT_DIR / filename
        if not file_path.exists():
            changed = True
            continue
        filtered_entries.append(entry)

    sorted_entries = sorted(
        filtered_entries,
        key=lambda item: (item.get("name") or item.get("filename") or "").lower(),
    )

    if changed:
        _save_funscript_index(sorted_entries)

    response_entries = []
    for entry in sorted_entries:
        enriched = dict(entry)
        file_path = FUNSCRIPT_DIR / entry["filename"]
        try:
            enriched["size"] = file_path.stat().st_size
        except OSError:
            enriched.setdefault("size", entry.get("size"))
        response_entries.append(enriched)

    return jsonify({"funscripts": response_entries})


@app.get("/funscripts/<path:filename>")
def stream_funscript(filename: str):
    """Stream a FunScript file for playback."""
    safe_name = secure_filename(filename)
    if not safe_name:
        return jsonify({"error": "Not found."}), 404

    entries = _load_funscript_index()
    allowed_names = {entry.get("filename") for entry in entries if isinstance(entry, dict)}
    if safe_name not in allowed_names:
        return jsonify({"error": "Not found."}), 404

    file_path = FUNSCRIPT_DIR / safe_name
    if not file_path.exists():
        return jsonify({"error": "Not found."}), 404

    return send_from_directory(
        FUNSCRIPT_DIR,
        safe_name,
        mimetype="application/json",
        as_attachment=False,
        conditional=True,
    )

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

@app.route('/get_updates')
def get_ui_updates_route():
    messages = [messages_for_ui.popleft() for _ in range(len(messages_for_ui))]
    if audio_chunk := audio.get_next_audio_chunk():
        return send_file(io.BytesIO(audio_chunk), mimetype='audio/mpeg')
    return jsonify({"messages": messages})

@app.route('/get_status')
def get_status_route():
    return jsonify({"mood": current_mood, "speed": handy.last_stroke_speed, "depth": handy.last_depth_pos})

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