# GOG Library Manager 1.0

A native **GTK4 / Wayland** desktop application for browsing a local GOG game collection, managing cover artwork, and enriching the library with optional **IGDB metadata**.

Version **1.0** is the first stable release of the project.

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
- Native GTK4 interface designed for Linux and Wayland

## Screenshot

A screenshot is intentionally not included in the repository template yet.  
For GitHub, add one as `docs/screenshot.png` and replace this section with:

```markdown
![GOG Library Manager](docs/screenshot.png)
```

## Requirements

The recommended platform is an Arch-based Linux distribution with a Wayland session.

Runtime dependencies:

- Python 3
- GTK 4
- PyGObject
- GdkPixbuf 2
- PyCairo
- Pillow
- requests

### Arch Linux

The easiest method is:

```bash
./install-arch.sh
```

Or install the packages manually:

```bash
sudo pacman -S --needed \
  python \
  gtk4 \
  python-gobject \
  python-cairo \
  python-pillow \
  python-requests
```

You can verify the runtime before launching:

```bash
python3 check_dependencies.py
```

### Other Linux distributions

Install the equivalent GTK4, PyGObject, Cairo, Pillow and requests packages supplied by your distribution.

`requirements.txt` is included for users who intentionally install Python packages with `pip`, but **system packages are recommended for GTK/PyGObject** because GTK itself is a native system dependency.

## Installation

Clone the repository:

```bash
git clone https://github.com/Wummhelm/gog-library-manager.git
cd gog-library-manager
```

Make sure the launcher is executable:

```bash
chmod +x GOG-Library-Manager.sh
```

Start the application:

```bash
./GOG-Library-Manager.sh
```

You can also run the Python file directly:

```bash
python3 gog_library_manager.py
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

## IGDB setup

IGDB functionality is optional, but required for automatic cover downloads and metadata.

The application expects a **Twitch/IGDB Client ID and Client Secret**. Create application credentials in the Twitch Developer Console and enter them under **Settings** in GOG Library Manager.

Useful resources:

- Twitch Developer Console: https://dev.twitch.tv/console
- IGDB API documentation: https://api-docs.igdb.com/

Do **not** commit your personal credentials to this repository.

The application stores its configuration locally in:

```text
~/.config/gog-library-manager/config.json
```

The configuration file is created with restrictive file permissions where supported.

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

The game directories themselves are therefore not used as the permanent cover storage location.

## Controls

- **Single left click:** no action
- **Double left click:** open the corresponding game folder
- **Right click:** replace the cover or show IGDB information
- **Search field:** filter the visible library by title
- **Filter controls:** show complete or incomplete entries
- **Sort menu:** sort by name, year, IGDB rating or completeness
- **Cover size slider:** change the cover grid size

## Wayland

The supplied launcher forces:

```bash
GDK_BACKEND=wayland
```

This matches the platform the application was developed for.

If you deliberately want GTK to choose the backend automatically, remove this line from `GOG-Library-Manager.sh`.

## Updating

Before replacing an older version, backing up the local configuration directory is optional but recommended:

```bash
cp -a ~/.config/gog-library-manager ~/.config/gog-library-manager.backup
```

The cover directory is separate:

```text
~/.local/share/gog-library-manager/covers/
```

## Privacy

GOG Library Manager works on your locally selected game directory.

When IGDB features are used, game-title searches and metadata requests are sent to Twitch/IGDB using the credentials configured by the user.

No analytics or telemetry are implemented by this project.

## Repository structure

```text
.
├── .github/
│   └── workflows/
│       └── syntax-check.yml
├── docs/
│   └── DEPENDENCIES.md
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── GOG-Library-Manager.sh
├── LICENSE
├── README.md
├── RELEASE_NOTES_1.0.md
├── SECURITY.md
├── VERSION
├── check_dependencies.py
├── gog_library_manager.py
├── install-arch.sh
└── requirements.txt
```

## Development check

A lightweight GitHub Actions workflow checks that the Python source compiles syntactically.

Locally:

```bash
python3 -m py_compile gog_library_manager.py
bash -n GOG-Library-Manager.sh
bash -n install-arch.sh
```

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Released under the [MIT License](LICENSE).

## Disclaimer

GOG Library Manager is an independent community project. It is not affiliated with, endorsed by, or sponsored by GOG, CD PROJEKT, Twitch, or IGDB.

GOG, IGDB, Twitch and other names or trademarks belong to their respective owners.
