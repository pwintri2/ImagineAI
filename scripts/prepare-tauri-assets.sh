#!/usr/bin/env sh
# Stage the web frontend into desktop-dist/ for Tauri's frontendDist.
set -eu
cd "$(dirname "$0")/.."
rm -rf desktop-dist
mkdir -p desktop-dist
cp -r web/. desktop-dist/
