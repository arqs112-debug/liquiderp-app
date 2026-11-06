"""Języki interfejsu: polski (język źródłowy) i angielski.

Teksty w kodzie i szablonach są po polsku i przechodzą przez _("…"). Dla angielskiego
szukamy ich w translations/en.json ({"tekst po polsku": "English text"}); brak wpisu = tekst polski.
Parametry wstawiamy po przetłumaczeniu: _("Dodano {n} poz.", n=3).
Język z Ustawień (klucz „language”); pusty = wg języka Windows (polski → pl, inne → en).
"""
import json
import locale
import os

import paths

LANGUAGES = {"pl": "Polski", "en": "English"}
_catalogs = {}


def _catalog(lang):
    if lang not in _catalogs:
        path = os.path.join(paths.RESOURCE_DIR, "translations", f"{lang}.json")
        try:
            with open(path, encoding="utf-8") as f:
                _catalogs[lang] = json.load(f)
        except (OSError, ValueError):
            _catalogs[lang] = {}
    return _catalogs[lang]


def system_language():
    """Język Windows (interfejsu użytkownika); pl dla polskiego, en dla każdego innego."""
    code = ""
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        code = locale.windows_locale.get(lang_id, "")
    except (AttributeError, OSError):
        try:
            code = locale.getlocale()[0] or ""
        except ValueError:
            code = ""
    return "pl" if code.lower().startswith("pl") else "en"


_forced = None  # testy i podgląd: wymuszony język bez zmiany ustawień


def current():
    if _forced:
        return _forced
    try:
        import settings
        lang = settings.get("language")
    except Exception:
        lang = ""
    return lang if lang in LANGUAGES else system_language()


def force(lang):
    global _forced
    _forced = lang


def gettext(text, lang=None, **params):
    lang = lang or current()
    out = text if lang == "pl" else _catalog(lang).get(text, text)
    return out.format(**params) if params else out


_ = gettext


def js_catalog(lang=None):
    """Tłumaczenia dla skryptów w przeglądarce (window.T); dla polskiego pusty słownik."""
    lang = lang or current()
    return {} if lang == "pl" else _catalog(lang)


# --- liczby i kwoty ---

def fmt_num(value, digits=2, lang=None):
    """1 017,52 (pl) albo 1,017.52 (en); zbędne zera po przecinku obcinane."""
    if value is None:
        return ""
    lang = lang or current()
    text = f"{value:,.{digits}f}"
    if digits and "." in text:
        text = text.rstrip("0").rstrip(".")
    if lang == "pl":
        text = text.replace(",", " ").replace(".", ",")
    return text


def fmt_money(value, currency, lang=None):
    if value is None:
        return "–"
    lang = lang or current()
    text = f"{value:,.2f}"
    if lang == "pl":
        text = text.replace(",", " ").replace(".", ",")
    return text + " " + currency


def js_locale(lang=None):
    return "pl-PL" if (lang or current()) == "pl" else "en-US"
