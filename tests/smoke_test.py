"""Szybki test dymny na tymczasowej bazie: python tests/smoke_test.py"""
import os, sys, tempfile
os.environ["LIQUIDERP_DATA"] = tempfile.mkdtemp()  # nic nie trafia do %AppData%
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import i18n
i18n.force("pl")  # test sprawdza polskie teksty niezależnie od języka Windows
db.init_db()
import app as m
import settings
c = m.app.test_client()

# --- pusta baza: kreator pierwszego uruchomienia ---
assert db.DB_PATH.startswith(os.environ["LIQUIDERP_DATA"]), db.DB_PATH
r = c.get("/")
assert r.status_code == 302 and r.headers["Location"].endswith("/start"), r.headers.get("Location")
assert c.get("/magazyn").status_code == 302
page = c.get("/start").get_data(as_text=True)
assert "Witaj w LiquidERP" in page and "EJuiceCalculator" in page
print("kreator: przekierowanie OK")

r = c.post("/przyjecie", data={
    "date": "2026-10-01", "supplier": "Sklep A", "note": "",
    "category": ["aroma", "vg", "bottle", "aroma"],
    "name": ["Truskawka", "VG", "Chubby 60", ""],
    "manufacturer": ["Inawera", "", "", ""],
    "pack_size": ["10", "1000", "10", ""],
    "pack_count": ["5", "1", "2", "1"],
    "pack_price": ["12,50", "25", "15", ""],
})
assert r.status_code == 302, r.status_code
with db.connect() as conn:
    st = db.stock_state(conn)
    ings = {i["name"]: i for i in conn.execute("SELECT * FROM ingredients")}
t = ings["Truskawka"]
assert t["pg_pct"] == 100 and t["vg_pct"] == 0
print("Truskawka", st[t["id"]])  # 50 ml, 1.25 zl/ml
print("Butelki", st[ings["Chubby 60"]["id"]])  # 20 szt, 1.5

# drugie przyjęcie, inna pojemność -> średnia ważona
c.post(f"/skladnik/{t['id']}/przyjmij", data={"pack_size": "30", "pack_count": "1", "pack_price": "30", "date": "2026-10-05"})
c.post(f"/skladnik/{t['id']}/korekta", data={"actual_qty": "70"})
with db.connect() as conn:
    print("Truskawka po", db.stock_state(conn)[t["id"]])  # qty 70, avg (62.5+30)/80=1.15625

for url in ["/magazyn", "/magazyn?kat=aroma", f"/skladnik/{t['id']}", "/skladnik/nowy?kat=bottle", "/przyjecie", "/przyjecia", "/przyjecie/1", f"/przyjecie?skladnik={t['id']}"]:
    resp = c.get(url)
    assert resp.status_code == 200, (url, resp.status_code)
print("strony OK")
r = c.post("/skladnik/nowy", data={"name": "Baza 18", "category": "nicotine", "manufacturer": "X", "pg_pct": "50", "vg_pct": "50", "nicotine_mg": "18", "grams_per_ml": "1,15", "min_stock": "100", "description": "test"})
assert r.status_code == 302
print("OK")

# --- przepisy i wyliczenia ---
import calc
with db.connect() as conn:
    base = db.create_ingredient(conn, "nicotine", "Baza 36", "", pg_pct=50, vg_pct=50, nicotine_mg=36)
    pg = db.create_ingredient(conn, "pg", "PG", "Test")
    vg = db.create_ingredient(conn, "vg", "VG", "Test")
    rec = {"amount_ml": 100, "nicotine_mg": 3, "pg_pct": 50, "vg_pct": 50, "precedence": "pg",
           "nicotine_id": base, "pg_id": pg, "vg_id": vg}
    res = calc.compute(conn, rec, [(t["id"], 10)])
    ml = {l["role"]: round(l["ml"], 3) for l in res["lines"]}
    assert ml == {"nicotine": 8.333, "aroma": 10, "pg": 35.833, "vg": 45.833}, ml
    assert round(res["totals"]["pg_pct"], 3) == 50 and round(res["totals"]["nicotine_mg"], 3) == 3
    assert {m["name"] for m in res["missing"]} == {"Baza 36", "PG", "VG"}, res["missing"]
    # Za dużo PG z aromatów przy 30/70 i pierwszeństwie PG -> ostrzeżenie o proporcji.
    res = calc.compute(conn, dict(rec, pg_pct=10, vg_pct=90), [(t["id"], 20)])
    assert any("Nie da się" in w for w in res["warnings"]), res["warnings"]
