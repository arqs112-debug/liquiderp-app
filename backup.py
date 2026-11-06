"""Kopie zapasowe bazy: automatyczna raz dziennie przy starcie, ręczne i przywracanie."""
import os
import re
import sqlite3
from datetime import datetime

import db
from i18n import _

DEFAULT_KEEP = 30
NAME_RE = re.compile(r"^liquiderp-(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})(?:-([\w-]+))?\.db$")
REASONS = {"auto": "automatyczna", "reczna": "ręczna", "przed-przywroceniem": "przed przywróceniem",
           "przed-importem": "przed importem"}


def backup_dir():
    """Folder kopii obok bazy (domyślnie %AppData%/LiquidERP/kopie)."""
    return os.path.join(os.path.dirname(db.DB_PATH), "kopie")


def keep():
    import settings
    try:
        return max(int(settings.get_num("backup_keep", default=DEFAULT_KEEP)), 1)
    except Exception:
        return DEFAULT_KEEP


def _copy(src_path, dst_path):
    """Spójna kopia przez API SQLite (bezpieczna także przy otwartej bazie)."""
    src, dst = sqlite3.connect(src_path), sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def create(reason="reczna"):
    if not os.path.exists(db.DB_PATH):
        return None
    os.makedirs(backup_dir(), exist_ok=True)
    name = f"liquiderp-{datetime.now():%Y-%m-%d_%H%M%S}-{reason}.db"
    _copy(db.DB_PATH, os.path.join(backup_dir(), name))
    prune()
    return name


def list_backups():
    if not os.path.isdir(backup_dir()):
        return []
    result = []
    for name in os.listdir(backup_dir()):
        m = NAME_RE.match(name)
        if not m:
            continue
        path = os.path.join(backup_dir(), name)
        result.append({
            "name": name,
            "when": f"{m.group(1)} {m.group(2)}:{m.group(3)}",
            "reason": _(REASONS[m.group(5)]) if m.group(5) in REASONS else (m.group(5) or ""),
            "size_kb": os.path.getsize(path) / 1024,
        })
    return sorted(result, key=lambda b: b["name"], reverse=True)


def prune():
    for b in list_backups()[keep():]:
        os.remove(os.path.join(backup_dir(), b["name"]))


def daily():
    """Kopia przy starcie programu, jeśli dziś jeszcze żadnej nie było."""
    today = datetime.now().strftime("%Y-%m-%d")
    if not any(b["name"].startswith(f"liquiderp-{today}") for b in list_backups()):
        create("auto")


def path_of(name):
    if not NAME_RE.match(name or ""):
        raise ValueError(_("Nieprawidłowa nazwa kopii."))
    path = os.path.join(backup_dir(), name)
    if not os.path.exists(path):
        raise ValueError(_("Nie ma takiej kopii."))
    return path


def restore(name):
    src = path_of(name)
    create("przed-przywroceniem")
    _copy(src, db.DB_PATH)
    db.init_db()  # starsza kopia mogła mieć wcześniejszą wersję schematu
