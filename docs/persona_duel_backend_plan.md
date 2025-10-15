# Persona Duel Backend Integration Plan

This plan describes how to wire the new `persona_duel_neon_dark_ai.html` interface into the existing StrokeGPT backend so that the UI can drive The Handy, manage personas, remember user preferences, and request imagery from a free text-to-image service.

## 1. Goals

* Serve the Persona Duel UI from Flask and back it with JSON endpoints instead of the legacy DOM-scraping script that powers `index.html`.
* Reuse the current control stack (`HandyController`, `LLMService`, `AudioService`, `MemoryManager`) so that chat, modes, and memory behave the same regardless of which front end is active.
* Persist API keys and persona templates through `SettingsManager`, while keeping sensitive values out of the browser when possible.
* Provide a server-side abstraction for image generation using a free-to-start provider so the browser can request themed art for each persona without exposing the upstream API key.

## 2. High-level architecture changes

1. **Split API routes from `app.py`:**
   * Move the existing JSON endpoints (`/send_message`, `/get_updates`, `/api/memory/*`, etc.) into a new Flask Blueprint (e.g., `persona_api`).
   * Normalise request/response payloads to structured JSON so the new UI can fetch discrete resources (chat history, persona catalog, active session state).

2. **Dual front-end support:**
   * Serve `index.html` at `/` for backwards compatibility.
   * Serve the neon Persona Duel UI at `/duel` (static render of `persona_duel_neon_dark_ai.html`).
   * Add a small bootstrap script that detects which front end is loaded and points it at the Blueprint endpoints.

3. **Session orchestration layer:**
   * Introduce `SessionService` (wrapper around the current globals in `app.py`) that keeps chat history, mood, and mode state, providing methods invoked by both UIs.
   * Replace global `deque`/flags with an instance of this service so state handling is isolated.