print("obliczenia OK")

r = c.post("/przepis/nowy", data={"name": "Test", "amount_ml": "50", "nicotine_mg": "3", "pg_pct": "50",
           "precedence": "pg", "nicotine_id": str(base), "pg_id": str(pg), "vg_id": str(vg),
           "flavor_id": [str(t["id"]), ""], "flavor_pct": ["8", ""]})
assert r.status_code == 302, r.status_code
rid = int(r.headers["Location"].rstrip("/").split("/")[-1])
assert c.get(f"/przepis/{rid}").status_code == 200
assert c.post(f"/przepis/{rid}/duplikuj").status_code == 302
j = c.post("/api/oblicz", data={"amount_ml": "50", "nicotine_mg": "0", "pg_pct": "70", "pg_id": str(pg), "vg_id": str(vg)}).get_json()
assert round(j["totals"]["pg_pct"]) == 70, j
assert c.get("/przepisy").status_code == 200 and c.get("/przepis/nowy").status_code == 200
print("przepisy OK")

# --- produkcja ---
import production
with db.connect() as conn:
    for ing_id in (base, pg, vg):
        conn.execute("INSERT INTO movements (ingredient_id, date, kind, qty, unit_cost) VALUES (?, '2026-10-01', 'purchase', 500, 0.1)", (ing_id,))
    bottle = db.create_ingredient(conn, "bottle", "Chubby 60", "Test", capacity_ml=60)
    conn.execute("INSERT INTO movements (ingredient_id, date, kind, qty, unit_cost) VALUES (?, '2026-10-01', 'purchase', 1, 2)", (bottle,))
    before = db.stock_state(conn)
form_ok = {"recipe_id": str(rid), "amount_ml": "100", "nicotine_mg": "3", "date": "2026-10-20",
           "bottle_id": [str(bottle)], "bottle_count": ["2"]}
d = c.post("/api/produkcja/podglad", data=form_ok).get_json()
assert any(m["name"] == "Chubby 60" for m in d["missing"]), d["missing"]   # 2 butelki, jest 1
r = c.post("/produkcja/nowa", data=form_ok)
assert r.status_code == 200 and "Brakuje" in r.get_data(as_text=True)      # zablokowane
with db.connect() as conn:
    assert conn.execute("SELECT COUNT(*) FROM productions").fetchone()[0] == 0
form_ok["bottle_count"] = ["1"]
d = c.post("/api/produkcja/podglad", data=form_ok).get_json()
assert not d["missing"], d["missing"]
assert abs(d["totals"]["cost"] - (d["totals"]["cost_liquid"] + 2)) < 1e-9
r = c.post("/produkcja/nowa", data=form_ok)
assert r.status_code == 302, r.get_data(as_text=True)[:500]
pid = int(r.headers["Location"].rstrip("/").split("/")[-1])
with db.connect() as conn:
    after = db.stock_state(conn)
    assert after[bottle]["qty"] == 0
    used = before[t["id"]]["qty"] - after[t["id"]]["qty"]
    assert abs(used - 8) < 1e-9, used                        # 8% z 100 ml
    assert abs(after[t["id"]]["avg"] - before[t["id"]]["avg"]) < 1e-12   # rozchód nie zmienia średniej
    assert conn.execute("SELECT COUNT(*) FROM recipe_history WHERE production_id = ?", (pid,)).fetchone()[0] == 1
for url in ["/produkcja", f"/produkcja/{pid}", f"/produkcja/nowa?przepis={rid}", f"/skladnik/{t['id']}"]:
    assert c.get(url).status_code == 200, url
assert c.post(f"/produkcja/{pid}/cofnij").status_code == 302
with db.connect() as conn:
    assert db.stock_state(conn)[t["id"]]["qty"] == before[t["id"]]["qty"]
    assert conn.execute("SELECT COUNT(*) FROM recipe_history WHERE production_id IS NOT NULL").fetchone()[0] == 0
# wymuszenie mimo braków
form_ok["bottle_count"] = ["3"]; form_ok["force"] = "1"
assert c.post("/produkcja/nowa", data=form_ok).status_code == 302
with db.connect() as conn:
    assert db.stock_state(conn)[bottle]["qty"] == -2
    assert conn.execute("SELECT forced FROM productions").fetchone()[0] == 1
