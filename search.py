"""Wyszukiwanie we wszystkim: składnikach, przepisach, produkcjach i przyjęciach.

Ignoruje wielkość liter i polskie znaki („jablko” znajdzie „Jabłko”); każde słowo musi pasować.
"""
import unicodedata

import db
from i18n import _


def fold(text):
    text = (text or "").lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _matches(words, *fields):
    haystack = fold(" ".join(str(f) for f in fields if f))
    return all(w in haystack for w in words)


def search(conn, query, limit=None):
    words = fold(query).split()
    groups = {"ingredients": [], "recipes": [], "productions": [], "purchases": []}
    if not words:
        return groups

    for ing in conn.execute("SELECT * FROM ingredients ORDER BY active DESC, lower(name)"):
        if _matches(words, ing["name"], ing["manufacturer"], ing["folder"], ing["description"],
                    _(db.CATEGORIES[ing["category"]]["single"])):
            groups["ingredients"].append({
                "id": ing["id"], "title": ing["name"], "active": bool(ing["active"]),
                "sub": " · ".join(x for x in (ing["manufacturer"], _(db.CATEGORIES[ing["category"]]["single"]), ing["folder"]) if x),
                "snippet": ing["description"][:140]})

    flavors = {}
    for f in conn.execute("SELECT rf.recipe_id, i.name, i.manufacturer FROM recipe_flavors rf"
                          " JOIN ingredients i ON i.id = rf.ingredient_id WHERE rf.pct > 0.0001 ORDER BY rf.position"):
        flavors.setdefault(f["recipe_id"], []).append(f"{f['name']} {f['manufacturer']}")
    for r in conn.execute("SELECT * FROM recipes ORDER BY archived, lower(name)"):
        flav = flavors.get(r["id"], [])
        if _matches(words, r["name"], r["folder"], r["notes"], *flav):
            groups["recipes"].append({
                "id": r["id"], "title": r["name"], "active": not r["archived"],
                "sub": " · ".join(x for x in (_("archiwum") if r["archived"] else "", r["folder"],
                                              f"{r['nicotine_mg']:g} mg", "★" * r["rating"]) if x),
                "snippet": ", ".join(flav)[:140]})

    for p in conn.execute("SELECT * FROM productions ORDER BY date DESC"):
        if _matches(words, p["recipe_name"], p["note"], p["date"]):
            groups["productions"].append({
                "id": p["id"], "title": f"{p['recipe_name']} – {p['amount_ml']:g} ml", "active": True,
                "sub": p["date"], "snippet": p["note"]})

    items = {}
    for m in conn.execute("SELECT m.purchase_id, i.name FROM movements m JOIN ingredients i ON i.id = m.ingredient_id"
                          " WHERE m.purchase_id IS NOT NULL"):
        items.setdefault(m["purchase_id"], []).append(m["name"])
    for p in conn.execute("SELECT * FROM purchases ORDER BY date DESC"):
        names = items.get(p["id"], [])
        if _matches(words, p["supplier"], p["note"], p["date"], *names):
            groups["purchases"].append({
                "id": p["id"], "title": _("Przyjęcie {date}", date=p["date"]) + (f" – {p['supplier']}" if p["supplier"] else ""),
                "active": True, "sub": p["note"], "snippet": ", ".join(names)[:140]})

    if limit:
        groups = {k: v[:limit] for k, v in groups.items()}
    return groups
