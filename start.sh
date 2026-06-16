#!/usr/bin/env bash
# Launch ImagineAI. Requires Python 3 and a running ComfyUI (default 127.0.0.1:8188).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${IMAGINEAI_PORT:-8799}"
echo "Starting ImagineAI on http://127.0.0.1:${PORT}"
echo "  (ComfyUI expected at ${COMFYUI_URL:-http://127.0.0.1:8188})"
exec python3 server.py --port "${PORT}" "$@"
