# Dependencies

## Runtime

| Component | Purpose | Arch Linux package |
|---|---|---|
| Python 3 | Application runtime | `python` |
| GTK 4 | Native graphical interface | `gtk4` |
| PyGObject | Python bindings for GTK/GIO/GLib | `python-gobject` |
| PyCairo | Animated background drawing | `python-cairo` |
| GdkPixbuf 2 | Image loading/scaling used through GTK bindings | provided through GTK/GdkPixbuf packages |
| Pillow | Image conversion and validation | `python-pillow` |
| requests | Twitch/IGDB HTTPS requests | `python-requests` |

Recommended Arch Linux command:

```bash
sudo pacman -S --needed \
  python gtk4 python-gobject python-cairo python-pillow python-requests
```

## Optional service

IGDB features require user-provided Twitch application credentials:

- Client ID
- Client Secret

The credentials are used to obtain an OAuth token from Twitch and to query the IGDB API.

The application can still browse the local GOG directory without IGDB credentials, but cover/metadata functions that depend on IGDB will not be available.

## Python package installation

`requirements.txt` contains:

```text
requests>=2.31,<3
Pillow>=10,<13
pycairo>=1.25
PyGObject>=3.48
```

For GTK applications on Linux, distribution packages are preferred over a pure `pip` environment because GTK itself and the introspection libraries are native system components.
