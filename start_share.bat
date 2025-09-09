@echo off
REM This batch file invokes the PowerShell launch script with default settings.
REM Adjust the -Port or -Pin parameters as desired.

set SCRIPT_DIR=%~dp0
powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_share.ps1" -Port 5000 -Pin 1234