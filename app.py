"""LiquidERP: domowy magazyn, receptury i produkcja liquidów."""
import json
import os
import secrets
import threading
import webbrowser

from flask import Flask, abort, flash, redirect, render_template, request, url_for

import db
import i18n
import paths
import settings
from i18n import _
from version import __version__, REPO_URL

app = Flask(__name__, root_path=paths.RESOURCE_DIR)
app.secret_key = secrets.token_hex(16)  # program działa lokalnie; sesja (komunikaty) żyje do zamknięcia

HOST, PORT = "127.0.0.1", int(os.environ.get("LIQUIDERP_PORT", 5077))


@app.template_filter("num")
def fmt_num(value, digits=2):
    return i18n.fmt_num(value, digits)


@app.template_filter("money")
def fmt_money(value):
    return i18n.fmt_money(value, settings.get("currency"))


app.jinja_env.globals["_"] = _


@app.after_request
def refresh_phone_pdf(response):
    """Każda udana zmiana (POST) odświeża PDF na telefon (jeśli włączony) – z opóźnieniem, w tle."""
    previews = ("/api/oblicz", "/api/produkcja/", "/api/przyjecie/", "/api/zglos", "/api/aktualizacje/")  # nic nie zmieniają
    if request.method == "POST" and response.status_code < 400 and not request.path.startswith(previews):
        import phone_export
        phone_export.schedule()
    return response


@app.context_processor
def inject_globals():
    try:
        with db.connect() as conn:
            cfg = settings.all_settings(conn)
    except Exception:
        cfg = dict(settings.DEFAULTS)
    # Nazwy kategorii i jednostki tłumaczone tylko w interfejsie (w bazie zostają klucze).
    categories = {k: {**v, "label": _(v["label"]), "single": _(v["single"]), "unit": _(v["unit"])}
                  for k, v in db.CATEGORIES.items()}
    return {"CATEGORIES": categories, "SETTINGS": cfg, "CURRENCY": cfg["currency"],
            "VERSION": __version__, "REPO_URL": REPO_URL, "LANG": i18n.current(), "LANGUAGES": i18n.LANGUAGES,
            "JS_T": i18n.js_catalog(), "JS_LOCALE": i18n.js_locale()}


@app.before_request
def first_run_wizard():
    """Nowa, pusta baza: zanim pokażemy program, prowadzimy przez kreator pierwszego uruchomienia."""
    if request.method != "GET" or request.endpoint in (None, "static", "setup_wizard", "setup_skip"):
        return None
    with db.connect() as conn:
        if settings.get("setup_done", conn) == "1":
            return None
        if not db.is_empty(conn):  # dane już są (np. przywrócona kopia) – kreator niepotrzebny
            settings.save(conn, {"setup_done": "1"})
            return None
    return redirect(url_for("setup_wizard"))


def ingredient_rows(conn, include_inactive=False):
    state = db.stock_state(conn)
    sql = "SELECT * FROM ingredients"
    if not include_inactive:
        sql += " WHERE active = 1"
    sql += " ORDER BY lower(name), lower(manufacturer)"
    rows = []
    for ing in conn.execute(sql):
        s = state.get(ing["id"], {"qty": 0.0, "avg": 0.0})
        rows.append({
            **dict(ing),
            "qty": s["qty"],
            "avg": s["avg"],
            "value": max(s["qty"], 0) * s["avg"],
            # Bez stanu pokazujemy ostatnią znaną cenę.
            "price": s["avg"] if s["qty"] > 0 and s["avg"] else ing["ref_price"],
            "price_is_ref": not (s["qty"] > 0 and s["avg"]),
            "low": ing["min_stock"] > 0 and s["qty"] < ing["min_stock"],
            "unit": _(db.CATEGORIES[ing["category"]]["unit"]),
        })
    return rows


@app.route("/")
def dashboard():
    from datetime import date
    month = date.today().strftime("%Y-%m")
    with db.connect() as conn:
        rows = ingredient_rows(conn)
        low = sorted((r for r in rows if r["low"]), key=lambda r: r["qty"] - r["min_stock"])
        missing_price = [r for r in rows if r["qty"] > 0 and not r["price"]]
        prod = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(amount_ml), 0) ml, COALESCE(SUM(cost_total), 0) cost"
                            " FROM productions WHERE substr(date, 1, 7) = ?", (month,)).fetchone()
        bought = conn.execute("SELECT COALESCE(SUM(m.qty * m.unit_cost), 0) FROM movements m JOIN purchases p"
                              " ON p.id = m.purchase_id WHERE substr(p.date, 1, 7) = ? AND p.note NOT LIKE 'Bilans otwarcia%'",
                              (month,)).fetchone()[0]
        stats = {
            "value": sum(r["value"] for r in rows),
            "items_in_stock": sum(1 for r in rows if r["qty"] > 0),
            "low": low,
            "missing_price": missing_price,
            "recipes": conn.execute("SELECT COUNT(*) FROM recipes WHERE archived = 0").fetchone()[0],
            "recipes_top": conn.execute("SELECT COUNT(*) FROM recipes WHERE archived = 0 AND rating >= 4").fetchone()[0],
            "prod": dict(prod),
            "bought": bought,
        }
        recent_receipts = conn.execute(
            "SELECT p.*, SUM(m.qty * m.unit_cost) total, COUNT(m.id) lines FROM purchases p"
            " LEFT JOIN movements m ON m.purchase_id = p.id GROUP BY p.id ORDER BY p.date DESC, p.id DESC LIMIT 5").fetchall()
        recent_made = conn.execute(
            "SELECT h.date, r.id, r.name, h.note FROM recipe_history h JOIN recipes r ON r.id = h.recipe_id"
            " WHERE h.event = 'made' ORDER BY h.date DESC, h.id DESC LIMIT 6").fetchall()
    return render_template("dashboard.html", stats=stats, recent_receipts=recent_receipts,
                           recent_made=recent_made, month=month)


@app.route("/magazyn")
def inventory():
    show_inactive = request.args.get("nieaktywne") == "1"
    with db.connect() as conn:
        rows = ingredient_rows(conn, include_inactive=show_inactive)
    counts = {key: sum(1 for r in rows if r["category"] == key) for key in db.CATEGORIES}
    return render_template(
        "inventory.html",
        rows=rows,
        counts=counts,
        total_value=sum(r["value"] for r in rows),
        active_cat=request.args.get("kat", ""),
        show_inactive=show_inactive,
    )


