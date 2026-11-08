@echo off
title Josepo Servidor - Auxilio Vial Inteligente
cd /d "%~dp0"
echo ============================================================
echo   Iniciando Josepo Servidor en http://localhost:5000 ...
echo ============================================================
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] No se encontro el entorno virtual en 'venv\Scripts\python.exe'.
    pause
    exit /b 1
)
".\venv\Scripts\python.exe" run.py
pause