4. **Image generation service:**
   * Add `image_service.py` to encapsulate calls to the [Hugging Face Inference API](https://huggingface.co/inference-api) using the community free tier.
   * Expose methods for single-image generation and for fetching model metadata; handle rate-limit retries and caching of recent prompts on disk (e.g., under `generated_images/`).

## 3. Endpoint map for Persona Duel

| UI feature | Endpoint | Notes |
|------------|----------|-------|
| Load initial state (keys saved, persona list, chat log, mood, active modes) | `GET /api/duel/bootstrap` | Aggregates data from `SettingsManager`, `SessionService`, and `MemoryManager` so the UI can hydrate without multiple round trips.
| Update Handy/voice/image API keys | `POST /api/duel/settings` | Body: `{"handy_key":..., "voice_key":..., "image_key":...}` (all optional). Stores via `SettingsManager` and updates controllers in-memory.
| Send chat message + persona text | `POST /api/duel/chat` | Body: `{ "message": "...", "persona": "...", "mode": "manual" }`. Uses `LLMService.generate_reply()` and pushes responses into `SessionService`. Returns `{ "messages": [...], "handy": {"speed":..,"depth":..} }` plus optional audio job id.
| Poll for incremental assistant output | `GET /api/duel/chat/updates?since=<cursor>` | Replaces the current `/get_updates`; returns new bot messages, audio URLs, and device telemetry.
| Persona CRUD | `GET /api/duel/personas`, `POST /api/duel/personas`, `DELETE /api/duel/personas/<id>` | Stores JSON persona definitions (name, role, body, description, goal) in `memory/personas.json`.
| Activate persona | `POST /api/duel/personas/<id>/activate` | Sets `SessionService.active_persona` and writes persona summary into `settings.persona_desc` so prompts stay consistent.
| Rate response | `POST /api/duel/ratings` | Body: `{ "message_id": "...", "score": 5 }`. Calls `MemoryManager.add_memory()` and logs to `feedback.log` with persona metadata.
| FunScript uploads | `POST /api/duel/funscripts` (multipart) | Accepts `.funscript`/`.json`, stores under `funscripts/` folder, and returns metadata used to populate the UI library.
| Handy control buttons | `POST /api/duel/modes/<mode>` | Modes: `auto`, `edging`, `milking`, `stop`, `nudge`, etc. Delegates to existing helpers (`start_background_mode`, `stop_auto_mode`, `handy.nudge_depth`, etc.).
| Image generation | `POST /api/duel/image` | Body: `{ "prompt": "...", "persona_id": "..." }`. Calls `ImageService.generate()` which hits Hugging Face and returns `{ "image_url": "/media/generated/<uuid>.png" }` or a base64 payload.

## 4. Image generation provider

* **Provider:** Hugging Face Inference API
  * Free tier allows 30 input credits/day, good enough for single persona portraits during testing.
  * Recommended model: `black-forest-labs/flux.1-dev` for stylistic neon renders or `stabilityai/stable-diffusion-xl-base-1.0` for general prompts.
  * Requires a personal token; store it encrypted via `SettingsManager` just like the ElevenLabs key.
* **Server implementation:**
  * `image_service.py` keeps the token and a configurable default model.
  * Provide `set_api_key()` and `set_model()` mutators invoked when settings change.
  * Use streaming download to write the image to `generated_images/<uuid>.png` and return a URL served via new static route (`/generated/<filename>`).
  * Guard against abuse by enforcing prompt length limits and caching the most recent successful generation per persona for 10 minutes.

## 5. Data persistence updates

* Extend `SettingsManager` with getters/setters for the image generator API key and preferred model name.
* Add `PersonaRepository` (simple JSON file) for storing persona definitions, allowing the Persona Creator UI to list previously saved personas.
* Persist funscript metadata (filename, duration, tags) into `memory/funscripts.json` so the UI dropzone can render a history list.

## 6. Front-end contract adjustments

Although the Persona Duel HTML is mostly static, ship a dedicated JS module (e.g., `static/js/persona_duel.js`) that:

1. Calls `/api/duel/bootstrap` on load to populate fields.
2. Debounces persona form edits and sends them via the persona endpoints.
3. Polls `/api/duel/chat/updates` every ~1s (or swap to Server-Sent Events later) for new assistant output and device telemetry.
4. Invokes `/api/duel/image` when the user requests a portrait, swapping in the returned URL.
5. Wires the star rating buttons to `/api/duel/ratings`.

## 7. Testing strategy

* **Unit tests:**
  * Mocked tests for `ImageService` (simulate Hugging Face responses, rate limit errors).
  * Tests for `PersonaRepository` CRUD and `SessionService` state transitions.
* **Integration tests (Flask):**
  * Verify `/api/duel/bootstrap` returns consistent JSON with fixtures.
  * Exercise chat endpoint using a stubbed `LLMService` to ensure persona text is injected and Handy commands are enqueued.
  * Upload a sample funscript and confirm it is persisted.
* **Manual QA checklist:**
  * Load `/duel`, enter keys, ensure `SettingsManager` updates.
  * Send chat message, watch for Handy telemetry updates.
  * Generate persona art; confirm image saved and served via `/generated/...`.
  * Trigger edging/milking/stop flows from the UI and confirm `HandyController` receives calls.

## 8. Migration steps

1. Implement `SessionService`, `ImageService`, and `PersonaRepository`.
2. Refactor `app.py` to instantiate the new services and register the Blueprint.
3. Port existing endpoints into the new namespace and adjust the legacy UI to call the new URLs (provide shims for compatibility).
4. Add `/duel` route and include compiled JS bundle for the neon UI.
5. Update documentation (`README.txt`) with instructions on obtaining a Hugging Face token and enabling the Persona Duel interface.
6. Ship automated tests and run the existing suite (`pytest`).

Following this plan will keep the legacy experience working while bringing the Persona Duel interface online with full Handy control, persona management, and image generation powered by an accessible free API.
