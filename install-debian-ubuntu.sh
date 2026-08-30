#!/usr/bin/env bash
set -euo pipefail
sudo apt update
sudo apt install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-pil python3-requests
echo "Dependencies installed. Start with: ./GOG-Library-Manager.sh"