def ingredient_fields_from_form(form):
    category = form.get("category", "aroma")
    if category not in db.CATEGORIES:
        abort(400)
    return {
        "name": form.get("name", "").strip(),
        "category": category,
        "manufacturer": form.get("manufacturer", "").strip(),
        "pg_pct": db.parse_num(form.get("pg_pct"), 0),
        "vg_pct": db.parse_num(form.get("vg_pct"), 0),
        "nicotine_mg": db.parse_num(form.get("nicotine_mg"), 0),
        "grams_per_ml": db.parse_num(form.get("grams_per_ml"), 1),
        "capacity_ml": db.parse_num(form.get("capacity_ml")),
        "min_stock": db.parse_num(form.get("min_stock"), 0),
        "description": form.get("description", "").strip(),
        "folder": form.get("folder", "").strip(),
        "default_pct": db.parse_num(form.get("default_pct")),
        "ref_price": db.parse_num(form.get("ref_price")),
    }


def manufacturers(conn):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT manufacturer FROM ingredients WHERE manufacturer <> '' ORDER BY lower(manufacturer)")]


def folders(conn, table="ingredients"):
    return [r[0] for r in conn.execute(
        f"SELECT DISTINCT folder FROM {table} WHERE folder <> '' ORDER BY lower(folder)")]


@app.route("/skladnik/nowy", methods=["GET", "POST"])
def ingredient_new():
    with db.connect() as conn:
        if request.method == "POST":
            fields = ingredient_fields_from_form(request.form)
            if not fields["name"]:
                flash(_("Podaj nazwę składnika."), "error")
            elif db.find_ingredient(conn, fields["category"], fields["name"], fields["manufacturer"]):
                flash(_("Taki składnik już istnieje (ta sama nazwa, producent i kategoria)."), "error")
            else:
                new_id = db.create_ingredient(conn, **fields)
                flash(_("Dodano składnik: {name}.", name=fields["name"]), "ok")
                if request.form.get("close"):
                    return redirect(url_for("inventory"))
                return redirect(url_for("ingredient_card", ingredient_id=new_id))
            ing = fields
        else:
            category = request.args.get("kat", "aroma")
            if category not in db.CATEGORIES:
                category = "aroma"
            defaults = db.CATEGORIES[category]
            ing = {"name": "", "category": category, "manufacturer": "", "pg_pct": defaults["pg"],
                   "vg_pct": defaults["vg"], "nicotine_mg": 0, "grams_per_ml": 1, "capacity_ml": None,
                   "min_stock": 0, "description": "", "folder": "", "default_pct": None, "ref_price": None,
                   "active": 1}
        return render_template("ingredient.html", ing=ing, is_new=True,
                               manufacturers=manufacturers(conn), folders=folders(conn), defaults_json=json.dumps(db.CATEGORIES))


@app.route("/skladnik/<int:ingredient_id>", methods=["GET", "POST"])
def ingredient_card(ingredient_id):
    with db.connect() as conn:
        ing = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
        if ing is None:
            abort(404)
        if request.method == "POST":
            fields = ingredient_fields_from_form(request.form)
            other = db.find_ingredient(conn, fields["category"], fields["name"], fields["manufacturer"])
            if not fields["name"]:
                flash(_("Podaj nazwę składnika."), "error")
            elif other and other["id"] != ingredient_id:
                flash(_("Inny składnik ma już tę nazwę, producenta i kategorię."), "error")
            else:
                fields["active"] = 1 if request.form.get("active") else 0
                assignments = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(f"UPDATE ingredients SET {assignments} WHERE id = ?",
                             (*fields.values(), ingredient_id))
                flash(_("Zapisano zmiany: {name}.", name=fields["name"]), "ok")
                if request.form.get("close"):
                    return redirect(url_for("inventory"))
            return redirect(url_for("ingredient_card", ingredient_id=ingredient_id))

        state = db.stock_state(conn, ingredient_id).get(ingredient_id, {"qty": 0.0, "avg": 0.0})
        history = conn.execute(
            "SELECT m.*, p.supplier FROM movements m LEFT JOIN purchases p ON p.id = m.purchase_id"
            " WHERE m.ingredient_id = ? ORDER BY m.date DESC, m.id DESC",
            (ingredient_id,),
        ).fetchall()
        suppliers = [r[0] for r in conn.execute(
            "SELECT DISTINCT supplier FROM purchases WHERE supplier <> '' ORDER BY lower(supplier)")]
        return render_template(
            "ingredient.html", ing=ing, is_new=False, state=state, history=history,
            unit=_(db.CATEGORIES[ing["category"]]["unit"]), today=db.today(), suppliers=suppliers,
            manufacturers=manufacturers(conn), folders=folders(conn), defaults_json=json.dumps(db.CATEGORIES),
        )


@app.post("/skladnik/<int:ingredient_id>/przyjmij")
def ingredient_receive(ingredient_id):
    pack_size = db.parse_num(request.form.get("pack_size"))
    pack_count = int(db.parse_num(request.form.get("pack_count"), 1))
    pack_price = db.parse_num(request.form.get("pack_price"), 0)
    if not pack_size or pack_size <= 0 or pack_count <= 0:
        flash(_("Podaj pojemność opakowania i liczbę sztuk."), "error")
        return redirect(url_for("ingredient_card", ingredient_id=ingredient_id))
    day = request.form.get("date") or db.today()
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO purchases (date, supplier) VALUES (?, ?)",
                           (day, request.form.get("supplier", "").strip()))
        db.add_purchase_line(conn, cur.lastrowid, ingredient_id, day, pack_size, pack_count, pack_price)
        done = mark_bought(conn, [ingredient_id])
    flash(_("Przyjęto {n} × {size}.", n=pack_count, size=fmt_num(pack_size)) + (" " + _("Odhaczono na liście zakupów.") if done else ""), "ok")
    return redirect(url_for("ingredient_card", ingredient_id=ingredient_id))


@app.post("/skladnik/<int:ingredient_id>/korekta")
def ingredient_adjust(ingredient_id):
    actual = db.parse_num(request.form.get("actual_qty"))
    if actual is None or actual < 0:
        flash(_("Podaj rzeczywisty stan (liczba ≥ 0)."), "error")
        return redirect(url_for("ingredient_card", ingredient_id=ingredient_id))
    with db.connect() as conn:
        current = db.stock_state(conn, ingredient_id).get(ingredient_id, {"qty": 0.0})["qty"]
        diff = actual - current
        if abs(diff) > 1e-9:
            conn.execute(
                "INSERT INTO movements (ingredient_id, date, kind, qty, note) VALUES (?, ?, 'adjustment', ?, ?)",
                (ingredient_id, db.today(), diff, request.form.get("note", "").strip()),
            )
    flash(_("Skorygowano stan."), "ok")
    return redirect(url_for("ingredient_card", ingredient_id=ingredient_id))


@app.post("/ruch/<int:movement_id>/usun")
def movement_delete(movement_id):
    with db.connect() as conn:
        mov = conn.execute("SELECT * FROM movements WHERE id = ?", (movement_id,)).fetchone()
        if mov is None:
            abort(404)
        conn.execute("DELETE FROM movements WHERE id = ?", (movement_id,))
        if mov["purchase_id"]:
            conn.execute(
                "DELETE FROM purchases WHERE id = ? AND NOT EXISTS"
                " (SELECT 1 FROM movements WHERE purchase_id = ?)",
                (mov["purchase_id"], mov["purchase_id"]),
            )
    flash(_("Usunięto wpis z historii."), "ok")
    return redirect(request.form.get("next") or url_for("ingredient_card", ingredient_id=mov["ingredient_id"]))


