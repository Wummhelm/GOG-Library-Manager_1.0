#!/usr/bin/env python3
"""GOG Library Manager 1.0

GTK4 application for managing a local GOG game library, cover artwork,
and optional IGDB metadata.

Project license: MIT
"""
import json
import math
import random
import os
import re
import sys
import shutil
import time
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from difflib import SequenceMatcher

import requests
from PIL import Image

import cairo
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib


VERSION = "1.0"
APP_ID = "de.goglibrarymanager.app.v1"
COVER_FILENAME = "cover.jpg"

CONFIG_DIR = Path.home() / ".config" / "gog-library-manager"
CONFIG_FILE = CONFIG_DIR / "config.json"
IGDB_MAPPING_FILE = CONFIG_DIR / "igdb_mappings.json"
IGDB_METADATA_FILE = CONFIG_DIR / "igdb_metadata.json"
IGDB_SYNC_STATE_FILE = CONFIG_DIR / "igdb_sync_state.json"

# v69: Cover liegen nicht mehr in den Spieleordnern.
DATA_DIR = Path.home() / ".local" / "share" / "gog-library-manager"
COVER_DIR = DATA_DIR / "covers"

AUTO_MATCH_SCORE = 0.88
AUTO_MATCH_MARGIN = 0.10

COVER_WIDTH = 240
COVER_HEIGHT = 340
RESULT_COVER_WIDTH = 190
RESULT_COVER_HEIGHT = 270

COVER_SIZE_PRESETS = {
    0: ("Klein", 170, 240, 174, 286, 8),
    1: ("Mittel", 210, 300, 214, 346, 6),
    2: ("Groß", 240, 340, 244, 386, 5),
}


# ============================================================
# CONFIG / HELPERS
# ============================================================

def load_config():
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(client_id, client_secret, gog_dir=None, cover_size=None, language=None, theme=None):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    old_data = load_config()

    data = {
        "client_id": client_id or "",
        "client_secret": client_secret or "",
        "cover_size": (
            int(cover_size)
            if cover_size is not None
            else int(old_data.get("cover_size", 2))
        ),
        "language": (
            language
            if language in ("de", "en")
            else old_data.get("language", "de")
        ),
        "theme": (
            theme
            if theme in ("system", "light", "dark")
            else old_data.get("theme", "system")
        ),
    }

    if gog_dir:
        data["gog_dir"] = str(gog_dir)
    elif old_data.get("gog_dir"):
        data["gog_dir"] = old_data["gog_dir"]

    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass



