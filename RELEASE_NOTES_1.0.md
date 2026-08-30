# GOG Library Manager 1.0

GOG Library Manager 1.0 is the first stable public release.

The application provides a native GTK4 interface for a local GOG collection, with a cover grid, IGDB-powered artwork and metadata, library statistics, filters, sorting, achievements and a permanently animated dark Aurora/Nebula background.

## Recommended platform

- Arch Linux or another modern Linux distribution
- Wayland
- GTK 4

## Install on Arch Linux

```bash
./install-arch.sh
./GOG-Library-Manager.sh
```

## IGDB

For cover and metadata features, enter a Twitch/IGDB Client ID and Client Secret in the application settings.

## Data

Configuration:

```text
~/.config/gog-library-manager/
```

Covers:

```text
~/.local/share/gog-library-manager/covers/
```

## Upgrade note

This release keeps the centralized cover storage introduced during development. Existing centralized covers and configuration use the same locations.
