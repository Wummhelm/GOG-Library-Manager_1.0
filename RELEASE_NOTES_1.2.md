# GOG Library Manager 1.2

## What's new

- Automatically checks the configured GOG library mount during application startup.
- Uses the existing `/etc/fstab` configuration instead of storing network server credentials inside the application.
- Detects a matching mount point even when the configured GOG directory is a subdirectory of that mount.
- Attempts a normal `mount` first and can retry with `pkexec` when PolicyKit is available.
- Shows a GTK error message when the library cannot be mounted instead of displaying an empty collection.
- Adds NFS client packages to the Arch, Debian/Ubuntu and Fedora installation helpers.
- Keeps the multi-distribution installer introduced for the 1.1 update.
- Allows GTK to select Wayland or X11 automatically.

## Upgrade

Existing configuration, IGDB mappings, metadata and covers remain compatible with this release.

For an NFS collection, make sure the mount containing the configured GOG directory exists in `/etc/fstab`.
