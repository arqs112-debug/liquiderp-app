"""Test rozpoznawania maili z zamówieniem (bez zapisu do bazy): python tests/mail_test.py"""
import os
import sys
import tempfile

os.environ["LIQUIDERP_DATA"] = tempfile.mkdtemp()  # pusta baza tymczasowa, nie dane z %AppData%
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import mailparse

db.init_db()

# Tabela tak, jak przychodzi w treści tekstowej maila ze sklepu na WooCommerce (przykładowe dane).
MARKDOWN = """
| Cześć, Otrzymaliśmy twoje zamówienie #10386, i właśnie je przygotowujemy: |
| Zamówienie #10386 (2026-10-27) |
| Produkt | Ilość | Cena |
|---|---|---|
| AROMAT SPOŻYWCZY DO CIAST NAPOJÓW INAWERA ON ICE - JEŻYNOWY CUKIEREK - 100ml | x 1 | 65,99 zł |
| AROMAT SPOŻYWCZY DO CIAST NAPOJÓW INAWERA MIX - BOMBIES - 10ml | x 1 | 9,99 zł |
| AROMAT SPOŻYWCZY DO CIAST NAPOJÓW INAWERA MIX - TROPICAL MOON 10 ML - 10ml | x 1 | 9,99 zł |
| AROMAT SPOŻYWCZY DO CIAST NAPOJÓW INAWERA ON ICE - KAKTUS LIMONKA - 100ml | x 2 | 171,98 zł |
| AROMAT SPOŻYWCZY INAWERA ON ICE - MELON & LICZI - 10ml | x 1 | 9,99 zł |
| Kwota: | 267,94 zł |
| Razem: | 267,94 zł (zawiera 50,10 zł Wszystko) |
| Dziękujemy za zakupy https://sklep-z-aromatami.pl! |
"""

# Ten sam mail skopiowany z widoku Gmaila (Ctrl+A, Ctrl+C) – komórki w osobnych liniach.
COPIED = """Dziękujemy za zamówienie
Cześć, Otrzymaliśmy twoje zamówienie #10386, i właśnie je przygotowujemy:
Zamówienie #10386 (2026-10-27)
Produkt\tIlość\tCena
AROMAT SPOŻYWCZY DO CIAST NAPOJÓW INAWERA ON ICE - JEŻYNOWY CUKIEREK - 100ml
x 1
65,99 zł
AROMAT SPOŻYWCZY DO CIAST NAPOJÓW INAWERA MIX - BOMBIES - 10ml\tx 1\t9,99 zł
Razem:\t75,98 zł
Dziękujemy za zakupy https://sklep-z-aromatami.pl!
"""

with db.connect() as conn:
    r = mailparse.recognize(conn, MARKDOWN)
    print(r["date"], r["supplier"], r["note"], r["total"], r["items_total"])
    for l in r["lines"]:
        print(f"  {l['match']:6} {l['name']} · {l['manufacturer']}  {l['pack_count']} × {l['pack_size']:g} ml po {l['pack_price']}")
    assert (r["date"], r["supplier"], r["total"], r["items_total"]) == ("2026-10-27", "sklep-z-aromatami.pl", 267.94, 267.94)
    assert len(r["lines"]) == 5
    kaktus = r["lines"][3]
    assert (kaktus["pack_count"], kaktus["pack_size"], kaktus["pack_price"]) == (2, 100, 85.99)
    assert r["lines"][2]["name"].endswith("Tropical Moon"), r["lines"][2]["name"]

    r2 = mailparse.recognize(conn, COPIED)
    assert [l["pack_price"] for l in r2["lines"]] == [65.99, 9.99] and r2["total"] == 75.98, r2
print("mail OK")
