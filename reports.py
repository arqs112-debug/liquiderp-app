"""Raporty: wydatki, produkcja, najczęściej robione przepisy i długo leżące aromaty."""
from datetime import date

import db
import i18n
from i18n import _

MONTHS = {"pl": ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"],
          "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}


def _last_months(n=12):
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _label(month):
    y, m = month.split("-")
    return f"{MONTHS[i18n.current()][int(m) - 1]} {y[2:]}"


def build(conn, months=12):
    keys = _last_months(months)
    since = keys[0] + "-01"
    spend = dict(conn.execute(
        "SELECT substr(p.date, 1, 7), SUM(m.qty * m.unit_cost) FROM movements m JOIN purchases p ON p.id = m.purchase_id"
        " WHERE p.date >= ? AND p.note NOT LIKE 'Bilans otwarcia%' GROUP BY 1", (since,)).fetchall())
    prod = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT substr(date, 1, 7), SUM(amount_ml), SUM(cost_total), COUNT(*) FROM productions WHERE date >= ? GROUP BY 1",
        (since,))}
    monthly = [{"label": _label(k), "spend": spend.get(k) or 0.0, "ml": (prod.get(k) or (0, 0, 0))[0] or 0.0,
                "prod_cost": (prod.get(k) or (0, 0, 0))[1] or 0.0, "batches": (prod.get(k) or (0, 0, 0))[2]} for k in keys]
    for m in monthly:
        m["cost_per_ml"] = m["prod_cost"] / m["ml"] if m["ml"] else None

    suppliers = [dict(r) for r in conn.execute(
        "SELECT COALESCE(NULLIF(p.supplier, ''), ?) AS supplier, SUM(m.qty * m.unit_cost) AS total,"
        " COUNT(DISTINCT p.id) AS orders FROM movements m JOIN purchases p ON p.id = m.purchase_id"
        " WHERE p.date >= ? AND p.note NOT LIKE 'Bilans otwarcia%' GROUP BY 1 ORDER BY total DESC", (_("(bez sklepu)"), since))]

    top = [dict(r) for r in conn.execute(
        "SELECT r.id, r.name, r.archived, COUNT(h.id) AS made, MAX(h.date) AS last,"
        " (SELECT COALESCE(SUM(p.amount_ml), 0) FROM productions p WHERE p.recipe_id = r.id AND p.date >= ?) AS ml,"
        " (SELECT AVG(p.rating) FROM productions p WHERE p.recipe_id = r.id AND p.rating IS NOT NULL) AS avg_rating"
        " FROM recipe_history h JOIN recipes r ON r.id = h.recipe_id"
        " WHERE h.event = 'made' AND h.date >= ? GROUP BY r.id ORDER BY made DESC, last DESC LIMIT 15", (since, since))]

    # Aromaty na stanie, z którymi nic się nie działo najdłużej (ostatni ruch dowolnego rodzaju).
    state = db.stock_state(conn)
    idle = []
    # „Ostatnio użyty” liczymy też z historii przepisów (zaimportowanej z EJuiceCalculatora), nie tylko z produkcji.
    for r in conn.execute(
            "SELECT i.*, (SELECT MAX(date) FROM movements m WHERE m.ingredient_id = i.id) AS last_move,"
            " MAX(COALESCE((SELECT MAX(date) FROM movements m WHERE m.ingredient_id = i.id AND m.kind = 'production'), ''),"
            "     COALESCE((SELECT MAX(h.date) FROM recipe_history h JOIN recipe_flavors rf ON rf.recipe_id = h.recipe_id"
            "               WHERE rf.ingredient_id = i.id AND rf.pct > 0.0001 AND h.event = 'made'), '')) AS last_used"
            " FROM ingredients i WHERE i.active = 1 AND i.category = 'aroma'"):
        s = state.get(r["id"], {"qty": 0, "avg": 0})
        if s["qty"] <= 0 or not r["last_move"]:
            continue
        since_date = (r["last_used"] or r["last_move"])[:10]
        days = (date.today() - date.fromisoformat(since_date)).days
        idle.append({"id": r["id"], "name": r["name"], "manufacturer": r["manufacturer"], "qty": s["qty"],
                     "value": max(s["qty"], 0) * s["avg"], "days": days, "last_used": (r["last_used"] or "")[:10] or None,
                     "opened_at": r["opened_at"]})
    idle.sort(key=lambda i: -i["days"])

    return {
        "monthly": monthly,
        "max_spend": max((m["spend"] for m in monthly), default=0) or 1,
        "max_ml": max((m["ml"] for m in monthly), default=0) or 1,
        "total_spend": sum(m["spend"] for m in monthly),
        "total_ml": sum(m["ml"] for m in monthly),
        "suppliers": suppliers,
        "top": top,
        "idle": idle[:20],
        "months": months,
    }
