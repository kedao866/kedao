#!/usr/bin/env bash
# Refresh the Space copy from the main project. Run after editing kedao-web/backend.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/.."
test -f "$src/backend/server.py"

rm -rf "$here/backend" "$here/frontend"
mkdir -p "$here/backend"
cp "$src/backend/server.py" "$src/backend/engine_web.py" "$src/backend/requirements.txt" "$here/backend/"
cp -r "$src/frontend" "$here/frontend"
echo "synced $(date '+%Y-%m-%d %H:%M:%S')"
