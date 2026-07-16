#!/bin/bash
# Double-click launcher for the macOS edition.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="${HOME}/Applications/ImagineAI.app"

if [ ! -d "${APP_PATH}" ]; then
  "${ROOT_DIR}/macos/install-macos-app.sh"
fi

open "${APP_PATH}"
