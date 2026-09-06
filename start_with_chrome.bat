@echo off
setlocal
cd /d "%~dp0"
echo Starting HanipNote...
echo Open http://localhost:8000 in your browser.
"C:\Users\User\.conda\envs\env_recipe\python.exe" -u server.py
