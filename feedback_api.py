"""Feedback persistence, isolated from device and service initialization."""

import json
import time

from flask import current_app, jsonify, request


def register_feedback_routes(app, log_path):
    """Register the endpoint; log_path resolves the current destination."""

    @app.post("/api/feedback")
    def api_feedback():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(ok=False, error="Expected a JSON object"), 400
        score = data.get("score")
        if type(score) is not int or score == 0 or not -5 <= score <= 5:
            return jsonify(ok=False, error="score must be an integer from -5 to -1 or 1 to 5"), 400
        note = data.get("note", "")
        if not isinstance(note, str) or len(note) > 300:
            return jsonify(ok=False, error="note must be a string of at most 300 characters"), 400
        rec = {"ts": time.time(), "score": score, "note": note}
        try:
            with open(log_path(), "a", encoding="utf-8") as stream:
                stream.write(json.dumps(rec) + "\n")
        except OSError:
            current_app.logger.exception("Feedback persistence failed")
            return jsonify(ok=False, error="Could not save feedback"), 500
        return jsonify(ok=True)
