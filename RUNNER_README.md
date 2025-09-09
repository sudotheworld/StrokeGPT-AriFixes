# One-command preset run (Windows PowerShell)

```pwsh
# unzip, then from the zip root:
./run_duel_preset.ps1 -ModelA "qwen2.5:7b" -ModelB "llama3.1:8b-instruct-q4_K_M" -Mode nsfw
```

- Pulls models (`ollama pull`), creates venv, installs deps, and runs a 30-turn interview arc.
- Output: `llm_duel_personas/runs/<timestamp>/` (transcript + persona YAML updates).
