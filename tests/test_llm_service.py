import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import llm_service


def test_response_length_instruction_added_to_prompt():
    service = llm_service.LLMService(url="http://dummy", model="dummy")
    context = {
        "persona_desc": "Playful Partner",
        "current_mood": "Curious",
        "last_stroke_speed": 50,
        "last_depth_pos": 40,
        "response_length": 1234,
    }
    prompt = service._build_system_prompt(context)
    assert "1234 characters" in prompt


def test_response_length_controls_num_predict(monkeypatch):
    captured_payload = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"chat": "ok", "move": null, "new_mood": null}'}}

    def fake_post(url, json=None, timeout=None):
        captured_payload["payload"] = json
        return DummyResponse()

    monkeypatch.setattr(llm_service.session, "post", fake_post)

    service = llm_service.LLMService(url="http://dummy", model="dummy")
    context = {
        "persona_desc": "Playful Partner",
        "current_mood": "Curious",
        "last_stroke_speed": 50,
        "last_depth_pos": 40,
        "response_length": 1200,
    }
    chat_history = [{"role": "user", "content": "Hello"}]

    service.get_chat_response(chat_history, context)

    assert "payload" in captured_payload
    options = captured_payload["payload"]["options"]
    assert options["num_predict"] == 400
