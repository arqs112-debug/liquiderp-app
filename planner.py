"""„Co mogę zrobić?”: ile każdego przepisu da się zrobić z magazynu i czego brakuje do planu produkcji."""
import math

import calc
import db
from i18n import _

REF_ML = 100  # przepis liczymy na 100 ml i skalujemy


def _recipe(conn, recipe_id):
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if row is None:
        return None, []
    flavors = [(r["ingredient_id"], r["pct"]) for r in conn.execute(
        "SELECT ingredient_id, pct FROM recipe_flavors WHERE recipe_id = ? ORDER BY position", (recipe_id,))]
    return dict(row), flavors


def _needs(conn, recipe, flavors, amount):
    """{ingredient_id: (nazwa, ml)} dla zadanej ilości albo None, gdy przepisu nie da się policzyć."""
    res = calc.compute(conn, dict(recipe, amount_ml=amount), flavors)
    if res.get("blocking") or not res["lines"]:
        return None, res
    needs = {}
    for l in res["lines"]:
        name, ml = needs.get(l["ingredient_id"], (l["name"], 0.0))
        needs[l["ingredient_id"]] = (name, ml + l["ml"])
    return needs, res


def capacity(conn):
    """Lista aktywnych przepisów z maksymalną ilością (ml) możliwą z obecnych stanów."""
    state = db.stock_state(conn)
    rows = []
    for r in conn.execute("SELECT id FROM recipes WHERE archived = 0 ORDER BY lower(name)"):
        recipe, flavors = _recipe(conn, r["id"])
        needs, res = _needs(conn, recipe, flavors, REF_ML)
        item = {"id": recipe["id"], "name": recipe["name"], "folder": recipe["folder"], "rating": recipe["rating"],
                "amount_ml": recipe["amount_ml"], "max_ml": 0.0, "limit": "", "problem": ""}
        if needs is None:
            item["problem"] = "; ".join(res["warnings"]) or _("przepis bez składników")
        else:
            best = None
            for ing_id, (name, ml) in needs.items():
                if ml <= 1e-9:
                    continue
                possible = max(state.get(ing_id, {"qty": 0.0})["qty"], 0) / ml * REF_ML
                if best is None or possible < best[0]:
                    best = (possible, name)
            item["max_ml"], item["limit"] = (math.floor(best[0] * 10) / 10, best[1]) if best else (0.0, "")
        item["portions"] = int(item["max_ml"] // item["amount_ml"]) if item["amount_ml"] else 0
        rows.append(item)
    return rows


def plan(conn, items):
    """items: [{"recipe_id", "ml", "count"}] -> łączne zapotrzebowanie, stany i braki."""
    state = db.stock_state(conn)
    total, cost, problems = {}, 0.0, []
    for it in items:
        recipe, flavors = _recipe(conn, int(it["recipe_id"]))
        ml, count = float(it.get("ml") or 0), max(int(it.get("count") or 1), 1)
        if recipe is None or ml <= 0:
            continue
        needs, res = _needs(conn, recipe, flavors, ml)
        if needs is None:
            problems.append(f"{recipe['name']}: {'; '.join(res['warnings'])}")
            continue
        cost += res["totals"]["cost"] * count
        for ing_id, (name, need) in needs.items():
            prev = total.get(ing_id, {"name": name, "need": 0.0})
            prev["need"] += need * count
            total[ing_id] = prev
    lines = []
    for ing_id, t in total.items():
        stock = state.get(ing_id, {"qty": 0.0})["qty"]
        lines.append({"ingredient_id": ing_id, "name": t["name"], "need": round(t["need"], 2), "stock": round(stock, 2),
                      "missing": round(max(t["need"] - max(stock, 0), 0), 2)})
    lines.sort(key=lambda l: (-l["missing"], l["name"].lower()))
    return {"lines": lines, "cost": round(cost, 2), "problems": problems,
            "missing_count": sum(1 for l in lines if l["missing"] > 0)}