print("produkcja OK")

# --- wyszukiwarka i kopie ---
with db.connect() as conn:
    db.create_ingredient(conn, "aroma", "Jabłko Zielone", "Inawera", description="kwaśne, startowo 4%")
j = c.get("/api/szukaj?q=jablko inaw").get_json()
assert [i["title"] for i in j["ingredients"]] == ["Jabłko Zielone"], j
j = c.get("/api/szukaj?q=truskawka").get_json()
assert j["ingredients"] and j["recipes"] and j["purchases"], j      # składnik, przepis i przyjęcie
j = c.get("/api/szukaj?q=startowo").get_json()
assert j["ingredients"][0]["title"] == "Jabłko Zielone"
assert c.get("/szukaj?q=truskawka").status_code == 200 and c.get("/szukaj?q=zzzz").status_code == 200

import backup
name = backup.create("reczna")
assert c.get("/kopie").status_code == 200 and c.get(f"/kopie/{name}").status_code == 200
with db.connect() as conn:
    conn.execute("DELETE FROM recipe_flavors"); conn.execute("DELETE FROM recipe_history")
    conn.execute("DELETE FROM recipes")
assert c.post(f"/kopie/{name}/przywroc").status_code == 302
with db.connect() as conn:
    assert conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0] > 0
assert any(b["reason"] == "przed przywróceniem" for b in backup.list_backups())
assert c.get("/kopie/..%5Capp.py").status_code == 404
print("wyszukiwarka i kopie OK")

# --- przyjęcie z maila: nowy składnik, a potem zapamiętana nazwa ze sklepu ---
mail = "| AROMAT SPOŻYWCZY INAWERA MIX - ZIMNA ŻURAWINA - 10ml | x 3 | 29,97 zł |\n| Razem: | 29,97 zł |"
d = c.post("/api/przyjecie/z-maila", data={"text": mail}).get_json()
l = d["lines"][0]
assert (l["match"], l["name"], l["pack_count"], l["pack_price"]) == ("new", "Mix - Zimna Żurawina", 3, 9.99), l
r = c.post("/przyjecie", data={"date": "2026-10-28", "supplier": "sklep-z-aromatami.pl", "note": "",
           "category": ["aroma"], "name": ["Żurawina zimna"], "manufacturer": ["Inawera"],
           "pack_size": ["10"], "pack_count": ["3"], "pack_price": ["9,99"], "source_name": [l["source_name"]]})
assert r.status_code == 302
d = c.post("/api/przyjecie/z-maila", data={"text": mail}).get_json()
assert (d["lines"][0]["match"], d["lines"][0]["name"]) == ("alias", "Żurawina zimna"), d["lines"][0]
assert c.get("/przyjecie").status_code == 200
print("przyjęcie z maila OK")

# --- pulpit ---
r = c.get("/")
assert r.status_code == 200 and "Wartość magazynu" in r.get_data(as_text=True)
print("pulpit OK")

# --- archiwum przepisów i Esc ---
assert c.post(f"/przepis/{rid}/archiwizuj").status_code == 302
assert "Test</strong>" not in c.get("/przepisy").get_data(as_text=True)
arch = c.get("/przepisy?archiwum=1").get_data(as_text=True)
assert "Test</strong>" in arch and "przywróć" in arch
page = c.get(f"/przepis/{rid}").get_data(as_text=True)
assert "Przywróć z archiwum" in page and 'data-back="/przepisy?archiwum=1"' in page
assert f'"id": {rid}' not in c.get("/produkcja/nowa").get_data(as_text=True).replace("'", '"')
j = c.get("/api/szukaj?q=test").get_json()
assert any(r["id"] == rid and not r["active"] and "archiwum" in r["sub"] for r in j["recipes"]), j["recipes"]
assert c.post(f"/przepis/{rid}/przywroc").status_code == 302
assert "Test</strong>" in c.get("/przepisy").get_data(as_text=True)
assert 'data-back="/magazyn"' in c.get(f"/skladnik/{t['id']}").get_data(as_text=True)
assert 'data-back=""' in c.get("/magazyn").get_data(as_text=True)
print("archiwum i Esc OK")