def load_igdb_mappings():
    try:
        if IGDB_MAPPING_FILE.exists():
            data = json.loads(
                IGDB_MAPPING_FILE.read_text(encoding="utf-8")
            )
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_igdb_mappings(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    IGDB_MAPPING_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_igdb_metadata():
    try:
        if IGDB_METADATA_FILE.exists():
            data = json.loads(
                IGDB_METADATA_FILE.read_text(encoding="utf-8")
            )
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_igdb_metadata(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    IGDB_METADATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_igdb_sync_state():
    try:
        if IGDB_SYNC_STATE_FILE.exists():
            data = json.loads(
                IGDB_SYNC_STATE_FILE.read_text(encoding="utf-8")
            )
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_igdb_sync_state(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    IGDB_SYNC_STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def clean_game_title_for_search(name):
    cleaned = name

    # Common release/edition suffixes that often hurt IGDB matching.
    patterns = [
        r"\b(game of the year|goty)\b",
        r"\bcomplete edition\b",
        r"\bcollector'?s edition\b",
        r"\bdeluxe edition\b",
        r"\bgold edition\b",
        r"\bultimate edition\b",
        r"\benhanced edition\b",
        r"\bremastered\b",
        r"\bremaster\b",
        r"\bspecial edition\b",
        r"\bdigital edition\b",
        r"\bclassic\b",
        r"\banniversary edition\b",
    ]

    for pattern in patterns:
        cleaned = re.sub(
            pattern,
            " ",
            cleaned,
            flags=re.IGNORECASE
        )

    cleaned = re.sub(r"[\[\]\(\)_]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_:")
    return cleaned or name


def normalize_name(name):
    name = name.lower()
    name = re.sub(r"[^a-z0-9äöüß ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def similarity(name1, name2):
    return SequenceMatcher(
        None,
        normalize_name(name1),
        normalize_name(name2)
    ).ratio()


def get_token(client_id, client_secret):
    response = requests.post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def search_game(game_name, client_id, token):
    escaped = game_name.replace('"', '\\"')

    query = (
        f'search "{escaped}";\n'
        'fields name,cover.image_id;\n'
        'limit 20;'
    )

    response = requests.post(
        "https://api.igdb.com/v4/games",
        headers={
            "Client-ID": client_id,
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain",
        },
        data=query,
        timeout=15,
    )
    response.raise_for_status()

    results = []

    for game in response.json():
        if not game.get("cover"):
            continue

        game["_score"] = similarity(
            game_name,
            game.get("name", "")
        )
        results.append(game)

    return sorted(
        results,
        key=lambda game: game["_score"],
        reverse=True
    )


def cover_url(image_id):
    return (
        "https://images.igdb.com/igdb/image/upload/"
        f"t_cover_big/{image_id}.jpg"
    )


def scaled_pixbuf_from_file(path, width, height):
    return GdkPixbuf.Pixbuf.new_from_file_at_scale(
        str(path),
        width,
        height,
        True,
    )


def pixbuf_from_bytes(data, width, height):
    loader = GdkPixbuf.PixbufLoader.new()
    loader.write(data)
    loader.close()

    pixbuf = loader.get_pixbuf()

    if not pixbuf:
        raise RuntimeError("Bild konnte nicht geladen werden.")

    scaled = pixbuf.scale_simple(
        width,
        height,
        GdkPixbuf.InterpType.BILINEAR
    )

    return scaled if scaled else pixbuf



TRANSLATIONS = {
    "de": {
        "app_title": "GOG Library Manager – v1.0",
        "missing_covers": "🔎 Fehlende Cover suchen",
        "reload": "↻ Sammlung neu laden",
        "search_placeholder": "Spiele suchen …",
        "settings": "⚙ Einstellungen",
        "status_default": "Doppelklick auf ein Spiel: Spieleordner öffnen",
        "library": "Bibliothek",
        "cover_size": "Covergröße",
        "small": "Klein",
        "large": "Groß",
        "replace_cover": "🔄 Cover ersetzen",
        "game_info": "🎮 Spielinformationen (IGDB)",
        "first_run_title": "GOG Library Manager einrichten",
        "first_run_heading": "GOG-Spieleordner auswählen",
        "first_run_text": (
            "Bitte wähle den Ordner aus, in dem sich deine GOG-Spiele befinden. "
            "Der Ordner wird gespeichert und beim nächsten Start automatisch verwendet."
        ),
        "quit": "Beenden",
        "select_folder": "📁 Ordner auswählen",
        "ready": "Bereit",
        "settings_title": "Einstellungen",
        "settings_heading": "IGDB & GOG-Ordner",
        "client_id": "Client ID",
        "client_secret": "Client Secret",
        "gog_folder": "GOG-Spieleordner",
        "no_folder": "Kein Ordner ausgewählt",
        "change": "📁 Ändern",
        "cancel": "Abbrechen",
        "save": "💾 Speichern",
        "language": "Sprache",
        "appearance": "Darstellung",
        "theme_system": "Automatisch (System)",
        "theme_light": "Hell",
        "theme_dark": "Dunkel",
        "german": "Deutsch",
        "english": "English",
        "credentials_missing_title": "Zugangsdaten fehlen",
        "credentials_missing_text": "Bitte Client ID und Client Secret eintragen.",
        "igdb_credentials_missing": "IGDB Zugangsdaten fehlen",
        "igdb_credentials_missing_text": (
            "Bitte zuerst unter Einstellungen die Client ID und das Client Secret eintragen."
        ),
        "folder_dialog_title": "GOG-Spieleordner auswählen",
        "igdb_info_loading": "IGDB-Spielinformationen werden geladen: {game}",
        "igdb_searching": "IGDB-Treffer werden gesucht: {game}",
        "igdb_choose_title": "IGDB-Spiel auswählen – {game}",
        "igdb_choose_text": (
            "Bitte den passenden IGDB-Eintrag auswählen. "
            "Die Auswahl wird für dieses Spiel gespeichert."
        ),
        "select": "Auswählen",
        "unknown_title": "Unbekannter Titel",
        "source_igdb": "Quelle: IGDB",
        "developer": "Entwickler",
        "publisher": "Publisher",
        "release": "Veröffentlichung",
        "genre": "Genre",
        "themes": "Themen",
        "game_modes": "Spielmodi",
        "perspective": "Perspektive",
        "platforms": "Plattformen",
        "franchise": "Franchise",
        "collection": "Reihe / Sammlung",
        "overall_rating": "IGDB-Gesamtwertung",
        "critic_rating": "Kritikerwertung",
        "user_rating": "Nutzerwertung",
        "description": "Beschreibung",
        "storyline": "Handlung",
        "no_description": "Für dieses Spiel ist bei IGDB keine Beschreibung hinterlegt.",
        "choose_igdb": "🎯 IGDB-Spiel auswählen",
        "open_igdb": "Auf IGDB öffnen",
        "close": "Schließen",
        "igdb_no_info": "Keine IGDB-Spielinformationen für „{game}“.",
        "igdb_no_match": "IGDB hat für dieses Spiel keinen passenden Eintrag gefunden.",
        "igdb_no_results": "IGDB hat keine passenden Treffer gefunden.",
        "choose_folder_first": "Bitte zuerst einen GOG-Spieleordner auswählen.",
        "games_count": "{count} Spiele",
        "no_gog_folder": "Kein GOG-Ordner ausgewählt",
        "data_reset": "Daten zurücksetzen",
        "delete_covers": "🗑 Alle Cover löschen",
        "delete_mappings": "🗑 IGDB-Metadaten löschen",
        "delete_all_data": "⚠ Cover & IGDB-Metadaten löschen",
        "delete_covers_confirm": "Alle Cover löschen?",
        "delete_covers_detail": "{count} Cover-Datei(en) werden dauerhaft gelöscht. Die Spiele selbst bleiben unverändert.",
        "delete_mappings_confirm": "IGDB-Metadaten löschen?",
        "delete_mappings_detail": "Alle gespeicherten IGDB-Metadaten und Spiel-Zuordnungen werden gelöscht.",
        "delete_all_confirm": "Cover und IGDB-Zuordnungen löschen?",
        "delete_all_detail": "{count} Cover-Datei(en) und alle gespeicherten IGDB-Zuordnungen werden dauerhaft gelöscht. Spiele und Einstellungen bleiben erhalten.",
        "delete": "Löschen",
        "deleted_covers": "{count} Cover wurden gelöscht.",
        "deleted_mappings": "Die IGDB-Metadaten und Zuordnungen wurden gelöscht.",
        "deleted_all": "{count} Cover und die IGDB-Zuordnungen wurden gelöscht.",
        "stat_games": "Spiele",
        "stat_total": "Insgesamt",
        "stat_complete": "Vollständig",
        "stat_complete_sub": "Cover + Metadaten",
        "stat_cover_missing": "Cover fehlt",
        "stat_cover_missing_sub": "Ohne Cover",
        "stat_metadata_missing": "Metadaten fehlt",
        "stat_metadata_missing_sub": "Ohne Metadaten",
        "current_achievement": "AKTUELLES ACHIEVEMENT",
        "all_achievements": "Alle Erfolge ▾",
        "achievement_archived": "{target} Spiele vollständig archiviert",
        "achievement_new": "Neu freigeschaltet – {target} Spiele vollständig archiviert.",
        "achievement_unlocked": "Erfolg freigeschaltet: mindestens {target} Spiele vollständig archiviert. Aktuell: {count}.",
        "achievement_remaining": "Noch {count} vollständig archivierte Spiele bis zum ersten Erfolg.",
        "achievement_perfect": "Perfekte Sammlung",
        "achievement_perfect_text": "Alle {total} Spiele besitzen Cover und Metadaten.",
        "achievement_cover_curator": "Cover-Kurator",
        "achievement_cover_curator_text": "Alle Spiele haben ein Cover",
        "achievement_data_archivist": "Datenarchivar",
        "achievement_data_archivist_text": "Alle Spiele haben Metadaten",
        "achievement_perfect_collection": "Perfekte Sammlung",
        "achievement_perfect_collection_text": "Cover + Metadaten vollständig",
        "achievement_collector_1": "Sammler I",
        "achievement_collector_2": "Sammler II",
        "achievement_collector_3": "Sammler III",
        "achievement_collector_4": "Sammler IV",
        "achievement_librarian": "Bibliothekar",
        "achievement_grand_archivist": "Großarchivar",
        "achievement_legendary": "Legendäre Sammlung",
        "tooltip_complete": "Cover und Metadaten vollständig",
        "tooltip_cover_missing": "Cover fehlt",
        "tooltip_metadata_missing": "Metadaten fehlen",
        "tooltip_both_missing": "Cover und Metadaten fehlen",
        "filter_all": "Alle",
        "filter_complete": "✓ Vollständig",
        "filter_cover_missing": "⚠ Cover fehlt",
        "filter_metadata_missing": "ⓘ Metadaten fehlt",
        "sort_label": "Sortieren:",
        "sort_name_az": "Name A–Z",
        "sort_name_za": "Name Z–A",
        "sort_year_new": "Jahr: neu → alt",
        "sort_year_old": "Jahr: alt → neu",
        "sort_rating_high": "IGDB-Wertung: hoch → niedrig",
        "sort_incomplete": "Unvollständige zuerst",
        "filter_sort_title": "FILTER & SORTIERUNG",
        "bottom_sort_title": "Alphabetisch:",
        "bottom_sort_az": "A–Z",
        "bottom_sort_za": "Z–A",
    },
    "en": {
        "app_title": "GOG Library Manager – v1.0",
        "missing_covers": "🔎 Find missing covers",
        "reload": "↻ Reload library",
        "search_placeholder": "Search games …",
        "settings": "⚙ Settings",
        "status_default": "Double-click a game: open game folder",
        "library": "Library",
        "cover_size": "Cover size",
        "small": "Small",
        "large": "Large",
        "replace_cover": "🔄 Replace cover",
        "game_info": "🎮 Game information (IGDB)",
        "first_run_title": "Set up GOG Library Manager",
        "first_run_heading": "Select GOG games folder",
        "first_run_text": (
            "Please select the folder that contains your GOG games. "
            "The folder will be saved and used automatically next time."
        ),
        "quit": "Quit",
        "select_folder": "📁 Select folder",
        "ready": "Ready",
        "settings_title": "Settings",
        "settings_heading": "IGDB & GOG folder",
        "client_id": "Client ID",
        "client_secret": "Client Secret",
        "gog_folder": "GOG games folder",
        "no_folder": "No folder selected",
        "change": "📁 Change",
        "cancel": "Cancel",
        "save": "💾 Save",
        "language": "Language",
        "appearance": "Appearance",
        "theme_system": "Automatic (System)",
        "theme_light": "Light",
        "theme_dark": "Dark",
        "german": "Deutsch",
        "english": "English",
        "credentials_missing_title": "Missing credentials",
        "credentials_missing_text": "Please enter Client ID and Client Secret.",
        "igdb_credentials_missing": "IGDB credentials missing",
        "igdb_credentials_missing_text": (
            "Please enter your Client ID and Client Secret in Settings first."
        ),
        "folder_dialog_title": "Select GOG games folder",
        "igdb_info_loading": "Loading IGDB game information: {game}",
        "igdb_searching": "Searching IGDB matches: {game}",
        "igdb_choose_title": "Select IGDB game – {game}",
        "igdb_choose_text": (
            "Please select the matching IGDB entry. "
            "The selection will be saved for this game."
        ),
        "select": "Select",
        "unknown_title": "Unknown title",
        "source_igdb": "Source: IGDB",
        "developer": "Developer",
        "publisher": "Publisher",
        "release": "Release date",
        "genre": "Genre",
        "themes": "Themes",
        "game_modes": "Game modes",
        "perspective": "Perspective",
        "platforms": "Platforms",
        "franchise": "Franchise",
        "collection": "Series / Collection",
        "overall_rating": "IGDB overall rating",
        "critic_rating": "Critic rating",
        "user_rating": "User rating",
        "description": "Description",
        "storyline": "Storyline",
        "no_description": "No description is available for this game on IGDB.",
        "choose_igdb": "🎯 Select IGDB game",
        "open_igdb": "Open on IGDB",
        "close": "Close",
        "igdb_no_info": "No IGDB game information for “{game}”.",
        "igdb_no_match": "IGDB did not find a matching entry for this game.",
        "igdb_no_results": "IGDB did not find any matching results.",
        "choose_folder_first": "Please select a GOG games folder first.",
        "games_count": "{count} games",
        "no_gog_folder": "No GOG folder selected",
        "data_reset": "Reset data",
        "delete_covers": "🗑 Delete all covers",
        "delete_mappings": "🗑 Delete IGDB metadata",
        "delete_all_data": "⚠ Delete covers & IGDB metadata",
        "delete_covers_confirm": "Delete all covers?",
        "delete_covers_detail": "{count} cover file(s) will be permanently deleted. The games themselves will remain unchanged.",
        "delete_mappings_confirm": "Delete IGDB metadata?",
        "delete_mappings_detail": "All saved IGDB metadata and game mappings will be deleted.",
        "delete_all_confirm": "Delete covers and IGDB mappings?",
        "delete_all_detail": "{count} cover file(s) and all saved IGDB mappings will be permanently deleted. Games and settings will remain unchanged.",
        "delete": "Delete",
        "deleted_covers": "{count} covers were deleted.",
        "deleted_mappings": "The IGDB metadata and mappings were deleted.",
        "deleted_all": "{count} covers and the IGDB mappings were deleted.",
        "stat_games": "Games",
        "stat_total": "Total",
        "stat_complete": "Complete",
        "stat_complete_sub": "Cover + metadata",
        "stat_cover_missing": "Cover missing",
        "stat_cover_missing_sub": "Without cover",
        "stat_metadata_missing": "Metadata missing",
        "stat_metadata_missing_sub": "Without metadata",
        "current_achievement": "CURRENT ACHIEVEMENT",
        "all_achievements": "All achievements ▾",
        "achievement_archived": "{target} games fully archived",
        "achievement_new": "Newly unlocked – {target} games fully archived.",
        "achievement_unlocked": "Achievement unlocked: at least {target} games fully archived. Current: {count}.",
        "achievement_remaining": "{count} more fully archived games until the first achievement.",
        "achievement_perfect": "Perfect Collection",
        "achievement_perfect_text": "All {total} games have covers and metadata.",
        "achievement_cover_curator": "Cover Curator",
        "achievement_cover_curator_text": "All games have a cover",
        "achievement_data_archivist": "Data Archivist",
        "achievement_data_archivist_text": "All games have metadata",
        "achievement_perfect_collection": "Perfect Collection",
        "achievement_perfect_collection_text": "Covers + metadata complete",
        "achievement_collector_1": "Collector I",
        "achievement_collector_2": "Collector II",
        "achievement_collector_3": "Collector III",
        "achievement_collector_4": "Collector IV",
        "achievement_librarian": "Librarian",
        "achievement_grand_archivist": "Grand Archivist",
        "achievement_legendary": "Legendary Collection",
        "tooltip_complete": "Cover and metadata complete",
        "tooltip_cover_missing": "Cover missing",
        "tooltip_metadata_missing": "Metadata missing",
        "tooltip_both_missing": "Cover and metadata missing",
        "filter_all": "All",
        "filter_complete": "✓ Complete",
        "filter_cover_missing": "⚠ Cover missing",
        "filter_metadata_missing": "ⓘ Metadata missing",
        "sort_label": "Sort:",
        "sort_name_az": "Name A–Z",
        "sort_name_za": "Name Z–A",
        "sort_year_new": "Year: newest → oldest",
        "sort_year_old": "Year: oldest → newest",
        "sort_rating_high": "IGDB rating: high → low",
        "sort_incomplete": "Incomplete first",
        "filter_sort_title": "FILTER & SORT",
        "bottom_sort_title": "Alphabetical:",
        "bottom_sort_az": "A–Z",
        "bottom_sort_za": "Z–A",
    },
}


# ============================================================
# MAIN WINDOW
# ============================================================

class GOGCoverWindow(Gtk.ApplicationWindow):
    def __init__(self, application, gog_dir=None):
        super().__init__(application=application)

        self.set_default_size(1420, 860)
        self.add_css_class("gaming-window")

        self.gog_dir = (
            Path(gog_dir).expanduser().resolve()
            if gog_dir
            else None
        )

        config = load_config()
        self.igdb_mappings = load_igdb_mappings()
        self.igdb_metadata = load_igdb_metadata()
        self.igdb_sync_state = load_igdb_sync_state()
        self.startup_sync_started = False
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.language = config.get("language", "de")
        self.theme = config.get("theme", "system")

        gtk_settings = Gtk.Settings.get_default()
        self.system_theme_name = (
            gtk_settings.get_property("gtk-theme-name")
            if gtk_settings
            else None
        )
        self.system_prefer_dark = (
            bool(
                gtk_settings.get_property(
                    "gtk-application-prefer-dark-theme"
                )
            )
            if gtk_settings
            else False
        )

        if self.language not in ("de", "en"):
            self.language = "de"
        try:
            self.cover_size = max(0, min(2, int(config.get("cover_size", 2))))
        except (TypeError, ValueError):
            self.cover_size = 2

        self.games = []
        self.filtered_games = []

        self.scan_running = False
        self.scan_event = None
        self.scan_answer = None
        self._achievement_glow_timeout = None
        self._dashboard_fade_timeout = None
        self._achievement_live_count = None
        self._new_achievement_timeout = None
        self.collection_filter = "all"
        self.collection_sort = "name_az"
        self._stat_filter_flash_timeout = None

        # v71: Dauerhaft animierter Nebula-/Aurora-Hintergrund.
        self._background_phase = 0.0
        self._background_particles = [
            {
                "x": random.random(),
                "y": random.random(),
                "size": random.uniform(0.8, 2.2),
                "speed": random.uniform(0.00015, 0.00045),
                "phase": random.uniform(0.0, math.tau),
            }
            for _ in range(64)
        ]
        self._background_tick_id = None

        self.set_title(self.tr("app_title"))
        self._build_ui()
        self.apply_theme()
        self._install_css()
        self._start_background_animation()

        if self.gog_dir:
            self.reload_collection()
            GLib.idle_add(self.start_startup_sync)
        else:
            self.status_label.set_text(
                self.tr("choose_folder_first")
            )

        # Einstellungen nicht automatisch öffnen.
        # Fehlende IGDB-Zugangsdaten werden erst dann abgefragt,
        # wenn eine IGDB-Funktion tatsächlich verwendet wird.

    def tr(self, key, **kwargs):
        table = TRANSLATIONS.get(self.language, TRANSLATIONS["de"])
        value = table.get(key, TRANSLATIONS["de"].get(key, key))
        if kwargs:
            try:
                value = value.format(**kwargs)
            except Exception:
                pass
        return value

    def apply_theme(self):
        settings = Gtk.Settings.get_default()
        if not settings:
            return

        # v48: Neben GTK wird auch das eigene Gaming-CSS umgeschaltet.
        self.remove_css_class("theme-light")
        self.remove_css_class("theme-dark")

        if self.theme == "dark":
            self.add_css_class("theme-dark")
            # Explicitly force a complete dark GTK appearance.
            settings.set_property(
                "gtk-theme-name",
                "Adwaita-dark"
            )
            settings.set_property(
                "gtk-application-prefer-dark-theme",
                True
            )

        elif self.theme == "light":
            self.add_css_class("theme-light")
            # Explicitly force a complete light GTK appearance.
            settings.set_property(
                "gtk-theme-name",
                "Adwaita"
            )
            settings.set_property(
                "gtk-application-prefer-dark-theme",
                False
            )

        else:
            # Systemmodus übernimmt auch für das Gaming-CSS die beim Start
            # erkannte helle/dunkle Darstellung.
            self.add_css_class(
                "theme-dark" if self.system_prefer_dark else "theme-light"
            )
            # Restore the GTK theme that was active when the app started.
            if self.system_theme_name:
                settings.set_property(
                    "gtk-theme-name",
                    self.system_theme_name
                )

            settings.set_property(
                "gtk-application-prefer-dark-theme",
                self.system_prefer_dark
            )

    def _theme_index(self):
        return {
            "system": 0,
            "light": 1,
            "dark": 2,
        }.get(self.theme, 0)

    def apply_language(self):
        self.set_title(self.tr("app_title"))

        if hasattr(self, "missing_button"):
            self.missing_button.set_label(self.tr("missing_covers"))
        if hasattr(self, "refresh_button"):
            self.refresh_button.set_label(self.tr("reload"))
        if hasattr(self, "search_entry"):
            self.search_entry.set_placeholder_text(
                self.tr("search_placeholder")
            )
        if hasattr(self, "settings_button"):
            self.settings_button.set_label(self.tr("settings"))
        if hasattr(self, "library_title"):
            self.library_title.set_text(self.tr("library"))
        if hasattr(self, "cover_size_label"):
            self.cover_size_label.set_text(self.tr("cover_size") + ":")
        if hasattr(self, "cover_small_label"):
            self.cover_small_label.set_text(self.tr("small"))
        if hasattr(self, "cover_large_label"):
            self.cover_large_label.set_text(self.tr("large"))
        if hasattr(self, "count_label"):
            self.count_label.set_text(
                self.tr("games_count", count=len(self.filtered_games))
            )
        if hasattr(self, "path_label") and not self.gog_dir:
            self.path_label.set_text(self.tr("no_gog_folder"))

        if hasattr(self, "stat_total"):
            self.stat_total["label"].set_text(self.tr("stat_games"))
            self.stat_total["subtitle"].set_text(self.tr("stat_total"))
            self.stat_complete["label"].set_text(self.tr("stat_complete"))
            self.stat_complete["subtitle"].set_text(self.tr("stat_complete_sub"))
            self.stat_cover_missing["label"].set_text(self.tr("stat_cover_missing"))
            self.stat_cover_missing["subtitle"].set_text(self.tr("stat_cover_missing_sub"))
            self.stat_metadata_missing["label"].set_text(self.tr("stat_metadata_missing"))
            self.stat_metadata_missing["subtitle"].set_text(self.tr("stat_metadata_missing_sub"))

        if hasattr(self, "bottom_sort_label"):
            self.bottom_sort_label.set_text(
                self.tr("sort_label")
            )
        if hasattr(self, "sort_dropdown"):
            selected = self.sort_dropdown.get_selected()
            self.sort_dropdown.set_model(self._build_sort_model())
            self.sort_dropdown.set_selected(selected)

        if hasattr(self, "current_achievement_heading"):
            self.current_achievement_heading.set_text(
                self.tr("current_achievement")
            )
        if hasattr(self, "achievement_menu_button"):
            self.achievement_menu_button.set_label(
                self.tr("all_achievements")
            )

        if hasattr(self, "stat_total"):
            self._update_dashboard()

        if not self.scan_running and hasattr(self, "status_label"):
            self.status_label.set_text(self.tr("status_default"))

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------

    def _build_ui(self):
        # v45: Full-bleed design surface. Previously the margins belonged
        # directly to app-root, so GTK's native window background showed
        # through as a thin mismatching frame around the application.
        window_surface = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL
        )
        window_surface.add_css_class("window-surface")
        window_surface.set_hexpand(True)
        window_surface.set_vexpand(True)
        # v71: Overlay legt die komplette Oberfläche über einen
        # animierten Hintergrund, ohne die bestehende UI umzubauen.
        background_overlay = Gtk.Overlay()
        background_overlay.set_hexpand(True)
        background_overlay.set_vexpand(True)
        self.set_child(background_overlay)

        self.background_area = Gtk.DrawingArea()
        self.background_area.set_hexpand(True)
        self.background_area.set_vexpand(True)
        self.background_area.set_draw_func(
            self._draw_animated_background
        )
        background_overlay.set_child(self.background_area)

        background_overlay.add_overlay(window_surface)
        window_surface.set_hexpand(True)
        window_surface.set_vexpand(True)

        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10
        )
        root.add_css_class("app-root")
        root.set_margin_top(14)
        root.set_margin_bottom(14)
        root.set_margin_start(18)
        root.set_margin_end(18)
        root.set_hexpand(True)
        root.set_vexpand(True)
        window_surface.append(root)

        # Header
        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12
        )
        root.append(header)

        title = Gtk.Label(label="GOG Library Manager")
        title.add_css_class("title-1")
        title.set_xalign(0)
        title.set_hexpand(True)
        header.append(title)

        # v46: Die bisherige Spieleanzahl oben rechts und die
        # sichtbare Pfadanzeige wurden entfernt, damit der Header ruhiger ist.

        # Toolbar
        toolbar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        toolbar.add_css_class("toolbar-shell")
        root.append(toolbar)

        self.missing_button = Gtk.Button(
            label=self.tr("missing_covers")
        )
        self.missing_button.add_css_class("gaming-button")
        self.missing_button.connect(
            "clicked",
            self.on_missing_clicked
        )
        toolbar.append(self.missing_button)

        self.refresh_button = Gtk.Button(
            label=self.tr("reload")
        )
        self.refresh_button.add_css_class("gaming-button")
        self.refresh_button.connect(
            "clicked",
            lambda *_: self.reload_collection()
        )
        toolbar.append(self.refresh_button)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.add_css_class("gaming-search")
        self.search_entry.set_placeholder_text(
            self.tr("search_placeholder")
        )
        self.search_entry.set_size_request(320, -1)
        self.search_entry.set_hexpand(False)
        self.search_entry.connect(
            "search-changed",
            lambda *_: self.filter_collection()
        )
        toolbar.append(self.search_entry)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        toolbar.append(spacer)

        self.settings_button = Gtk.Button(
            label=self.tr("settings")
        )
        self.settings_button.add_css_class("gaming-button")
        self.settings_button.connect(
            "clicked",
            lambda *_: self.open_settings()
        )
        toolbar.append(self.settings_button)

        self.status_label = Gtk.Label(
            label=self.tr("status_default")
        )
        self.status_label.set_xalign(0)
        self.status_label.add_css_class("dim-label")
        root.append(self.status_label)

        # Main dashboard
        content_area = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12
        )
        content_area.set_hexpand(True)
        content_area.set_vexpand(True)
        root.append(content_area)

        # Right side
        right_area = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6
        )
        right_area.set_hexpand(True)
        right_area.set_vexpand(True)
        content_area.append(right_area)

        # Statistics and current achievement
        dashboard_top = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6
        )
        dashboard_top.set_hexpand(True)
        dashboard_top.add_css_class("dashboard-strip")
        self.dashboard_top = dashboard_top
        right_area.append(dashboard_top)

        self.stat_total = self._make_stat_card(
            "🎮", "0", self.tr("stat_games"), self.tr("stat_total"), "all"
        )
        self.stat_total["box"].add_css_class("stat-total")
        self.stat_total["box"].set_size_request(145, 56)
        self.stat_complete = self._make_stat_card(
            "✓", "0", self.tr("stat_complete"), self.tr("stat_complete_sub"), "complete"
        )
        self.stat_complete["box"].add_css_class("stat-complete")
        self.stat_cover_missing = self._make_stat_card(
            "⚠", "0", self.tr("stat_cover_missing"), self.tr("stat_cover_missing_sub"), "missing_cover"
        )
        self.stat_cover_missing["box"].add_css_class("stat-cover-missing")
        self.stat_metadata_missing = self._make_stat_card(
            "ⓘ", "0", self.tr("stat_metadata_missing"), self.tr("stat_metadata_missing_sub"), "missing_metadata"
        )
        self.stat_metadata_missing["box"].add_css_class("stat-metadata-missing")

        for card in (
            self.stat_total,
            self.stat_complete,
            self.stat_cover_missing,
            self.stat_metadata_missing
        ):
            dashboard_top.append(card["box"])

        self.current_achievement_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2
        )
        self.current_achievement_box.set_hexpand(True)
        self.current_achievement_box.add_css_class("current-achievement")
        dashboard_top.append(self.current_achievement_box)

        current_header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        self.current_achievement_box.append(current_header)

        current_label = Gtk.Label(
            label=self.tr("current_achievement")
        )
        self.current_achievement_heading = current_label
        current_label.set_xalign(0)
        current_label.set_hexpand(True)
        current_label.add_css_class("achievement-heading")
        current_header.append(current_label)

        self.achievement_menu_button = Gtk.MenuButton(
            label=self.tr("all_achievements")
        )
        self.achievement_menu_button.add_css_class("achievement-menu-button")
        current_header.append(self.achievement_menu_button)

        self.current_achievement_title = Gtk.Label(label="—")
        self.current_achievement_title.set_xalign(0)
        self.current_achievement_title.add_css_class("title-3")
        self.current_achievement_box.append(self.current_achievement_title)

        self.current_achievement_text = Gtk.Label(label="")
        self.current_achievement_text.set_xalign(0)
        self.current_achievement_text.set_wrap(True)
        self.current_achievement_text.add_css_class("dim-label")
        self.current_achievement_box.append(self.current_achievement_text)

        self.achievement_popover = Gtk.Popover()
        self.achievement_popover.set_has_arrow(True)
        self.achievement_popover.set_autohide(True)

        achievement_popover_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6
        )
        achievement_popover_box.set_margin_top(10)
        achievement_popover_box.set_margin_bottom(10)
        achievement_popover_box.set_margin_start(10)
        achievement_popover_box.set_margin_end(10)
        achievement_popover_box.set_size_request(340, 420)

        achievement_scroll = Gtk.ScrolledWindow()
        achievement_scroll.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC
        )
        achievement_scroll.set_vexpand(True)
        achievement_popover_box.append(achievement_scroll)

        self.achievement_list = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4
        )
        achievement_scroll.set_child(self.achievement_list)

        self.achievement_popover.set_child(
            achievement_popover_box
        )
        self.achievement_menu_button.set_popover(
            self.achievement_popover
        )

        self._update_stat_filter_selection()

        # Library panel - no duplicated "Bibliothek" heading.
        library_panel = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8
        )
        library_panel.set_hexpand(True)
        library_panel.set_vexpand(True)
        library_panel.add_css_class("library-panel")
        right_area.append(library_panel)

        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_hexpand(True)
        self.scrolled.set_vexpand(True)
        self.scrolled.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC
        )
        self.scrolled.add_css_class("library-scroll")
        library_panel.append(self.scrolled)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_row_spacing(8)
        self.flowbox.set_column_spacing(8)
        self.flowbox.set_min_children_per_line(2)
        self.flowbox.set_max_children_per_line(COVER_SIZE_PRESETS[self.cover_size][5])
        self.flowbox.set_homogeneous(True)
        self.flowbox.set_margin_top(8)
        self.flowbox.set_margin_bottom(8)
        self.flowbox.set_margin_start(8)
        self.flowbox.set_margin_end(8)

        self.scrolled.set_child(self.flowbox)

        # Bottom bar
        # v66: Drei feste Bereiche verhindern, dass Sortierung/Filter
        # beim Ein-/Ausblenden des Ladebalkens ihre Position verändern.
        bottom_bar = Gtk.CenterBox()
        root.append(bottom_bar)

        size_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=7
        )
        size_box.set_halign(Gtk.Align.START)
        bottom_bar.set_start_widget(size_box)

        self.cover_size_label = Gtk.Label(
            label=self.tr("cover_size") + ":"
        )
        size_box.append(self.cover_size_label)

        self.cover_small_label = Gtk.Label(label=self.tr("small"))
        self.cover_small_label.add_css_class("dim-label")
        size_box.append(self.cover_small_label)

        self.size_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL,
            0,
            2,
            1
        )
        self.size_scale.set_value(self.cover_size)
        self.size_scale.set_draw_value(False)
        self.size_scale.set_digits(0)
        self.size_scale.set_size_request(90, -1)
        self.size_scale.set_hexpand(False)
        self.size_scale.connect(
            "value-changed",
            self.on_cover_size_changed
        )
        size_box.append(self.size_scale)

        self.cover_large_label = Gtk.Label(label=self.tr("large"))
        self.cover_large_label.add_css_class("dim-label")
        size_box.append(self.cover_large_label)

        # Ladebalken sitzt unabhängig von linker und rechter Seite
        # dauerhaft im mittleren Bereich.
        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        self.progress.set_text("")
        self.progress.set_size_request(320, -1)
        self.progress.set_hexpand(False)
        self.progress.set_halign(Gtk.Align.CENTER)
        self.progress.set_visible(False)
        bottom_bar.set_center_widget(self.progress)

        # Vollständige Sortierung bleibt fest rechts.
        bottom_sort_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=5
        )
        bottom_sort_box.set_halign(Gtk.Align.END)
        bottom_sort_box.add_css_class("bottom-sort-box")
        bottom_bar.set_end_widget(bottom_sort_box)

        self.bottom_sort_label = Gtk.Label(
            label=self.tr("sort_label")
        )
        self.bottom_sort_label.add_css_class("dim-label")
        bottom_sort_box.append(self.bottom_sort_label)

        self.sort_dropdown = Gtk.DropDown(
            model=self._build_sort_model()
        )
        self.sort_dropdown.set_selected(0)
        self.sort_dropdown.add_css_class("bottom-sort-dropdown")
        self.sort_dropdown.connect(
            "notify::selected",
            self._on_sort_changed
        )
        bottom_sort_box.append(self.sort_dropdown)

    def _pulse_current_achievement(self):
        if not hasattr(self, "current_achievement_box"):
            return

        self.current_achievement_box.add_css_class(
            "achievement-pulse"
        )

        if self._achievement_glow_timeout:
            try:
                GLib.source_remove(
                    self._achievement_glow_timeout
                )
            except Exception:
                pass

        self._achievement_glow_timeout = GLib.timeout_add(
            900,
            self._stop_achievement_pulse
        )

    def _stop_achievement_pulse(self):
        if hasattr(self, "current_achievement_box"):
            self.current_achievement_box.remove_css_class(
                "achievement-pulse"
            )
        self._achievement_glow_timeout = None
        return False

    def _fade_dashboard(self):
        if not hasattr(self, "dashboard_top"):
            return

        self.dashboard_top.add_css_class(
            "dashboard-fade"
        )

        if self._dashboard_fade_timeout:
            try:
                GLib.source_remove(
                    self._dashboard_fade_timeout
                )
            except Exception:
                pass

        self._dashboard_fade_timeout = GLib.timeout_add(
            420,
            self._stop_dashboard_fade
        )

    def _stop_dashboard_fade(self):
        if hasattr(self, "dashboard_top"):
            self.dashboard_top.remove_css_class(
                "dashboard-fade"
            )
        self._dashboard_fade_timeout = None
        return False

    def _complete_game_count(self):
        return sum(
            1 for game in self.games
            if (
                self.has_valid_cover(game)
                and self._has_metadata(game)
            )
        )

    def _begin_live_achievement_tracking(self):
        self._achievement_live_count = self._complete_game_count()

    def _live_scan_dashboard_update(self, game_name=None):
        previous = self._achievement_live_count
        current = self._complete_game_count()

        if previous is None:
            previous = current

        self._achievement_live_count = current
        self._update_dashboard()

        newly_unlocked = []
        for icon, name, target in self._achievement_definitions():
            if previous < target <= current:
                newly_unlocked.append(
                    (icon, name, target)
                )

        if newly_unlocked:
            icon, name, target = newly_unlocked[-1]
            self._flash_new_achievement(
                icon,
                name,
                target
            )

        return False

    def _flash_new_achievement(self, icon, name, target):
        if not hasattr(self, "current_achievement_box"):
            return

        self.current_achievement_box.add_css_class(
            "achievement-new-flash"
        )

        self.current_achievement_title.set_text(
            f"{icon} {name}"
        )
        self.current_achievement_text.set_text(
            self.tr("achievement_new", target=target)
        )

        if self._new_achievement_timeout:
            try:
                GLib.source_remove(
                    self._new_achievement_timeout
                )
            except Exception:
                pass

        self._new_achievement_timeout = GLib.timeout_add(
            1200,
            self._stop_new_achievement_flash
        )

    def _stop_new_achievement_flash(self):
        if hasattr(self, "current_achievement_box"):
            self.current_achievement_box.remove_css_class(
                "achievement-new-flash"
            )
            self._update_dashboard()

        self._new_achievement_timeout = None
        return False

    def _make_stat_card(self, icon, value, label, subtitle, filter_id=None):
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=3
        )
        box.set_size_request(145, 56)
        box.add_css_class("stat-card")

        top = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        box.append(top)

        icon_label = Gtk.Label(label=icon)
        icon_label.add_css_class("stat-icon")
        top.append(icon_label)

        value_label = Gtk.Label(label=value)
        value_label.set_xalign(0)
        value_label.add_css_class("stat-value")
        top.append(value_label)

        name_label = Gtk.Label(label=label)
        name_label.set_xalign(0)
        name_label.add_css_class("stat-name")
        box.append(name_label)

        subtitle_label = Gtk.Label(label=subtitle)
        subtitle_label.set_xalign(0)
        subtitle_label.add_css_class("dim-label")
        box.append(subtitle_label)

        if filter_id is not None:
            click = Gtk.GestureClick()
            click.set_button(1)
            click.connect(
                "pressed",
                self._on_stat_filter_clicked,
                filter_id
            )
            box.add_controller(click)
            box.add_css_class("stat-filter-card")

        return {
            "box": box,
            "value": value_label,
            "label": name_label,
            "subtitle": subtitle_label,
        }

    def _has_metadata(self, game_name):
        metadata = self.igdb_metadata.get(game_name)
        return isinstance(metadata, dict) and bool(metadata)

    def _game_status(self, game_name):
        has_cover = self.has_valid_cover(game_name)
        has_metadata = self._has_metadata(game_name)

        if has_cover and has_metadata:
            return "complete"
        if not has_cover and not has_metadata:
            return "missing_both"
        if not has_cover:
            return "missing_cover"
        return "missing_metadata"

    def _achievement_definitions(self):
        return [
            ("🎮", self.tr("achievement_collector_1"), 10),
            ("🏅", self.tr("achievement_collector_2"), 25),
            ("🥉", self.tr("achievement_collector_3"), 50),
            ("🏆", self.tr("achievement_collector_4"), 100),
            ("👑", self.tr("achievement_librarian"), 250),
            ("💎", self.tr("achievement_grand_archivist"), 500),
            ("🌟", self.tr("achievement_legendary"), 1000),
        ]

    def _update_dashboard(self):
        if not hasattr(self, "stat_total"):
            return

        total = len(self.games)
        cover_count = sum(
            1 for game in self.games
            if self.has_valid_cover(game)
        )
        metadata_count = sum(
            1 for game in self.games
            if self._has_metadata(game)
        )
        complete = sum(
            1 for game in self.games
            if (
                self.has_valid_cover(game)
                and self._has_metadata(game)
            )
        )
        cover_missing = total - cover_count
        metadata_missing = total - metadata_count

        self.stat_total["value"].set_text(str(total))
        self.stat_complete["value"].set_text(str(complete))
        self.stat_cover_missing["value"].set_text(str(cover_missing))
        self.stat_metadata_missing["value"].set_text(str(metadata_missing))
        self._fade_dashboard()

        # Rebuild achievement list.
        child = self.achievement_list.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.achievement_list.remove(child)
            child = next_child

        # v43: Sammler-Erfolge zählen vollständig archivierte Spiele
        # (Cover + IGDB-Metadaten) statt nur vorhandene Ordner.
        # Dadurch steht der Achievement-Fortschritt nach einem Daten-Reset
        # tatsächlich wieder auf 0 und wächst beim erneuten Scannen mit.
        achievement_count = complete

        count_achievements = self._achievement_definitions()
        unlocked = []

        for icon, name, target in count_achievements:
            achieved = achievement_count >= target
            if achieved:
                unlocked.append((icon, name, target))

            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8
            )
            row.add_css_class(
                "achievement-unlocked"
                if achieved
                else "achievement-locked"
            )

            icon_label = Gtk.Label(label=icon)
            icon_label.add_css_class("achievement-icon")
            row.append(icon_label)

            info = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=1
            )
            info.set_hexpand(True)
            row.append(info)

            title = Gtk.Label(label=name)
            title.set_xalign(0)
            title.add_css_class("heading")
            info.append(title)

            detail = Gtk.Label(
                label=self.tr("achievement_archived", target=target)
            )
            detail.set_xalign(0)
            detail.set_wrap(True)
            detail.add_css_class("dim-label")
            info.append(detail)

            progress = Gtk.Label(
                label=(
                    f"✓ {achievement_count} / {target}"
                    if achieved
                    else f"{achievement_count} / {target}"
                )
            )
            progress.set_xalign(0)
            progress.add_css_class(
                "achievement-done"
                if achieved
                else "dim-label"
            )
            info.append(progress)

            self.achievement_list.append(row)

        special_achievements = [
            (
                "🖼",
                self.tr("achievement_cover_curator"),
                self.tr("achievement_cover_curator_text"),
                total > 0 and cover_missing == 0,
                f"{cover_count} / {total}"
            ),
            (
                "📚",
                self.tr("achievement_data_archivist"),
                self.tr("achievement_data_archivist_text"),
                total > 0 and metadata_missing == 0,
                f"{metadata_count} / {total}"
            ),
            (
                "🏆",
                self.tr("achievement_perfect_collection"),
                self.tr("achievement_perfect_collection_text"),
                total > 0 and complete == total,
                f"{complete} / {total}"
            ),
        ]

        for icon, name, detail_text, achieved, progress_text in special_achievements:
            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8
            )
            row.add_css_class(
                "achievement-unlocked"
                if achieved
                else "achievement-locked"
            )

            icon_label = Gtk.Label(label=icon)
            icon_label.add_css_class("achievement-icon")
            row.append(icon_label)

            info = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=1
            )
            info.set_hexpand(True)
            row.append(info)

            title = Gtk.Label(label=name)
            title.set_xalign(0)
            title.add_css_class("heading")
            info.append(title)

            detail = Gtk.Label(label=detail_text)
            detail.set_xalign(0)
            detail.set_wrap(True)
            detail.add_css_class("dim-label")
            info.append(detail)

            progress = Gtk.Label(
                label=("✓ " if achieved else "") + progress_text
            )
            progress.set_xalign(0)
            progress.add_css_class(
                "achievement-done"
                if achieved
                else "dim-label"
            )
            info.append(progress)

            self.achievement_list.append(row)

        if total > 0 and complete == total:
            current_title = "🏆 " + self.tr("achievement_perfect")
            current_text = self.tr(
                "achievement_perfect_text",
                total=total
            )
        elif unlocked:
            icon, name, target = unlocked[-1]
            current_title = f"{icon} {name}"
            current_text = self.tr(
                "achievement_unlocked",
                target=target,
                count=achievement_count
            )
        else:
            icon, name, target = count_achievements[0]
            current_title = f"🔒 {name}"
            current_text = self.tr(
                "achievement_remaining",
                count=max(0, target - achievement_count)
            )

        self.current_achievement_title.set_text(current_title)
        self.current_achievement_text.set_text(current_text)

        self.current_achievement_box.remove_css_class(
            "achievement-highlight"
        )
        self.current_achievement_box.remove_css_class(
            "achievement-highlight-gold"
        )

        if total > 0 and complete == total:
            self.current_achievement_box.add_css_class(
                "achievement-highlight-gold"
            )
        elif unlocked:
            self.current_achievement_box.add_css_class(
                "achievement-highlight"
            )

    def _make_status_badge(self, game_name):
        status = self._game_status(game_name)

        if status == "complete":
            text = "✓"
            css = "badge-complete"
            tooltip = self.tr("tooltip_complete")
        elif status == "missing_cover":
            text = "🖼"
            css = "badge-cover"
            tooltip = self.tr("tooltip_cover_missing")
        elif status == "missing_metadata":
            text = "ⓘ"
            css = "badge-metadata"
            tooltip = self.tr("tooltip_metadata_missing")
        else:
            text = "!"
            css = "badge-missing"
            tooltip = self.tr("tooltip_both_missing")

        badge = Gtk.Label(label=text)
        badge.set_halign(Gtk.Align.START)
        badge.set_valign(Gtk.Align.START)
        badge.set_margin_top(6)
        badge.set_margin_start(6)
        badge.set_tooltip_text(tooltip)
        badge.add_css_class("status-badge")
        badge.add_css_class(css)
        return badge

    def _start_background_animation(self):
        if self._background_tick_id is not None:
            return

        self._background_tick_id = GLib.timeout_add(
            33,
            self._animate_background
        )

    def _animate_background(self):
        self._background_phase = (
            self._background_phase + 0.006
        ) % math.tau

        for particle in self._background_particles:
            particle["y"] -= particle["speed"]
            if particle["y"] < -0.03:
                particle["y"] = 1.03
                particle["x"] = random.random()

        if hasattr(self, "background_area"):
            self.background_area.queue_draw()

        return True

    def _draw_animated_background(self, area, cr, width, height):
        # Dunkle Grundfläche.
        cr.set_source_rgb(0.018, 0.024, 0.045)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        phase = self._background_phase

        # Mehrere sehr weiche, langsam wandernde Aurora-/Nebula-Glows.
        glows = [
            (
                0.20 + math.sin(phase * 0.72) * 0.08,
                0.20 + math.cos(phase * 0.54) * 0.07,
                0.56,
                (0.42, 0.12, 0.86),
                0.34,
            ),
            (
                0.78 + math.cos(phase * 0.48) * 0.09,
                0.32 + math.sin(phase * 0.61) * 0.08,
                0.50,
                (0.08, 0.34, 0.92),
                0.30,
            ),
            (
                0.54 + math.sin(phase * 0.39 + 1.7) * 0.12,
                0.82 + math.cos(phase * 0.44 + 0.9) * 0.06,
                0.60,
                (0.38, 0.06, 0.72),
                0.26,
            ),
        ]

        max_dim = max(width, height)

        for gx, gy, radius_factor, color, alpha in glows:
            cx = gx * width
            cy = gy * height
            radius = radius_factor * max_dim

            gradient = cairo.RadialGradient(
                cx, cy, 0,
                cx, cy, radius
            )
            gradient.add_color_stop_rgba(
                0.0, color[0], color[1], color[2], alpha
            )
            gradient.add_color_stop_rgba(
                0.55, color[0], color[1], color[2], alpha * 0.55
            )
            gradient.add_color_stop_rgba(
                1.0, color[0], color[1], color[2], 0.0
            )
            cr.set_source(gradient)
            cr.rectangle(0, 0, width, height)
            cr.fill()

        # Dezente schwebende Lichtpartikel.
        for particle in self._background_particles:
            px = particle["x"] * width
            py = particle["y"] * height
            twinkle = (
                0.5
                + 0.5 * math.sin(
                    phase * 1.8 + particle["phase"]
                )
            )
            alpha = 0.12 + twinkle * 0.20
            radius = particle["size"] * 1.25

            cr.set_source_rgba(
                0.78, 0.74, 1.0, alpha
            )
            cr.arc(px, py, radius, 0, math.tau)
            cr.fill()

    def _install_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"""
            .gaming-window,
            .window-surface,
            .app-root {
                background: transparent;
                color: #f3f4f6;
            }

            .gaming-window {
                box-shadow: none;
                border: none;
            }

            .window-surface {
                padding: 0;
                margin: 0;
            }

            .collection-controls {
                padding: 2px 2px 4px 2px;
            }

            .stat-filter-card {
                transition: 170ms ease;
            }

            .stat-filter-card:hover {
                border-color: #a78bfa;
                box-shadow: 0 0 0 1px alpha(#8b5cf6, 0.30),
                            0 0 16px alpha(#8b5cf6, 0.20);
            }


            .bottom-sort-box {
                padding: 2px 6px;
                border-radius: 9px;
                background: #111720;
                border: 1px solid #2b3544;
            }


            .stat-selected-total {
                background: alpha(#7c3aed, 0.20);
                border-color: #9b6cff;
                box-shadow: inset 0 0 18px alpha(#7c3aed, 0.12);
            }

            .stat-selected-complete {
                background: alpha(#2f9e44, 0.20);
                border-color: #51cf66;
                box-shadow: inset 0 0 18px alpha(#2f9e44, 0.12);
            }

            .stat-selected-cover {
                background: alpha(#d97706, 0.22);
                border-color: #f59f00;
                box-shadow: inset 0 0 18px alpha(#d97706, 0.14);
            }

            .stat-selected-metadata {
                background: alpha(#2563eb, 0.20);
                border-color: #4dabf7;
                box-shadow: inset 0 0 18px alpha(#2563eb, 0.12);
            }

            .stat-flash-total {
                background: alpha(#7c3aed, 0.48);
                border-color: #c4b5fd;
                box-shadow: inset 0 0 26px alpha(#a78bfa, 0.42),
                            0 0 24px alpha(#7c3aed, 0.42);
            }

            .stat-flash-complete {
                background: alpha(#2f9e44, 0.48);
                border-color: #8ce99a;
                box-shadow: inset 0 0 26px alpha(#51cf66, 0.40),
                            0 0 24px alpha(#2f9e44, 0.40);
            }

            .stat-flash-cover {
                background: alpha(#d97706, 0.52);
                border-color: #ffd43b;
                box-shadow: inset 0 0 26px alpha(#fcc419, 0.40),
                            0 0 24px alpha(#d97706, 0.42);
            }

            .stat-flash-metadata {
                background: alpha(#2563eb, 0.48);
                border-color: #74c0fc;
                box-shadow: inset 0 0 26px alpha(#4dabf7, 0.40),
                            0 0 24px alpha(#2563eb, 0.42);
            }

            .bottom-sort-dropdown {
                min-width: 205px;
                min-height: 28px;
            }

            .toolbar-shell {
                padding: 8px;
                border-radius: 12px;
                background: #111720;
                border: 1px solid #252d3a;
            }

            .gaming-button,
            .achievement-menu-button {
                border-radius: 9px;
                padding: 7px 12px;
                background: #171e28;
                border: 1px solid #313b4b;
            }

            .gaming-button,
            .achievement-menu-button,
            .status-badge {
                transition: 180ms ease;
            }

            .gaming-button:hover,
            .achievement-menu-button:hover {
                background: #202938;
                border-color: #8b5cf6;
                box-shadow: 0 0 12px alpha(#8b5cf6, 0.16);
            }

            .status-badge:hover {
                box-shadow: 0 0 10px alpha(white, 0.18);
            }

            .gaming-search {
                border-radius: 9px;
                background: #111720;
                border: 1px solid #313b4b;
            }

            .game-card {
                padding: 5px;
                border-radius: 10px;
                background: #111720;
                border: 1px solid #242d39;
                transition: 180ms ease;
            }

            .game-card:hover {
                background: #151d28;
                border-color: #8b5cf6;
                box-shadow: 0 0 0 1px alpha(#8b5cf6, 0.55),
                            0 0 16px alpha(#8b5cf6, 0.18);
            }

            .cover-frame {
                border-radius: 7px;
                background: #171e28;
            }

            .missing-cover {
                border: 1px dashed #5b6575;
                border-radius: 7px;
                background: #121821;
            }

            .missing-label {
                font-weight: bold;
            }

            .result-card {
                padding: 10px;
                border-radius: 10px;
                background: #111720;
                border: 1px solid #273142;
            }

            .library-panel {
                padding: 10px;
                border-radius: 12px;
                background: #0f151d;
                border: 1px solid #252d3a;
            }

            .library-title {
                margin-left: 4px;
                margin-bottom: 2px;
            }

            .library-scroll {
                background: transparent;
            }

            .current-achievement,
            .stat-card {
                padding: 4px 7px;
                border-radius: 8px;
                background: #111720;
                border: 1px solid #2b3544;
                transition: 220ms ease;
            }

            .dashboard-fade .stat-card {
                opacity: 0.76;
            }

            .achievement-pulse {
                border-color: #b67cff;
                box-shadow: 0 0 0 1px alpha(#b67cff, 0.45),
                            0 0 18px alpha(#b67cff, 0.28);
            }

            .achievement-new-flash {
                border-color: #f5c451;
                background: alpha(#f5c451, 0.10);
                box-shadow: 0 0 0 1px alpha(#f5c451, 0.45),
                            0 0 22px alpha(#f5c451, 0.30);
            }

            .stat-card {
                min-width: 145px;
            }

            .stat-total {
                border-color: #7c3aed;
            }

            .stat-complete {
                border-color: #2f9e44;
            }

            .stat-cover-missing {
                border-color: #d97706;
            }

            .stat-metadata-missing {
                border-color: #2563eb;
            }

            .achievement-heading {
                font-size: 10px;
                font-weight: bold;
                color: #c084fc;
                letter-spacing: 0.6px;
            }

            .achievement-unlocked,
            .achievement-locked {
                padding: 8px 4px;
                border-bottom: 1px solid #222b36;
                border-radius: 8px;
            }

            .achievement-unlocked {
                background: alpha(#8b5cf6, 0.08);
            }

            .achievement-locked {
                opacity: 0.48;
            }

            .achievement-icon {
                font-size: 24px;
                min-width: 34px;
            }

            .achievement-done {
                color: #62d878;
                font-weight: bold;
            }

            .achievement-highlight {
                border-color: #8b5cf6;
                background: alpha(#8b5cf6, 0.10);
            }

            .achievement-highlight-gold {
                border-color: #eab308;
                background: alpha(#eab308, 0.08);
            }

            .stat-icon {
                font-size: 16px;
            }

            .stat-value {
                font-size: 18px;
                font-weight: 800;
            }

            .stat-name {
                font-weight: bold;
            }

            .current-achievement {
                min-width: 290px;
                min-height: 56px;
            }

            .status-badge {
                min-width: 26px;
                min-height: 26px;
                padding: 2px 5px;
                border-radius: 999px;
                font-weight: bold;
                font-size: 14px;
                border: 2px solid #0b0f14;
            }

            .badge-complete {
                background: #2f9e44;
                color: white;
            }

            .badge-cover,
            .badge-missing {
                background: #d97706;
                color: white;
            }

            .badge-metadata {
                background: #2563eb;
                color: white;
            }

            progressbar trough {
                border-radius: 999px;
                background: #1d2530;
            }

            progressbar progress {
                border-radius: 999px;
                background: #8b5cf6;
            }

            scale trough {
                border-radius: 999px;
                background: #222a35;
            }

            scale highlight {
                border-radius: 999px;
                background: #8b5cf6;
            }

            /* v48 light gaming theme */
            .gaming-window.theme-light,
            .gaming-window.theme-light .window-surface,
            .gaming-window.theme-light .app-root {
                background: #f4f6f9;
                color: #18202b;
            }

            .gaming-window.theme-light .bottom-sort-box {
                background: #ffffff;
                border-color: #d6dce5;
            }


            .gaming-window.theme-light .stat-selected-total {
                background: #eee8ff;
                border-color: #7c3aed;
            }

            .gaming-window.theme-light .stat-selected-complete {
                background: #e6f7e9;
                border-color: #2f9e44;
            }

            .gaming-window.theme-light .stat-selected-cover {
                background: #fff1db;
                border-color: #d97706;
            }

            .gaming-window.theme-light .stat-selected-metadata {
                background: #e7f0ff;
                border-color: #2563eb;
            }

            .gaming-window.theme-light .stat-flash-total {
                background: #d9c8ff;
                border-color: #7c3aed;
            }

            .gaming-window.theme-light .stat-flash-complete {
                background: #bfe8c6;
                border-color: #2f9e44;
            }

            .gaming-window.theme-light .stat-flash-cover {
                background: #ffdca8;
                border-color: #d97706;
            }

            .gaming-window.theme-light .stat-flash-metadata {
                background: #bfd7ff;
                border-color: #2563eb;
            }

            .gaming-window.theme-light .stat-filter-card:hover {
                border-color: #8b5cf6;
                background: #f7f4ff;
            }

            .gaming-window.theme-light .toolbar-shell,
            .gaming-window.theme-light .game-card,
            .gaming-window.theme-light .result-card,
            .gaming-window.theme-light .current-achievement,
            .gaming-window.theme-light .stat-card {
                background: #ffffff;
                border-color: #d6dce5;
                color: #18202b;
            }

            .gaming-window.theme-light .library-panel {
                background: #eef2f7;
                border-color: #d6dce5;
            }

            .gaming-window.theme-light .gaming-button,
            .gaming-window.theme-light .achievement-menu-button,
            .gaming-window.theme-light .gaming-search {
                background: #ffffff;
                border-color: #cbd3df;
                color: #18202b;
            }

            .gaming-window.theme-light .gaming-button:hover,
            .gaming-window.theme-light .achievement-menu-button:hover {
                background: #f4f0ff;
                border-color: #8b5cf6;
            }

            .gaming-window.theme-light .game-card:hover {
                background: #f7f4ff;
                border-color: #8b5cf6;
            }

            .gaming-window.theme-light .cover-frame {
                background: #e6eaf0;
            }

            .gaming-window.theme-light .missing-cover {
                background: #edf1f6;
                border-color: #aab4c3;
            }

            .gaming-window.theme-light .achievement-unlocked,
            .gaming-window.theme-light .achievement-locked {
                border-bottom-color: #d8dee8;
            }

            .gaming-window.theme-light progressbar trough,
            .gaming-window.theme-light scale trough {
                background: #dfe5ed;
            }
            """
        )

        display = Gdk.Display.get_default()

        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def on_cover_size_changed(self, scale):
        new_size = int(round(scale.get_value()))
        new_size = max(0, min(2, new_size))

        # Snap exactly to one of the three positions.
        if abs(scale.get_value() - new_size) > 0.001:
            scale.set_value(new_size)
            return

        if new_size == self.cover_size:
            return

        self.cover_size = new_size

        self.flowbox.set_max_children_per_line(
            COVER_SIZE_PRESETS[new_size][5]
        )

        save_config(
            self.client_id,
            self.client_secret,
            self.gog_dir,
            self.cover_size,
            self.language,
                            self.theme
        )

        self.filter_collection()

    # --------------------------------------------------------
    # COLLECTION
    # --------------------------------------------------------

    def _on_stat_filter_clicked(
        self,
        gesture,
        n_press,
        x,
        y,
        filter_id
    ):
        if n_press != 1:
            return

        self.collection_filter = filter_id
        self._update_stat_filter_selection()
        self._flash_stat_filter(filter_id)
        self.filter_collection()

    def _flash_stat_filter(self, filter_id):
        cards = {
            "all": self.stat_total["box"],
            "complete": self.stat_complete["box"],
            "missing_cover": self.stat_cover_missing["box"],
            "missing_metadata": self.stat_metadata_missing["box"],
        }
        flash_classes = (
            "stat-flash-total",
            "stat-flash-complete",
            "stat-flash-cover",
            "stat-flash-metadata",
        )

        # v54: Vor jedem neuen Effekt werden alle Flash-Klassen von
        # allen Karten entfernt. So kann immer nur die angeklickte Karte leuchten.
        for card in cards.values():
            for css_class in flash_classes:
                card.remove_css_class(css_class)

        box = cards.get(filter_id)
        if box is None:
            return

        if self._stat_filter_flash_timeout:
            try:
                GLib.source_remove(self._stat_filter_flash_timeout)
            except Exception:
                pass

        class_map = {
            "all": "stat-flash-total",
            "complete": "stat-flash-complete",
            "missing_cover": "stat-flash-cover",
            "missing_metadata": "stat-flash-metadata",
        }
        box.add_css_class(class_map[filter_id])

        self._stat_filter_flash_timeout = GLib.timeout_add(
            700,
            self._stop_stat_filter_flash
        )

    def _stop_stat_filter_flash(self):
        flash_classes = (
            "stat-flash-total",
            "stat-flash-complete",
            "stat-flash-cover",
            "stat-flash-metadata",
        )
        for card in (
            self.stat_total["box"],
            self.stat_complete["box"],
            self.stat_cover_missing["box"],
            self.stat_metadata_missing["box"],
        ):
            for css_class in flash_classes:
                card.remove_css_class(css_class)
        self._stat_filter_flash_timeout = None
        return False

    def _update_stat_filter_selection(self):
        cards = {
            "all": self.stat_total["box"],
            "complete": self.stat_complete["box"],
            "missing_cover": self.stat_cover_missing["box"],
            "missing_metadata": self.stat_metadata_missing["box"],
        }
        selected_classes = (
            "stat-selected-total",
            "stat-selected-complete",
            "stat-selected-cover",
            "stat-selected-metadata",
        )
        class_map = {
            "all": "stat-selected-total",
            "complete": "stat-selected-complete",
            "missing_cover": "stat-selected-cover",
            "missing_metadata": "stat-selected-metadata",
        }

        for card in cards.values():
            card.remove_css_class("stat-filter-selected")
            for css_class in selected_classes:
                card.remove_css_class(css_class)

        selected_box = cards.get(self.collection_filter)
        if selected_box is not None:
            selected_box.add_css_class(
                class_map[self.collection_filter]
            )

    def _build_sort_model(self):
        return Gtk.StringList.new([
            self.tr("sort_name_az"),
            self.tr("sort_name_za"),
            self.tr("sort_year_new"),
            self.tr("sort_year_old"),
            self.tr("sort_rating_high"),
            self.tr("sort_incomplete"),
        ])

    def _on_filter_chip_toggled(self, button, filter_id):
        if not button.get_active():
            # Ein aktiver Chip bleibt immer ausgewählt.
            if self.collection_filter == filter_id:
                button.set_active(True)
            return

        self.collection_filter = filter_id

        for other_id, other_button in self.filter_buttons.items():
            if other_id != filter_id and other_button.get_active():
                other_button.set_active(False)

        self.filter_collection()

    def _on_sort_changed(self, dropdown, _pspec):
        sort_ids = [
            "name_az",
            "name_za",
            "year_new",
            "year_old",
            "rating_high",
            "incomplete",
        ]
        selected = dropdown.get_selected()
        if 0 <= selected < len(sort_ids):
            self.collection_sort = sort_ids[selected]
            self.filter_collection()

    def _game_release_year(self, game_name):
        metadata = self.igdb_metadata.get(game_name)
        if not isinstance(metadata, dict):
            return 0

        timestamp = metadata.get("first_release_date")
        if not timestamp:
            return 0

        try:
            from datetime import datetime
            return datetime.fromtimestamp(timestamp).year
        except (TypeError, ValueError, OSError):
            return 0

    def _game_rating(self, game_name):
        metadata = self.igdb_metadata.get(game_name)
        if not isinstance(metadata, dict):
            return -1.0

        for key in ("total_rating", "aggregated_rating", "rating"):
            value = metadata.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return -1.0

    def _sort_collection_games(self, games):
        games = list(games)

        if self.collection_sort == "name_za":
            return sorted(games, key=str.lower, reverse=True)

        if self.collection_sort == "year_new":
            return sorted(
                games,
                key=lambda game: (
                    self._game_release_year(game),
                    game.lower()
                ),
                reverse=True
            )

        if self.collection_sort == "year_old":
            # Spiele ohne bekanntes Jahr stehen am Ende.
            return sorted(
                games,
                key=lambda game: (
                    self._game_release_year(game) == 0,
                    self._game_release_year(game),
                    game.lower()
                )
            )

        if self.collection_sort == "rating_high":
            return sorted(
                games,
                key=lambda game: (
                    self._game_rating(game),
                    game.lower()
                ),
                reverse=True
            )

        if self.collection_sort == "incomplete":
            return sorted(
                games,
                key=lambda game: (
                    self._game_status(game) == "complete",
                    game.lower()
                )
            )

        return sorted(games, key=str.lower)

    def reload_collection(self):
        self.games = []

        if not self.gog_dir or not self.gog_dir.is_dir():
            self.status_label.set_text(
                "❌ GOG-Ordner nicht gefunden."
            )
            self._render_collection([])
            return

        try:
            self.games = sorted(
                [
                    entry.name
                    for entry in self.gog_dir.iterdir()
                    if entry.is_dir()
                ],
                key=str.lower
            )
        except Exception as exc:
            self.show_error(
                "GOG-Ordner konnte nicht gelesen werden.",
                str(exc)
            )
            return

        # v69: Bestehende cover.jpg aus Spieleordnern automatisch übernehmen.
        self._migrate_legacy_covers()

        self.filter_collection()

    def filter_collection(self):
        query = normalize_name(
            self.search_entry.get_text()
        )

        games = list(self.games)

        if query:
            games = [
                game
                for game in games
                if query in normalize_name(game)
            ]

        if self.collection_filter == "complete":
            games = [
                game for game in games
                if self._game_status(game) == "complete"
            ]
        elif self.collection_filter == "missing_cover":
            games = [
                game for game in games
                if self._game_status(game) in (
                    "missing_cover",
                    "missing_both"
                )
            ]
        elif self.collection_filter == "missing_metadata":
            games = [
                game for game in games
                if self._game_status(game) in (
                    "missing_metadata",
                    "missing_both"
                )
            ]

        self.filtered_games = self._sort_collection_games(games)

        self._render_collection(
            self.filtered_games
        )

    def _clear_flowbox(self):
        child = self.flowbox.get_first_child()

        while child:
            next_child = child.get_next_sibling()
            self.flowbox.remove(child)
            child = next_child

    def _render_collection(self, games):
        self._clear_flowbox()

        # v47: count_label wurde in v46 bewusst aus der Oberfläche entfernt.
        # Die Sammlung darf deshalb hier nicht mehr auf dieses Widget zugreifen.
        self._update_dashboard()

        if not games:
            empty = Gtk.Label(
                label="Keine Spiele gefunden."
            )
            empty.set_margin_top(30)
            self.flowbox.append(empty)
            return

        for game_name in games:
            self.flowbox.append(
                self._create_game_card(game_name)
            )

    def _refresh_game_card_live(self, game_name):
        """Aktualisiert genau eine sichtbare Spielkarte während eines Scans."""
        try:
            if game_name not in self.filtered_games:
                # Das Spiel ist durch den aktuellen Filter gerade nicht sichtbar.
                self._update_dashboard()
                return False

            index = self.filtered_games.index(game_name)
            old_child = self.flowbox.get_child_at_index(index)

            if old_child is None:
                return False

            new_card = self._create_game_card(game_name)

            # FlowBox verwaltet intern FlowBoxChild-Wrapper.
            # Entfernen und an derselben Position wieder einsetzen erhält
            # Reihenfolge und Scrollposition wesentlich besser als ein
            # kompletter Neuaufbau der Sammlung.
            self.flowbox.remove(old_child)
            self.flowbox.insert(new_card, index)

            self._update_dashboard()

        except Exception:
            # Live-Anzeige darf niemals den eigentlichen Scan abbrechen.
            pass

        return False

    def _create_game_card(self, game_name):
        card = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4
        )
        _, cover_width, cover_height, card_width, card_height, _ = (
            COVER_SIZE_PRESETS[self.cover_size]
        )

        card.set_size_request(card_width, card_height)
        card.add_css_class("game-card")

        cover_path = self.get_cover_path(game_name)

        cover_overlay = Gtk.Overlay()
        cover_overlay.set_size_request(
            cover_width,
            cover_height
        )
        cover_overlay.set_halign(Gtk.Align.CENTER)
        cover_overlay.set_valign(Gtk.Align.CENTER)

        cover_widget = None

        if self.has_valid_cover(game_name):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(cover_path),
                    cover_width,
                    cover_height,
                    False
                )

                picture = Gtk.Picture.new_for_pixbuf(pixbuf)
                picture.set_size_request(
                    cover_width,
                    cover_height
                )
                picture.set_can_shrink(False)
                picture.set_content_fit(Gtk.ContentFit.FILL)
                picture.set_halign(Gtk.Align.CENTER)
                picture.set_valign(Gtk.Align.CENTER)
                picture.add_css_class("cover-frame")
                cover_widget = picture

            except Exception:
                cover_widget = self._create_missing_cover_widget(
                    cover_width,
                    cover_height
                )
        else:
            cover_widget = self._create_missing_cover_widget(
                cover_width,
                cover_height
            )

        cover_overlay.set_child(cover_widget)
        cover_overlay.add_overlay(
            self._make_status_badge(game_name)
        )
        card.append(cover_overlay)

        title = Gtk.Label(label=game_name)
        title.set_wrap(True)
        title.set_wrap_mode(2)
        title.set_justify(Gtk.Justification.CENTER)
        title.set_max_width_chars(28)
        title.set_lines(2)
        title.set_tooltip_text(game_name)
        card.append(title)

        # Double click
        left_click = Gtk.GestureClick()
        left_click.set_button(1)
        left_click.connect(
            "pressed",
            self._on_card_left_click,
            game_name
        )
        card.add_controller(left_click)

        # Right click
        right_click = Gtk.GestureClick()
        right_click.set_button(3)
        right_click.connect(
            "pressed",
            self._on_card_right_click,
            card,
            game_name
        )
        card.add_controller(right_click)

        return card

    def _create_missing_cover_widget(self, cover_width, cover_height):
        frame = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8
        )
        frame.set_size_request(
            cover_width,
            cover_height
        )
        frame.set_valign(Gtk.Align.CENTER)
        frame.set_halign(Gtk.Align.CENTER)
        frame.add_css_class("missing-cover")

        icon = Gtk.Image.new_from_icon_name(
            "image-missing-symbolic"
        )
        icon.set_pixel_size(64)
        frame.append(icon)

        label = Gtk.Label(label="Kein Cover")
        label.add_css_class("missing-label")
        frame.append(label)

        return frame

    def _on_card_left_click(
        self,
        gesture,
        n_press,
        x,
        y,
        game_name
    ):
        # v70: Einzelklick hat wieder keine Funktion.
        # Doppelklick öffnet wie vor v68 den Spielordner.
        if n_press == 2 and not self.scan_running:
            self.open_game_folder(game_name)

    def _on_card_right_click(
        self,
        gesture,
        n_press,
        x,
        y,
        card,
        game_name
    ):
        if n_press != 1:
            return

        popover = Gtk.Popover()
        popover.set_parent(card)
        popover.set_autohide(True)

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4
        )
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        replace_button = Gtk.Button(
            label=self.tr("replace_cover")
        )
        replace_button.connect(
            "clicked",
            lambda *_: (
                popover.popdown(),
                self.start_replace(game_name)
            )
        )
        box.append(replace_button)

        info_button = Gtk.Button(
            label=self.tr("game_info")
        )
        info_button.connect(
            "clicked",
            lambda *_: (
                popover.popdown(),
                self.show_german_game_info(game_name)
            )
        )
        box.append(info_button)

        popover.set_child(box)
        popover.popup()

    # --------------------------------------------------------
    # COVER / PATH
    # --------------------------------------------------------

    def get_cover_path(self, game_name):
        return (
            COVER_DIR
            / game_name
            / COVER_FILENAME
        )

    def _legacy_cover_path(self, game_name):
        if not self.gog_dir:
            return None
        return self.gog_dir / game_name / COVER_FILENAME

    def _migrate_legacy_covers(self):
        """Verschiebt alte Cover aus den Spieleordnern in den zentralen Cover-Ordner."""
        if not self.gog_dir or not self.gog_dir.is_dir():
            return 0

        moved = 0
        for game_name in self.games:
            old_path = self._legacy_cover_path(game_name)
            if not old_path or not old_path.is_file():
                continue

            new_path = self.get_cover_path(game_name)

            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)

                if new_path.is_file():
                    # Zentrales Cover hat Vorrang; altes Duplikat entfernen.
                    old_path.unlink()
                else:
                    shutil.move(str(old_path), str(new_path))

                moved += 1
            except Exception:
                # Migration darf die Bibliothek nicht blockieren.
                pass

        return moved

    def has_valid_cover(self, game_name):
        if not self.gog_dir:
            return False

        path = self.get_cover_path(game_name)

        if not path.is_file():
            return False

        try:
            with Image.open(path) as image:
                image.verify()
            return True
        except Exception:
            return False

    def open_game_folder(self, game_name):
        if not self.gog_dir:
            return

        folder = self.gog_dir / game_name

        try:
            Gio.AppInfo.launch_default_for_uri(
                folder.as_uri(),
                None
            )
        except Exception as exc:
            self.show_error(
                "Ordner konnte nicht geöffnet werden.",
                str(exc)
            )

    # --------------------------------------------------------
    # IGDB GAME METADATA
    # --------------------------------------------------------

    def show_german_game_info(self, game_name):
        self.status_label.set_text(
            self.tr("igdb_info_loading", game=game_name)
        )
        thread = threading.Thread(
            target=self._igdb_game_info_worker,
            args=(game_name,),
            daemon=True
        )
        thread.start()

    def _igdb_headers(self, token):
        return {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def _igdb_fields(self):
        return (
            "id,name,summary,storyline,first_release_date,"
            "genres.name,themes.name,game_modes.name,"
            "player_perspectives.name,platforms.name,"
            "involved_companies.company.name,"
            "involved_companies.developer,"
            "involved_companies.publisher,"
            "franchises.name,collections.name,"
            "aggregated_rating,aggregated_rating_count,"
            "rating,rating_count,total_rating,total_rating_count,"
            "cover.image_id,url"
        )

    def _fetch_igdb_by_id(self, igdb_id, token):
        body = (
            f"fields {self._igdb_fields()}; "
            f"where id = {int(igdb_id)}; "
            "limit 1;"
        )
        response = requests.post(
            "https://api.igdb.com/v4/games",
            headers=self._igdb_headers(token),
            data=body,
            timeout=20
        )
        response.raise_for_status()
        games = response.json()
        return games[0] if games else None

    def _search_igdb_candidates(self, game_name, token, limit=12):
        names_to_try = []
        cleaned = clean_game_title_for_search(game_name)

        for candidate in (game_name, cleaned):
            candidate = candidate.strip()
            if candidate and candidate not in names_to_try:
                names_to_try.append(candidate)

        all_games = {}
        for query_name in names_to_try:
            escaped = query_name.replace('"', '\\"')
            body = (
                f"fields {self._igdb_fields()}; "
                f'search "{escaped}"; '
                f"limit {int(limit)};"
            )
            response = requests.post(
                "https://api.igdb.com/v4/games",
                headers=self._igdb_headers(token),
                data=body,
                timeout=20
            )
            response.raise_for_status()
            for game in response.json():
                if game.get("id") is not None:
                    all_games[game["id"]] = game

        target_names = {
            normalize_name(game_name),
            normalize_name(cleaned),
        }

        def score(game):
            game_norm = normalize_name(game.get("name", ""))
            return max(
                similarity(target, game_norm)
                for target in target_names
                if target
            )

        candidates = list(all_games.values())
        candidates.sort(key=score, reverse=True)
        return candidates, score

    def _igdb_game_info_worker(self, game_name):
        try:
            cached_game = self.igdb_metadata.get(game_name)
            if isinstance(cached_game, dict) and cached_game:
                info = self._igdb_game_to_info(
                    cached_game,
                    game_name
                )
                GLib.idle_add(
                    self._show_igdb_game_info_window,
                    game_name,
                    info
                )
                return

            if not self.client_id or not self.client_secret:
                raise RuntimeError(
                    "Bitte zuerst in den Einstellungen die IGDB Client ID "
                    "und das IGDB Client Secret eintragen."
                )

            token = get_token(self.client_id, self.client_secret)

            mapped_id = self.igdb_mappings.get(game_name)
            game = None

            if mapped_id:
                try:
                    game = self._fetch_igdb_by_id(mapped_id, token)
                except Exception:
                    game = None

            if game is None:
                candidates, score_fn = self._search_igdb_candidates(
                    game_name,
                    token
                )
                if not candidates:
                    raise RuntimeError(
                        self.tr("igdb_no_match")
                    )

                best = candidates[0]
                best_score = score_fn(best)
                second_score = (
                    score_fn(candidates[1])
                    if len(candidates) > 1
                    else 0.0
                )

                # Only auto-accept a clearly strong match.
                if (
                    best_score >= 0.90 and
                    (best_score - second_score) >= 0.08
                ):
                    game = best
                    self.igdb_mappings[game_name] = game["id"]
                    save_igdb_mappings(self.igdb_mappings)
                else:
                    GLib.idle_add(
                        self._show_igdb_candidate_window,
                        game_name,
                        candidates
                    )
                    return

            self.igdb_metadata[game_name] = game
            save_igdb_metadata(self.igdb_metadata)

            info = self._igdb_game_to_info(game, game_name)
            GLib.idle_add(
                self._show_igdb_game_info_window,
                game_name,
                info
            )

        except Exception as exc:
            GLib.idle_add(
                self._igdb_game_info_failed,
                game_name,
                str(exc)
            )

    def _igdb_game_to_info(self, game, game_name):
        developers = []
        publishers = []

        for item in game.get("involved_companies", []) or []:
            company = item.get("company") or {}
            name = company.get("name")
            if not name:
                continue
            if item.get("developer") and name not in developers:
                developers.append(name)
            if item.get("publisher") and name not in publishers:
                publishers.append(name)

        release_date = []
        timestamp = game.get("first_release_date")
        if timestamp:
            try:
                from datetime import datetime
                release_date.append(
                    datetime.fromtimestamp(timestamp).strftime("%d.%m.%Y")
                )
            except (TypeError, ValueError, OSError):
                pass

        def names(field):
            result = []
            for item in game.get(field, []) or []:
                name = item.get("name") if isinstance(item, dict) else None
                if name and name not in result:
                    result.append(name)
            return result

        return {
            "igdb_id": game.get("id"),
            "title": game.get("name") or game_name,
            "summary": (game.get("summary") or "").strip(),
            "storyline": (game.get("storyline") or "").strip(),
            "developer": developers,
            "publisher": publishers,
            "genre": names("genres"),
            "themes": names("themes"),
            "game_modes": names("game_modes"),
            "perspectives": names("player_perspectives"),
            "platforms": names("platforms"),
            "franchises": names("franchises"),
            "collections": names("collections"),
            "release_date": release_date,
            "aggregated_rating": game.get("aggregated_rating"),
            "aggregated_rating_count": game.get("aggregated_rating_count"),
            "rating": game.get("rating"),
            "rating_count": game.get("rating_count"),
            "total_rating": game.get("total_rating"),
            "total_rating_count": game.get("total_rating_count"),
            "igdb_url": game.get("url"),
        }

    def choose_igdb_game_manually(self, game_name):
        self.status_label.set_text(
            self.tr("igdb_searching", game=game_name)
        )

        thread = threading.Thread(
            target=self._manual_igdb_search_worker,
            args=(game_name,),
            daemon=True
        )
        thread.start()

    def _manual_igdb_search_worker(self, game_name):
        try:
            if not self.client_id or not self.client_secret:
                raise RuntimeError(
                    "Bitte zuerst in den Einstellungen die IGDB Client ID "
                    "und das IGDB Client Secret eintragen."
                )

            token = get_token(
                self.client_id,
                self.client_secret
            )
            candidates, _ = self._search_igdb_candidates(
                game_name,
                token,
                limit=20
            )

            if not candidates:
                raise RuntimeError(
                    self.tr("igdb_no_results")
                )

            GLib.idle_add(
                self._show_igdb_candidate_window,
                game_name,
                candidates
            )

        except Exception as exc:
            GLib.idle_add(
                self._igdb_game_info_failed,
                game_name,
                str(exc)
            )

    def _show_igdb_candidate_window(self, game_name, candidates):
        self.status_label.set_text(self.tr("ready"))

        window = Gtk.Window(
            title=self.tr("igdb_choose_title", game=game_name)
        )
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(620, 520)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12
        )
        outer.set_margin_top(16)
        outer.set_margin_bottom(16)
        outer.set_margin_start(16)
        outer.set_margin_end(16)
        window.set_child(outer)

        info = Gtk.Label(
            label=self.tr("igdb_choose_text")
        )
        info.set_xalign(0)
        info.set_wrap(True)
        outer.append(info)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC
        )
        outer.append(scrolled)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scrolled.set_child(list_box)

        for game in candidates:
            row = Gtk.ListBoxRow()
            row.igdb_game = game

            box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=3
            )
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(10)
            box.set_margin_end(10)
            row.set_child(box)

            title = Gtk.Label(
                label=game.get("name", "Unbekannter Titel")
            )
            title.set_xalign(0)
            title.add_css_class("heading")
            box.append(title)

            year = ""
            timestamp = game.get("first_release_date")
            if timestamp:
                try:
                    from datetime import datetime
                    year = str(
                        datetime.fromtimestamp(timestamp).year
                    )
                except Exception:
                    year = ""

            platforms = ", ".join(
                p.get("name", "")
                for p in (game.get("platforms") or [])
                if p.get("name")
            )

            details_parts = []
            if year:
                details_parts.append(year)
            if platforms:
                details_parts.append(platforms)

            if details_parts:
                details = Gtk.Label(
                    label=" • ".join(details_parts)
                )
                details.set_xalign(0)
                details.set_wrap(True)
                details.add_css_class("dim-label")
                box.append(details)

            list_box.append(row)

        def choose_selected(*_):
            row = list_box.get_selected_row()
            if row is None:
                return

            game = row.igdb_game
            igdb_id = game.get("id")
            if igdb_id is None:
                return

            self.igdb_mappings[game_name] = igdb_id
            save_igdb_mappings(self.igdb_mappings)
            window.close()

            info_data = self._igdb_game_to_info(
                game,
                game_name
            )
            self._show_igdb_game_info_window(
                game_name,
                info_data
            )

        list_box.connect(
            "row-activated",
            lambda *_: choose_selected()
        )

        button_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        outer.append(button_row)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        button_row.append(spacer)

        cancel = Gtk.Button(label=self.tr("cancel"))
        cancel.connect(
            "clicked",
            lambda *_: window.close()
        )
        button_row.append(cancel)

        select = Gtk.Button(label=self.tr("select"))
        select.add_css_class("suggested-action")
        select.connect("clicked", choose_selected)
        button_row.append(select)

        window.present()

    def _show_igdb_game_info_window(self, game_name, info):
        self.status_label.set_text(self.tr("ready"))

        window = Gtk.Window(
            title=f"IGDB – {info.get('title') or game_name}"
        )
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(720, 680)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12
        )
        outer.set_margin_top(18)
        outer.set_margin_bottom(18)
        outer.set_margin_start(20)
        outer.set_margin_end(20)
        window.set_child(outer)

        title = Gtk.Label(
            label=info.get("title") or game_name
        )
        title.add_css_class("title-2")
        title.set_xalign(0)
        title.set_wrap(True)
        outer.append(title)

        source = Gtk.Label(label=self.tr("source_igdb"))
        source.set_xalign(0)
        source.add_css_class("dim-label")
        outer.append(source)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC
        )
        outer.append(scrolled)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10
        )
        content.set_margin_top(4)
        content.set_margin_bottom(4)
        content.set_margin_start(4)
        content.set_margin_end(12)
        scrolled.set_child(content)

        def add_field(label_text, values):
            if not values:
                return
            if not isinstance(values, (list, tuple)):
                values = [str(values)]
            row = Gtk.Label()
            row.set_xalign(0)
            row.set_wrap(True)
            row.set_selectable(True)
            row.set_markup(
                f"<b>{GLib.markup_escape_text(label_text)}:</b> "
                f"{GLib.markup_escape_text(', '.join(map(str, values)))}"
            )
            content.append(row)

        add_field(self.tr("developer"), info.get("developer"))
        add_field(self.tr("publisher"), info.get("publisher"))
        add_field(self.tr("release"), info.get("release_date"))
        add_field(self.tr("genre"), info.get("genre"))
        add_field(self.tr("themes"), info.get("themes"))
        add_field(self.tr("game_modes"), info.get("game_modes"))
        add_field(self.tr("perspective"), info.get("perspectives"))
        add_field(self.tr("platforms"), info.get("platforms"))
        add_field(self.tr("franchise"), info.get("franchises"))
        add_field(self.tr("collection"), info.get("collections"))

        rating = info.get("total_rating")
        rating_count = info.get("total_rating_count")
        if rating is not None:
            rating_text = f"{rating:.1f} / 100"
            if rating_count:
                rating_text += f" ({rating_count} Bewertungen)"
            add_field(self.tr("overall_rating"), rating_text)

        critic = info.get("aggregated_rating")
        critic_count = info.get("aggregated_rating_count")
        if critic is not None:
            critic_text = f"{critic:.1f} / 100"
            if critic_count:
                critic_text += f" ({critic_count} Kritikerwertungen)"
            add_field(self.tr("critic_rating"), critic_text)

        user_rating = info.get("rating")
        user_count = info.get("rating_count")
        if user_rating is not None:
            user_text = f"{user_rating:.1f} / 100"
            if user_count:
                user_text += f" ({user_count} Nutzerwertungen)"
            add_field(self.tr("user_rating"), user_text)

        summary = info.get("summary")
        storyline = info.get("storyline")

        if summary:
            separator = Gtk.Separator(
                orientation=Gtk.Orientation.HORIZONTAL
            )
            content.append(separator)

            heading = Gtk.Label(label=self.tr("description"))
            heading.set_xalign(0)
            heading.add_css_class("heading")
            content.append(heading)

            description = Gtk.Label(label=summary)
            description.set_xalign(0)
            description.set_yalign(0)
            description.set_wrap(True)
            description.set_selectable(True)
            content.append(description)

        if storyline:
            heading = Gtk.Label(label=self.tr("storyline"))
            heading.set_xalign(0)
            heading.add_css_class("heading")
            content.append(heading)

            storyline_label = Gtk.Label(label=storyline)
            storyline_label.set_xalign(0)
            storyline_label.set_yalign(0)
            storyline_label.set_wrap(True)
            storyline_label.set_selectable(True)
            content.append(storyline_label)

        if not summary and not storyline:
            note = Gtk.Label(
                label=self.tr("no_description")
            )
            note.set_xalign(0)
            note.set_wrap(True)
            content.append(note)

        button_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        outer.append(button_row)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        button_row.append(spacer)

        choose_igdb_button = Gtk.Button(
            label=self.tr("choose_igdb")
        )
        choose_igdb_button.connect(
            "clicked",
            lambda *_: (
                window.close(),
                self.choose_igdb_game_manually(game_name)
            )
        )
        button_row.append(choose_igdb_button)

        if info.get("igdb_url"):
            igdb_button = Gtk.Button(label=self.tr("open_igdb"))
            igdb_button.connect(
                "clicked",
                lambda *_: webbrowser.open(info["igdb_url"])
            )
            button_row.append(igdb_button)

        close_button = Gtk.Button(label=self.tr("close"))
        close_button.connect(
            "clicked",
            lambda *_: window.close()
        )
        button_row.append(close_button)

        window.present()

    def _igdb_game_info_failed(self, game_name, message):
        self.status_label.set_text(self.tr("ready"))
        self.show_error(
            self.tr("igdb_no_info", game=game_name),
            message
        )

    # --------------------------------------------------------
    # FIRST RUN / MISSING GOG FOLDER
    # --------------------------------------------------------

    def show_first_run_setup(self):
        # v64: Beim echten Erststart ist Englisch die Standardsprache.
        self.language = "en"
        self.apply_language()

        setup = Gtk.Window(title=self.tr("first_run_title"))
        setup.set_transient_for(self)
        setup.set_modal(True)
        setup.set_default_size(500, 300)
        setup.set_resizable(False)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.set_margin_top(24)
        outer.set_margin_bottom(24)
        outer.set_margin_start(28)
        outer.set_margin_end(28)
        setup.set_child(outer)

        title = Gtk.Label(label=self.tr("first_run_heading"))
        title.add_css_class("title-2")
        title.set_xalign(0)
        outer.append(title)

        info = Gtk.Label(label=self.tr("first_run_text"))
        info.set_xalign(0)
        info.set_wrap(True)
        outer.append(info)

        # v63: Ordnerauswahl an der früheren Position der Sprachauswahl.
        folder_label = Gtk.Label(label=self.tr("select_folder"))
        folder_label.set_xalign(0)
        outer.append(folder_label)

        folder_button = Gtk.Button(label=self.tr("select_folder"))
        folder_button.add_css_class("suggested-action")
        outer.append(folder_button)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        outer.append(spacer)

        # v63: Sprachauswahl unten an der früheren Position des Ordnerbuttons.
        language_label = Gtk.Label(label=self.tr("language"))
        language_label.set_xalign(0)
        outer.append(language_label)

        language_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new([
                self.tr("german"),
                self.tr("english")
            ])
        )
        language_dropdown.set_selected(0 if self.language == "de" else 1)
        outer.append(language_dropdown)

        buttons = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        buttons.set_halign(Gtk.Align.END)
        outer.append(buttons)

        quit_button = Gtk.Button(label=self.tr("quit"))
        buttons.append(quit_button)

        def first_run_language_changed(dropdown, _pspec):
            new_language = "de" if dropdown.get_selected() == 0 else "en"
            if new_language == self.language:
                return

            self.language = new_language
            save_config(
                self.client_id, self.client_secret, self.gog_dir,
                self.cover_size, self.language, self.theme
            )

            # v65: Oberfläche sofort übersetzen, aber das Dropdown-Modell
            # während seines eigenen notify::selected-Signals NICHT ersetzen.
            # Das konnte in GTK4 zu einem Absturz führen.
            self.apply_language()
            setup.set_title(self.tr("first_run_title"))
            title.set_text(self.tr("first_run_heading"))
            info.set_text(self.tr("first_run_text"))
            folder_label.set_text(self.tr("select_folder"))
            folder_button.set_label(self.tr("select_folder"))
            language_label.set_text(self.tr("language"))
            quit_button.set_label(self.tr("quit"))

        def folder_selected(path):
            if path:
                setup.close()
                self.status_label.set_text(self.tr("ready"))

        def choose_folder(_button):
            self.choose_gog_folder(
                parent=setup,
                callback=folder_selected
            )

        language_dropdown.connect(
            "notify::selected",
            first_run_language_changed
        )
        folder_button.connect("clicked", choose_folder)
        quit_button.connect(
            "clicked",
            lambda *_: self.get_application().quit()
        )

        setup.connect(
            "close-request",
            lambda *_: self._quit_from_first_run()
        )

        setup.present()
        return False


    def _quit_from_first_run(self):
        if not self.gog_dir:
            self.get_application().quit()
        return False

    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

    def open_settings(self, *_):
        window = Gtk.Window(
            title=self.tr("settings_title")
        )
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(650, 560)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12
        )
        outer.set_margin_top(20)
        outer.set_margin_bottom(20)
        outer.set_margin_start(24)
        outer.set_margin_end(24)
        window.set_child(outer)

        title = Gtk.Label(
            label=self.tr("settings_heading")
        )
        title.add_css_class("title-2")
        title.set_xalign(0)
        outer.append(title)

        client_label = Gtk.Label(label=self.tr("client_id"))
        client_label.set_xalign(0)
        outer.append(client_label)

        client_entry = Gtk.Entry()
        client_entry.set_text(self.client_id)
        outer.append(client_entry)

        secret_label = Gtk.Label(
            label=self.tr("client_secret")
        )
        secret_label.set_xalign(0)
        outer.append(secret_label)

        secret_entry = Gtk.PasswordEntry()
        secret_entry.set_show_peek_icon(True)
        secret_entry.set_text(self.client_secret)
        outer.append(secret_entry)

        separator = Gtk.Separator()
        outer.append(separator)

        folder_title = Gtk.Label(
            label=self.tr("gog_folder")
        )
        folder_title.set_xalign(0)
        outer.append(folder_title)

        folder_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10
        )
        outer.append(folder_row)

        folder_label = Gtk.Label(
            label=(
                str(self.gog_dir)
                if self.gog_dir
                else self.tr("no_folder")
            )
        )
        folder_label.set_xalign(0)
        folder_label.set_hexpand(True)
        folder_label.set_ellipsize(3)
        folder_row.append(folder_label)

        change_button = Gtk.Button(
            label=self.tr("change")
        )
        folder_row.append(change_button)

        def change_folder(*_):
            self.choose_gog_folder(
                parent=window,
                callback=lambda path: folder_label.set_text(
                    str(path)
                ) if path else None
            )

        change_button.connect(
            "clicked",
            change_folder
        )

        separator_language = Gtk.Separator()
        outer.append(separator_language)

        language_label = Gtk.Label(
            label=self.tr("language")
        )
        language_label.set_xalign(0)
        outer.append(language_label)

        language_model = Gtk.StringList.new([
            self.tr("german"),
            self.tr("english")
        ])
        language_dropdown = Gtk.DropDown(
            model=language_model
        )
        language_dropdown.set_selected(
            0 if self.language == "de" else 1
        )
        language_dropdown.set_hexpand(False)
        outer.append(language_dropdown)

        appearance_label = Gtk.Label(
            label=self.tr("appearance")
        )
        appearance_label.set_xalign(0)
        outer.append(appearance_label)

        theme_model = Gtk.StringList.new([
            self.tr("theme_system"),
            self.tr("theme_light"),
            self.tr("theme_dark")
        ])
        theme_dropdown = Gtk.DropDown(
            model=theme_model
        )
        theme_dropdown.set_selected(
            self._theme_index()
        )
        theme_dropdown.set_hexpand(False)
        outer.append(theme_dropdown)

        reset_separator = Gtk.Separator()
        outer.append(reset_separator)

        reset_label = Gtk.Label(
            label=self.tr("data_reset")
        )
        reset_label.add_css_class("heading")
        reset_label.set_xalign(0)
        outer.append(reset_label)

        reset_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        reset_row.set_halign(Gtk.Align.START)
        outer.append(reset_row)

        delete_covers_button = Gtk.Button(
            label=self.tr("delete_covers")
        )
        delete_covers_button.add_css_class("destructive-action")
        delete_covers_button.connect(
            "clicked",
            lambda *_: self.confirm_delete_covers(window)
        )
        reset_row.append(delete_covers_button)

        delete_mappings_button = Gtk.Button(
            label=self.tr("delete_mappings")
        )
        delete_mappings_button.add_css_class("destructive-action")
        delete_mappings_button.connect(
            "clicked",
            lambda *_: self.confirm_delete_mappings(window)
        )
        reset_row.append(delete_mappings_button)

        delete_all_button = Gtk.Button(
            label=self.tr("delete_all_data")
        )
        delete_all_button.add_css_class("destructive-action")
        delete_all_button.connect(
            "clicked",
            lambda *_: self.confirm_delete_all_data(window)
        )
        reset_row.append(delete_all_button)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        outer.append(spacer)

        button_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        button_row.set_halign(Gtk.Align.END)
        outer.append(button_row)

        cancel_button = Gtk.Button(
            label=self.tr("cancel")
        )
        cancel_button.connect(
            "clicked",
            lambda *_: window.close()
        )
        button_row.append(cancel_button)

        save_button = Gtk.Button(
            label=self.tr("save")
        )
        save_button.add_css_class("suggested-action")
        button_row.append(save_button)

        def save_settings(*_):
            client_id = client_entry.get_text().strip()
            client_secret = secret_entry.get_text().strip()

            if not client_id or not client_secret:
                self.show_error(
                    self.tr("credentials_missing_title"),
                    self.tr("credentials_missing_text"),
                    parent=window
                )
                return

            self.client_id = client_id
            self.client_secret = client_secret
            self.language = (
                "de"
                if language_dropdown.get_selected() == 0
                else "en"
            )
            self.theme = (
                "system"
                if theme_dropdown.get_selected() == 0
                else "light"
                if theme_dropdown.get_selected() == 1
                else "dark"
            )

            save_config(
                self.client_id,
                self.client_secret,
                self.gog_dir,
                self.cover_size,
                self.language,
                self.theme
            )

            self.apply_theme()
            self.apply_language()
            self.reload_collection()
            window.close()

        save_button.connect(
            "clicked",
            save_settings
        )

        window.present()
        return False

    def _cover_files(self):
        if not COVER_DIR.is_dir():
            return []

        return [
            game_dir / COVER_FILENAME
            for game_dir in COVER_DIR.iterdir()
            if game_dir.is_dir()
            and (game_dir / COVER_FILENAME).is_file()
        ]

    def _delete_cover_files(self):
        deleted = 0
        for cover_path in self._cover_files():
            try:
                cover_path.unlink()
                deleted += 1
            except OSError:
                pass

        try:
            if COVER_DIR.is_dir():
                for game_dir in COVER_DIR.iterdir():
                    if game_dir.is_dir():
                        try:
                            game_dir.rmdir()
                        except OSError:
                            pass
        except OSError:
            pass

        self.reload_collection()
        return deleted

    def _delete_igdb_mappings(self):
        self.igdb_mappings = {}
        self.igdb_metadata = {}
        self.igdb_sync_state = {}

        try:
            if IGDB_MAPPING_FILE.exists():
                IGDB_MAPPING_FILE.unlink()
        except OSError:
            save_igdb_mappings({})

        try:
            if IGDB_METADATA_FILE.exists():
                IGDB_METADATA_FILE.unlink()
        except OSError:
            save_igdb_metadata({})

        try:
            if IGDB_SYNC_STATE_FILE.exists():
                IGDB_SYNC_STATE_FILE.unlink()
        except OSError:
            save_igdb_sync_state({})

        return True

    def _confirm_destructive(self, parent, title, detail, callback):
        dialog = Gtk.AlertDialog()
        dialog.set_message(title)
        dialog.set_detail(detail)
        dialog.set_buttons([
            self.tr("cancel"),
            self.tr("delete")
        ])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)

        def finished(alert, result):
            try:
                choice = alert.choose_finish(result)
            except GLib.Error:
                return

            if choice == 1:
                callback()

        dialog.choose(
            parent or self,
            None,
            finished
        )

    def confirm_delete_covers(self, parent=None):
        count = len(self._cover_files())

        def delete_covers():
            deleted = self._delete_cover_files()
            self.reload_collection()
            self.show_info(
                self.tr("data_reset"),
                self.tr("deleted_covers", count=deleted),
                parent=parent
            )

        self._confirm_destructive(
            parent,
            self.tr("delete_covers_confirm"),
            self.tr("delete_covers_detail", count=count),
            delete_covers
        )

    def confirm_delete_mappings(self, parent=None):
        def delete_mappings():
            self._delete_igdb_mappings()
            self.reload_collection()
            self.show_info(
                self.tr("data_reset"),
                self.tr("deleted_mappings"),
                parent=parent
            )

        self._confirm_destructive(
            parent,
            self.tr("delete_mappings_confirm"),
            self.tr("delete_mappings_detail"),
            delete_mappings
        )

    def confirm_delete_all_data(self, parent=None):
        count = len(self._cover_files())

        def delete_all():
            deleted = self._delete_cover_files()
            self._delete_igdb_mappings()

            # v43: Nach dem Komplett-Reset sofort neu auswerten.
            # complete == 0 -> alle Achievement-Zähler stehen bei 0.
            self.reload_collection()

            self.show_info(
                self.tr("data_reset"),
                self.tr("deleted_all", count=deleted),
                parent=parent
            )

        self._confirm_destructive(
            parent,
            self.tr("delete_all_confirm"),
            self.tr("delete_all_detail", count=count),
            delete_all
        )

    def check_credentials(self):
        if self.client_id and self.client_secret:
            return True

        self.show_error(
            self.tr("igdb_credentials_missing"),
            self.tr("igdb_credentials_missing_text")
        )
        self.open_settings()
        return False

    # --------------------------------------------------------
    # GTK FILE DIALOGS
    # --------------------------------------------------------

    def choose_gog_folder(
        self,
        parent=None,
        callback=None
    ):
        dialog = Gtk.FileDialog()
        dialog.set_title(
            self.tr("folder_dialog_title")
        )

        parent = parent or self

        def finished(file_dialog, result):
            selected_path = None

            try:
                file = file_dialog.select_folder_finish(
                    result
                )

                if file:
                    path = file.get_path()

                    if path:
                        selected_path = Path(
                            path
                        ).expanduser().resolve()

                        self.gog_dir = selected_path
                        if hasattr(self, "path_label"):
                            self.path_label.set_text(
                                str(self.gog_dir)
                            )

                        save_config(
                            self.client_id,
                            self.client_secret,
                            self.gog_dir,
                            self.cover_size,
                            self.language,
                            self.theme
                        )

                        self.reload_collection()

            except GLib.Error:
                pass

            if callback:
                callback(selected_path)

        dialog.select_folder(
            parent,
            None,
            finished
        )

    def choose_local_cover(
        self,
        game_name,
        allow_overwrite=True,
        callback=None
    ):
        if (
            not allow_overwrite
            and self.has_valid_cover(game_name)
        ):
            if callback:
                callback(False)
            return

        dialog = Gtk.FileDialog()
        dialog.set_title("Cover auswählen")

        def finished(file_dialog, result):
            success = False

            try:
                file = file_dialog.open_finish(result)

                if file:
                    path = file.get_path()

                    if path:
                        destination = self.get_cover_path(
                            game_name
                        )
                        destination.parent.mkdir(
                            parents=True,
                            exist_ok=True
                        )

                        with Image.open(path) as image:
                            image.convert("RGB").save(
                                destination,
                                "JPEG",
                                quality=95
                            )

                        success = True
                        self.reload_collection()

            except GLib.Error:
                pass

            except Exception as exc:
                self.show_error(
                    "Cover konnte nicht gespeichert werden.",
                    str(exc)
                )

            if callback:
                callback(success)

        dialog.open(
            self,
            None,
            finished
        )

    # --------------------------------------------------------
    # BROWSER
    # --------------------------------------------------------

    def search_cover_in_browser(
        self,
        game_name
    ):
        query = urllib.parse.quote(
            f"{game_name} game cover"
        )

        webbrowser.open(
            "https://www.google.com/search"
            f"?tbm=isch&q={query}"
        )

    # --------------------------------------------------------
    # REPLACE
    # --------------------------------------------------------

    def start_replace(self, game_name):
        if self.scan_running:
            return

        if not self.check_credentials():
            return

        self.set_busy(
            True,
            f"Suche Cover für {game_name} …"
        )

        def worker():
            try:
                token = get_token(
                    self.client_id,
                    self.client_secret
                )

                results = search_game(
                    game_name,
                    self.client_id,
                    token
                )

                GLib.idle_add(
                    self._replace_results_ready,
                    game_name,
                    results,
                    None
                )

            except Exception as exc:
                GLib.idle_add(
                    self._replace_results_ready,
                    game_name,
                    [],
                    str(exc)
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def _replace_results_ready(
        self,
        game_name,
        results,
        error
    ):
        self.set_busy(False)

        if error:
            self.show_error(
                "IGDB Fehler",
                error
            )
            return False

        if not results:
            self.show_no_result_window(
                game_name,
                replace=True
            )
            return False

        self.show_result_window(
            game_name,
            results,
            replace=True
        )

        return False

    # --------------------------------------------------------
    # AUTOMATIC STARTUP SYNC
    # --------------------------------------------------------

    def start_startup_sync(self):
        if self.startup_sync_started:
            return False

        self.startup_sync_started = True

        if (
            not self.gog_dir
            or not self.games
            or not self.client_id
            or not self.client_secret
        ):
            return False

        # Only games that are genuinely missing data AND have not already
        # been checked automatically are sent to IGDB. This prevents
        # unresolved/no-match games from being searched again on every start.
        pending_games = []

        for game_name in self.games:
            cached_game = self.igdb_metadata.get(game_name)
            has_metadata = (
                isinstance(cached_game, dict)
                and bool(cached_game)
            )
            has_cover = self.has_valid_cover(game_name)

            if has_cover and has_metadata:
                self.igdb_sync_state[game_name] = {
                    "checked": True,
                    "complete": True
                }
                continue

            state = self.igdb_sync_state.get(game_name, {})
            already_checked = (
                isinstance(state, dict)
                and state.get("checked") is True
            )

            if not already_checked:
                pending_games.append(game_name)

        save_igdb_sync_state(self.igdb_sync_state)

        if not pending_games:
            self.status_label.set_text(
                "✓ Keine neue automatische IGDB-Suche erforderlich."
            )
            return False

        self._begin_live_achievement_tracking()

        self.scan_running = True
        self.set_buttons_enabled(False)
        self.progress.set_visible(True)
        self.progress.set_fraction(0)
        self.progress.set_text(
            f"0 / {len(pending_games)}"
        )
        self.status_label.set_text(
            "Fehlende IGDB-Daten werden automatisch synchronisiert …"
        )

        threading.Thread(
            target=self._startup_sync_worker,
            args=(pending_games,),
            daemon=True
        ).start()

        return False

    def _startup_sync_worker(self, pending_games):
        try:
            token = get_token(
                self.client_id,
                self.client_secret
            )
        except Exception as exc:
            GLib.idle_add(
                self._startup_sync_failed,
                str(exc)
            )
            return

        total = len(pending_games)
        metadata_changed = False
        mappings_changed = False

        for index, game_name in enumerate(
            pending_games,
            start=1
        ):
            needs_cover = not self.has_valid_cover(game_name)
            cached_game = self.igdb_metadata.get(game_name)
            needs_metadata = not (
                isinstance(cached_game, dict)
                and cached_game
            )

            game = cached_game if isinstance(cached_game, dict) else None

            try:
                if game is None:
                    mapped_id = self.igdb_mappings.get(game_name)

                    if mapped_id:
                        game = self._fetch_igdb_by_id(
                            mapped_id,
                            token
                        )

                    if game is None:
                        candidates, score_fn = self._search_igdb_candidates(
                            game_name,
                            token
                        )

                        if candidates:
                            best = candidates[0]
                            best_score = score_fn(best)
                            second_score = (
                                score_fn(candidates[1])
                                if len(candidates) > 1
                                else 0.0
                            )

                            if (
                                best_score >= 0.90
                                and (
                                    best_score - second_score
                                ) >= 0.08
                            ):
                                game = best
                                self.igdb_mappings[game_name] = game["id"]
                                mappings_changed = True

                if game is not None:
                    if needs_metadata:
                        self.igdb_metadata[game_name] = game
                        metadata_changed = True

                    if needs_cover and game.get("cover", {}).get("image_id"):
                        cover_downloaded = self.download_cover(
                            game_name,
                            game,
                            allow_overwrite=False
                        )
                        if cover_downloaded:
                            GLib.idle_add(
                                self._refresh_game_card_live,
                                game_name
                            )

            except Exception:
                # Startup sync remains silent for individual failures.
                pass

            self.igdb_sync_state[game_name] = {
                "checked": True,
                "complete": (
                    self.has_valid_cover(game_name)
                    and isinstance(
                        self.igdb_metadata.get(game_name),
                        dict
                    )
                    and bool(
                        self.igdb_metadata.get(game_name)
                    )
                )
            }

            GLib.idle_add(
                self._set_progress,
                index,
                total,
                game_name
            )
            GLib.idle_add(
                self._live_scan_dashboard_update,
                game_name
            )

            time.sleep(0.05)

        save_igdb_sync_state(
            self.igdb_sync_state
        )

        if mappings_changed:
            save_igdb_mappings(self.igdb_mappings)

        if metadata_changed:
            save_igdb_metadata(self.igdb_metadata)

        GLib.idle_add(
            self._finish_startup_sync
        )

    def _startup_sync_failed(self, message):
        self.scan_running = False
        self.set_buttons_enabled(True)
        self.progress.set_visible(False)
        self.progress.set_fraction(0)
        self.progress.set_text("")
        self.status_label.set_text(
            "Automatische IGDB-Synchronisierung fehlgeschlagen."
        )
        return False

    def _finish_startup_sync(self):
        self.scan_running = False
        self.set_buttons_enabled(True)
        self.progress.set_visible(False)
        self.progress.set_fraction(0)
        self.progress.set_text("")
        self.status_label.set_text(
            "✓ Cover und IGDB-Metadaten synchronisiert."
        )
        self._achievement_live_count = None
        self.reload_collection()
        return False

    # --------------------------------------------------------
    # MISSING COVER SCAN
    # --------------------------------------------------------

    def on_missing_clicked(self, *_):
        if self.scan_running:
            return

        if not self.gog_dir:
            self.show_error(
                "Kein GOG-Ordner",
                "Bitte zuerst unter Einstellungen einen GOG-Spieleordner auswählen."
            )
            return

        if not self.check_credentials():
            return

        # v42: Der manuelle Scan prüft jetzt nicht nur Cover,
        # sondern auch fehlende IGDB-Metadaten.
        missing = [
            game
            for game in self.games
            if (
                not self.has_valid_cover(game)
                or not self._has_metadata(game)
            )
        ]

        if not missing:
            self.show_info(
                "Sammlung vollständig",
                "Alle Spiele besitzen ein gültiges Cover und IGDB-Metadaten."
            )
            return

        self._begin_live_achievement_tracking()

        self.scan_running = True
        self.set_buttons_enabled(False)
        self.progress.set_visible(True)
        self.progress.set_fraction(0)
        self.progress.set_text(
            f"0 / {len(missing)}"
        )

        threading.Thread(
            target=self._missing_scan_worker,
            args=(missing,),
            daemon=True
        ).start()

    def _missing_scan_worker(self, games):
        try:
            token = get_token(
                self.client_id,
                self.client_secret
            )
        except Exception as exc:
            GLib.idle_add(
                self._scan_failed,
                str(exc)
            )
            return

        total = len(games)

        for index, game_name in enumerate(
            games,
            start=1
        ):
            needs_cover = not self.has_valid_cover(game_name)
            needs_metadata = not self._has_metadata(game_name)

            game = None

            try:
                # Bereits gespeicherte Metadaten können direkt für ein
                # fehlendes Cover verwendet werden.
                cached_game = self.igdb_metadata.get(game_name)
                if isinstance(cached_game, dict) and cached_game:
                    game = cached_game

                # Eine vorhandene manuelle IGDB-Zuordnung ist zuverlässiger
                # als eine neue Namenssuche.
                if game is None:
                    mapped_id = self.igdb_mappings.get(game_name)
                    if mapped_id:
                        game = self._fetch_igdb_by_id(
                            mapped_id,
                            token
                        )

                candidates = []
                score_fn = None

                if game is None:
                    candidates, score_fn = self._search_igdb_candidates(
                        game_name,
                        token,
                        limit=20
                    )

                    # Das Auswahlfenster benötigt _score. Die Kandidaten
                    # enthalten jetzt trotzdem den vollständigen IGDB-Datensatz.
                    if score_fn:
                        for candidate in candidates:
                            candidate["_score"] = score_fn(candidate)

                    if candidates:
                        best = candidates[0]
                        best_score = best.get("_score", 0.0)
                        second_score = (
                            candidates[1].get("_score", 0.0)
                            if len(candidates) > 1
                            else 0.0
                        )

                        automatic = (
                            best_score >= AUTO_MATCH_SCORE
                            and (
                                len(candidates) == 1
                                or best_score - second_score
                                >= AUTO_MATCH_MARGIN
                            )
                        )

                        if automatic:
                            game = best

                if game is not None:
                    igdb_id = game.get("id")

                    if igdb_id is not None:
                        self.igdb_mappings[game_name] = igdb_id
                        save_igdb_mappings(
                            self.igdb_mappings
                        )

                    # Der entscheidende v42-Fix:
                    # vollständige IGDB-Daten beim Scan speichern.
                    self.igdb_metadata[game_name] = game
                    save_igdb_metadata(
                        self.igdb_metadata
                    )

                    if (
                        needs_cover
                        and game.get("cover", {}).get("image_id")
                    ):
                        cover_downloaded = self.download_cover(
                            game_name,
                            game,
                            allow_overwrite=False
                        )

                        # v67: Cover sofort sichtbar machen, während der
                        # restliche Scan im Hintergrund weiterläuft.
                        if cover_downloaded:
                            GLib.idle_add(
                                self._refresh_game_card_live,
                                game_name
                            )

                elif needs_cover:
                    # Bei unsicheren Treffern weiterhin wie bisher
                    # eine manuelle Auswahl anbieten. Die Treffer enthalten
                    # jetzt bereits vollständige Metadaten.
                    answer = self._wait_for_manual_answer(
                        game_name,
                        candidates,
                        False
                    )

                    if answer == "stop":
                        break

                # Bei einem Spiel mit vorhandenem Cover, aber unsicherem
                # IGDB-Match, wird das Cover nicht unnötig überschrieben.
                # Die Zuordnung kann weiterhin über "Spielinformationen
                # (IGDB)" manuell gewählt werden.

            except Exception:
                # Ein einzelner fehlerhafter IGDB-Eintrag soll den gesamten
                # Scan nicht abbrechen.
                pass

            self.igdb_sync_state[game_name] = {
                "checked": True,
                "complete": (
                    self.has_valid_cover(game_name)
                    and self._has_metadata(game_name)
                )
            }
            save_igdb_sync_state(
                self.igdb_sync_state
            )

            GLib.idle_add(
                self._set_progress,
                index,
                total,
                game_name
            )
            GLib.idle_add(
                self._live_scan_dashboard_update,
                game_name
            )

            time.sleep(0.10)

        GLib.idle_add(
            self._finish_scan
        )

    def _wait_for_manual_answer(
        self,
        game_name,
        results,
        replace
    ):
        event = threading.Event()
        answer_holder = {
            "answer": "skip"
        }

        def show():
            def done(answer):
                answer_holder["answer"] = answer
                event.set()

            if results:
                self.show_result_window(
                    game_name,
                    results,
                    replace=replace,
                    completion_callback=done
                )
            else:
                self.show_no_result_window(
                    game_name,
                    replace=replace,
                    completion_callback=done
                )

            return False

        GLib.idle_add(show)
        event.wait()

        return answer_holder["answer"]

    def _set_progress(
        self,
        current,
        total,
        game_name
    ):
        fraction = (
            current / total
            if total
            else 0
        )

        self.progress.set_fraction(fraction)
        self.progress.set_text(
            f"{current} / {total} – {game_name}"
        )

        return False

    def _scan_failed(self, message):
        self.scan_running = False
        self.set_buttons_enabled(True)
        self.progress.set_visible(False)
        self.progress.set_fraction(0)
        self.progress.set_text("")

        self.show_error(
            "IGDB Fehler",
            message
        )

        return False

    def _finish_scan(self):
        self.scan_running = False
        self.set_buttons_enabled(True)
        self.progress.set_visible(False)
        self.progress.set_fraction(0)
        self.progress.set_text("")

        self.status_label.set_text(
            "✓ Cover und IGDB-Metadaten verarbeitet."
        )

        self._achievement_live_count = None
        self.reload_collection()
        return False

    # --------------------------------------------------------
    # RESULT WINDOW
    # --------------------------------------------------------

    def _refresh_metadata_for_selected_game(
        self,
        game_name,
        igdb_id
    ):
        if (
            not self.client_id
            or not self.client_secret
            or igdb_id is None
        ):
            return

        def worker():
            try:
                token = get_token(
                    self.client_id,
                    self.client_secret
                )
                full_game = self._fetch_igdb_by_id(
                    igdb_id,
                    token
                )

                if not full_game:
                    return

                self.igdb_metadata[game_name] = full_game
                save_igdb_metadata(
                    self.igdb_metadata
                )

                self.igdb_sync_state[game_name] = {
                    "checked": True,
                    "complete": self.has_valid_cover(game_name)
                }
                save_igdb_sync_state(
                    self.igdb_sync_state
                )

                GLib.idle_add(
                    self.status_label.set_text,
                    f"✓ Cover und IGDB-Metadaten aktualisiert: {game_name}"
                )
            except Exception as exc:
                GLib.idle_add(
                    self.status_label.set_text,
                    f"Cover geändert – Metadaten konnten nicht geladen werden: {exc}"
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def show_result_window(
        self,
        game_name,
        results,
        replace=False,
        completion_callback=None
    ):
        window = Gtk.Window(
            title=(
                "Cover ersetzen"
                if replace
                else "Cover auswählen"
            )
        )
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(850, 700)

        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10
        )
        root.set_margin_top(16)
        root.set_margin_bottom(16)
        root.set_margin_start(16)
        root.set_margin_end(16)
        window.set_child(root)

        title = Gtk.Label(label=game_name)
        title.add_css_class("title-2")
        title.set_xalign(0)
        root.append(title)

        subtitle = Gtk.Label(
            label="Wähle das passende Cover aus."
        )
        subtitle.set_xalign(0)
        subtitle.add_css_class("dim-label")
        root.append(subtitle)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC
        )
        root.append(scrolled)

        result_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10
        )
        scrolled.set_child(result_box)

        closed = {
            "done": False
        }

        def complete(answer):
            if closed["done"]:
                return

            closed["done"] = True

            if completion_callback:
                completion_callback(answer)

        def choose_result(game):
            success = self.download_cover(
                game_name,
                game,
                allow_overwrite=replace
            )

            if success:
                if game.get("id") is not None:
                    self.igdb_mappings[game_name] = game["id"]
                    save_igdb_mappings(
                        self.igdb_mappings
                    )

                    if replace:
                        # Beim Cover-Ersetzen kann der Treffer aus einer
                        # schlanken Cover-Suche stammen: vollständige Daten
                        # deshalb weiterhin explizit per ID nachladen.
                        self._refresh_metadata_for_selected_game(
                            game_name,
                            game["id"]
                        )
                    else:
                        # v42: Beim normalen Scan stammen die Treffer aus
                        # _search_igdb_candidates und enthalten bereits die
                        # vollständigen IGDB-Felder.
                        self.igdb_metadata[game_name] = game
                        save_igdb_metadata(
                            self.igdb_metadata
                        )
                        self.igdb_sync_state[game_name] = {
                            "checked": True,
                            "complete": self.has_valid_cover(game_name)
                        }
                        save_igdb_sync_state(
                            self.igdb_sync_state
                        )

                window.close()
                self.reload_collection()
                complete("done")
            else:
                self.show_error(
                    "Download fehlgeschlagen",
                    "Das Cover konnte nicht gespeichert werden.",
                    parent=window
                )

        for game in results:
            card = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=14
            )
            card.add_css_class("result-card")
            card.set_margin_start(4)
            card.set_margin_end(4)
            result_box.append(card)

            image = Gtk.Picture()
            image.set_size_request(
                RESULT_COVER_WIDTH,
                RESULT_COVER_HEIGHT
            )
            image.set_can_shrink(False)
            image.set_content_fit(
                Gtk.ContentFit.FILL
            )
            image.set_halign(Gtk.Align.CENTER)
            image.set_valign(Gtk.Align.CENTER)
            card.append(image)

            info = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=8
            )
            info.set_hexpand(True)
            info.set_valign(Gtk.Align.CENTER)
            card.append(info)

            name_label = Gtk.Label(
                label=game.get(
                    "name",
                    "Unbekannt"
                )
            )
            name_label.add_css_class(
                "heading"
            )
            name_label.set_xalign(0)
            name_label.set_wrap(True)
            info.append(name_label)

            score = Gtk.Label(
                label=(
                    "Übereinstimmung: "
                    f"{game['_score'] * 100:.1f}%"
                )
            )
            score.set_xalign(0)
            score.add_css_class("dim-label")
            info.append(score)

            choose = Gtk.Button(
                label="✓ Dieses Cover verwenden"
            )
            choose.set_halign(Gtk.Align.START)
            choose.connect(
                "clicked",
                lambda _button, g=game:
                    choose_result(g)
            )
            info.append(choose)

            self.load_remote_preview(
                game,
                image
            )

        action_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        action_row.set_halign(Gtk.Align.END)
        root.append(action_row)

        browser_button = Gtk.Button(
            label="🌐 Browser-Suche"
        )
        browser_button.connect(
            "clicked",
            lambda *_:
                self.search_cover_in_browser(
                    game_name
                )
        )
        action_row.append(browser_button)

        local_button = Gtk.Button(
            label="📥 Von Festplatte"
        )

        def local_clicked(*_):
            def selected(success):
                if success:
                    window.close()
                    complete("done")

            self.choose_local_cover(
                game_name,
                allow_overwrite=replace,
                callback=selected
            )

        local_button.connect(
            "clicked",
            local_clicked
        )
        action_row.append(local_button)

        cancel_button = Gtk.Button(
            label=(
                "Abbrechen"
                if replace
                else "⏭ Überspringen"
            )
        )

        def cancel(*_):
            window.close()
            complete("skip")

        cancel_button.connect(
            "clicked",
            cancel
        )
        action_row.append(cancel_button)

        def on_close_request(*_):
            complete("skip")
            return False

        window.connect(
            "close-request",
            on_close_request
        )

        window.present()

    def show_no_result_window(
        self,
        game_name,
        replace=False,
        completion_callback=None
    ):
        window = Gtk.Window(
            title="Kein Cover gefunden"
        )
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(620, 230)

        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12
        )
        root.set_margin_top(22)
        root.set_margin_bottom(22)
        root.set_margin_start(24)
        root.set_margin_end(24)
        window.set_child(root)

        title = Gtk.Label(label=game_name)
        title.add_css_class("title-2")
        title.set_xalign(0)
        root.append(title)

        message = Gtk.Label(
            label="IGDB hat kein passendes Cover gefunden."
        )
        message.set_xalign(0)
        root.append(message)

        actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )
        actions.set_halign(Gtk.Align.END)
        actions.set_vexpand(True)
        actions.set_valign(Gtk.Align.END)
        root.append(actions)

        closed = {
            "done": False
        }

        def complete(answer):
            if closed["done"]:
                return
            closed["done"] = True

            if completion_callback:
                completion_callback(answer)

        browser_button = Gtk.Button(
            label="🌐 Im Browser suchen"
        )
        browser_button.connect(
            "clicked",
            lambda *_:
                self.search_cover_in_browser(
                    game_name
                )
        )
        actions.append(browser_button)

        local_button = Gtk.Button(
            label="📥 Von Festplatte"
        )

        def local_clicked(*_):
            def selected(success):
                if success:
                    window.close()
                    complete("done")

            self.choose_local_cover(
                game_name,
                allow_overwrite=replace,
                callback=selected
            )

        local_button.connect(
            "clicked",
            local_clicked
        )
        actions.append(local_button)

        cancel_button = Gtk.Button(
            label=(
                "Abbrechen"
                if replace
                else "⏭ Überspringen"
            )
        )

        def cancel(*_):
            window.close()
            complete("skip")

        cancel_button.connect(
            "clicked",
            cancel
        )
        actions.append(cancel_button)

        def on_close_request(*_):
            complete("skip")
            return False

        window.connect(
            "close-request",
            on_close_request
        )

        window.present()

    def load_remote_preview(
        self,
        game,
        image_widget
    ):
        image_id = (
            game.get("cover", {})
            .get("image_id")
        )

        if not image_id:
            image_widget.set_paintable(None)
            return

        def worker():
            try:
                response = requests.get(
                    cover_url(image_id),
                    timeout=20
                )
                response.raise_for_status()

                pixbuf = pixbuf_from_bytes(
                    response.content,
                    RESULT_COVER_WIDTH,
                    RESULT_COVER_HEIGHT
                )

                GLib.idle_add(
                    image_widget.set_pixbuf,
                    pixbuf
                )

            except Exception:
                GLib.idle_add(
                    image_widget.set_paintable,
                    None
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    # --------------------------------------------------------
    # DOWNLOAD
    # --------------------------------------------------------

    def download_cover(
        self,
        game_name,
        game,
        allow_overwrite=False
    ):
        if (
            not allow_overwrite
            and self.has_valid_cover(game_name)
        ):
            return False

        image_id = (
            game.get("cover", {})
            .get("image_id")
        )

        if not image_id:
            return False

        try:
            response = requests.get(
                cover_url(image_id),
                timeout=20
            )
            response.raise_for_status()

            destination = self.get_cover_path(
                game_name
            )
            destination.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            destination.write_bytes(
                response.content
            )

            return True

        except Exception:
            return False

    # --------------------------------------------------------
    # BUSY / BUTTONS
    # --------------------------------------------------------

    def set_busy(
        self,
        busy,
        status=None
    ):
        self.set_buttons_enabled(
            not busy
        )

        if status:
            self.status_label.set_text(
                status
            )

    def set_buttons_enabled(
        self,
        enabled
    ):
        self.missing_button.set_sensitive(
            enabled
        )
        self.refresh_button.set_sensitive(
            enabled
        )
        self.settings_button.set_sensitive(
            enabled
        )

    # --------------------------------------------------------
    # DIALOG HELPERS
    # --------------------------------------------------------

    def show_error(
        self,
        title,
        message,
        parent=None
    ):
        dialog = Gtk.AlertDialog()
        dialog.set_message(title)
        dialog.set_detail(message)
        dialog.show(parent or self)

    def show_info(
        self,
        title,
        message,
        parent=None
    ):
        dialog = Gtk.AlertDialog()
        dialog.set_message(title)
        dialog.set_detail(message)
        dialog.show(parent or self)


# ============================================================
# APPLICATION
# ============================================================

class GOGCoverApplication(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )

    def do_activate(self):
        window = self.props.active_window

        if window:
            window.present()
            return

        config = load_config()
        saved = config.get("gog_dir", "")

        gog_dir = None

        if saved:
            candidate = Path(
                saved
            ).expanduser()

            if candidate.is_dir():
                gog_dir = candidate.resolve()

        window = GOGCoverWindow(
            self,
            gog_dir=gog_dir
        )
        window.present()

        if not gog_dir:
            GLib.idle_add(
                window.show_first_run_setup
            )


def main():
    app = GOGCoverApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
