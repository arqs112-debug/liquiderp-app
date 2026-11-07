"""Produkcja liquidu: podgląd z walidacją stanów, zapis rozchodów i cofnięcie."""
from datetime import date, timedelta

import calc
import settings
import db
import i18n
from i18n import _


class ProductionError(Exception):
    pass


def params_from_form(form):
    """Parametry produkcji z formularza: przepis, ilość, moc, data, butelki."""
    bottles = []
    for bottle_id, count in zip(form.getlist("bottle_id"), form.getlist("bottle_count")):
        n = int(db.parse_num(count, 0))
        if bottle_id.isdigit() and n > 0:
            bottles.append((int(bottle_id), n))
    recipe_id = form.get("recipe_id", "")
    return {
        "recipe_id": int(recipe_id) if recipe_id.isdigit() else None,
        "amount_ml": db.parse_num(form.get("amount_ml")),
        "nicotine_mg": db.parse_num(form.get("nicotine_mg")),
        "pg_pct": db.parse_num(form.get("pg_pct")),
        "save_ratio": bool(form.get("save_ratio")),
        "date": form.get("date") or db.today(),
        "note": form.get("note", "").strip(),
        "force": bool(form.get("force")),
        "bottles": bottles,
    }


def load_recipe(conn, recipe_id):
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if row is None:
        raise ProductionError(_("Wybierz przepis."))
    flavors = [(r["ingredient_id"], r["pct"]) for r in conn.execute(
        "SELECT ingredient_id, pct FROM recipe_flavors WHERE recipe_id = ? ORDER BY position", (recipe_id,))]
    return dict(row), flavors


def preview(conn, params):
    recipe, flavors = load_recipe(conn, params["recipe_id"])
    if params["amount_ml"]:
        recipe["amount_ml"] = params["amount_ml"]
    if params["nicotine_mg"] is not None:
        recipe["nicotine_mg"] = params["nicotine_mg"]
    if params.get("pg_pct") is not None:  # proporcja zmieniona tylko dla tej produkcji
        recipe["pg_pct"] = min(max(params["pg_pct"], 0), 100)
        recipe["vg_pct"] = 100 - recipe["pg_pct"]
    result = calc.compute(conn, recipe, flavors)
    result["recipe"] = {k: recipe[k] for k in ("id", "name", "amount_ml", "nicotine_mg", "pg_pct", "vg_pct", "steep_days")}

    state = db.stock_state(conn)
    bottle_lines, bottle_cost = [], 0.0
    for bottle_id, count in params["bottles"]:
        ing = conn.execute("SELECT * FROM ingredients WHERE id = ? AND category = 'bottle'", (bottle_id,)).fetchone()
        if ing is None:
            continue
        s = state.get(bottle_id, {"qty": 0.0, "avg": 0.0})
        price = s["avg"] if s["qty"] > 0 and s["avg"] else ing["ref_price"]
        line = {"ingredient_id": bottle_id, "name": ing["name"], "count": count, "capacity_ml": ing["capacity_ml"],
                "unit_cost": price or 0, "cost": count * (price or 0), "stock": s["qty"],
                "missing": max(count - max(s["qty"], 0), 0)}
        bottle_lines.append(line)
        bottle_cost += line["cost"]
        if line["missing"]:
            result["missing"].append({"name": ing["name"], "missing": line["missing"], "unit": _("szt")})
        if not price:
            result["no_price"].append(ing["name"])

    capacity = sum((b["capacity_ml"] or 0) * b["count"] for b in bottle_lines)
    if bottle_lines and capacity and capacity < result["totals"].get("ml", 0) - 1e-9:
        result["warnings"].append(_("Butelki pomieszczą {cap} ml, a robisz {ml} ml.", cap=i18n.fmt_num(capacity),
                                    ml=i18n.fmt_num(result["totals"]["ml"])))

    totals = result["totals"]
    totals["cost_liquid"] = totals.get("cost", 0)
    totals["cost_bottles"] = bottle_cost
    totals["cost"] = totals["cost_liquid"] + bottle_cost
    totals["cost_per_ml"] = totals["cost"] / totals["ml"] if totals.get("ml") else 0
    result["bottles"] = bottle_lines
    return result


def commit(conn, params):
    result = preview(conn, params)
    if not result["lines"]:
        raise ProductionError(_("Nie ma czego produkować – sprawdź ilość i przepis."))
    blocking = result.get("blocking", [])
    if blocking:
        raise ProductionError(" ".join(blocking))
    if result["missing"] and not params["force"]:
        raise ProductionError(_("Brakuje składników na magazynie: {items}. Uzupełnij stany albo zaznacz „produkuj mimo braków”.",
                                items=", ".join(f"{m['name']} ({i18n.fmt_num(m['missing'])} {m.get('unit', 'ml')})"
                                                for m in result["missing"])))

    rec, totals = result["recipe"], result["totals"]
    # Gotowe do spróbowania po dniach dojrzewania z przepisu.
    ready_at = (date.fromisoformat(params["date"]) + timedelta(days=int(rec.get("steep_days") or 0))).isoformat()
    production_id = conn.execute(
        "INSERT INTO productions (recipe_id, recipe_name, date, amount_ml, nicotine_mg, pg_pct, vg_pct,"
        " cost_total, note, forced, ready_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rec["id"], rec["name"], params["date"], totals["ml"], totals["nicotine_mg"], totals["pg_pct"],
         totals["vg_pct"], totals["cost"], params["note"], 1 if result["missing"] else 0, ready_at),
    ).lastrowid
    note = _("Produkcja: {name} ({ml} ml)", name=rec["name"], ml=f"{totals['ml']:g}")
    rows = [(l["ingredient_id"], -l["ml"], (l["cost"] / l["ml"]) if l["cost"] and l["ml"] else None)
            for l in result["lines"]]
    rows += [(b["ingredient_id"], -b["count"], b["unit_cost"] or None) for b in result["bottles"]]
    conn.executemany(
        "INSERT INTO movements (ingredient_id, date, kind, qty, unit_cost, production_id, note)"
        " VALUES (?, ?, 'production', ?, ?, ?, ?)",
        [(i, params["date"], q, c, production_id, note) for i, q, c in rows])
    if params.get("save_ratio") and params.get("pg_pct") is not None:
        conn.execute("UPDATE recipes SET pg_pct = ?, vg_pct = ? WHERE id = ?",
                     (rec["pg_pct"], rec["vg_pct"], rec["id"]))
    conn.execute(
        "INSERT INTO recipe_history (recipe_id, date, event, note, production_id) VALUES (?, ?, 'made', ?, ?)",
        (rec["id"], params["date"], f"{i18n.fmt_num(totals['ml'])} ml · {i18n.fmt_money(totals['cost'], settings.get('currency'))}",
         production_id))
    return production_id, result


def undo(conn, production_id):
    conn.execute("DELETE FROM movements WHERE production_id = ?", (production_id,))
    conn.execute("DELETE FROM recipe_history WHERE production_id = ?", (production_id,))
    conn.execute("DELETE FROM productions WHERE id = ?", (production_id,))
