@echo off
rem ============================================================
rem  Mallo local real-model test server
rem  STT: WhisperMediumSTT(merged-bf16) sidecar - STT venv process
rem  TTS: MeloTTS(G_2800, speaker 10) - .venvs\runtime main server process
rem  Browser: http://127.0.0.1:8000
rem  Logs: %TEMP%\mallo_stt_*.log / mallo_server_*.log
rem ============================================================
setlocal
set ROOT=%~dp0..
set VENV=%ROOT%\.venvs\runtime
set PYTHONUNBUFFERED=1

rem 1) start STT sidecar (port 8001)
start "mallo-stt-sidecar" /min "%ROOT%\scripts\run_stt_sidecar.bat"

rem 2) wait for sidecar health
powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){try{Invoke-WebRequest http://127.0.0.1:8001/health -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0}catch{Start-Sleep 2}}; exit 1"
if errorlevel 1 (
  echo [ERROR] STT sidecar failed - check %%TEMP%%\mallo_stt_err.log
  pause
  exit /b 1
)

rem 3) main server (uses sidecar on port 8001)
"%VENV%\Scripts\python.exe" -u "%ROOT%\scripts\run_local_server.py" ^
  --host 127.0.0.1 --port 8000 ^
  --stt http ^
  --stt-model "http://127.0.0.1:8001/transcribe" ^
  --tts melo ^
  --tts-ckpt "%ROOT%\logs\mallo-friendly\G_2800.pth" ^
  --tts-config "%ROOT%\data\tts\runs\melotts\config.json" ^
  --tts-speaker 10 %* 1> "%TEMP%\mallo_server_out.log" 2> "%TEMP%\mallo_server_err.log"
