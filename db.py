"""Warstwa danych LiquidERP: schemat SQLite, kategorie i wyliczanie stanów."""
import os
import re
import sqlite3
from datetime import date

import paths

DB_PATH = paths.DB_PATH  # testy podmieniają na bazę tymczasową

# Kolejność ma znaczenie: tak wyświetlamy kategorie w interfejsie.
CATEGORIES = {
    "aroma":    {"label": "Aromaty",          "single": "Aromat",          "unit": "ml",  "pg": 100, "vg": 0},
    "nicotine": {"label": "Bazy nikotynowe",  "single": "Baza nikotynowa", "unit": "ml",  "pg": 50,  "vg": 50},
    "pg":       {"label": "PG",               "single": "PG",              "unit": "ml",  "pg": 100, "vg": 0},
    "vg":       {"label": "VG",               "single": "VG",              "unit": "ml",  "pg": 0,   "vg": 100},
    "other":    {"label": "Inne",             "single": "Inny składnik",   "unit": "ml",  "pg": 0,   "vg": 0},
    "bottle":   {"label": "Butelki",          "single": "Butelka",         "unit": "szt", "pg": 0,   "vg": 0},
}

SCHEMA = """
CREATE TABLE ingredients (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,
    manufacturer  TEXT NOT NULL DEFAULT '',
    pg_pct        REAL NOT NULL DEFAULT 0,
    vg_pct        REAL NOT NULL DEFAULT 0,
    nicotine_mg   REAL NOT NULL DEFAULT 0,
    grams_per_ml  REAL NOT NULL DEFAULT 1,
    capacity_ml   REAL,
    min_stock     REAL NOT NULL DEFAULT 0,
    description   TEXT NOT NULL DEFAULT '',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE UNIQUE INDEX ux_ingredients_key
    ON ingredients(category, lower(name), lower(manufacturer));

-- Dokument przyjęcia (np. jedno zamówienie ze sklepu).
CREATE TABLE purchases (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,
    supplier    TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Każda zmiana stanu. qty w ml (płyny) lub sztukach (butelki), ze znakiem.
CREATE TABLE movements (
    id             INTEGER PRIMARY KEY,
    ingredient_id  INTEGER NOT NULL REFERENCES ingredients(id),
    date           TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('purchase', 'production', 'adjustment')),
    qty            REAL NOT NULL,
    unit_cost      REAL,
    pack_size      REAL,
    pack_count     INTEGER,
    purchase_id    INTEGER REFERENCES purchases(id) ON DELETE CASCADE,
    note           TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX ix_movements_ingredient ON movements(ingredient_id);
"""

SCHEMA_V2 = """
ALTER TABLE ingredients ADD COLUMN folder TEXT NOT NULL DEFAULT '';
ALTER TABLE ingredients ADD COLUMN default_pct REAL;
-- Ostatnia znana cena jednostki; koszt przepisu, gdy składnika nie ma na stanie.
ALTER TABLE ingredients ADD COLUMN ref_price REAL;

CREATE TABLE recipes (
    id                 INTEGER PRIMARY KEY,
    name               TEXT NOT NULL,
    folder             TEXT NOT NULL DEFAULT '',
    notes              TEXT NOT NULL DEFAULT '',
    rating             INTEGER NOT NULL DEFAULT 0,
    amount_ml          REAL NOT NULL DEFAULT 50,
    nicotine_mg        REAL NOT NULL DEFAULT 0,
    pg_pct             REAL NOT NULL DEFAULT 50,
    vg_pct             REAL NOT NULL DEFAULT 50,
    precedence         TEXT NOT NULL DEFAULT 'pg' CHECK (precedence IN ('pg', 'vg')),
    nicotine_id        INTEGER REFERENCES ingredients(id),
    pg_id              INTEGER REFERENCES ingredients(id),
    vg_id              INTEGER REFERENCES ingredients(id),
    steep_days         INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE recipe_flavors (
    id             INTEGER PRIMARY KEY,
    recipe_id      INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ingredient_id  INTEGER NOT NULL REFERENCES ingredients(id),
    pct            REAL NOT NULL,
    position       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_recipe_flavors_recipe ON recipe_flavors(recipe_id);

-- Zdarzenia przepisu: zrobienie (także historyczne z importu), wydruk.
CREATE TABLE recipe_history (
    id         INTEGER PRIMARY KEY,
    recipe_id  INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    event      TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_recipe_history_recipe ON recipe_history(recipe_id);
"""

SCHEMA_V3 = """
CREATE TABLE productions (
    id           INTEGER PRIMARY KEY,
    recipe_id    INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
    recipe_name  TEXT NOT NULL,
    date         TEXT NOT NULL,
    amount_ml    REAL NOT NULL,
    nicotine_mg  REAL NOT NULL DEFAULT 0,
    pg_pct       REAL NOT NULL DEFAULT 0,
    vg_pct       REAL NOT NULL DEFAULT 0,
    cost_total   REAL NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT '',
    forced       INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
ALTER TABLE movements ADD COLUMN production_id INTEGER REFERENCES productions(id) ON DELETE CASCADE;
ALTER TABLE recipe_history ADD COLUMN production_id INTEGER REFERENCES productions(id) ON DELETE CASCADE;
"""

SCHEMA_V4 = """
-- Nazwy ze sklepów (z wklejonych maili) przypisane do składników; klucz bez wielkości liter i polskich znaków.
CREATE TABLE ingredient_aliases (
    alias          TEXT PRIMARY KEY,
    ingredient_id  INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE
);
"""

SCHEMA_V5 = """
ALTER TABLE recipes ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
"""