@app.route("/przyjecie", methods=["GET", "POST"])
def receipt_new():
    with db.connect() as conn:
        if request.method == "POST":
            return save_receipt(conn)
        ingredients = [dict(r) for r in conn.execute(
            "SELECT id, name, category, manufacturer FROM ingredients WHERE active = 1"
            " ORDER BY lower(name)")]
        last_packs = {r["ingredient_id"]: {"size": r["pack_size"], "price": r["unit_cost"] * r["pack_size"]}
                      for r in conn.execute(
                          "SELECT ingredient_id, pack_size, unit_cost FROM movements"
                          " WHERE kind = 'purchase' AND pack_size IS NOT NULL ORDER BY date, id")}
        suppliers = [r[0] for r in conn.execute(
            "SELECT DISTINCT supplier FROM purchases WHERE supplier <> '' ORDER BY lower(supplier)")]
        return render_template(
            "receipt.html", today=db.today(), suppliers=suppliers, manufacturers=manufacturers(conn),
            ingredients_json=json.dumps(ingredients), last_packs_json=json.dumps(last_packs),
            preselect=request.args.get("skladnik", type=int),
        )


def save_receipt(conn):
    form = request.form
    day = form.get("date") or db.today()
    lines = []
    errors = []
    for i, name in enumerate(form.getlist("name")):
        name = name.strip()
        if not name:
            continue
        category = form.getlist("category")[i]
        manufacturer = form.getlist("manufacturer")[i].strip()
        size = db.parse_num(form.getlist("pack_size")[i])
        count = db.parse_num(form.getlist("pack_count")[i], 1)
        price = db.parse_num(form.getlist("pack_price")[i], 0)
        if category not in db.CATEGORIES or not size or size <= 0 or not count or count <= 0:
            errors.append(_("Pozycja „{name}”: uzupełnij pojemność i liczbę sztuk.", name=name))
            continue
        sources = form.getlist("source_name")
        lines.append((category, name, manufacturer, size, int(count), price, sources[i] if i < len(sources) else ""))
    if errors or not lines:
        for e in errors or [_("Dodaj przynajmniej jedną pozycję.")]:
            flash(e, "error")
        return redirect(url_for("receipt_new"))

    cur = conn.execute("INSERT INTO purchases (date, supplier, note) VALUES (?, ?, ?)",
                       (day, form.get("supplier", "").strip(), form.get("note", "").strip()))
    purchase_id = cur.lastrowid
    created = 0
    import mailparse
    bought = []
    for category, name, manufacturer, size, count, price, source_name in lines:
        ing = db.find_ingredient(conn, category, name, manufacturer)
        if ing is None:
            ing_id = db.create_ingredient(conn, category, name, manufacturer)
            created += 1
        else:
            ing_id = ing["id"]
        db.add_purchase_line(conn, purchase_id, ing_id, day, size, count, price)
        # Zapamiętaj nazwę ze sklepu – następny mail z tą pozycją trafi od razu w ten składnik.
        mailparse.remember(conn, source_name, ing_id)
        bought.append(ing_id)
    done = mark_bought(conn, bought)
    msg = _("Zapisano przyjęcie: {n} poz.", n=len(lines))
    if done:
        msg += " " + _("Odhaczono na liście zakupów: {n}.", n=done)
    if created:
        msg += " " + _("Utworzono nowe składniki: {n}.", n=created)
    flash(msg, "ok")
    return redirect(url_for("receipt_view", purchase_id=purchase_id))


@app.post("/api/przyjecie/z-maila")
def api_receipt_from_mail():
    import mailparse
    with db.connect() as conn:
        return mailparse.recognize(conn, request.form.get("text", ""))


def mark_bought(conn, ingredient_ids):
    """Odhacza na liście zakupów pozycje składników, które właśnie przyszły."""
    ids = list(set(ingredient_ids))
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    return conn.execute(f"UPDATE shopping_list SET done_at = datetime('now', 'localtime')"
                        f" WHERE done_at IS NULL AND ingredient_id IN ({marks})", ids).rowcount


def default_pack(conn, ing):
    """Pojemność do zamówienia: ostatnio kupowana (bez bilansu otwarcia z importu)."""
    last = conn.execute("SELECT m.pack_size FROM movements m JOIN purchases p ON p.id = m.purchase_id"
                        " WHERE m.ingredient_id = ? AND m.kind = 'purchase' AND m.pack_size IS NOT NULL"
                        " AND p.note NOT LIKE 'Bilans otwarcia%' ORDER BY m.date DESC, m.id DESC LIMIT 1",
                        (ing["id"],)).fetchone()
    return last[0] if last else None


def add_to_list(conn, ing, pack_size=None, count=1):
    """Dodaje składnik do listy zakupów; zwraca False, gdy już na niej jest."""
    if conn.execute("SELECT 1 FROM shopping_list WHERE ingredient_id = ? AND done_at IS NULL", (ing["id"],)).fetchone():
        return False
    conn.execute("INSERT INTO shopping_list (ingredient_id, name, pack_size, pack_count) VALUES (?, ?, ?, ?)",
                 (ing["id"], ing["name"], pack_size or default_pack(conn, ing), count))
    return True


def back_or(default):
    target = request.form.get("next") or request.referrer
    return redirect(target if target and target.startswith(request.host_url) else default)


@app.route("/lista-zakupow")
def shopping():
    with db.connect() as conn:
        state = db.stock_state(conn)
        items = []
        for row in conn.execute("SELECT s.*, i.name AS ing_name, i.manufacturer, i.category, i.id AS ing_id"
                                " FROM shopping_list s LEFT JOIN ingredients i ON i.id = s.ingredient_id"
                                " WHERE s.done_at IS NULL ORDER BY i.manufacturer, lower(COALESCE(i.name, s.name))"):
            item = dict(row)
            item["stock"] = state.get(row["ingredient_id"], {"qty": 0})["qty"] if row["ing_id"] else None
            item["unit"] = _(db.CATEGORIES[row["category"]]["unit"]) if row["category"] else ""
            items.append(item)
        done = conn.execute("SELECT s.*, i.name AS ing_name, i.manufacturer FROM shopping_list s"
                            " LEFT JOIN ingredients i ON i.id = s.ingredient_id WHERE s.done_at IS NOT NULL"
                            " ORDER BY s.done_at DESC LIMIT 15").fetchall()
        options = [{"id": r["id"], "label": ingredient_label(r)} for r in conn.execute(
            "SELECT * FROM ingredients WHERE active = 1 ORDER BY lower(name)")]
        low_count = sum(1 for r in ingredient_rows(conn) if r["low"])
    preselect = next((o for o in options if o["id"] == request.args.get("dodaj", type=int)), None)
    return render_template("shopping.html", items=items, done=done, options=options, low_count=low_count,
                           preselect=preselect)


