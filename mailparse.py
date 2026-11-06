"""Rozpoznawanie potwierdzeń zamówień wklejonych z maila i dopasowanie pozycji do składników.

Obsługuje tabele „Produkt | Ilość | Cena” / „Product | Quantity | Price” (np. sklepy na WooCommerce), zarówno
skopiowane jako tekst z Gmaila (komórki w osobnych liniach albo rozdzielone tabulatorami),
jak i w postaci jednej linii „nazwa x 2 19,98 zł”.
"""
import difflib
import re

import db
from i18n import _
from search import fold

QTY_RE = re.compile(r"^[x×]\s*(\d+)$", re.I)
# Kwota z walutą przed albo za liczbą: „19,98 zł”, „19.98 PLN”, „€9.98”, „$ 12.50”, „1,250.00 EUR”.
CURRENCY = r"(?:zł|pln|€|eur|\$|usd|£|gbp)"
AMOUNT = r"\d[\d\s\u00a0,.]*[,.]\d{2}"
PRICE_RE = re.compile(rf"^(?:{CURRENCY}\s*({AMOUNT})|({AMOUNT})\s*{CURRENCY})$", re.I)
INLINE_RE = re.compile(rf"^(.+?)\s+[x×]\s*(\d+)\s+(?:{CURRENCY}\s*({AMOUNT})|({AMOUNT})\s*{CURRENCY})\s*$", re.I)
SIZE_RE = re.compile(r"\s*[-–]?\s*(\d+(?:[,.]\d+)?)\s*(ml|l)\s*$", re.I)
PREFIX_RE = re.compile(r"^aromat(?:y)?\s+spożywcz\w*\s+(?:do\s+ciast\s+(?:i\s+)?napojów\s+)?", re.I)
FUZZY_MIN = 0.86
# Producenci rozpoznawani w nazwach produktów także wtedy, gdy nie ma ich jeszcze w bazie.
COMMON_BRANDS = {"Select", "MaiArt", "Inawera", "TPA", "Capella", "Atmos Lab", "Aromatyczny.pl", "FlavourArt",
                 "Flavor West", "Solub Arome", "Extreme Flavours", "Hangsen", "Easychem", "E-Dym"}


def _num(text):
    return db.parse_num(text)


def _price(m, first=1):
    """Kwota z dopasowania PRICE_RE/INLINE_RE (waluta mogła stać przed albo za liczbą)."""
    return _num(m.group(first) or m.group(first + 1))


def _cells(text):
    for line in text.replace("\r", "").split("\n"):
        for cell in re.split(r"\t|\s\|\s|^\||\|$", line):
            cell = cell.strip(" |")
            if cell:
                yield cell


def parse_items(text):
    items = []
    cells = list(_cells(text))
    for i, cell in enumerate(cells):
        m = QTY_RE.match(cell)
        if m and i > 0 and i + 1 < len(cells) and PRICE_RE.match(cells[i + 1]):
            items.append((cells[i - 1], int(m.group(1)), _price(PRICE_RE.match(cells[i + 1]))))
    if not items:  # cała pozycja w jednej linii
        for line in text.replace("\r", "").split("\n"):
            m = INLINE_RE.match(line.strip(" |\t"))
            if m:
                items.append((m.group(1).strip(" |\t"), int(m.group(2)), _price(m, 3)))
    return items


def parse_header(text):
    header = {"date": None, "supplier": "", "note": "", "total": None}
    m = re.search(r"(?:zamówieni\w*|order)\s*(?:nr\.?|no\.?|number)?\s*#?\s*(\d{3,})", text, re.I)
    if m:
        header["note"] = _("Zamówienie #{n} (z maila)", n=m.group(1))
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text) or re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if m:
        header["date"] = m.group(1) if len(m.groups()) == 1 else f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"https?://(?:www\.)?([\w-]+(?:\.[\w-]+)*\.(?:pl|com|eu|net|de|uk|shop|store))", text, re.I) \
        or re.search(r"@([\w-]+(?:\.[\w-]+)*\.(?:pl|com|eu|net|de|uk|shop|store))", text)
    if m:
        header["supplier"] = m.group(1).lower()
    m = re.search(rf"(?<!\w)(?:Razem|Total):?\s*\|?\s*(?:{CURRENCY}\s*({AMOUNT})|({AMOUNT})\s*{CURRENCY})", text, re.I)
    if m:
        header["total"] = _price(m)
    return header


