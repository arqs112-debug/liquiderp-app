"""PDF „na telefon”: lista zakupów i stany aktywnych składników, zapisywany do wybranego folderu.

Domyślnie wyłączony – włącza się go w Ustawieniach razem z wyborem folderu (np. OneDrive albo Dysk Google
zsynchronizowany z telefonem).

Strony mają format wąskiego ekranu (nie A4), żeby na telefonie czytało się bez powiększania.
Plik jest nadpisywany po zmianach w programie (z opóźnieniem), przy starcie i przy zamknięciu.
"""
import logging
import os
import tempfile
import threading
from datetime import datetime

from fpdf import FPDF
from fpdf.fonts import FontFace

import db
import i18n
from i18n import _

FILE_NAME = "LiquidERP na telefon.pdf"
PAGE = (90, 170)          # mm – proporcje ekranu telefonu
MARGIN = 5
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
DEBOUNCE_S = 5

logging.getLogger("fontTools").setLevel(logging.ERROR)  # ostrzeżenia o przycinaniu czcionek są nieistotne

GREY, RED, ACCENT, MUTED = (150, 150, 150), (200, 50, 40), (95, 158, 47), (110, 115, 120)
SECTIONS = [("nicotine", "Bazy nikotynowe"), ("pg", "PG"), ("vg", "VG"), ("other", "Inne"), ("bottle", "Butelki")]


def target_path():
    """Plik w folderze z ustawień; None, gdy folderu nie wybrano albo nie istnieje."""
    import settings
    folder = settings.get("phone_pdf_dir").strip()
    if not folder or not os.path.isdir(folder):
        return None
    return os.path.join(folder, _(FILE_NAME))


def _num(value, digits=1):
    return i18n.fmt_num(value, digits)


def _money(value):
    import settings
    return i18n.fmt_money(value, settings.get("currency"))


class PhonePDF(FPDF):
    def __init__(self, stamp):
        super().__init__(unit="mm", format=PAGE)
        self.stamp = stamp
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, MARGIN + 4)
        self.add_font("Segoe", "", os.path.join(FONT_DIR, "segoeui.ttf"))
        self.add_font("Segoe", "B", os.path.join(FONT_DIR, "segoeuib.ttf"))
        self.set_font("Segoe", size=9)

    def footer(self):
        self.set_y(-MARGIN - 3)
        self.set_font("Segoe", size=6)
        self.set_text_color(*GREY)
        self.cell(0, 3, _("LiquidERP · {stamp} · str. {page}/{total}", stamp=self.stamp, page=self.page_no(), total="{nb}"), align="C")

    def heading(self, text, link=None):
        if self.get_y() > self.h - 30:
            self.add_page()
        self.ln(2)
        self.set_font("Segoe", "B", 11)
        self.set_text_color(*ACCENT)
        if link is not None:
            self.set_link(link, y=self.get_y())
        self.start_section(text)
        self.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*ACCENT)
        self.line(MARGIN, self.get_y(), self.w - MARGIN, self.get_y())
        self.ln(1)
        self.set_text_color(0, 0, 0)

    def subheading(self, text):
        if self.get_y() > self.h - 22:
            self.add_page()
        self.ln(1)
        self.set_font("Segoe", "B", 9)
        self.set_text_color(*MUTED)
        self.cell(0, 5, text.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)

    def rows(self, rows):
        """rows: [(nazwa, podpis, wartość, kolor)] – nazwa zawija się, wartość wyrównana do prawej."""
        self.set_font("Segoe", size=9)
        self.set_draw_color(215, 218, 222)
        with self.table(col_widths=(62, 18), text_align=("LEFT", "RIGHT"), borders_layout="HORIZONTAL_LINES",
                        first_row_as_headings=False, line_height=4.6, padding=(0.8, 0.5)) as table:
            for name, sub, value, color in rows:
                row = table.row()
                style = FontFace(color=color) if color else None
                row.cell(name + (f"\n{sub}" if sub else ""), style=style)
                row.cell(value, style=FontFace(color=color, emphasis="BOLD") if color else FontFace(emphasis="BOLD"))