@app.get("/api/lista/opakowania")
def api_shopping_packs():
    """Podpowiedź przy dodawaniu do listy: ostatnio kupowana pojemność i jednostka."""
    with db.connect() as conn:
        ing = conn.execute("SELECT * FROM ingredients WHERE id = ?", (request.args.get("ingredient_id", type=int),)).fetchone()
        if ing is None:
            abort(404)
        return {"default": default_pack(conn, ing), "unit": _(db.CATEGORIES[ing["category"]]["unit"]),
                "on_list": bool(conn.execute(
                    "SELECT 1 FROM shopping_list WHERE ingredient_id = ? AND done_at IS NULL", (ing["id"],)).fetchone())}


@app.post("/lista/dodaj")
def shopping_add():
    with db.connect() as conn:
        ing_id = request.form.get("ingredient_id", "")
        ing = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ing_id,)).fetchone() if ing_id.isdigit() else None
        if ing is None:
            name = request.form.get("name", "").strip()
            if not name:
                flash(_("Wybierz składnik z listy albo wpisz nazwę."), "error")
                return back_or(url_for("shopping"))
            conn.execute("INSERT INTO shopping_list (name, pack_count) VALUES (?, 1)", (name,))
            flash(_("Dodano do listy zakupów: {name} (spoza magazynu).", name=name), "ok")
        elif add_to_list(conn, ing, db.parse_num(request.form.get("pack_size")),
                         int(db.parse_num(request.form.get("pack_count"), 1))):
            flash(_("Dodano do listy zakupów: {name}.", name=ing["name"]), "ok")
        else:
            flash(_("{name} już jest na liście zakupów.", name=ing["name"]), "error")
    return back_or(url_for("shopping"))


@app.post("/lista/dodaj-braki")
def shopping_add_low():
    with db.connect() as conn:
        low = [r for r in ingredient_rows(conn) if r["low"]]
        added = 0
        for r in low:
            ing = conn.execute("SELECT * FROM ingredients WHERE id = ?", (r["id"],)).fetchone()
            added += add_to_list(conn, ing)
    rest = len(low) - added
    flash(_("Dodano do listy zakupów braki: {n}", n=added) + (" " + _("(pozostałe {n} już były na liście).", n=rest) if rest else "."), "ok")
    return back_or(url_for("shopping"))


@app.post("/api/lista/<int:item_id>")
def api_shopping_update(item_id):
    with db.connect() as conn:
        n = conn.execute("UPDATE shopping_list SET pack_size = ?, pack_count = ? WHERE id = ?",
                         (db.parse_num(request.form.get("pack_size")),
                          max(int(db.parse_num(request.form.get("pack_count"), 1)), 1), item_id)).rowcount
        if not n:
            abort(404)
    return {"ok": True}


@app.post("/lista/<int:item_id>/kupione")
def shopping_done(item_id):
    with db.connect() as conn:
        conn.execute("UPDATE shopping_list SET done_at = CASE WHEN done_at IS NULL THEN datetime('now', 'localtime') END"
                     " WHERE id = ?", (item_id,))
    return redirect(url_for("shopping"))


@app.post("/lista/<int:item_id>/usun")
def shopping_delete(item_id):
    with db.connect() as conn:
        conn.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
    return redirect(url_for("shopping"))


@app.post("/lista/wyczysc-kupione")
def shopping_clear_done():
    with db.connect() as conn:
        n = conn.execute("DELETE FROM shopping_list WHERE done_at IS NOT NULL").rowcount
    flash(_("Usunięto kupione pozycje: {n}.", n=n), "ok")
    return redirect(url_for("shopping"))


@app.route("/przyjecia")
def receipts():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT p.*, COUNT(m.id) AS lines, SUM(m.qty * m.unit_cost) AS total"
            " FROM purchases p LEFT JOIN movements m ON m.purchase_id = p.id"
            " GROUP BY p.id ORDER BY p.date DESC, p.id DESC").fetchall()
    return render_template("receipts.html", rows=rows)


@app.route("/przyjecie/<int:purchase_id>")
def receipt_view(purchase_id):
    with db.connect() as conn:
        purchase = conn.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        if purchase is None:
            abort(404)
        lines = conn.execute(
            "SELECT m.*, i.name, i.manufacturer, i.category FROM movements m"
            " JOIN ingredients i ON i.id = m.ingredient_id WHERE m.purchase_id = ? ORDER BY m.id",
            (purchase_id,)).fetchall()
    return render_template("receipt_view.html", purchase=purchase, lines=lines)


@app.post("/przyjecie/<int:purchase_id>/usun")
def receipt_delete(purchase_id):
    with db.connect() as conn:
        conn.execute("DELETE FROM movements WHERE purchase_id = ?", (purchase_id,))
        conn.execute("DELETE FROM purchases WHERE id = ?", (purchase_id,))
    flash(_("Usunięto przyjęcie."), "ok")
    return redirect(url_for("receipts"))


@app.route("/przepisy")
def recipes():
    archive = request.args.get("archiwum") == "1"
    with db.connect() as conn:
        archived_count = conn.execute("SELECT COUNT(*) FROM recipes WHERE archived = 1").fetchone()[0]
        rows = [dict(r) for r in conn.execute(
            "SELECT r.*, n.name AS nicotine_name,"
            " (SELECT MAX(date) FROM recipe_history h WHERE h.recipe_id = r.id AND h.event = 'made') AS last_made,"
            " (SELECT COUNT(*) FROM recipe_history h WHERE h.recipe_id = r.id AND h.event = 'made') AS made_count"
            " FROM recipes r LEFT JOIN ingredients n ON n.id = r.nicotine_id WHERE r.archived = ?"
            " ORDER BY lower(r.name)", (1 if archive else 0,))]
        flavors = {}
        for f in conn.execute(
                "SELECT rf.recipe_id, rf.pct, i.name, i.manufacturer FROM recipe_flavors rf"
                " JOIN ingredients i ON i.id = rf.ingredient_id ORDER BY rf.recipe_id, rf.position"):
            flavors.setdefault(f["recipe_id"], []).append(dict(f))
        recipe_folders = sorted({r["folder"] for r in rows if r["folder"]}, key=str.lower)
    for r in rows:
        r["flavors"] = flavors.get(r["id"], [])
        r["search"] = " ".join([r["name"], r["folder"], r["notes"]] +
                               [f"{f['name']} {f['manufacturer']}" for f in r["flavors"]]).lower()
    return render_template("recipes.html", rows=rows, folders=recipe_folders, archive=archive,
                           archived_count=archived_count)


