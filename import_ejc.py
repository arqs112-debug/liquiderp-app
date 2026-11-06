"""Import danych z pliku EJuiceCalculatora (XML <JuiceData>).

Użycie z wiersza poleceń:  python import_ejc.py "D:\\ścieżka\\Baza.xml" [--zastap]
"""
import sys
import xml.etree.ElementTree as ET

import db
from i18n import _

TYPE_MAP = {"Flavor": "aroma", "Nicotine": "nicotine", "PGEntry": "pg", "VGEntry": "vg"}
OPENING_NOTE = "Bilans otwarcia – import z EJuiceCalculatora"


class ImportError_(Exception):
    pass


def _text(el, path, default=""):
    value = el.findtext(path)
    return value.strip() if value else default


def _num(el, path, default=0.0):
    return db.parse_num(el.findtext(path), default)


def _date(value):
    """'2020-03-21T22:48:21.66+01:00' -> '2020-03-21 22:48'."""
    if not value:
        return None
    return value[:16].replace("T", " ")


def _key(el):
    category = TYPE_MAP.get(_text(el, "IngredientType"), "other")
    return category, _text(el, "Name").lower(), _text(el, "ManEntry/Name").lower()


def wipe(conn):
    for table in ("recipe_history", "recipe_flavors", "movements", "productions", "recipes", "purchases",
                  "ingredients"):
        conn.execute(f"DELETE FROM {table}")


def import_file(conn, path, replace=False):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ImportError_(_("Nie można odczytać pliku: {err}", err=exc)) from exc
    if root.tag != "JuiceData":
        raise ImportError_(_("To nie jest plik danych EJuiceCalculatora (brak <JuiceData>)."))

    has_data = conn.execute("SELECT EXISTS (SELECT 1 FROM ingredients)").fetchone()[0]
    if has_data and not replace:
        raise ImportError_(_("Baza LiquidERP nie jest pusta. Zaznacz „zastąp istniejące dane”, aby zaimportować od nowa."))
    if has_data:
        wipe(conn)

    stats = {"ingredients": 0, "inactive": 0, "stock": 0, "recipes": 0, "flavors": 0, "history": 0}
    ids = {}
    opening_lines = []

    for el in root.iterfind("AllAvailableIngredients/Ingredient"):
        category = _key(el)[0]
        cost, cost_amount = _num(el, "Cost"), _num(el, "CostMLs", 0)
        if _text(el, "CostType") == "Liters":
            cost_amount *= 1000
        unit_cost = cost / cost_amount if cost and cost_amount else None
        default_pct = _num(el, "DefaultPercentage", 0) * 100
        active = _text(el, "Deactivated") != "true"
        ing_id = db.create_ingredient(
            conn, category, _text(el, "Name"), _text(el, "ManEntry/Name"),
            pg_pct=_num(el, "DefaultPGPercentage") * 100,
            vg_pct=_num(el, "DefaultVGPercentage") * 100,
            nicotine_mg=_num(el, "DefaultMGNicotineLevel"),
            grams_per_ml=_num(el, "DefaultGramsPerML", 1) or 1,
            min_stock=_num(el, "InventoryThreshhold"),
            description=el.findtext("DefaultNotes") or "",
            folder=_text(el, "FolderName"),
            default_pct=default_pct or None,
            ref_price=unit_cost,
        )
        if not active:
            conn.execute("UPDATE ingredients SET active = 0 WHERE id = ?", (ing_id,))
            stats["inactive"] += 1
        ids[_key(el)] = ing_id
        stats["ingredients"] += 1

        qty = _num(el, "AmountInInventory")
        if qty:
            opening_lines.append((ing_id, qty, unit_cost or 0, _text(el, "Vendor")))

    if opening_lines:
        day = db.today()
        purchase_id = conn.execute(
            "INSERT INTO purchases (date, note) VALUES (?, ?)", (day, OPENING_NOTE)).lastrowid
        for ing_id, qty, unit_cost, vendor in opening_lines:
            conn.execute(
                "INSERT INTO movements (ingredient_id, date, kind, qty, unit_cost, pack_size, pack_count,"
                " purchase_id, note) VALUES (?, ?, 'purchase', ?, ?, ?, 1, ?, ?)",
                (ing_id, day, qty, unit_cost, qty, purchase_id,
                 f"Stan z EJuiceCalculatora{' · ' + vendor if vendor else ''}"),
            )
            stats["stock"] += 1

    for rec in root.iterfind("AllRecipes/Recipe"):
        entries = rec.findall("AllIngredients/RecipeEntry")
        by_cat = {}
        for entry in entries:
            ing = entry.find("RecipeIngredient")
            by_cat.setdefault(_key(ing)[0], []).append((entry, ids.get(_key(ing))))

        def first_id(category):
            items = by_cat.get(category)
            return items[0][1] if items else None

        def ratio(category, default):
            items = by_cat.get(category)
            return _num(items[0][0], "RecipeTotalPercentageInRecipe") * 100 if items else default

        nic = rec.find("NicotineEntry/RecipeIngredient")
        nicotine_id = ids.get(_key(nic)) if nic is not None else first_id("nicotine")
        pg_pct = ratio("pg", 50)
        vg_pct = ratio("vg", 100 - pg_pct)
        recipe_id = conn.execute(
            "INSERT INTO recipes (name, folder, notes, rating, amount_ml, nicotine_mg, pg_pct, vg_pct,"
            " precedence, nicotine_id, pg_id, vg_id, steep_days, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_text(rec, "Name"), _text(rec, "RecipeCategory"), rec.findtext("Notes") or "",
             int(_num(rec, "RecipeRating")), _num(rec, "DefaultAmountToMake", 50),
             _num(rec, "DefaultNicotineLevel"), pg_pct, vg_pct,
             "vg" if _text(rec, "DefaultPGVGPrecedence") == "VGHasPrecedence" else "pg",
             nicotine_id, first_id("pg"), first_id("vg"), int(_num(rec, "DaysToSteep")),
             _date(_text(rec, "RecipeCreatedDate")) or db.today()),
        ).lastrowid
        stats["recipes"] += 1

        position = 0
        for category in ("aroma", "other"):
            for entry, ing_id in by_cat.get(category, []):
                if ing_id is None:
                    continue
                conn.execute(
                    "INSERT INTO recipe_flavors (recipe_id, ingredient_id, pct, position) VALUES (?, ?, ?, ?)",
                    # EJuiceCalculator zapisuje czasem szum typu 1e-10 zamiast zera.
                    (recipe_id, ing_id, round(_num(entry, "RecipePercentage") * 100, 4), position))
                position += 1
                stats["flavors"] += 1

        events = {"LastMade": "made", "Printed": "printed"}
        for h in rec.iterfind("TheHistory/HistoryEntries/RecipeHistoryEntry"):
            day = _date(_text(h, "TheDate"))
            if day:
                conn.execute(
                    "INSERT INTO recipe_history (recipe_id, date, event, note) VALUES (?, ?, ?, ?)",
                    (recipe_id, day, events.get(_text(h, "HistoryEvent"), _text(h, "HistoryEvent")),
                     "import z EJuiceCalculatora"))
                stats["history"] += 1
    return stats


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    db.init_db()
    with db.connect() as conn:
        try:
            print(import_file(conn, sys.argv[1], replace="--zastap" in sys.argv))
        except ImportError_ as exc:
            sys.exit(str(exc))
