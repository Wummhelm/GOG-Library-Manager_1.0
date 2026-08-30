#!/usr/bin/env bash
set -euo pipefail
. /etc/os-release
case "${ID:-}" in
  arch|manjaro|endeavouros|cachyos) exec "$(dirname "$0")/install-arch.sh" ;;
  ubuntu|debian|linuxmint|pop) exec "$(dirname "$0")/install-debian-ubuntu.sh" ;;
  fedora) exec "$(dirname "$0")/install-fedora.sh" ;;
esac
case " ${ID_LIKE:-} " in
  *" arch "*) exec "$(dirname "$0")/install-arch.sh" ;;
  *" debian "*|*" ubuntu "*) exec "$(dirname "$0")/install-debian-ubuntu.sh" ;;
  *" fedora "*|*" rhel "*) exec "$(dirname "$0")/install-fedora.sh" ;;
esac
echo "No automatic installer for ${PRETTY_NAME:-$ID}. See README.md."
exit 2
