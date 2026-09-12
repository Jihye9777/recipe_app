@echo off
setlocal
cd /d "%~dp0"
echo Docker Desktop must be running with virtualization enabled.
"C:\Program Files\Docker\Docker\resources\bin\docker.exe" compose up -d
if errorlevel 1 (
  echo Weaviate did not start. Check Docker Desktop and README.md.
) else (
  echo Weaviate: http://127.0.0.1:8080/v1/.well-known/ready
)
pause
