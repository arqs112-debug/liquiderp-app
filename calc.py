"""Wyliczenia przepisu: ilości, waga, proporcje PG/VG, koszt i dostępność na magazynie."""
import db

TOLERANCE_PCT = 0.5  # odchyłka proporcji, od której ostrzegamy


def compute(conn, recipe, flavors, amount_ml=None):
    """recipe: dict z polami jak w tabeli recipes; flavors: [(ingredient_id, pct), ...]."""
    amount = amount_ml if amount_ml is not None else recipe["amount_ml"]
    ids = {i for i, _ in flavors} | {recipe.get(k) for k in ("nicotine_id", "pg_id", "vg_id")}
    ids.discard(None)
    ings = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        ings = {r["id"]: dict(r) for r in conn.execute(f"SELECT * FROM ingredients WHERE id IN ({marks})", tuple(ids))}
    state = db.stock_state(conn)

    lines, warnings = [], []

    def add_line(role, ingredient_id, ml, pct=None):
        ing = ings.get(ingredient_id)
        if ing is None:
            return
        s = state.get(ingredient_id, {"qty": 0.0, "avg": 0.0})
        price = s["avg"] if s["qty"] > 0 and s["avg"] else ing["ref_price"]
        lines.append({
            "role": role,
            "ingredient_id": ingredient_id,
            "name": ing["name"],
            "manufacturer": ing["manufacturer"],
            "active": bool(ing["active"]),
            "pct": pct if pct is not None else (ml / amount * 100 if amount else 0),
            "ml": ml,
            "g": ml * (ing["grams_per_ml"] or 1),
            "pg_ml": ml * ing["pg_pct"] / 100,
            "vg_ml": ml * ing["vg_pct"] / 100,
            "nic_mg": ml * ing["nicotine_mg"],
            "cost": ml * price if price else None,
            "stock": s["qty"],
        })

    if amount <= 0:
        return {"lines": [], "totals": {}, "warnings": ["Podaj ilość do zrobienia."]}

    # Baza nikotynowa.
    nic_ml = 0.0
    base = ings.get(recipe.get("nicotine_id"))
    target_nic = recipe.get("nicotine_mg") or 0
    if target_nic > 0:
        if base is None:
            warnings.append("Wybierz bazę nikotynową, aby uzyskać zadaną moc.")
        elif base["nicotine_mg"] <= 0:
            warnings.append("Wybrana baza nie ma ustawionej mocy nikotyny.")
        else:
            nic_ml = amount * target_nic / base["nicotine_mg"]
            add_line("nicotine", base["id"], nic_ml)

    for ingredient_id, pct in flavors:
        # Aromaty na 0 % to zwykle wyłączone warianty – zostają w przepisie, ale nie w wyliczeniu.
        if pct > 1e-4:
            add_line("aroma", ingredient_id, amount * pct / 100, pct)

    fixed_ml = sum(l["ml"] for l in lines)
    contrib_pg = sum(l["pg_ml"] for l in lines)
    contrib_vg = sum(l["vg_ml"] for l in lines)
    remaining = amount - fixed_ml
    if remaining < -1e-9:
        warnings.append(f"Baza i aromaty zajmują {fixed_ml:.2f} ml – więcej niż {amount:g} ml do zrobienia.")
        remaining = 0

    target_pg = amount * recipe["pg_pct"] / 100
    target_vg = amount * recipe["vg_pct"] / 100
    clamp = lambda v: min(max(v, 0.0), remaining)
    if recipe.get("precedence") == "vg":
        vg_add = clamp(target_vg - contrib_vg)
        pg_add = remaining - vg_add
    else:
        pg_add = clamp(target_pg - contrib_pg)
        vg_add = remaining - pg_add

    for role, key, ml in (("pg", "pg_id", pg_add), ("vg", "vg_id", vg_add)):
        if ml > 1e-9:
            if ings.get(recipe.get(key)) is None:
                warnings.append(f"Wybierz składnik {role.upper()} – potrzeba {ml:.2f} ml.")
            else:
                add_line(role, recipe[key], ml)

    total_ml = sum(l["ml"] for l in lines)
    pg_ml = sum(l["pg_ml"] for l in lines)
    vg_ml = sum(l["vg_ml"] for l in lines)
    nic_mg = sum(l["nic_mg"] for l in lines)
    actual_pg = pg_ml / total_ml * 100 if total_ml else 0
    if total_ml and abs(actual_pg - recipe["pg_pct"]) > TOLERANCE_PCT:
        warnings.append(f"Nie da się uzyskać {recipe['pg_pct']:g}/{recipe['vg_pct']:g} – wyjdzie "
                        f"{actual_pg:.1f}/{100 - actual_pg:.1f} PG/VG.")

    costs = [l["cost"] for l in lines]
    no_price = [l["name"] for l in lines if l["cost"] is None and l["ml"] > 0]
    # Ten sam składnik może wystąpić kilka razy – braki liczymy łącznie.
    need = {}
    for l in lines:
        need[l["ingredient_id"]] = need.get(l["ingredient_id"], 0) + l["ml"]
    missing = []
    for l in lines:
        short = need[l["ingredient_id"]] - max(l["stock"], 0)
        l["missing"] = short if short > 1e-9 else 0
        if l["missing"] and all(m["ingredient_id"] != l["ingredient_id"] for m in missing):
            missing.append(l)
    total_cost = sum(c for c in costs if c)
    return {
        "lines": lines,
        "totals": {
            "ml": total_ml,
            "g": sum(l["g"] for l in lines),
            "pg_pct": actual_pg,
            "vg_pct": vg_ml / total_ml * 100 if total_ml else 0,
            "nicotine_mg": nic_mg / total_ml if total_ml else 0,
            "flavor_pct": sum(p for _, p in flavors),
            "cost": total_cost,
            "cost_per_ml": total_cost / total_ml if total_ml else 0,
            "cost_complete": not no_price,
        },
        "warnings": warnings,
        "no_price": no_price,
        "missing": [{"name": l["name"], "missing": l["missing"]} for l in missing],
    }
