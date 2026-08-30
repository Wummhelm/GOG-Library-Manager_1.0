# GOG Library Manager 1.2

A native **GTK4** desktop application for browsing a local GOG game collection, managing cover artwork, and enriching the library with optional **IGDB metadata**.

Version **1.2** adds automatic activation of a configured Linux mount for the saved GOG games directory.

## Highlights

- Displays the complete local GOG library as a cover grid
- Automatic and manual cover search through IGDB
- Replaces individual covers
- Stores covers centrally outside the game folders
- IGDB metadata including release date, genres, platforms, ratings, developers, publishers and descriptions
- Manual IGDB matching for ambiguous game names
- Search, filters and sorting
- Collection statistics and achievements
- Adjustable cover sizes
- German and English interface
- System, light and dark appearance settings
- Animated dark **Nebula / Aurora** background with subtle particles
- Double-click a game to open its game folder
- Automatic startup mount attempt for GOG directories configured through `/etc/fstab`
- Wayland and X11 support through GTK's automatic backend selection

## Linux support

Installation helpers are included for:

- **Arch Linux** and Arch-based distributions such as Manjaro, EndeavourOS and CachyOS
- **Debian / Ubuntu** and Debian-based distributions such as Linux Mint and Pop!_OS
- **Fedora**
- **openSUSE** with manual installation instructions

## Requirements

Runtime dependencies:

- Python 3
- GTK 4
- PyGObject
- GdkPixbuf 2
- PyCairo
- Pillow
- requests
- Linux `mount` / `findmnt` utilities for automatic mount detection
- NFS client utilities when the GOG collection is stored on NFS

System packages are recommended for GTK/PyGObject.

## Installation

Clone the repository:

```bash
git clone https://github.com/Wummhelm/GOG-Library-Manager_1.0.git
cd GOG-Library-Manager_1.0
chmod +x GOG-Library-Manager.sh install-*.sh
```

### Automatic Linux installer

On Arch-based, Debian/Ubuntu-based and Fedora systems:

```bash
./install-linux.sh
./GOG-Library-Manager.sh
```

### Arch Linux / Manjaro / EndeavourOS / CachyOS

```bash
./install-arch.sh
./GOG-Library-Manager.sh
```

Manual installation:

```bash
sudo pacman -S --needed \
  python gtk4 python-gobject python-cairo \
  python-pillow python-requests nfs-utils
```

`nfs-utils` provides the NFS support programs on Arch Linux.

### Debian / Ubuntu / Linux Mint / Pop!_OS

```bash
./install-debian-ubuntu.sh
./GOG-Library-Manager.sh
```

Manual installation:

```bash
sudo apt update
sudo apt install -y \
  python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
  python3-pil python3-requests nfs-common
```

### Fedora

```bash
./install-fedora.sh
./GOG-Library-Manager.sh
```

Manual installation:

```bash
sudo dnf install -y \
  python3 python3-gobject gtk4 python3-cairo \
  python3-pillow python3-requests nfs-utils
```

### openSUSE

Install the GTK/PyGObject runtime packages appropriate for your release. A typical Tumbleweed setup also uses the `nfs-client` package when accessing an NFS library.

After installing the dependencies:

```bash
./GOG-Library-Manager.sh
```

### Check dependencies

```bash
python3 check_dependencies.py
```

## First start

On first launch, select the directory containing your locally installed or archived GOG games.

The application treats the direct subdirectories of that directory as individual games.

Example:

```text
/mnt/games/GOG/
├── Baldur's Gate/
├── Cyberpunk 2077/
└── The Witcher 3/
```

The selected path is stored locally and reused on later starts.

## Automatic GOG mount at startup

Version 1.2 can automatically activate the system mount containing the saved GOG directory before scanning the library.

The application deliberately **does not store an NFS server address or mount password itself**. Instead it uses the existing Linux mount configuration in `/etc/fstab`.

Startup behavior:

