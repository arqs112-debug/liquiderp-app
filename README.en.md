# LiquidERP

[Polski](README.md) · **English**

A home program for people who mix their own e-liquids: **flavor and base inventory, recipes with live
calculation, and production** that takes ingredients out of stock. Runs on Windows, entirely on your computer –
no account, no cloud, no ads. Free, MIT licensed. The interface is available in **Polish and English**.

## Features

- **Inventory** – flavors, nicotine bases, PG, VG, bottles; stock levels, minimums, weighted average cost,
  adjustments (stocktaking), inventory value.
- **Receipts** – manual, or **“Paste from e-mail”**: paste an order confirmation and the program recognizes
  products, pack sizes, quantities and prices and matches them to your ingredients (it remembers shop names).
- **Recipes** – live calculation in ml and grams (also cumulative for weighing into one bottle), PG/VG with
  ±0.5% arrows, nicotine, cost, shortages; groups, ratings, archive.
- **Production** – “Make e-liquid” with stock validation, bottles, batch cost and undo; steeping (ready date from
  the recipe) and batch rating with tasting notes, plus a “Ready to taste” list on the dashboard.
- **What can I make?** – how much of each recipe your current stock allows, and a production plan whose shortages
  go to the shopping list in one click.
- **Reports** – spending and production by month, purchases by shop, most-made recipes, long-unused flavors.
- **Mixing calculator** – combine ready-made liquids (e-liquid, shortfill, base, nic shot, PG/VG) and see volume,
  nicotine strength and ratio; it can also work out how much base to add for a target strength.
- **Shopping list** – shortages in one click, pack size and count, copy as text, ticked off automatically on receipt.
- **Import from EJuiceCalculator** – ingredients, stock, prices, recipes and history from its XML file.
- Search (`/` or `Ctrl+K`), `Ctrl+S` saves, `Ctrl+F` searches the list, sortable lists, `Esc` returns to the list,
  dark and light theme; flavor opening date with a warning after a year, “Undo last change” on the ingredient card.
- **Settings** (bottom of the menu): language, default recipe parameters, currency, theme, ml/g, number of backups,
  PDF for phone; tabs for backups, data import and program information.
- **Backups** – automatic once a day, manual, and one-click restore.
- **PDF for phone** (optional) – shopping list and stock in a file saved to a folder of your choice
  (e.g. OneDrive or Google Drive), so you have it with you in the shop.

## Installation

1. Download `LiquidERP-Setup-x.y.z.exe` from [Releases](https://github.com/arqs112-debug/liquiderp-app/releases/latest).
2. Run the installer. Windows may show a SmartScreen warning (“Unknown publisher”) – the program has no paid code
   signing certificate; click **More info → Run anyway**.
3. Start LiquidERP from the desktop or Start menu shortcut. On first start a wizard lets you pick the language,
   start from scratch or import EJuiceCalculator data, and set default recipe parameters.

The language follows Windows by default (Polish → Polish, anything else → English) and can be changed at any time
in Settings → General.

Requirements: Windows 10 or 11 (64-bit) with Microsoft Edge WebView2 – built into Windows 11, usually installed
by updates on Windows 10 ([download WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) if the window does not open).

### Where is my data?

In `%AppData%\LiquidERP` (type it into the Explorer address bar; full paths are shown in Settings → About):
the database `liquiderp.db`, backups in `kopie\`, the error log `liquiderp.log`. Uninstalling does **not** delete
your data. To update: Settings › About › **Check for updates** – the program checks GitHub, downloads the update, installs it
in the background and restarts by itself (or install the new version over the old one manually). Your data stays.

## Feedback

Found a bug or have an idea? Click **“Send feedback”** in the program (Tools menu or the icon in the top bar),
describe it and choose “Bug” or “Idea” – your browser opens a prepared issue on GitHub (a free account is enough).
The program adds only its version, language and Windows version; **no inventory data is sent**.
You can also open an issue directly under [Issues](https://github.com/arqs112-debug/liquiderp-app/issues).
Issues in English are welcome.

## For developers

Python 3.10, Flask, SQLite, a [pywebview](https://pywebview.flowrl.com/) window (WebView2), PDF via fpdf2.

```bat
py -3.10 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python desktop.py            :: program window
.venv\Scripts\python app.py                :: or in a browser: http://127.0.0.1:5077
.venv\Scripts\python tests\smoke_test.py   :: tests
.venv\Scripts\python tests\mail_test.py
.venv\Scripts\python tests\i18n_test.py
.venv\Scripts\python tests\update_test.py
build.bat                                  :: dist\LiquidERP + installer (needs Inno Setup 6)
```

Translations: the source language is Polish; texts go through `_("…")` (Python, templates) and `t('…')`
(JavaScript), and English versions live in `translations/en.json`. `python tools/i18n_extract.py` lists
missing and unused entries. `LIQUIDERP_DATA` points to another data folder (e.g. for tests), `LIQUIDERP_PORT`
to another port. The version number is in `version.py`.

## License

MIT – see [LICENSE](LICENSE). The program is provided “as is”; you are responsible for the ratios and safety of
your mixes – double-check the calculations, especially for nicotine.
