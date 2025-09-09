Param(
    [int]$Port = 5000,
    [string]$Pin = ""
)

<#
This PowerShell script automates launching the StrokeGPT app and opening a
public Cloudflare tunnel. It performs the following steps:

1. Ensures a Python virtual environment exists and installs dependencies from
   `requirements.txt`.
2. Copies `.env.example` to `.env` if no `.env` file is present.
3. Sets environment variables for Flask (`FLASK_ENV=production`, `PORT`, and
   optionally `ROOM_PIN` if a pin is supplied).
4. Starts the Flask app in the background, logging output to `app.log`.
5. Waits up to ~30 seconds for the `/health` endpoint to become available.
6. Installs Cloudflared via winget if it is not already installed.
7. Launches a quick Cloudflare tunnel pointed at the app and extracts the
   public URL from the tunnel output.
8. Opens the public URL in the default browser and keeps the tunnel
   process running. When the tunnel exits, the Flask process is also
   terminated.
>
Example usage:
```
# run at default port 5000 without PIN
powershell -ExecutionPolicy Bypass -File start_share.ps1

# run with a custom port and PIN
powershell -ExecutionPolicy Bypass -File start_share.ps1 -Port 6000 -Pin 1234
```
>
Note: Cloudflare quick tunnels are best-effort and not intended for
production use. See Cloudflare’s docs for details.
#>

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# Ensure a .env file exists
if (!(Test-Path '.env') -and (Test-Path '.env.example')) {
    Copy-Item '.env.example' '.env'
}

# Create a virtual environment if it doesn't exist
if (!(Test-Path '.venv')) {
    & py -m venv .venv
}
$pythonExe = Join-Path '.venv' 'Scripts' 'python.exe'

# Upgrade pip and install dependencies
& $pythonExe -m pip install --quiet --upgrade pip
if (Test-Path 'requirements.txt') {
    & $pythonExe -m pip install --quiet -r 'requirements.txt'
}

# Set runtime environment variables
$env:FLASK_ENV = 'production'
$env:PORT = $Port.ToString()
if ($Pin) {
    $env:ROOM_PIN = $Pin
}

# Start the Flask application
$logFile = Join-Path $PSScriptRoot 'app.log'
$flaskProcess = Start-Process -FilePath $pythonExe -ArgumentList 'app.py' \
    -RedirectStandardOutput $logFile -RedirectStandardError $logFile \
    -PassThru

# Wait until the /health endpoint returns a 200 or a timeout occurs
$healthUrl = "http://127.0.0.1:$Port/health"
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { break }
    } catch {}
    Start-Sleep -Seconds 1
}

# Install cloudflared if missing
if (-not (Get-Command 'cloudflared' -ErrorAction SilentlyContinue)) {
    try {
        winget install --id Cloudflare.cloudflared -e --source winget
    } catch {
        Write-Warning 'Could not install cloudflared via winget; please install it manually.'
    }
}

# Start the Cloudflare tunnel
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'cloudflared'
$psi.Arguments = "tunnel --url http://127.0.0.1:$Port --no-autoupdate"
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$tunnelProcess = [System.Diagnostics.Process]::Start($psi)

# Parse the public URL from tunnel output
$publicUrl = $null
$deadline = (Get-Date).AddSeconds(30)
while (-not $publicUrl -and (Get-Date) -lt $deadline) {
    $line = $tunnelProcess.StandardOutput.ReadLine()
    if ($line -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
        $publicUrl = $Matches[0]
    }
}
if ($publicUrl) {
    if ($Pin) { $publicUrl = "$publicUrl/?pin=$Pin" }
    Write-Host "\n🌐 Tunnel URL: $publicUrl\n"
    Start-Process $publicUrl
} else {
    Write-Warning 'Failed to obtain Cloudflare tunnel URL.'
}

# Keep processes alive; when the tunnel exits, terminate the Flask process
$tunnelProcess.WaitForExit() | Out-Null
if (-not $flaskProcess.HasExited) {
    Stop-Process -Id $flaskProcess.Id -Force
}