# --- „Zapisz i zamknij” ---
form = {"name": "Truskawka", "category": "aroma", "manufacturer": "Inawera", "pg_pct": "100", "vg_pct": "0", "active": "1"}
r = c.post(f"/skladnik/{t['id']}", data=form)
assert r.headers["Location"].endswith(f"/skladnik/{t['id']}"), r.headers["Location"]
r = c.post(f"/skladnik/{t['id']}", data={**form, "close": "1"})
assert r.headers["Location"].endswith("/magazyn"), r.headers["Location"]
rec = {"name": "Test", "amount_ml": "50", "pg_pct": "50", "pg_id": str(pg), "vg_id": str(vg)}
assert c.post(f"/przepis/{rid}", data=rec).headers["Location"].endswith(f"/przepis/{rid}")
assert c.post(f"/przepis/{rid}", data={**rec, "close": "1"}).headers["Location"].endswith("/przepisy")
assert "Zapisz i zamknij" in c.get(f"/skladnik/{t['id']}").get_data(as_text=True)
print("zapisz i zamknij OK")

# --- pulpit: pozycje bez ceny z nazwą i linkiem, cena referencyjna na karcie ---
with db.connect() as conn:
    np_id = db.create_ingredient(conn, "aroma", "Bez Ceny", "Test")
    conn.execute("INSERT INTO movements (ingredient_id, date, kind, qty, note) VALUES (?, '2026-10-01', 'adjustment', 5, '')", (np_id,))
html = c.get("/").get_data(as_text=True)
assert f'href="/skladnik/{np_id}">Bez Ceny · Test</a>' in html and "Pozycja na stanie bez ceny (1)" in html, html[-2000:]
r = c.post(f"/skladnik/{np_id}", data={"name": "Bez Ceny", "category": "aroma", "manufacturer": "Test", "active": "1", "ref_price": "0,85"})
assert r.status_code == 302
c.get("/")  # zużywa komunikat flash po zapisie
assert "na stanie bez ceny" not in c.get("/").get_data(as_text=True)
print("brak ceny OK")

# --- lista zakupów (bez sklepu: ręczna pojemność i sztuki) ---
with db.connect() as conn:
    sel = db.create_ingredient(conn, "aroma", "Mix - Test", "Firma")
assert c.post("/lista/dodaj", data={"ingredient_id": str(sel), "pack_size": "10"}).status_code == 302
assert "już jest" in c.post("/lista/dodaj", data={"ingredient_id": str(sel)}, follow_redirects=True).get_data(as_text=True)
with db.connect() as conn:
    item = conn.execute("SELECT * FROM shopping_list WHERE ingredient_id = ?", (sel,)).fetchone()
    assert item["pack_size"] == 10
j = c.post(f"/api/lista/{item['id']}", data={"pack_size": "30", "pack_count": "2"}).get_json()
assert j == {"ok": True}, j
with db.connect() as conn:
    assert tuple(conn.execute("SELECT pack_size, pack_count FROM shopping_list WHERE id = ?", (item["id"],)).fetchone()) == (30, 2)
assert c.post("/api/lista/99999", data={"pack_size": "1"}).status_code == 404
page = c.get("/lista-zakupow").get_data(as_text=True)
assert "Mix - Test" in page and "Kopiuj listę" in page
for banned in ("Select&quot;", "koszyk", "sklepselect", "Cena w sklepie", "z Select"):
    assert banned not in page, banned
c.post("/lista/dodaj", data={"name": "Nakrętki"})
# przyjęcie odhacza pozycję
r = c.post("/przyjecie", data={"date": "2026-10-30", "supplier": "", "note": "", "category": ["aroma"], "name": ["Mix - Test"],
           "manufacturer": ["Firma"], "pack_size": ["30"], "pack_count": ["2"], "pack_price": ["26,99"], "source_name": [""]},
           follow_redirects=True)
assert "Odhaczono na liście zakupów: 1" in r.get_data(as_text=True)
with db.connect() as conn:
    assert conn.execute("SELECT done_at FROM shopping_list WHERE ingredient_id = ?", (sel,)).fetchone()[0]
assert c.post("/lista/wyczysc-kupione").status_code == 302
assert c.post("/lista/dodaj-braki").status_code == 302
assert c.get(f"/skladnik/{sel}").status_code == 200 and c.get("/").status_code == 200
print("lista zakupów OK")