RECIPE_FIELDS = ("name", "folder", "notes", "rating", "amount_ml", "nicotine_mg", "pg_pct", "vg_pct",
                 "precedence", "nicotine_id", "pg_id", "vg_id", "steep_days")


def recipe_from_form(form):
    def ref(key):
        value = form.get(key, "")
        return int(value) if value.isdigit() else None

    pg = min(max(db.parse_num(form.get("pg_pct"), 50), 0), 100)
    recipe = {
        "name": form.get("name", "").strip(),
        "folder": form.get("folder", "").strip(),
        "notes": form.get("notes", "").strip(),
        "rating": int(db.parse_num(form.get("rating"), 0)),
        "amount_ml": db.parse_num(form.get("amount_ml"), 0),
        "nicotine_mg": db.parse_num(form.get("nicotine_mg"), 0),
        "pg_pct": pg,
        "vg_pct": 100 - pg,
        "precedence": "vg" if form.get("precedence") == "vg" else "pg",
        "nicotine_id": ref("nicotine_id"),
        "pg_id": ref("pg_id"),
        "vg_id": ref("vg_id"),
        "steep_days": int(db.parse_num(form.get("steep_days"), 0)),
    }
    flavors = []
    for ing_id, pct in zip(form.getlist("flavor_id"), form.getlist("flavor_pct")):
        if ing_id.isdigit():
            flavors.append((int(ing_id), db.parse_num(pct, 0)))
    return recipe, flavors


def ingredient_label(ing):
    label = ing["name"] + (f" · {ing['manufacturer']}" if ing["manufacturer"] else "")
    return label + ("" if ing["active"] else " " + _("(nieaktywny)"))


def recipe_editor(conn, recipe, flavors, recipe_id=None):
    used = {i for i, _ in flavors} | {recipe[k] for k in ("nicotine_id", "pg_id", "vg_id") if recipe[k]}
    options = {"nicotine": [], "pg": [], "vg": [], "flavor": []}
    for ing in conn.execute("SELECT * FROM ingredients ORDER BY lower(name), lower(manufacturer)"):
        if not ing["active"] and ing["id"] not in used:
            continue
        entry = {"id": ing["id"], "label": ingredient_label(ing), "default_pct": ing["default_pct"],
                 "nicotine_mg": ing["nicotine_mg"], "pg_pct": ing["pg_pct"], "vg_pct": ing["vg_pct"]}
        if ing["category"] in ("nicotine", "pg", "vg"):
            options[ing["category"]].append(entry)
        elif ing["category"] in ("aroma", "other"):
            options["flavor"].append(entry)
    labels = {o["id"]: o["label"] for o in options["flavor"]}
    flavor_rows = [{"id": i, "pct": p, "label": labels.get(i, "?")} for i, p in flavors]
    history = []
    if recipe_id:
        history = conn.execute("SELECT * FROM recipe_history WHERE recipe_id = ? ORDER BY date DESC",
                               (recipe_id,)).fetchall()
    return render_template("recipe_edit.html", recipe=recipe, recipe_id=recipe_id, flavor_rows=flavor_rows,
                           options=options, folders=folders(conn, "recipes"), history=history)


def save_recipe(conn, recipe, flavors, recipe_id=None):
    values = [recipe[k] for k in RECIPE_FIELDS]
    if recipe_id:
        conn.execute(f"UPDATE recipes SET {', '.join(f'{k} = ?' for k in RECIPE_FIELDS)} WHERE id = ?",
                     (*values, recipe_id))
        conn.execute("DELETE FROM recipe_flavors WHERE recipe_id = ?", (recipe_id,))
    else:
        recipe_id = conn.execute(
            f"INSERT INTO recipes ({', '.join(RECIPE_FIELDS)}) VALUES ({', '.join('?' for _ in RECIPE_FIELDS)})",
            values).lastrowid
    conn.executemany("INSERT INTO recipe_flavors (recipe_id, ingredient_id, pct, position) VALUES (?, ?, ?, ?)",
                     [(recipe_id, i, p, n) for n, (i, p) in enumerate(flavors)])
    return recipe_id


def load_recipe(conn, recipe_id):
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if row is None:
        abort(404)
    flavors = [(r["ingredient_id"], r["pct"]) for r in conn.execute(
        "SELECT ingredient_id, pct FROM recipe_flavors WHERE recipe_id = ? ORDER BY position", (recipe_id,))]
    return dict(row), flavors


@app.route("/przepis/nowy", methods=["GET", "POST"])
@app.route("/przepis/<int:recipe_id>", methods=["GET", "POST"])
def recipe_edit(recipe_id=None):
    with db.connect() as conn:
        if request.method == "POST":
            recipe, flavors = recipe_from_form(request.form)
            if not recipe["name"]:
                flash(_("Podaj nazwę przepisu."), "error")
                return recipe_editor(conn, recipe, flavors, recipe_id)
            if recipe_id:
                load_recipe(conn, recipe_id)
            recipe_id = save_recipe(conn, recipe, flavors, recipe_id)
            flash(_("Zapisano przepis: {name}.", name=recipe["name"]), "ok")
            if request.form.get("close"):
                archived = conn.execute("SELECT archived FROM recipes WHERE id = ?", (recipe_id,)).fetchone()[0]
                return redirect(url_for("recipes", archiwum=1) if archived else url_for("recipes"))
            return redirect(url_for("recipe_edit", recipe_id=recipe_id))
        if recipe_id:
            recipe, flavors = load_recipe(conn, recipe_id)
        else:
            recipe = new_recipe_defaults(conn)
            flavors = []
        return recipe_editor(conn, recipe, flavors, recipe_id)


def new_recipe_defaults(conn):
    """Nowy przepis: parametry z Ustawień; bazy bez ustawienia – jak w ostatnio utworzonym przepisie."""
    cfg = settings.all_settings(conn)
    last = conn.execute("SELECT * FROM recipes ORDER BY id DESC LIMIT 1").fetchone()
    pg = min(max(db.parse_num(cfg["recipe_pg_pct"], 50), 0), 100)
    recipe = {k: None for k in RECIPE_FIELDS}
    recipe.update(name="", folder="", notes="", rating=0, steep_days=0, precedence=last["precedence"] if last else "pg",
                  amount_ml=db.parse_num(cfg["recipe_amount_ml"], 50), pg_pct=pg, vg_pct=100 - pg,
                  nicotine_mg=db.parse_num(cfg["recipe_nicotine_mg"], 0))
    existing = {r[0] for r in conn.execute("SELECT id FROM ingredients WHERE active = 1")}
    for field, key in (("nicotine_id", "recipe_nicotine_id"), ("pg_id", "recipe_pg_id"), ("vg_id", "recipe_vg_id")):
        value = settings.get_id(key, conn)
        if value not in existing:
            value = last[field] if last else None
        recipe[field] = value
    return recipe


