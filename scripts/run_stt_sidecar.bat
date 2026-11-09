@echo off
rem STT sidecar launcher (port 8001) - must run under the STT venv
setlocal
set ROOT=%~dp0..
set PYTHONUNBUFFERED=1
"%ROOT%\.venvs\runtime\Scripts\python.exe" -u -m sidecars.stt_server 1> "%TEMP%\mallo_stt_out.log" 2> "%TEMP%\mallo_stt_err.log"