# --- podpowiedź pojemności: ostatnio kupowana ---
j = c.get(f"/api/lista/opakowania?ingredient_id={sel}").get_json()
assert j["default"] == 30 and j["unit"] == "ml" and not j["on_list"], j
c.post("/lista/dodaj", data={"ingredient_id": str(sel), "pack_size": "100", "pack_count": "3"})
with db.connect() as conn:
    it = conn.execute("SELECT pack_size, pack_count FROM shopping_list WHERE ingredient_id = ? AND done_at IS NULL", (sel,)).fetchone()
    assert (it["pack_size"], it["pack_count"]) == (100, 3), tuple(it)
assert c.get(f"/api/lista/opakowania?ingredient_id={sel}").get_json()["on_list"]
assert '"Mix - Test · Firma"' in c.get(f"/lista-zakupow?dodaj={sel}").get_data(as_text=True)
assert f'/lista-zakupow?dodaj={sel}' in c.get(f"/skladnik/{sel}").get_data(as_text=True)
print("pojemność na liście OK")

# --- PDF na telefon: domyślnie wyłączony, włączany w Ustawieniach z folderem ---
import phone_export
with db.connect() as conn:
    pdf = phone_export.build(conn)
assert pdf[:4] == b"%PDF" and len(pdf) > 5000
assert not phone_export.enabled() and phone_export.flush() is None   # domyślnie wyłączony
pdf_dir = tempfile.mkdtemp()
base_form = {"theme": "dark", "measure": "ml", "currency": "zł", "recipe_amount_ml": "60", "recipe_pg_pct": "30",
             "recipe_nicotine_mg": "6", "recipe_nicotine_id": str(base), "recipe_pg_id": str(pg), "recipe_vg_id": str(vg),
             "backup_keep": "5"}
r = c.post("/ustawienia", data={**base_form, "phone_pdf_enabled": "1", "phone_pdf_dir": os.path.join(pdf_dir, "nie-ma")},
           follow_redirects=True)
assert "wybierz istniejący folder" in r.get_data(as_text=True)
assert settings.get("phone_pdf_enabled") == "0"
r = c.post("/ustawienia", data={**base_form, "phone_pdf_enabled": "1", "phone_pdf_dir": pdf_dir}, follow_redirects=True)
assert "Zapisano ustawienia" in r.get_data(as_text=True)
assert phone_export.enabled()
path = phone_export.flush()
assert path == os.path.join(pdf_dir, phone_export.FILE_NAME) and os.path.getsize(path) > 5000, path
print("PDF na telefon OK")

# --- ustawienia: domyślne parametry przepisu, motyw, waluta, kopie ---
page = c.get("/przepis/nowy").get_data(as_text=True)
assert 'name="amount_ml" value="60"' in page and 'name="nicotine_mg" value="6"' in page and 'id="pg_pct" value="30"' in page
assert c.get("/ustawienia").status_code == 200
assert c.post("/api/ustawienia", data={"key": "theme", "value": "light"}).get_json() == {"ok": True}
assert 'data-theme="light"' in c.get("/").get_data(as_text=True)
assert c.post("/api/ustawienia", data={"key": "theme", "value": "<x>"}).status_code == 400
assert c.post("/api/ustawienia", data={"key": "phone_pdf_dir", "value": "C:/"}).status_code == 400
c.post("/api/ustawienia", data={"key": "measure", "value": "g"})
assert 'data-measure="g"' in c.get("/").get_data(as_text=True)
c.post("/ustawienia", data={**base_form, "currency": "€"})
assert "€" in c.get("/magazyn").get_data(as_text=True) and settings.get("currency") == "€"
c.post("/ustawienia", data=base_form)
import backup
for n in range(7):  # kopie z różnych dni (create() w tej samej sekundzie nadpisałby jedną)
    open(os.path.join(backup.backup_dir(), f"liquiderp-2026-01-0{n + 1}_120000-auto.db"), "wb").close()
backup.prune()
assert len(backup.list_backups()) == 5, len(backup.list_backups())
assert backup.backup_dir().startswith(os.environ["LIQUIDERP_DATA"])
print("ustawienia OK")