@app.post("/przepis/<int:recipe_id>/duplikuj")
def recipe_duplicate(recipe_id):
    with db.connect() as conn:
        recipe, flavors = load_recipe(conn, recipe_id)
        recipe["name"] += " " + _("(kopia)")
        new_id = save_recipe(conn, recipe, flavors)
    flash(_("Utworzono kopię przepisu."), "ok")
    return redirect(url_for("recipe_edit", recipe_id=new_id))


@app.post("/przepis/<int:recipe_id>/archiwizuj")
def recipe_archive(recipe_id):
    with db.connect() as conn:
        load_recipe(conn, recipe_id)
        conn.execute("UPDATE recipes SET archived = 1 WHERE id = ?", (recipe_id,))
    flash(_("Przeniesiono przepis do archiwum. Przywrócisz go z listy „Archiwum” w Przepisach."), "ok")
    return redirect(url_for("recipes"))


@app.post("/przepis/<int:recipe_id>/przywroc")
def recipe_restore(recipe_id):
    with db.connect() as conn:
        load_recipe(conn, recipe_id)
        conn.execute("UPDATE recipes SET archived = 0 WHERE id = ?", (recipe_id,))
    flash(_("Przywrócono przepis z archiwum."), "ok")
    return redirect(url_for("recipe_edit", recipe_id=recipe_id))


@app.post("/przepis/<int:recipe_id>/usun")
def recipe_delete(recipe_id):
    with db.connect() as conn:
        conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    flash(_("Usunięto przepis."), "ok")
    return redirect(url_for("recipes"))


@app.post("/api/oblicz")
def api_compute():
    import calc
    recipe, flavors = recipe_from_form(request.form)
    with db.connect() as conn:
        return calc.compute(conn, recipe, flavors)


@app.route("/produkcja/nowa", methods=["GET", "POST"])
def production_new():
    import production
    with db.connect() as conn:
        if request.method == "POST":
            params = production.params_from_form(request.form)
            try:
                production_id, _result = production.commit(conn, params)
            except production.ProductionError as exc:
                flash(str(exc), "error")
            else:
                flash(_("Zapisano produkcję i zdjęto składniki z magazynu."), "ok")
                return redirect(url_for("production_view", production_id=production_id))
            form = request.form
        else:
            form = {}
        recipe_rows = conn.execute("SELECT id, name, folder, amount_ml, nicotine_mg, pg_pct FROM recipes WHERE archived = 0"
                                   " ORDER BY lower(name)").fetchall()
        counts = {}
        for r in recipe_rows:
            counts[r["name"].lower()] = counts.get(r["name"].lower(), 0) + 1
        recipe_options = [{"id": r["id"], "amount_ml": r["amount_ml"], "nicotine_mg": r["nicotine_mg"], "pg_pct": r["pg_pct"],
                           "label": r["name"] + (f" [{r['folder'] or r['id']}]" if counts[r["name"].lower()] > 1 else "")}
                          for r in recipe_rows]
        state = db.stock_state(conn)
        bottles = [{"id": b["id"], "label": ingredient_label(b), "capacity_ml": b["capacity_ml"],
                    "stock": state.get(b["id"], {"qty": 0})["qty"]}
                   for b in conn.execute("SELECT * FROM ingredients WHERE category = 'bottle' AND active = 1"
                                         " ORDER BY lower(name)")]
    preselect = request.args.get("przepis", type=int) or (int(form["recipe_id"]) if form.get("recipe_id", "").isdigit() else None)
    return render_template("production_new.html", recipes=recipe_options, bottles=bottles, today=db.today(),
                           preselect=preselect, form=form)


@app.post("/api/produkcja/podglad")
def api_production_preview():
    import production
    params = production.params_from_form(request.form)
    if params["recipe_id"] is None:
        return {"error": _("Wybierz przepis.")}
    with db.connect() as conn:
        try:
            return production.preview(conn, params)
        except production.ProductionError as exc:
            return {"error": str(exc)}


@app.route("/produkcja")
def productions():
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM productions ORDER BY date DESC, id DESC").fetchall()
    return render_template("productions.html", rows=rows)


@app.route("/produkcja/<int:production_id>")
def production_view(production_id):
    with db.connect() as conn:
        prod = conn.execute("SELECT * FROM productions WHERE id = ?", (production_id,)).fetchone()
        if prod is None:
            abort(404)
        lines = conn.execute(
            "SELECT m.*, i.name, i.manufacturer, i.category FROM movements m JOIN ingredients i ON i.id = m.ingredient_id"
            " WHERE m.production_id = ? ORDER BY i.category = 'bottle', m.id", (production_id,)).fetchall()
    return render_template("production_view.html", prod=prod, lines=lines)


@app.post("/produkcja/<int:production_id>/cofnij")
def production_undo(production_id):
    import production
    with db.connect() as conn:
        production.undo(conn, production_id)
    flash(_("Cofnięto produkcję – składniki wróciły na magazyn."), "ok")
    return redirect(url_for("productions"))


SEARCH_LINKS = {"ingredients": "ingredient_card", "recipes": "recipe_edit",
                "productions": "production_view", "purchases": "receipt_view"}
SEARCH_ARGS = {"ingredients": "ingredient_id", "recipes": "recipe_id",
               "productions": "production_id", "purchases": "purchase_id"}


def search_results(query, limit=None):
    import search
    with db.connect() as conn:
        groups = search.search(conn, query, limit)
    for key, items in groups.items():
        for item in items:
            item["url"] = url_for(SEARCH_LINKS[key], **{SEARCH_ARGS[key]: item["id"]})
    return groups


@app.route("/kalkulator-mieszania")
def mixer():
    """Kalkulator łączenia gotowych płynów – bez wpływu na magazyn."""
    with db.connect() as conn:
        options = [{"label": ingredient_label(r), "mg": r["nicotine_mg"], "pg": r["pg_pct"]} for r in conn.execute(
            "SELECT * FROM ingredients WHERE active = 1 AND category IN ('nicotine', 'pg', 'vg', 'other')"
            " ORDER BY category, lower(name)")]
        options += [{"label": _("Produkcja: {name} ({date}, {mg} mg, {pg}/{vg})", name=p["recipe_name"], date=p["date"],
                              mg=f"{p['nicotine_mg']:g}", pg=f"{p['pg_pct']:.0f}", vg=f"{p['vg_pct']:.0f}"),
                     "mg": round(p["nicotine_mg"], 2), "pg": round(p["pg_pct"], 1)}
                    for p in conn.execute("SELECT * FROM productions ORDER BY date DESC, id DESC LIMIT 30")]
    return render_template("mixer.html", options=options)


@app.route("/szukaj")
def search_page():
    q = request.args.get("q", "").strip()
    return render_template("search.html", q=q, groups=search_results(q) if q else None)


