"""Ustawienia programu w bazie (tabela settings: klucz → wartość tekstowa)."""
import os

DEFAULTS = {
    "setup_done": "0",            # kreator pierwszego uruchomienia zakończony
    "language": "",               # pl / en; pusty = wg języka Windows
    "theme": "dark",              # dark / light
    "measure": "ml",              # ml (odmierzam) / g (ważę)
    "currency": "zł",             # symbol waluty za kwotą
    "recipe_amount_ml": "50",
    "recipe_pg_pct": "50",
    "recipe_nicotine_mg": "0",
    "recipe_nicotine_id": "",     # domyślna baza nikotynowa nowego przepisu
    "recipe_pg_id": "",
    "recipe_vg_id": "",
    "phone_pdf_enabled": "0",
    "phone_pdf_dir": "",
    "backup_keep": "30",
}

_cache = {}


def _load(conn):
    values = dict(DEFAULTS)
    values.update({r[0]: r[1] for r in conn.execute("SELECT key, value FROM settings")})
    return values


def all_settings(conn=None):
    """Wszystkie ustawienia; bez połączenia – ostatnio wczytane (np. w wątku PDF)."""
    if conn is not None:
        _cache.clear()
        _cache.update(_load(conn))
    elif not _cache:
        import db
        with db.connect() as c:
            _cache.update(_load(c))
    return dict(_cache)


def get(key, conn=None):
    return all_settings(conn).get(key, DEFAULTS.get(key, ""))


def get_num(key, conn=None, default=0.0):
    import db
    return db.parse_num(get(key, conn), default)


def get_id(key, conn=None):
    value = get(key, conn)
    return int(value) if str(value).isdigit() else None


def save(conn, values):
    for key, value in values.items():
        if key not in DEFAULTS:
            raise KeyError(key)
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
                     " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, "" if value is None else str(value)))
    all_settings(conn)


def reset_cache():
    _cache.clear()


def default_phone_dir():
    """Propozycja folderu na PDF: OneDrive (synchronizuje się z telefonem), inaczej Dokumenty."""
    return (os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
            or os.path.join(os.path.expanduser("~"), "Documents"))
