@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
if exist ".venv-graph\Scripts\python.exe" (
  ".venv-graph\Scripts\python.exe" -X utf8 -u server.py
) else (
  "C:\ProgramData\anaconda3\Scripts\conda.exe" run --no-capture-output -n env_recipe_graph python -X utf8 -u server.py
)
pause
