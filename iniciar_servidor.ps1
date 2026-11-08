# Script PowerShell para iniciar Josepo
Set-Location $PSScriptRoot
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Iniciando Josepo Servidor en http://localhost:5000 ..." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "[ERROR] No se encontro el entorno virtual en '.\venv\Scripts\python.exe'." -ForegroundColor Red
    pause
    exit 1
}

& ".\venv\Scripts\python.exe" run.py

