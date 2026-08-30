#!/usr/bin/env bash
set -euo pipefail
sudo dnf install -y \
  python3 \
  python3-gobject \
  gtk4 \
  python3-cairo \
  python3-pillow \
  python3-requests \
  nfs-utils

echo
echo "Dependencies installed. Start with: ./GOG-Library-Manager.sh"
