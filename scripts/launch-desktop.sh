#!/usr/bin/env bash
# ImagineAI desktop launcher.
# Ensures the local backend is running, opens the Tauri window, and stops the
# backend again when the window closes (only if this launcher started it).
set -u

APP_DIR="/home/pwintri2/imagineai"
PORT="8799"
BIN="${APP_DIR}/src-tauri/target/release/imagineai"
LOG="/tmp/imagineai-server.log"
export COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"
export IMAGINEAI_PORT="${PORT}"

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; }

started_server=0
SERVER_PID=""
if ! port_open; then
  # `exec` so $! is the python PID itself, letting us stop exactly what we start.
  ( cd "${APP_DIR}" && exec python3 server.py --host 127.0.0.1 --port "${PORT}" >"${LOG}" 2>&1 ) &
  SERVER_PID=$!
  started_server=1
  for _ in $(seq 1 100); do port_open && break; sleep 0.15; done
fi

# Prefer the native Tauri window; fall back to the default browser if the
# binary hasn't been built yet.
if [ -x "${BIN}" ]; then
  "${BIN}"
else
  xdg-open "http://127.0.0.1:${PORT}" >/dev/null 2>&1
  # Keep the backend alive while the browser tab is open (best-effort).
  if [ "${started_server}" = "1" ]; then
    echo "ImagineAI: Tauri binary not built; opened in browser. Press Ctrl+C to stop the server." >&2
    wait
  fi
fi

if [ "${started_server}" = "1" ] && [ -n "${SERVER_PID}" ]; then
  kill "${SERVER_PID}" 2>/dev/null
fi