@app.get("/api/szukaj")
def api_search():
    return search_results(request.args.get("q", ""), limit=6)


@app.route("/kopie")
def backups():
    import backup
    return render_template("backups.html", backups=backup.list_backups(), folder=backup.backup_dir(), keep=backup.keep())


@app.post("/kopie/nowa")
def backup_create():
    import backup
    flash(_("Utworzono kopię {name}.", name=backup.create("reczna")), "ok")
    return redirect(url_for("backups"))


@app.get("/kopie/<name>")
def backup_download(name):
    import backup
    from flask import send_file
    try:
        return send_file(backup.path_of(name), as_attachment=True, download_name=name)
    except ValueError:
        abort(404)


@app.post("/kopie/<name>/przywroc")
def backup_restore(name):
    import backup
    try:
        backup.restore(name)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash(_("Przywrócono dane z kopii {name}. Poprzedni stan zapisano jako kopię „przed przywróceniem”.", name=name), "ok")
    return redirect(url_for("backups"))


def import_message(stats):
    return _("Zaimportowano: {ingredients} składników (w tym {inactive} nieaktywnych), {stock} stanów magazynowych,"
             " {recipes} przepisów ({flavors} pozycji aromatów), {history} wpisów historii.", **stats)


def run_import(conn, replace=False):
    """Import z pliku wybranego w formularzu (pole „file”) albo ze ścieżki (pole „path”)."""
    import import_ejc
    upload = request.files.get("file")
    if upload and upload.filename:
        source = upload.stream
    else:
        source = request.form.get("path", "").strip().strip('"')
        if not source:
            raise import_ejc.ImportError_(_("Wybierz plik z danymi EJuiceCalculatora."))
    return import_ejc.import_file(conn, source, replace=replace)


@app.route("/import", methods=["GET", "POST"])
def import_page():
    import import_ejc
    path = request.form.get("path", "").strip().strip('"')
    if request.method == "POST":
        replace = bool(request.form.get("replace"))
        if replace:
            import backup
            backup.create("przed-importem")
        with db.connect() as conn:
            try:
                stats = run_import(conn, replace)
            except import_ejc.ImportError_ as exc:
                flash(str(exc), "error")
            else:
                flash(import_message(stats), "ok")
                return redirect(url_for("inventory"))
    with db.connect() as conn:
        has_data = conn.execute("SELECT EXISTS (SELECT 1 FROM ingredients)").fetchone()[0]
    return render_template("import.html", path=path, has_data=has_data)


# --- Kreator pierwszego uruchomienia ---

@app.route("/start", methods=["GET", "POST"])
def setup_wizard():
    import import_ejc
    with db.connect() as conn:
        if request.method == "GET":
            again = request.args.get("ponownie") == "1"
            if request.args.get("jezyk") in i18n.LANGUAGES:  # przełącznik języka na pierwszym ekranie
                settings.save(conn, {"language": request.args["jezyk"]})
                return redirect(url_for("setup_wizard", ponownie=1) if again else url_for("setup_wizard"))
            if settings.get("setup_done", conn) == "1" and not again:
                return redirect(url_for("dashboard"))
            return render_template("setup.html", empty=db.is_empty(conn))
        form = request.form
        msg = []
        if form.get("start") == "import":
            try:
                stats = run_import(conn, replace=False)
            except import_ejc.ImportError_ as exc:
                conn.rollback()
                flash(str(exc), "error")
                return render_template("setup.html", empty=db.is_empty(conn), form=form)
            msg.append(import_message(stats))
        pg = min(max(db.parse_num(form.get("pg_pct"), 50), 0), 100)
        values = {"setup_done": "1", "recipe_pg_pct": f"{pg:g}", "language": i18n.current(),
                  "currency": (form.get("currency", "").strip() or settings.get("currency", conn))[:6],
                  "recipe_nicotine_mg": f"{max(db.parse_num(form.get('nicotine_mg'), 0), 0):g}",
                  "recipe_amount_ml": f"{max(db.parse_num(form.get('amount_ml'), 50), 1):g}",
                  "measure": "g" if form.get("measure") == "g" else "ml"}
        created = []
        if form.get("add_pg"):
            values["recipe_pg_id"] = setup_ingredient(conn, "pg", "PG", form.get("pg_maker", ""), created)
        if form.get("add_vg"):
            values["recipe_vg_id"] = setup_ingredient(conn, "vg", "VG", form.get("vg_maker", ""), created)
        if form.get("add_base"):
            mg = db.parse_num(form.get("base_mg"), 18) or 18
            base_pg = min(max(db.parse_num(form.get("base_pg"), 50), 0), 100)
            values["recipe_nicotine_id"] = setup_ingredient(
                conn, "nicotine", _("Baza {mg} mg", mg=f"{mg:g}"), form.get("base_maker", ""), created,
                nicotine_mg=mg, pg_pct=base_pg, vg_pct=100 - base_pg, grams_per_ml=1.15 if base_pg < 50 else 1.1)
        settings.save(conn, values)
        if created:
            msg.append(_("Dodano do magazynu: {names} (stan 0 – uzupełnisz przyjęciem).", names=", ".join(created)))
    flash(" ".join(msg) or _("Gotowe! Zacznij od przyjęcia składników albo dodania przepisu."), "ok")
    return redirect(url_for("dashboard"))


def setup_ingredient(conn, category, name, manufacturer, created, **fields):
    """Składnik z kreatora; jeśli już jest (np. z importu), używamy istniejącego."""
    manufacturer = manufacturer.strip()
    ing = db.find_ingredient(conn, category, name, manufacturer)
    if ing:
        return ing["id"]
    created.append(name)
    defaults = {"pg": {"grams_per_ml": 1.036}, "vg": {"grams_per_ml": 1.26}}.get(category, {})
    return db.create_ingredient(conn, category, name, manufacturer, **{**defaults, **fields})


@app.post("/start/pomin")
def setup_skip():
    with db.connect() as conn:
        settings.save(conn, {"setup_done": "1"})
    return redirect(url_for("dashboard"))


# --- Ustawienia ---

