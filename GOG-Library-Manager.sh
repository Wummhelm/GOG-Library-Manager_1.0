#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# GTK chooses Wayland or X11 automatically.
exec python3 "$SCRIPT_DIR/gog_library_manager.py" "$@"
