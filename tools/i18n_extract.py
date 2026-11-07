"""Lista tekstów do tłumaczenia i braki w translations/en.json.

Użycie:  python tools/i18n_extract.py          – wypisuje brakujące i zbędne wpisy
         python tools/i18n_extract.py --json   – brakujące jako JSON (do uzupełnienia)
"""
import ast
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TPL = re.compile(r"""\b_\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")
JS = re.compile(r"""\bt\(\s*'((?:[^'\\]|\\.)*)'""")


def unescape(s):
    return s.replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n")


def from_templates():
    keys = set()
    for path in glob.glob(os.path.join(ROOT, "templates", "*.html")):
        src = open(path, encoding="utf-8").read()
        for m in TPL.finditer(src):
            keys.add(unescape(m.group(1) if m.group(1) is not None else m.group(2)))
        for m in JS.finditer(src):
            keys.add(unescape(m.group(1)))
    return keys


def from_python():
    keys = set()
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.add(arg.value)
                elif isinstance(arg, ast.BinOp):  # sklejone literały "a" " b" są już jednym Constant
                    pass
    return keys


def dynamic():
    """Teksty tłumaczone przez zmienną: menu, zakładki, kategorie, rodzaje kopii, sekcje PDF."""
    import backup
    import db
    import phone_export
    keys = set()
    for cat in db.CATEGORIES.values():
        keys |= {cat["label"], cat["single"], cat["unit"]}
    keys |= set(backup.REASONS.values())
    keys |= {label for _, label in phone_export.SECTIONS}
    keys.add(phone_export.FILE_NAME)
    import import_ejc
    keys |= {import_ejc.OPENING_NOTE, "import z EJuiceCalculatora"}  # notatki z importu tłumaczone przy wyświetlaniu
    base = open(os.path.join(ROOT, "templates", "base.html"), encoding="utf-8").read()
    nav = base[base.index("{% set nav = ["):base.index("] %}", base.index("{% set nav = ["))]
    keys |= set(re.findall(r"\('([^']+)', \[", nav))                     # grupy
    keys |= set(re.findall(r"\('\w+', '([^']+)', 'i-", nav))             # pozycje
    tabs = open(os.path.join(ROOT, "templates", "settings_tabs.html"), encoding="utf-8").read()
    keys |= set(re.findall(r"\('\w+', '([^']+)', 'i-", tabs))
    return keys


def all_keys():
    return {k for k in from_templates() | from_python() | dynamic() if k.strip() and k not in ("ml", "PG", "VG")}


if __name__ == "__main__":
    keys = all_keys()
    en = json.load(open(os.path.join(ROOT, "translations", "en.json"), encoding="utf-8"))
    missing = sorted(k for k in keys if k not in en)
    extra = sorted(k for k in en if k not in keys)
    if "--json" in sys.argv:
        print(json.dumps({k: "" for k in missing}, ensure_ascii=False, indent=1))
    else:
        print(f"teksty: {len(keys)}, brakuje: {len(missing)}, zbędne: {len(extra)}")
        for k in missing:
            print("  BRAK  ", repr(k))
        for k in extra:
            print("  ZBĘDNE", repr(k))