@app.route("/ustawienia", methods=["GET", "POST"])
def settings_page():
    import backup
    with db.connect() as conn:
        if request.method == "POST":
            form = request.form
            pg = min(max(db.parse_num(form.get("recipe_pg_pct"), 50), 0), 100)
            phone_dir = form.get("phone_pdf_dir", "").strip().strip('"')
            phone_on = bool(form.get("phone_pdf_enabled"))
            errors = []
            if phone_on and not (phone_dir and os.path.isdir(phone_dir)):
                errors.append(_("PDF na telefon: wybierz istniejący folder albo wyłącz tę opcję."))
                phone_on = False
            values = {
                "language": form.get("language") if form.get("language") in i18n.LANGUAGES else settings.get("language", conn),
                "theme": "light" if form.get("theme") == "light" else "dark",
                "measure": "g" if form.get("measure") == "g" else "ml",
                "currency": (form.get("currency", "").strip() or "zł")[:6],
                "recipe_amount_ml": f"{max(db.parse_num(form.get('recipe_amount_ml'), 50), 1):g}",
                "recipe_pg_pct": f"{pg:g}",
                "recipe_nicotine_mg": f"{max(db.parse_num(form.get('recipe_nicotine_mg'), 0), 0):g}",
                "recipe_nicotine_id": form.get("recipe_nicotine_id", ""),
                "recipe_pg_id": form.get("recipe_pg_id", ""),
                "recipe_vg_id": form.get("recipe_vg_id", ""),
                "phone_pdf_enabled": "1" if phone_on else "0",
                "phone_pdf_dir": phone_dir,
                "backup_keep": str(min(max(int(db.parse_num(form.get("backup_keep"), 30)), 1), 365)),
            }
            settings.save(conn, values)
            for e in errors:
                flash(e, "error")
            if not errors:
                flash(_("Zapisano ustawienia."), "ok")
            if phone_on:
                import phone_export
                phone_export.schedule(1)
            backup.prune()
            return redirect(url_for("settings_page"))
        options = {cat: [{"id": r["id"], "label": ingredient_label(r)} for r in conn.execute(
            "SELECT * FROM ingredients WHERE category = ? AND active = 1 ORDER BY lower(name)", (cat,))]
            for cat in ("nicotine", "pg", "vg")}
        cfg = settings.all_settings(conn)
    return render_template("settings.html", cfg=cfg, options=options, data_dir=os.path.dirname(db.DB_PATH),
                           suggested_dir=settings.default_phone_dir())


@app.route("/ustawienia/informacje")
def settings_info():
    import backup
    import phone_export

    def size(path):
        try:
            return f"{os.path.getsize(path) / 1024:,.0f} KB".replace(",", " ")
        except (OSError, TypeError):
            return ""

    with db.connect() as conn:
        count = lambda sql: conn.execute(sql).fetchone()[0]
        info = {
            "ingredients": count("SELECT COUNT(*) FROM ingredients"),
            "ingredients_active": count("SELECT COUNT(*) FROM ingredients WHERE active = 1"),
            "recipes_active": count("SELECT COUNT(*) FROM recipes WHERE archived = 0"),
            "recipes_archived": count("SELECT COUNT(*) FROM recipes WHERE archived = 1"),
            "purchases": count("SELECT COUNT(*) FROM purchases"),
            "productions": count("SELECT COUNT(*) FROM productions"),
        }
    data_dir = os.path.dirname(db.DB_PATH)
    log = os.path.join(data_dir, "liquiderp.log")
    pdf = phone_export.target_path() if phone_export.enabled() else None
    info["paths"] = [(_("Folder danych"), data_dir, ""),
                     (_("Baza danych"), db.DB_PATH, size(db.DB_PATH)),
                     (_("Kopie zapasowe"), backup.backup_dir(), ""),
                     (_("PDF na telefon"), pdf, size(pdf)),
                     (_("Dziennik błędów"), log, size(log)),
                     (_("Folder programu"), paths.RESOURCE_DIR, "")]
    return render_template("settings_info.html", info=info)


@app.post("/api/ustawienia")
def api_setting():
    """Szybka zmiana z interfejsu (przełącznik motywu, „Odmierzam ml / Ważę g”)."""
    allowed = {"theme": ("dark", "light"), "measure": ("ml", "g")}
    key, value = request.form.get("key", ""), request.form.get("value", "")
    if value not in allowed.get(key, ()):
        abort(400)
    with db.connect() as conn:
        settings.save(conn, {key: value})
    return {"ok": True}


@app.post("/api/wybierz-folder")
def api_pick_folder():
    """Okno wyboru folderu Windows (w oknie programu) – zwraca wybraną ścieżkę."""
    try:
        import webview
        window = webview.windows[0] if webview.windows else None
    except Exception:
        window = None
    if window is None:
        return {"path": None, "error": _("Wybór folderu działa w oknie programu – wpisz ścieżkę ręcznie.")}
    result = window.create_file_dialog(webview.FOLDER_DIALOG, directory=request.form.get("start", ""))
    return {"path": result[0] if result else None}


@app.post("/ustawienia/pdf-teraz")
def phone_pdf_now():
    import phone_export
    path = phone_export.export()
    if path:
        flash(_("Zapisano PDF: {path}", path=path), "ok")
    else:
        flash(_("Nie udało się zapisać PDF – sprawdź folder w ustawieniach (szczegóły w pliku liquiderp.log)."), "error")
    return redirect(url_for("settings_page"))


# --- Aktualizacje (GitHub Releases) ---

@app.post("/api/aktualizacje/sprawdz")
def api_update_check():
    import updates
    return updates.check()


@app.post("/api/aktualizacje/pobierz")
def api_update_download():
    import updates
    return updates.start_download()


@app.get("/api/aktualizacje/stan")
def api_update_state():
    import updates
    return updates.state()


@app.post("/api/aktualizacje/zainstaluj")
def api_update_install():
    import updates
    return updates.install()


# --- Zgłoś uwagę (GitHub Issues) ---

def issue_url(kind, title, description):
    """Adres nowego zgłoszenia na GitHubie z wypełnionym opisem; nie wysyła żadnych danych z bazy."""
    import platform
    from urllib.parse import urlencode
    label = "bug" if kind == "bug" else "enhancement"
    prefix = _("[Błąd]") if kind == "bug" else _("[Pomysł]")
    title = title.strip() or (description.strip().splitlines() or [""])[0][:80] or _("Uwaga")
    steps = ""
    if kind == "bug":
        steps = "\n\n**" + _("Kroki, żeby powtórzyć:") + "**\n1. \n\n**" + _("Co powinno się stać:") + "**\n"
    body = (f"{description.strip()}{steps}\n\n---\n"
            f"{_('Wersja LiquidERP')}: {__version__}\n"
            f"{_('Język programu')}: {i18n.LANGUAGES[i18n.current()]}\n"
            f"System: {platform.system()} {platform.release()} ({platform.version()}, {platform.machine()})\n")
    return f"{REPO_URL}/issues/new?" + urlencode({"title": f"{prefix} {title}", "body": body, "labels": label})


@app.post("/api/zglos")
def api_report():
    description = request.form.get("description", "")
    if not description.strip():
        return {"error": _("Opisz uwagę – choćby jednym zdaniem.")}, 400
    url = issue_url(request.form.get("kind", "bug"), request.form.get("title", ""), description)
    opened = webbrowser.open(url)
    return {"url": url, "opened": bool(opened)}


if __name__ == "__main__":
    import sys
    db.init_db()
    import backup
    import phone_export
    backup.daily()
    if phone_export.enabled():
        phone_export.schedule(2)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}/")).start()
    app.run(host=HOST, port=PORT, debug=False)
