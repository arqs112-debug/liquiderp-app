"""Gdzie program trzyma pliki.

RESOURCE_DIR – szablony, style, ikona (w wersji z instalatora: folder rozpakowany przez PyInstaller).
DATA_DIR – dane użytkownika: baza, kopie zapasowe, log, stan okna, dane WebView.
Domyślnie %AppData%\\LiquidERP; zmienna LIQUIDERP_DATA wskazuje inny folder (np. w testach).
"""
import os
import sys

if getattr(sys, "frozen", False):
    RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))


def _default_data_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "LiquidERP")


DATA_DIR = os.environ.get("LIQUIDERP_DATA") or _default_data_dir()
DB_PATH = os.path.join(DATA_DIR, "liquiderp.db")
BACKUP_DIR = os.path.join(DATA_DIR, "kopie")
LOG_PATH = os.path.join(DATA_DIR, "liquiderp.log")
WINDOW_STATE = os.path.join(DATA_DIR, "window.json")
WEBVIEW_DIR = os.path.join(DATA_DIR, "webview")
ICON = os.path.join(RESOURCE_DIR, "static", "liquiderp.ico")