# --- Zgłoś uwagę: adres GitHub Issues z wersją i systemem, bez danych z bazy ---
import webbrowser
from urllib.parse import parse_qs, urlparse
opened = []
webbrowser.open = lambda url, *a, **k: opened.append(url) or True
assert c.post("/api/zglos", data={"kind": "bug", "description": " "}).status_code == 400
j = c.post("/api/zglos", data={"kind": "bug", "title": "Nie liczy", "description": "Przepis nie przelicza VG."}).get_json()
u = urlparse(j["url"])
q = parse_qs(u.query)
assert u.netloc == "github.com" and u.path == "/arqs112-debug/liquiderp-app/issues/new", j["url"]
assert q["title"] == ["[Błąd] Nie liczy"] and q["labels"] == ["bug"], q
assert "Przepis nie przelicza VG." in q["body"][0] and m.__version__ in q["body"][0] and "System:" in q["body"][0]
assert "Truskawka" not in j["url"] and opened == [j["url"]]
j = c.post("/api/zglos", data={"kind": "idea", "description": "Eksport do CSV\nbyłby super"}).get_json()
q = parse_qs(urlparse(j["url"]).query)
assert q["title"] == ["[Pomysł] Eksport do CSV"] and q["labels"] == ["enhancement"], q
html = c.get("/").get_data(as_text=True)
assert "Zgłoś uwagę" in html and f"wersja {m.__version__}" in html
print("zgłoś uwagę OK")

# --- PG/VG zmieniane przy produkcji ---
with db.connect() as conn:
    conn.execute("UPDATE recipes SET pg_pct = 50, vg_pct = 50, nicotine_id = ?, pg_id = ?, vg_id = ? WHERE id = ?", (base, pg, vg, rid))
    for i in (base, pg, vg, t["id"]):
        conn.execute("INSERT INTO movements (ingredient_id, date, kind, qty, unit_cost) VALUES (?, '2026-10-01', 'purchase', 500, 0.1)", (i,))
d = c.post("/api/produkcja/podglad", data={"recipe_id": str(rid), "amount_ml": "30", "nicotine_mg": "3", "pg_pct": "30"}).get_json()
assert round(d["totals"]["pg_pct"]) == 30 and round(d["totals"]["vg_pct"]) == 70, d["totals"]
r = c.post("/produkcja/nowa", data={"recipe_id": str(rid), "amount_ml": "30", "nicotine_mg": "3", "pg_pct": "30", "date": "2026-11-01"})
assert r.status_code == 302, __import__("re").findall(r"class=\"flash[^>]*>([^<]*)", r.get_data(as_text=True))
with db.connect() as conn:
    assert conn.execute("SELECT pg_pct FROM recipes WHERE id = ?", (rid,)).fetchone()[0] == 50   # przepis bez zmian
    assert round(conn.execute("SELECT pg_pct FROM productions ORDER BY id DESC").fetchone()[0]) == 30
r = c.post("/produkcja/nowa", data={"recipe_id": str(rid), "amount_ml": "30", "nicotine_mg": "3", "pg_pct": "35",
           "save_ratio": "1", "date": "2026-11-01"})
with db.connect() as conn:
    assert conn.execute("SELECT pg_pct, vg_pct FROM recipes WHERE id = ?", (rid,)).fetchone()[:] == (35, 65)
assert 'id="pg_pct"' in c.get(f"/produkcja/nowa?przepis={rid}").get_data(as_text=True)
print("PG/VG w produkcji OK")

# --- kalkulator mieszania ---
page = c.get("/kalkulator-mieszania").get_data(as_text=True)
assert "Kalkulator mieszania" in page and "Baza 36" in page and "Dobierz" in page
print("kalkulator mieszania OK")

# --- ustawienia: zakładki Ogólne / Kopie / Import / Informacje, pozycja na dole menu ---
for url, text in [("/ustawienia", "Nowy przepis – wartości domyślne"), ("/kopie", "Zrób kopię teraz"),
                  ("/import", "Import z EJuiceCalculatora"), ("/ustawienia/informacje", "Gdzie są dane")]:
    page = c.get(url).get_data(as_text=True)
    assert text in page and 'class="tabs"' in page and "Ustawienia</span>" in page, url
    assert '<a href="/ustawienia" class="on">' in page or url != "/ustawienia", url
info = c.get("/ustawienia/informacje").get_data(as_text=True)
assert os.environ["LIQUIDERP_DATA"] in info and m.__version__ in info and "data-report" in info
assert "OneDrive" not in c.get("/kopie").get_data(as_text=True)
home = c.get("/").get_data(as_text=True)
assert "Import danych</span>" not in home and "Kalkulator mieszania</span>" in home
print("zakładki ustawień OK")

