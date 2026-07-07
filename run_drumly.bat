@echo off
REM Lanzador de Drumly. Usa el Python del entorno virtual (.venv).
REM Muestra consola para ver errores si algo falla.
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
