#!/usr/bin/env python3
"""Check runtime dependencies without starting the GUI."""

import importlib
import shutil
import sys

MODULES = [
    ("requests", "requests"),
    ("PIL", "Pillow"),
    ("cairo", "pycairo / python-cairo"),
    ("gi", "PyGObject / python-gobject"),
]

missing = []

for module, package in MODULES:
    try:
        importlib.import_module(module)
        print(f"[OK] {package}")
    except Exception as exc:
        missing.append((package, str(exc)))
        print(f"[MISSING] {package}: {exc}")

if missing:
    print("\nOne or more dependencies are missing.")
    print("Use ./install-linux.sh on a supported distribution.")
    sys.exit(1)

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gtk, GdkPixbuf  # noqa: F401
    print("[OK] GTK 4 / GdkPixbuf 2")
except Exception as exc:
    print(f"[MISSING] GTK 4 / GdkPixbuf 2: {exc}")
    sys.exit(1)

for command in ("mount", "findmnt"):
    if shutil.which(command):
        print(f"[OK] {command}")
    else:
        print(f"[WARNING] {command} not found; automatic mount support may be unavailable")

if shutil.which("pkexec"):
    print("[OK] pkexec (optional PolicyKit fallback)")
else:
    print("[INFO] pkexec not found; privileged mount fallback is unavailable")

print("\nAll required GUI runtime dependencies are available.")