SCHEMA_V6 = """
CREATE TABLE shopping_list (
    id             INTEGER PRIMARY KEY,
    ingredient_id  INTEGER REFERENCES ingredients(id) ON DELETE CASCADE,
    name           TEXT NOT NULL DEFAULT '',
    pack_size      REAL,
    pack_count     INTEGER NOT NULL DEFAULT 1,
    note           TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    done_at        TEXT
);
"""

SCHEMA_V7 = """
-- Dojrzewanie i ocena partii.
ALTER TABLE productions ADD COLUMN ready_at TEXT;
ALTER TABLE productions ADD COLUMN rating INTEGER;
ALTER TABLE productions ADD COLUMN tasting_note TEXT NOT NULL DEFAULT '';
ALTER TABLE productions ADD COLUMN tasted_at TEXT;
UPDATE productions SET ready_at = date WHERE ready_at IS NULL;
-- Data otwarcia butelki aromatu i historia zmian karty składnika (do cofania).
ALTER TABLE ingredients ADD COLUMN opened_at TEXT;
CREATE TABLE ingredient_changes (
    id             INTEGER PRIMARY KEY,
    ingredient_id  INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    changed_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    old_values     TEXT NOT NULL
);
"""

# Ustawienia tworzymy zawsze (IF NOT EXISTS) – także w bazie przywróconej ze starszej kopii.
SCHEMA_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL DEFAULT ''
);
"""

SCHEMA_VERSION = 7


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            conn.executescript(SCHEMA)
        if version < 2:
            conn.executescript(SCHEMA_V2)
        if version < 3:
            conn.executescript(SCHEMA_V3)
        if version < 4:
            conn.executescript(SCHEMA_V4)
        if version < 5:
            conn.executescript(SCHEMA_V5)
        if version < 6:
            conn.executescript(SCHEMA_V6)
        if version < 7:
            conn.executescript(SCHEMA_V7)
        conn.executescript(SCHEMA_SETTINGS)
        conn.execute(f"PRAGMA user_version = {max(version, SCHEMA_VERSION)}")
    import settings
    settings.reset_cache()


def is_empty(conn):
    """Pusta baza (nowa instalacja) – wtedy pokazujemy kreator pierwszego uruchomienia."""
    return not conn.execute("SELECT EXISTS (SELECT 1 FROM ingredients) OR EXISTS (SELECT 1 FROM recipes)").fetchone()[0]


def parse_num(value, default=None):
    """Liczba z formularza w obu zapisach: „1 017,52”, „1,017.52”, „12,5”, „12.5”.

    Gdy są oba znaki, ostatni z nich oddziela część dziesiętną. Sam przecinek to część
    dziesiętna („12,5”), chyba że wygląda jak separator tysięcy z angielskiego zapisu („1,250,000”).
    """
    if value is None:
        return default
    text = re.sub(r"[\s  ']", "", str(value)).replace("−", "-")
    if not text:
        return default
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(",") > 1 and re.fullmatch(r"-?\d{1,3}(,\d{3})+", text):
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return default


def today():
    return date.today().isoformat()


def stock_state(conn, ingredient_id=None):
    """Zwraca {ingredient_id: {"qty": stan, "avg": średni koszt jednostki}}.

    Średnia ważona krocząca: każde przyjęcie miesza swój koszt z wartością
    bieżącego (dodatniego) stanu; rozchody i korekty nie zmieniają średniej.
    """
    sql = "SELECT ingredient_id, kind, qty, unit_cost FROM movements"
    params = ()
    if ingredient_id is not None:
        sql += " WHERE ingredient_id = ?"
        params = (ingredient_id,)
    sql += " ORDER BY date, id"

    state = {}
    for row in conn.execute(sql, params):
        s = state.setdefault(row["ingredient_id"], {"qty": 0.0, "avg": 0.0})
        qty = row["qty"]
        if row["kind"] == "purchase" and qty > 0 and row["unit_cost"] is not None:
            base = max(s["qty"], 0.0)
            s["avg"] = (base * s["avg"] + qty * row["unit_cost"]) / (base + qty)
        s["qty"] += qty
    return state


def find_ingredient(conn, category, name, manufacturer):
    # lower() w SQLite nie zna polskich liter („Ż” ≠ „ż”), więc porównujemy w Pythonie.
    key = (name.strip().casefold(), manufacturer.strip().casefold())
    for ing in conn.execute("SELECT * FROM ingredients WHERE category = ?", (category,)):
        if (ing["name"].casefold(), ing["manufacturer"].casefold()) == key:
            return ing
    return None


def create_ingredient(conn, category, name, manufacturer="", **fields):
    defaults = CATEGORIES[category]
    values = {
        "name": name.strip(),
        "category": category,
        "manufacturer": manufacturer.strip(),
        "pg_pct": defaults["pg"],
        "vg_pct": defaults["vg"],
        "nicotine_mg": 0,
        "grams_per_ml": 1,
        "min_stock": 0,
        "description": "",
        "folder": "",
    }
    values.update({k: v for k, v in fields.items() if v is not None})
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO ingredients ({cols}) VALUES ({marks})", tuple(values.values()))
    return cur.lastrowid


def add_purchase_line(conn, purchase_id, ingredient_id, day, pack_size, pack_count, pack_price):
    qty = pack_size * pack_count
    unit_cost = pack_price / pack_size if pack_size else 0
    conn.execute(
        "INSERT INTO movements (ingredient_id, date, kind, qty, unit_cost, pack_size, pack_count, purchase_id)"
        " VALUES (?, ?, 'purchase', ?, ?, ?, ?, ?)",
        (ingredient_id, day, qty, unit_cost, pack_size, pack_count, purchase_id),
    )
    if unit_cost:
        conn.execute("UPDATE ingredients SET ref_price = ? WHERE id = ?", (unit_cost, ingredient_id))
