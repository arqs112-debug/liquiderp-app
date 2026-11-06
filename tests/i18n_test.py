"""Test wersji angielskiej i formatów liczb: python tests/i18n_test.py

Na bazie z danymi bez polskich znaków przełącza program na angielski i sprawdza, że na żadnym
ekranie (ani w komunikatach, PDF i zgłoszeniu) nie zostały polskie teksty.
"""
import os
import re
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

os.environ["LIQUIDERP_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import i18n
import settings

db.init_db()
import app as m

c = m.app.test_client()
POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]|\b(nie|jest|albo|oraz|się|przepis\w*|Dodaj|Zapisz|Usuń|brak|Stan|Wybierz|kopi\w|sztuk|Razem|"
                    r"Nazwa|Sklep|Uwagi|Producent|Kategoria|Grupa|Ocena|pozycj\w*|dni|aktywn\w*|zamknij|Magazyn|Pulpit|"
                    r"Przyjęcie|Produkcja|Ustawienia|Narzędzia|szt|Szukaj|wersja|Ilość|Koszt|Wartość)\b")
ALLOWED = {"Język", "Polski", "zł"}  # nazwa języka w przełączniku i domyślna waluta


def leftovers(html):
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S)   # słownik T zawiera polskie klucze
    html = re.sub(r"<code>.*?</code>", " ", html, flags=re.S)                # ścieżki plików
    attrs = " ".join(re.findall(r'(?:title|placeholder|alt|aria-label)="([^"]*)"', html))
    html += " " + attrs
    html = re.sub(r"<datalist.*?</datalist>|<option[^>]*>|<[^>]+>", " ", html, flags=re.S)
    html = re.sub(r"&\w+;|&#\d+;", " ", html)
    found = []
    for mt in POLISH.finditer(html):
        word = html[max(0, mt.start() - 30):mt.end() + 30].replace("\n", " ")
        if not any(a in word for a in ALLOWED):
            found.append(word.strip())
    return found


# --- pusta baza po angielsku: kreator ---
c.get("/start?jezyk=en")
assert settings.get("language") == "en" and i18n.current() == "en"
page = c.get("/start").get_data(as_text=True)
assert 'lang="en"' in page and "Welcome to LiquidERP!" in page and "How do you want to start?" in page
assert not leftovers(page), leftovers(page)
r = c.post("/start", data={"start": "zero", "pg_pct": "30", "nicotine_mg": "3", "amount_ml": "60", "currency": "€",
                           "add_pg": "1", "add_vg": "1", "add_base": "1", "base_mg": "18", "base_pg": "50"}, follow_redirects=True)
html = r.get_data(as_text=True)
assert "Added to inventory: PG, VG, Base 18 mg (stock 0" in html, html[:2000]
assert settings.get("currency") == "€" and settings.get("language") == "en"
print("kreator EN OK")

# --- dane bez polskich znaków ---
r = c.post("/przyjecie", data={
    "date": "2026-10-01", "supplier": "Shop A", "note": "",
    "category": ["aroma", "bottle", "aroma"], "name": ["Strawberry", "Chubby 60", "Mango"],
    "manufacturer": ["TPA", "", "TPA"], "pack_size": ["10", "10", "30"], "pack_count": ["5", "2", "1"],
    "pack_price": ["12.50", "15", "1,250.00"], "source_name": ["", "", ""]}, follow_redirects=True)
html = r.get_data(as_text=True)
assert "Receipt saved: 3 lines." in html and "New ingredients created: 3." in html, html[:1500]
with db.connect() as conn:
    ings = {i["name"]: i for i in conn.execute("SELECT * FROM ingredients")}
    st = db.stock_state(conn)
assert abs(st[ings["Mango"]["id"]]["avg"] - 1250 / 30) < 1e-9          # „1,250.00” = 1250
assert abs(st[ings["Strawberry"]["id"]]["avg"] - 1.25) < 1e-9           # „12.50” = 12,5
straw, bottle = ings["Strawberry"]["id"], ings["Chubby 60"]["id"]
c.post(f"/skladnik/{bottle}", data={"name": "Chubby 60", "category": "bottle", "manufacturer": "", "capacity_ml": "60",
                                   "active": "1"})
r = c.post("/przepis/nowy", data={"name": "Test Mix", "amount_ml": "60", "nicotine_mg": "3", "pg_pct": "30",
                                 "precedence": "pg", "nicotine_id": str(settings.get_id("recipe_nicotine_id")), "pg_id": str(settings.get_id("recipe_pg_id")),
                                 "vg_id": str(settings.get_id("recipe_vg_id")), "flavor_id": [str(straw)], "flavor_pct": ["5"]},
           follow_redirects=True)
assert "Recipe saved: Test Mix." in r.get_data(as_text=True)
with db.connect() as conn:
    rid = conn.execute("SELECT id FROM recipes").fetchone()[0]
    for i in (settings.get_id("recipe_nicotine_id"), settings.get_id("recipe_pg_id"), settings.get_id("recipe_vg_id")):
        conn.execute("INSERT INTO movements (ingredient_id, date, kind, qty, unit_cost) VALUES (?, '2026-10-01', 'purchase', 1000, 0.02)", (i,))
r = c.post("/produkcja/nowa", data={"recipe_id": str(rid), "amount_ml": "60", "nicotine_mg": "3", "date": "2026-10-20",
                                   "bottle_id": [str(bottle)], "bottle_count": ["1"]}, follow_redirects=True)
assert "Production saved and ingredients taken out of stock." in r.get_data(as_text=True)
with db.connect() as conn:
    pid = conn.execute("SELECT id FROM productions").fetchone()[0]
    note = conn.execute("SELECT note FROM movements WHERE production_id = ?", (pid,)).fetchone()[0]
