#!/usr/bin/env bash
set -euo pipefail
sudo pacman -S --needed \
  python \
  gtk4 \
  python-gobject \
  python-cairo \
  python-pillow \
  python-requests \
  nfs-utils

echo
echo "Dependencies installed. Start with: ./GOG-Library-Manager.sh"
