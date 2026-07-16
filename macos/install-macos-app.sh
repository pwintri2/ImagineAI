#!/bin/bash
# Build and install the native ImagineAI macOS wrapper for this checkout.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/.wrapper-build"
APP_DIR="${HOME}/Applications/ImagineAI.app"
CONTENTS_DIR="${APP_DIR}/Contents"

command -v xcrun >/dev/null 2>&1 || {
  echo "Xcode command-line tools are required (xcrun was not found)." >&2
  exit 1
}

mkdir -p "${BUILD_DIR}" "${CONTENTS_DIR}/MacOS" "${CONTENTS_DIR}/Resources"

xcrun swiftc "${ROOT_DIR}/macos/ImagineAI.swift" \
  -o "${BUILD_DIR}/ImagineAI" \
  -framework Cocoa \
  -framework WebKit \
  -framework UniformTypeIdentifiers

install -m 755 "${BUILD_DIR}/ImagineAI" "${CONTENTS_DIR}/MacOS/ImagineAI"
install -m 644 "${ROOT_DIR}/macos/Info.plist" "${CONTENTS_DIR}/Info.plist"
install -m 644 "${ROOT_DIR}/src-tauri/icons/icon.icns" "${CONTENTS_DIR}/Resources/AppIcon.icns"
plutil -replace ImagineAIRepoPath -string "${ROOT_DIR}" "${CONTENTS_DIR}/Info.plist"
codesign --force --deep --sign - "${APP_DIR}"
codesign --verify --deep --strict "${APP_DIR}"

echo "Installed ${APP_DIR}"