assert note.startswith("Production: Test Mix"), note
c.post("/lista/dodaj", data={"ingredient_id": str(straw), "pack_size": "10"})
c.post("/lista/dodaj", data={"name": "Caps"})
import backup
backup.create("reczna")
with db.connect() as conn:  # składnik poniżej minimum i bez ceny – ramki na pulpicie
    conn.execute("UPDATE ingredients SET min_stock = 500 WHERE id = ?", (straw,))
    nop = db.create_ingredient(conn, "aroma", "No Price", "X")
    conn.execute("INSERT INTO movements (ingredient_id, date, kind, qty, note) VALUES (?, '2026-10-01', 'adjustment', 5, '')", (nop,))

pages = ["/", "/magazyn", "/magazyn?nieaktywne=1", "/skladnik/nowy", f"/skladnik/{straw}", f"/skladnik/{bottle}", "/przyjecie",
         "/lista-zakupow", "/przyjecia", "/przyjecie/1", "/przepisy", "/przepisy?archiwum=1", "/przepis/nowy", f"/przepis/{rid}",
         "/produkcja/nowa", f"/produkcja/nowa?przepis={rid}", "/produkcja", f"/produkcja/{pid}", "/kalkulator-mieszania",
         "/szukaj?q=straw", "/szukaj?q=zzzz", "/kopie", "/import", "/ustawienia", "/ustawienia/informacje", "/start?ponownie=1"]
bad = {}
for url in pages:
    resp = c.get(url)
    assert resp.status_code == 200, (url, resp.status_code)
    html = resp.get_data(as_text=True)
    left = leftovers(html)
    if left:
        bad[url] = left[:8]
assert not bad, "\n".join(f"{u}: {l}" for u, l in bad.items())
html = c.get("/").get_data(as_text=True)
assert "Inventory value" in html and "Dashboard" in html and "Item in stock without a price (1)" in html
assert "€" in html and 'window.LOCALE = "en-US"' in html
print("ekrany EN OK:", len(pages))

# --- liczby: zapis angielski i polski ---
assert i18n.fmt_num(1017.52) == "1,017.52" and i18n.fmt_money(1017.5, "€") == "1,017.50 €"
assert i18n.fmt_num(1017.52, lang="pl") == "1 017,52" and i18n.fmt_money(3, "zł", lang="pl") == "3,00 zł"
for text, value in [("1,017.52", 1017.52), ("1 017,52", 1017.52), ("12,5", 12.5), ("12.5", 12.5), ("1.017,52", 1017.52),
                    ("1,250,000", 1250000), ("0,85", 0.85), ("-3", -3)]:
    assert db.parse_num(text) == value, (text, db.parse_num(text))
j = c.post("/api/oblicz", data={"amount_ml": "50", "nicotine_mg": "0", "pg_pct": "70",
                                "pg_id": str(settings.get_id("recipe_pg_id")), "vg_id": str(settings.get_id("recipe_vg_id"))}).get_json()
assert round(j["totals"]["pg_pct"]) == 70
j = c.post("/api/oblicz", data={"amount_ml": "50", "nicotine_mg": "6", "pg_pct": "50"}).get_json()
assert any(w.startswith("Choose a nicotine base") for w in j["warnings"]), j["warnings"]
print("liczby OK")

# --- PDF, zgłoszenie, komunikaty z modułów ---
import phone_export
with db.connect() as conn:
    pdf = phone_export.build(conn)
assert pdf[:4] == b"%PDF"
pdf_dir = tempfile.mkdtemp()
settings_form = {"language": "en", "theme": "dark", "measure": "ml", "currency": "€", "recipe_amount_ml": "60",
                 "recipe_pg_pct": "30", "recipe_nicotine_mg": "3", "backup_keep": "30", "phone_pdf_enabled": "1",
                 "phone_pdf_dir": pdf_dir}
assert "Settings saved." in c.post("/ustawienia", data=settings_form, follow_redirects=True).get_data(as_text=True)
assert phone_export.flush().endswith("LiquidERP for phone.pdf")
import webbrowser
webbrowser.open = lambda url, *a, **k: True
j = c.post("/api/zglos", data={"kind": "bug", "title": "Crash", "description": "It crashes."}).get_json()
q = parse_qs(urlparse(j["url"]).query)
assert q["title"] == ["[Bug] Crash"] and "Steps to reproduce:" in q["body"][0] and "Program language: English" in q["body"][0], q
j = c.post("/api/zglos", data={"kind": "idea", "description": "CSV export"}).get_json()
assert parse_qs(urlparse(j["url"]).query)["title"] == ["[Idea] CSV export"]
assert c.post("/api/zglos", data={"description": ""}).get_json()["error"].startswith("Describe")
assert [b["reason"] for b in backup.list_backups() if b["name"].endswith("reczna.db")] == ["manual"]
import mailparse
with db.connect() as conn:
    d = mailparse.recognize(conn, "Order #20001 (2026-11-02)\nProduct\tQuantity\tPrice\nTPA Strawberry - 10ml\tx 2\t€9.98\nTotal:\t€9.98\n")
assert d["lines"] and d["lines"][0]["pack_price"] == 4.99 and d["note"] == "Order #20001 (from e-mail)", d
print("PDF, zgłoszenie, mail EN OK")

# --- powrót do polskiego bez restartu ---
c.post("/ustawienia", data={**settings_form, "language": "pl"})
html = c.get("/").get_data(as_text=True)
assert 'lang="pl"' in html and "Wartość magazynu" in html and "window.T = {}" in html
print("i18n OK")
