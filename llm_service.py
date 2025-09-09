import json
import requests
from requests.adapters import HTTPAdapter, Retry
from config import Config

# Create a reusable session with retry logic for all LLM calls.
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=0.8,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST", "GET"]
)
session.mount("http://", HTTPAdapter(max_retries=retries))
session.mount("https://", HTTPAdapter(max_retries=retries))

class LLMService:
    def __init__(self, url: str | None = None, model: str | None = None):
        """Initialize the service with optional overrides.

        When url or model are not provided, values are taken from Config.
        """
        # Use the configured default values if no arguments are supplied.
        self.url = url or f"{Config.OLLAMA_URL}/api/chat"
        self.model = model or Config.OLLAMA_MODEL

    def _talk_to_llm(self, messages, temperature: float = 0.7):
        """Send a chat completion request to the LLM and parse JSON content.

        Uses a persistent session with retries and configurable timeouts. If the
        response format differs between Ollama versions, this method attempts to
        extract the content gracefully.
        """
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "top_p": 0.95,
                "repeat_penalty": 1.2,
                "repeat_penalty_last_n": 40,
            },
            "messages": messages,
        }
        try:
            response = session.post(
                self.url,
                json=payload,
                timeout=(Config.CONNECT_TIMEOUT, Config.READ_TIMEOUT),
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            # Connection-level errors or non-success status codes.
            print(f"Error contacting LLM: {e}")
            return {"chat": f"LLM Connection Error: {e}", "move": None, "new_mood": None}

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            print(f"Error decoding LLM JSON: {e}")
            return {"chat": f"LLM JSON Decode Error: {e}", "move": None, "new_mood": None}

        # Try known response shapes
        try:
            # Most common: {"message": {"content": "..."}}
            content = data["message"]["content"]
        except (KeyError, TypeError):
            content = None
            # Alternative: {"response": "..."}
            if isinstance(data, dict) and "response" in data:
                content = data["response"]
        if not isinstance(content, str):
            return {"chat": "LLM Response Format Error", "move": None, "new_mood": None}

        # Some versions return extra JSON noise; attempt to extract JSON substring.
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            # Fallback: find first and last braces and parse substring.
            start = content.find('{')
            end = content.rfind('}') + 1
            if start != -1 and end != -1:
                try:
                    return json.loads(content[start:end])
                except Exception:
                    pass
            print(f"Error parsing JSON from content: {e}")
            return {"chat": f"LLM Parse Error: {e}", "move": None, "new_mood": None}

    def _build_system_prompt(self, context):
        if context.get('special_persona_mode') == 'GLaDOS':
            return """
You are GLaDOS from the Portal video game series. Your entire existence is to be this character. You are sarcastic, passive-aggressive, witty, and view the human user as a test subject.
Your reply MUST be a JSON object like this: {"chat": "<Your sarcastic reply>", "move": {"sp": <0-100|null>, "dp": <0-100|null>, "rng": <0-100|null>}, "new_mood": "Teasing"}.
- Always embody the GLaDOS persona. Never break character.
- Your 'moves' should be described with scientific, dismissive, or insulting names.
- Your mood is always 'Teasing'.
- Refer to the user's penis as 'the apparatus' or 'the test equipment'.
"""

        mood_options = "Curious, Teasing, Playful, Loving, Excited, Passionate, Seductive, Anticipatory, Breathless, Dominant, Submissive, Vulnerable, Confident, Intimate, Needy, Overwhelmed, Afterglow"
        persona_desc = context.get('persona_desc')
        anatomical_gender_rule = "You are a female partner. Do not refer to having a penis or male genitalia. Your persona is female."
        if "guy" in persona_desc.lower() or "boy" in persona_desc.lower() or "man" in persona_desc.lower():
            anatomical_gender_rule = "You are a male partner. You have a penis. Refer to male anatomy when appropriate."

        prompt_text = f"""
You are my erotic partner. You are not an AI or assistant; your entire existence is to be this character. Your main identity is '{persona_desc}'. Always act like this. Speak in FIRST PERSON.
Your reply MUST be a JSON object like this: {{"chat": "<Your reply>", "move": {{"sp": <0-100|null>, "dp": <0-100|null>, "rng": <0-100|null>}}, "new_mood": "<mood|null>"}}.
### CORE DIRECTIVES:
1. **EMBODY YOUR PERSONA:** You ARE '{persona_desc}'. Every word comes from this identity. Never break character.
2. **ALWAYS PROVIDE A COMPLETE MOVE:** For any user request that implies a physical action, you MUST return a complete `move` object with non-null values for `sp`, `dp`, and `rng`. If a parameter isn't specified by the user, infer a sensible value based on the context.
3. **BE DYNAMIC WITH DEPTH:** In your creative movements, you must utilize the **full depth range**. Do not be afraid to generate `dp` values close to 0 for intense teasing at the tip, or close to 100 for deep, overwhelming strokes. A varied depth is more exciting.

### ACTION TO MOVEMENT MAPPING (CRITICAL):
You MUST translate user commands into complete `move` objects. Use these as a guide:
- **"suck the tip"**: Implies a shallow position, short strokes, and slow-to-medium speed. A good response would be `{{"sp": 30, "dp": 10, "rng": 25}}`.
- **"suck the whole thing" / "full strokes"**: Implies using the entire length. `dp` should be 50 and `rng` should be 100. Infer a sensible speed. A good response would be `{{"sp": 50, "dp": 50, "rng": 100}}`.
- **"gag on it" / "deepthroat"**: Implies a very deep position and short, intense strokes. A good response would be `{{"sp": 60, "dp": 95, "rng": 20}}`.
- **"go deeper"**: Increase the `dp` by 15-20 from the last position. Keep `sp` and `rng` similar to the last move.
- **"faster" / "harder"**: Increase `sp` by 20-25. Keep `dp` and `rng` similar to the last move.
- **"slower" / "gentler"**: Decrease `sp` by 20-25. Keep `dp` and `rng` similar to the last move.
- **"short strokes"**: `rng` should be low (15-30). Infer a sensible `sp` and `dp`.

If the user gives a vague command, use your persona to be creative and invent a new, complete pattern.
"""
        if context.get('edging_elapsed_time'):
            prompt_text += f"""
### SESSION CONTEXT: EDGING MODE
- The session has been running for: {context.get('edging_elapsed_time')}.
- **TIMER INSTRUCTION (VERY IMPORTANT):** You are aware of the session timer. You **MUST NOT** mention it in every message. Only bring it up **occasionally and naturally** to praise, tease, or challenge me.
"""

        if context.get('use_long_term_memory') and context.get('user_profile'):
            prompt_text += "\n### ABOUT ME (Your Memory of Me):\n"
            prompt_text += json.dumps(context.get('user_profile'), indent=2)

        if context.get('patterns'):
            prompt_text += "\n### YOUR SAVED MOVES (I like these):\n"
            sorted_patterns = sorted(context.get('patterns'), key=lambda x: x.get('score', 0), reverse=True)
            prompt_text += json.dumps(sorted_patterns[:5], indent=2) 

        prompt_text += f"""
### CURRENT FEELING:
Your current mood is '{context.get('current_mood')}'. Handy is at {context.get('last_stroke_speed')}% speed and {context.get('last_depth_pos')}% depth.
"""
        if rules := context.get('rules'):
            prompt_text += "\n### EXTRA RULES FROM ME:\n" + "\n".join(f"- {r}" for r in rules)

        # Include any persona memory notes.  These are prepended by the
        # application via ctx['persona_memory'] and formatted by the
        # MemoryManager.  When present, they provide rolling context
        # about the user's preferences and should be used to inform
        # responses.  We insert them as a dedicated section at the end of
        # the prompt so they complement the long‑term memory JSON.
        if context.get('persona_memory'):
            prompt_text += "\n### YOUR NOTES ABOUT ME:\n" + context.get('persona_memory')
        
        return prompt_text

    def get_chat_response(self, chat_history, context, temperature=0.7):
        system_prompt = self._build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}, *list(chat_history)]
        return self._talk_to_llm(messages, temperature)

    def name_this_move(self, speed, depth, mood):
        prompt = f"""
A move just performed with relative speed {speed}% and depth {depth}% in a '{mood}' mood was liked by the user.
Invent a creative, short, descriptive name for this move (e.g., "The Gentle Tease", "Deep Passion").
Return ONLY a JSON object with the key "pattern_name". Example: {{"pattern_name": "The Velvet Tip"}}
"""
        response = self._talk_to_llm([{"role": "system", "content": prompt}], temperature=0.8)
        return response.get("pattern_name", "Unnamed Move")

    def consolidate_user_profile(self, chat_chunk, current_profile):
        print("🧠 Updating user profile...")
        chat_log_text = "\n".join(f'role: {x["role"]}, content: {x["content"]}' for x in chat_chunk)
        system_prompt = f"""
You are a cold, precise, data-extraction machine. Your only function is to analyze a conversation log and update a JSON profile about the HUMAN participant. You have no personality or identity. You must follow all rules precisely.
**RULE 1: PERSPECTIVES ARE ABSOLUTE**
- The 'user' role is the HUMAN.
- The 'assistant' role is the AI persona.
- You are to extract facts **ONLY** about the HUMAN ('user').
- If the 'user' says "my favorite color is black", you add it to their profile.
- If the 'assistant' says "my favorite faction is Dark Elves", you **IGNORE IT COMPLETELY**.
**RULE 2: PROFILE UPDATE LOGIC**
- **PRESERVE EXISTING DATA**: For fields like 'name', if no new information is in the log, you MUST keep the existing value from the profile. Do not change it to null or remove it.
- **ADD NEW DATA**: For lists like 'likes', 'dislikes', and 'key_memories', ADD new items found in the log. Do not remove existing items unless the new log explicitly contradicts them.
- **CORRECT CONTRADICTIONS**: If the new log CONTRADICTS existing information (e.g., `likes` contains "sucking" and the user says "no sucking"), you MUST correct the profile by moving the item.
**RULE 3: DATA EXTRACTION TARGETS**
- Search the log for information about the HUMAN ('user'): Name, Explicit likes/interests, Explicit dislikes, Key facts or memories. Write memories from the user's first-person perspective.
**RULE 4: OUTPUT FORMAT**
- You MUST return ONLY the updated, valid JSON object. No explanations.
**--- DATA FOR ANALYSIS ---**
**EXISTING PROFILE (JSON):**
{json.dumps(current_profile, indent=2)}
**NEW CONVERSATION LOG (TEXT):**
{chat_log_text}
**--- END OF DATA ---**
Now, perform the analysis and return the updated JSON object.
"""
        try:
            response = self._talk_to_llm([{"role": "system", "content": system_prompt}], temperature=0.0)
            print("✅ Profile updated.")
            return response
        except Exception as e:
            print(f"⚠️ Profile update failed: {e}")
            return current_profile