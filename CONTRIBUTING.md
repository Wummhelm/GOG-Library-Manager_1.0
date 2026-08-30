# Contributing

Thanks for your interest in GOG Library Manager.

## Development environment

The project targets Python 3, GTK 4 and Wayland.

On Arch Linux:

```bash
sudo pacman -S --needed   python gtk4 python-gobject python-cairo python-pillow python-requests
```

## Before submitting a pull request

Run:

```bash
python3 -m py_compile gog_library_manager.py
bash -n GOG-Library-Manager.sh
bash -n install-arch.sh
```

Please keep changes focused and avoid committing local configuration, credentials, caches or cover images.

## Style

- Keep the GTK4/PyGObject implementation native.
- Preserve German and English UI strings when adding user-facing text.
- Do not embed personal Twitch/IGDB credentials.
- Keep local game files untouched unless a feature explicitly requires access.
