#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The application is developed for native GTK4/Wayland.
# Remove this line if you explicitly want GTK to choose another backend.
export GDK_BACKEND=wayland

exec python3 "$SCRIPT_DIR/gog_library_manager.py" "$@"
