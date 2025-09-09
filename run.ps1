Param()
$ErrorActionPreference = "Stop"
Write-Host ">>> Checking Python..."
python --version
Write-Host ">>> Ensuring dependencies..."
pip install -r requirements.txt
Write-Host ">>> Checking Ollama..."
try {
    Invoke-WebRequest http://127.0.0.1:11434/api/tags -UseBasicParsing | Out-Null
} catch {
    Write-Host "Ollama not responding. Start Ollama Desktop or run 'ollama serve'." ; exit 1
}
Write-Host ">>> Starting StrokeGPT..."
$env:FLASK_ENV="production"
python app.py