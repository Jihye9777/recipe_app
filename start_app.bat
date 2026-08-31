@echo off
cd /d "%~dp0"
"C:\ProgramData\anaconda3\Scripts\conda.exe" run -n env_recipe python server.py