# --- brak śladów integracji ze sklepem i pocztą ---
with db.connect() as conn:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ingredients)")}
assert not tables & {"pending_receipts", "kit_rules"}, tables
assert not {c_ for c_ in cols if c_.startswith("shop_")}, cols
assert c.get("/przyjecia-z-maili").status_code == 404
print("bez integracji OK")

# --- kreator na nowej bazie: import z EJuiceCalculatora + bazy + domyślne parametry ---
import io
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "nowa.db")
db.init_db()
assert c.get("/").headers["Location"].endswith("/start")
EJC = """<?xml version="1.0" encoding="utf-8"?>
<JuiceData>
  <AllAvailableIngredients>
    <Ingredient><Name>Truskawka</Name><IngredientType>Flavor</IngredientType><ManEntry><Name>TPA</Name></ManEntry>
      <DefaultPGPercentage>1</DefaultPGPercentage><Cost>20</Cost><CostMLs>10</CostMLs><AmountInInventory>8</AmountInInventory></Ingredient>
    <Ingredient><Name>VG</Name><IngredientType>VGEntry</IngredientType><DefaultVGPercentage>1</DefaultVGPercentage></Ingredient>
  </AllAvailableIngredients>
  <AllRecipes>
    <Recipe><Name>Truskawkowy</Name><DefaultAmountToMake>30</DefaultAmountToMake>
      <AllIngredients><RecipeEntry><RecipePercentage>0.05</RecipePercentage>
        <RecipeIngredient><Name>Truskawka</Name><IngredientType>Flavor</IngredientType><ManEntry><Name>TPA</Name></ManEntry></RecipeIngredient>
      </RecipeEntry></AllIngredients></Recipe>
  </AllRecipes>
</JuiceData>"""
r = c.post("/start", data={"start": "import", "file": (io.BytesIO(b"<zly>"), "Baza.xml"), "pg_pct": "30"})
assert r.status_code == 200 and "Nie można odczytać" in r.get_data(as_text=True)
with db.connect() as conn:
    assert db.is_empty(conn) and settings.get("setup_done", conn) == "0"
r = c.post("/start", data={"start": "import", "file": (io.BytesIO(EJC.encode()), "Baza.xml"), "amount_ml": "30",
           "pg_pct": "30", "nicotine_mg": "3", "measure": "g", "add_pg": "1", "add_vg": "1", "add_base": "1",
           "base_mg": "20", "base_pg": "50"}, follow_redirects=True)
html = r.get_data(as_text=True)
assert "Zaimportowano: 2 składników" in html and "Dodano do magazynu: PG, Baza 20 mg" in html, html[:3000]
with db.connect() as conn:
    cfg = settings.all_settings(conn)
    names = {r["name"]: r for r in conn.execute("SELECT * FROM ingredients")}
assert cfg["setup_done"] == "1" and cfg["measure"] == "g" and cfg["recipe_pg_pct"] == "30"
assert int(cfg["recipe_vg_id"]) == names["VG"]["id"]          # istniejące VG z importu, bez duplikatu
assert names["Baza 20 mg"]["nicotine_mg"] == 20 and int(cfg["recipe_nicotine_id"]) == names["Baza 20 mg"]["id"]
assert c.get("/").status_code == 200 and c.get("/start").status_code == 302
page = c.get("/przepis/nowy").get_data(as_text=True)
assert f'<option value="{names["Baza 20 mg"]["id"]}" selected>Baza 20 mg' in page

# „Zacznij od zera” i „Pomiń kreator”
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "zero.db")
db.init_db()
r = c.post("/start", data={"start": "zero", "pg_pct": "50", "nicotine_mg": "0", "amount_ml": "100"}, follow_redirects=True)
assert r.status_code == 200 and "Gotowe" in r.get_data(as_text=True)
with db.connect() as conn:
    assert db.is_empty(conn) and settings.get("setup_done", conn) == "1" and settings.get("recipe_amount_ml", conn) == "100"
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "pomin.db")
db.init_db()
assert c.post("/start/pomin").status_code == 302 and c.get("/").status_code == 200
print("kreator OK")
print("WSZYSTKO OK")
