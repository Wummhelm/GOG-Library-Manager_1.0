#!/usr/bin/env bash
set -euo pipefail

echo "Installing GOG Library Manager runtime dependencies for Arch Linux..."
sudo pacman -S --needed     python     gtk4     python-gobject     python-cairo     python-pillow     python-requests

echo
echo "Dependencies installed."
echo "Start the application with:"
echo "  ./GOG-Library-Manager.sh"