1. The saved GOG path is read from the local configuration.
2. If it is already on an active mounted filesystem, the library opens normally.
3. Otherwise the application searches `/etc/fstab` for the most specific mount point containing the saved GOG path.
4. It first runs `mount <mountpoint>` as the current user.
5. If that fails and `pkexec` is available in a graphical session, it retries through PolicyKit, which may display an authentication dialog.
6. The GOG collection is scanned only after the mount is available.
7. If mounting fails, the application displays an error instead of silently showing an empty collection.

### Example `/etc/fstab` entry for NFS

Replace the server, export and mount path with your own values:

```fstab
server:/export/GOG  /mnt/nfs/Spiele/GOG  nfs  defaults,_netdev,nofail  0  0
```

If your actual NFS mount is a parent directory, that also works. For example:

```fstab
server:/export/Spiele  /mnt/nfs/Spiele  nfs  defaults,_netdev,nofail  0  0
```

and the configured GOG directory may still be:

```text
/mnt/nfs/Spiele/GOG
```

For mounting without an administrator prompt, configure the mount permissions/options according to your Linux distribution and security requirements. Otherwise the application can use `pkexec` when available.

You can test the mount outside the application with:

```bash
mount /mnt/nfs/Spiele/GOG
```

or, if the parent directory is the actual mount point:

```bash
mount /mnt/nfs/Spiele
```

Check the result with:

```bash
findmnt /mnt/nfs/Spiele/GOG
```

## IGDB setup

IGDB functionality is optional, but required for automatic cover downloads and metadata.

The application expects a **Twitch/IGDB Client ID and Client Secret**. Create application credentials in the Twitch Developer Console and enter them under **Settings** in GOG Library Manager.

Do **not** commit your personal credentials to this repository.

Configuration is stored locally in:

```text
~/.config/gog-library-manager/config.json
```

## Data locations

Configuration and IGDB cache:

```text
~/.config/gog-library-manager/
├── config.json
├── igdb_mappings.json
├── igdb_metadata.json
└── igdb_sync_state.json
```

Covers:

```text
~/.local/share/gog-library-manager/covers/<Game Name>/cover.jpg
```

## Controls

- **Single left click:** no action
- **Double left click:** open the corresponding game folder
- **Right click:** replace the cover or show IGDB information
- **Search field:** filter the visible library by title
- **Filter controls:** show complete or incomplete entries
- **Sort menu:** sort by name, year, IGDB rating or completeness
- **Cover size slider:** change the cover grid size

## Wayland and X11

The launcher does not force a display backend. GTK automatically selects Wayland or X11 according to the current desktop session.

## Updating

Before replacing an older version, backing up the local configuration directory is optional but recommended:

```bash
cp -a ~/.config/gog-library-manager ~/.config/gog-library-manager.backup
```

Existing settings, IGDB mappings, metadata and downloaded covers remain in the user's configuration/data directories.

## Privacy

GOG Library Manager works on your locally selected game directory.

When IGDB features are used, game-title searches and metadata requests are sent to Twitch/IGDB using the credentials configured by the user.

No analytics or telemetry are implemented by this project.

## Repository structure

```text
.
├── .github/workflows/syntax-check.yml
├── docs/DEPENDENCIES.md
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── GOG-Library-Manager.sh
├── LICENSE
├── README.md
├── RELEASE_NOTES_1.0.md
├── RELEASE_NOTES_1.2.md
├── SECURITY.md
├── VERSION
├── check_dependencies.py
├── gog_library_manager.py
├── install-arch.sh
├── install-debian-ubuntu.sh
├── install-fedora.sh
├── install-linux.sh
└── requirements.txt
```

## Development check

```bash
python3 -m py_compile gog_library_manager.py
bash -n GOG-Library-Manager.sh
bash -n install-arch.sh
bash -n install-debian-ubuntu.sh
bash -n install-fedora.sh
bash -n install-linux.sh
```

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Released under the [MIT License](LICENSE).

## Disclaimer

GOG Library Manager is an independent community project. It is not affiliated with, endorsed by, or sponsored by GOG, CD PROJEKT, Twitch, or IGDB.
