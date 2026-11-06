# LiquidERP

**Polski** · [English](README.en.md)

Domowy program dla osób, które same robią liquidy do e-papierosów: **magazyn aromatów i baz, przepisy
z wyliczeniem na żywo i produkcja** z odejmowaniem składników ze stanów. Działa na Windows, w całości na Twoim
komputerze – bez konta, bez chmury, bez reklam. Darmowy, na licencji MIT. Interfejs po polsku albo po angielsku.

## Co potrafi

- **Magazyn** – aromaty, bazy nikotynowe, PG, VG, butelki; stany, minimalne ilości, średnia ważona cena,
  korekty (inwentaryzacja), wartość magazynu.
- **Przyjęcia** – ręcznie albo **„Wklej z maila”**: wklejasz treść potwierdzenia zamówienia ze sklepu,
  program rozpoznaje pozycje, pojemności, sztuki i ceny i dopasowuje je do składników (zapamiętuje nazwy ze sklepu).
- **Przepisy** – wyliczenie na żywo w ml i gramach (także narastająco dla ważenia do jednej butelki), PG/VG
  ze strzałkami ±0,5%, nikotyna, koszt, braki na magazynie; grupy, oceny, archiwum.
- **Produkcja** – „Zrób liquid” z walidacją stanów, butelkami, kosztem partii i możliwością cofnięcia.
- **Lista zakupów** – braki jednym kliknięciem, pojemność i liczba sztuk, kopiowanie jako tekst,
  automatyczne odhaczanie przy przyjęciu.
- **Kalkulator mieszania** – łączysz gotowe płyny (liquid, shortfill, bazę, shot, PG/VG) i widzisz objętość, moc
  nikotyny i proporcję; dobiera też ilość bazy do docelowej mocy (np. ile ml bazy 18 mg do 50 ml shortfilla na 3 mg).
- **Import z EJuiceCalculatora** – składniki, stany, ceny, przepisy i historia z pliku XML.
- Wyszukiwarka (klawisz `/` lub `Ctrl+K`), sortowanie list, `Esc` wraca do listy, ciemny i jasny motyw.
- **Ustawienia** (na dole menu): język (polski / English), domyślne parametry przepisu, waluta, motyw, ml/g, liczba kopii, PDF na telefon;
  w zakładkach także kopie zapasowe, import danych i informacje o programie.
- **Kopie zapasowe** – automatycznie raz dziennie, ręcznie i przywracanie jednym kliknięciem.
- **PDF na telefon** (opcjonalnie) – lista zakupów i stany w pliku, który program zapisuje do wybranego folderu
  (np. OneDrive albo Dysk Google), żeby mieć go w sklepie pod ręką.

## Instalacja

1. Pobierz `LiquidERP-Setup-x.y.z.exe` z zakładki [Releases](https://github.com/arqs112-debug/liquiderp-app/releases/latest).
2. Uruchom instalator. Windows może pokazać ostrzeżenie SmartScreen („Nieznany wydawca”) – program nie ma płatnego
   podpisu cyfrowego; kliknij **Więcej informacji → Uruchom mimo to**.
3. Uruchom LiquidERP ze skrótu na pulpicie albo z menu Start. Przy pierwszym uruchomieniu kreator zapyta,
   czy zaczynasz od zera, czy importujesz dane z EJuiceCalculatora, i ustawi domyślne parametry przepisów.

Wymagania: Windows 10 lub 11 (64-bit) z Microsoft Edge WebView2 – w Windows 11 jest wbudowany, w Windows 10
zwykle instaluje się z aktualizacjami ([pobierz WebView2](https://developer.microsoft.com/microsoft-edge/webview2/), jeśli okno się nie otwiera).

### Gdzie są moje dane?

W folderze `%AppData%\LiquidERP` (pełne ścieżki: Ustawienia › Informacje) (wpisz to w pasku adresu Eksploratora): baza `liquiderp.db`,
kopie zapasowe w `kopie\`, dziennik błędów `liquiderp.log`. Odinstalowanie programu **nie usuwa** danych.
Aktualizacja = zainstalowanie nowej wersji na starą – dane zostają.

## Zgłaszanie uwag

Znalazłeś błąd albo masz pomysł? W programie kliknij **„Zgłoś uwagę”** (w menu Narzędzia albo ikonka w górnym
pasku), opisz sprawę i wybierz „Błąd” lub „Pomysł” – otworzy się przeglądarka z gotowym zgłoszeniem na GitHubie
(wystarczy darmowe konto). Program dopisuje tylko swoją wersję i wersję Windows, **nie wysyła żadnych danych z magazynu**.
Możesz też od razu założyć zgłoszenie w zakładce [Issues](https://github.com/arqs112-debug/liquiderp-app/issues).

## Dla programistów

Python 3.10, Flask, SQLite, okno [pywebview](https://pywebview.flowrl.com/) (WebView2), PDF: fpdf2.

```bat
py -3.10 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python desktop.py            :: okno programu
.venv\Scripts\python app.py                :: albo w przeglądarce: http://127.0.0.1:5077
.venv\Scripts\python tests\smoke_test.py   :: testy
.venv\Scripts\python tests\mail_test.py
.venv\Scripts\python tests\i18n_test.py   :: wersja angielska
build.bat                                  :: dist\LiquidERP + instalator (wymaga Inno Setup 6)
```

Zmienna `LIQUIDERP_DATA` wskazuje inny folder danych (np. do testów), `LIQUIDERP_PORT` – inny port.
Numer wersji jest w `version.py`. Tłumaczenia: teksty po polsku przechodzą przez `_("…")` / `t('…')`,
angielskie są w `translations/en.json`; `python tools/i18n_extract.py` pokazuje braki.

Zasady liczenia: płyny w ml, butelki w sztukach; przyjęcie = opakowanie × sztuki × cena za opakowanie;
koszt jednostkowy to średnia ważona krocząca (rozchody i korekty jej nie zmieniają).

## Licencja

MIT – zob. plik [LICENSE](LICENSE). Program jest dostarczany „tak jak jest”; za proporcje i bezpieczeństwo
mieszanek odpowiadasz sam – sprawdzaj wyliczenia, szczególnie przy nikotynie.