def build(conn):
    from app import ingredient_rows  # te same wyliczenia stanów co w programie
    rows = ingredient_rows(conn)       # tylko aktywne
    stamp = datetime.now().strftime("%d.%m.%Y %H:%M" if i18n.current() == "pl" else "%Y-%m-%d %H:%M")
    pdf = PhonePDF(stamp)
    pdf.alias_nb_pages()
    pdf.set_title(_("LiquidERP – stany i lista zakupów"))
    pdf.add_page()

    pdf.set_font("Segoe", "B", 15)
    pdf.cell(0, 8, "LiquidERP", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Segoe", size=8)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 4, _("Stan na {stamp}", stamp=stamp), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    shopping = conn.execute(
        "SELECT s.*, i.name AS ing_name, i.manufacturer, i.category FROM shopping_list s"
        " LEFT JOIN ingredients i ON i.id = s.ingredient_id WHERE s.done_at IS NULL"
        " ORDER BY i.manufacturer, lower(COALESCE(i.name, s.name))").fetchall()
    aromas = [r for r in rows if r["category"] == "aroma"]
    no_man = _("bez producenta")
    shop_title = _("Lista zakupów")
    sections = [(cat, _(label)) for cat, label in SECTIONS]
    manufacturers = sorted({r["manufacturer"] or no_man for r in aromas}, key=str.lower)

    # Spis treści z odnośnikami – na telefonie szybciej niż przewijanie.
    links = {}
    entries = [(shop_title, len(shopping), _("poz.")), *[(m, sum(1 for r in aromas if (r["manufacturer"] or no_man) == m), "")
                                                           for m in manufacturers],
               *[(label, sum(1 for r in rows if r["category"] == cat), "") for cat, label in sections
                 if any(r["category"] == cat for r in rows)]]
    pdf.ln(2)
    pdf.set_font("Segoe", size=10)
    for title, count, unit in entries:
        links[title] = pdf.add_link()
        pdf.set_text_color(*ACCENT)
        label = _("Aromaty {m}", m=title) if title in manufacturers else title
        pdf.cell(65, 6.5, label, link=links[title])
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 6.5, f"{count} {unit}".strip(), align="R", new_x="LMARGIN", new_y="NEXT")
    low = [r for r in rows if r["low"]]
    if low:
        pdf.ln(1)
        pdf.set_text_color(*RED)
        pdf.multi_cell(0, 4.5, _("Poniżej minimum: {names}", names=", ".join(r["name"] for r in low)))
    pdf.set_text_color(0, 0, 0)

    # 1. Lista zakupów
    pdf.heading(shop_title, links[shop_title])
    if shopping:
        items = []
        for s in shopping:
            unit = _(db.CATEGORIES[s["category"]]["unit"]) if s["category"] else ""
            pack = f"{_num(s['pack_size'])} {unit} × {s['pack_count']}" if s["pack_size"] else f"× {s['pack_count']}"
            items.append((s["ing_name"] or s["name"], s["manufacturer"] or "", pack, None))
        pdf.rows(items)
    else:
        pdf.set_font("Segoe", size=9)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 6, _("Lista jest pusta."), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    def stock_rows(items):
        out = []
        for r in sorted(items, key=lambda r: r["name"].lower()):
            color = RED if r["low"] or r["qty"] < 0 else (GREY if r["qty"] <= 0 else None)
            note = _("min. {x} {unit}", x=_num(r["min_stock"]), unit=r["unit"]) if r["low"] else ""
            out.append((r["name"], note, f"{_num(r['qty'])} {r['unit']}", color))
        return out

    # 2. Aromaty wg producenta
    for m in manufacturers:
        pdf.heading(_("Aromaty {m}", m=m), links[m])
        pdf.rows(stock_rows(r for r in aromas if (r["manufacturer"] or no_man) == m))

    # 3. Pozostałe kategorie
    for cat, label in sections:
        items = [r for r in rows if r["category"] == cat]
        if items:
            pdf.heading(label, links[label])
            out = []
            for name, sub, value, color in stock_rows(items):
                man = next(r["manufacturer"] for r in items if r["name"] == name)
                out.append((name, " · ".join(x for x in (man, sub) if x), value, color))
            pdf.rows(out)
    return bytes(pdf.output())


def export(path=None):
    """Zapisuje PDF atomowo (plik tymczasowy + podmiana), żeby synchronizacja nie wysłała połowy pliku."""
    path = path or target_path()
    if not path:
        return None
    try:
        with db.connect() as conn:
            data = build(conn)
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(path))
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return path
    except Exception:
        logging.exception("Nie udało się zapisać PDF na telefon")
        return None


_timer = None
_lock = threading.Lock()


def enabled():
    import settings
    if os.environ.get("LIQUIDERP_NO_PHONE_PDF"):
        return False
    try:
        return settings.get("phone_pdf_enabled") == "1" and target_path() is not None
    except Exception:
        return False


def schedule(delay=DEBOUNCE_S):
    """Odświeża PDF kilka sekund po ostatniej zmianie (seria kliknięć = jeden zapis)."""
    global _timer
    if not enabled():
        return
    with _lock:
        if _timer:
            _timer.cancel()
        _timer = threading.Timer(delay, export)
        _timer.daemon = True
        _timer.start()


def flush():
    """Przy zamykaniu programu: zapis od razu, bez czekania."""
    global _timer
    with _lock:
        if _timer:
            _timer.cancel()
            _timer = None
    return export() if enabled() else None
