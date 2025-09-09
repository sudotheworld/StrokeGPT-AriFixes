# Requires: Windows, PowerShell, Python 3.10+, and Ollama installed.
# Pulls models, sets up venv, installs deps, and runs a 30-turn preset duel.

param(
  [string]$ModelA = "qwen2.5:7b",
  # If you have a quantized Llama tag (e.g., llama3.1:8b-instruct-q4_K_M), put it here:
  [string]$ModelB = "llama3.1:8b-instruct-q4_K_M",
  [ValidateSet("sfw","mixed","nsfw")][string]$Mode = "nsfw"
)

$ErrorActionPreference = "Stop"

$duelDir = "$PSScriptRoot\llm_duel_personas"
$arcFile = "$duelDir\interview_arc.md"

Write-Host "==> Pulling models via Ollama..." -ForegroundColor Cyan
& ollama pull $ModelA 2>$null | Out-Null
& ollama pull $ModelB 2>$null | Out-Null

Write-Host "==> Creating Python venv + installing requirements..." -ForegroundColor Cyan
$venv = "$duelDir\.venv"
if (!(Test-Path $venv)) { python -m venv $venv }
& "$venv\Scripts\pip.exe" install --upgrade pip
& "$venv\Scripts\pip.exe" install -r "$duelDir\requirements.txt"

Write-Host "==> Starting Persona Duel (30 turns, mode=$Mode)..." -ForegroundColor Green
$py = "$venv\Scripts\python.exe"
& $py "$duelDir\persona_duel.py" --backend ollama --model-a $ModelA --model-b $ModelB --content-mode $Mode --max-turns 30 --arc-file $arcFile --name-a "Ari" --name-b "Dee"