def split_product(raw, brands=()):
    """'AROMAT SPOŻYWCZY … INAWERA ON ICE - KAKTUS LIMONKA - 100ml' -> ('On Ice - Kaktus Limonka', 'Inawera', 100)."""
    name, size = raw.strip(), None
    m = SIZE_RE.search(name)
    if m:
        size = _num(m.group(1)) * (1000 if m.group(2).lower() == "l" else 1)
        name = name[:m.start()].strip(" -–")
    name = SIZE_RE.sub("", name).strip(" -–")  # rozmiar powtórzony w nazwie, np. „TROPICAL MOON 10 ML”
    name = PREFIX_RE.sub("", name).strip(" -–")  # „Aromat Spożywczy - Limonka” -> „Limonka”
    manufacturer = ""
    for brand in sorted(brands, key=len, reverse=True):  # dłuższe najpierw: „Atmos Lab” przed „Atmos”
        if fold(name).startswith(fold(brand) + " "):
            manufacturer, name = brand, name[len(brand):].strip(" -–")
            break
    if name.isupper():
        name = " ".join(w if w in ("&", "-") else w.capitalize() for w in name.split())
    return name, manufacturer, size


def match(conn, name, manufacturer, raw):
    """Zwraca (składnik albo None, sposób): alias, exact, fuzzy, new."""
    alias = conn.execute("SELECT i.* FROM ingredient_aliases a JOIN ingredients i ON i.id = a.ingredient_id"
                         " WHERE a.alias = ?", (fold(raw),)).fetchone()
    if alias:
        return alias, "alias"
    candidates = conn.execute("SELECT * FROM ingredients WHERE category IN ('aroma', 'other', 'nicotine', 'pg', 'vg')"
                              " AND (? = '' OR manufacturer = ?)", (manufacturer, manufacturer)).fetchall()
    key = fold(name)
    for ing in candidates:
        if fold(ing["name"]) == key:
            return ing, "exact"
    # Bez przedrostka linii („Mix - Cloud Lover” = „Cloud lover”) – porównujemy same nazwy smaku.
    short = key.split(" - ")[-1]
    exact_short = [ing for ing in candidates if fold(ing["name"]).split(" - ")[-1] == short]
    if len(exact_short) == 1:
        return exact_short[0], "exact"
    best, score = None, 0.0
    for ing in candidates:
        for variant in (fold(ing["name"]), fold(ing["name"]).split(" - ")[-1]):
            ratio = max(difflib.SequenceMatcher(None, key, variant).ratio(),
                        difflib.SequenceMatcher(None, short, variant).ratio())
            if ratio > score:
                best, score = ing, ratio
    if best is not None and score >= FUZZY_MIN:
        return best, "fuzzy"
    return None, "new"


def recognize(conn, text):
    header = parse_header(text)
    brands = {r[0] for r in conn.execute("SELECT DISTINCT manufacturer FROM ingredients WHERE manufacturer <> ''")}
    brands |= COMMON_BRANDS
    lines = []
    for raw, count, line_total in parse_items(text):
        name, manufacturer, size = split_product(raw, brands)
        ing, how = match(conn, name, manufacturer, raw)
        lines.append({
            "source_name": raw,
            "category": ing["category"] if ing else "aroma",
            "name": ing["name"] if ing else name,
            "manufacturer": ing["manufacturer"] if ing else manufacturer,
            "pack_size": size,
            "pack_count": count,
            # W tabelach zamówień cena jest za całą pozycję – dzielimy na sztuki.
            "pack_price": round(line_total / count, 2) if count else line_total,
            "match": how,
        })
    header["lines"] = lines
    header["items_total"] = round(sum(l["pack_price"] * l["pack_count"] for l in lines), 2)
    return header


def remember(conn, source_name, ingredient_id):
    if source_name.strip():
        conn.execute("INSERT OR REPLACE INTO ingredient_aliases (alias, ingredient_id) VALUES (?, ?)",
                     (fold(source_name), ingredient_id))
