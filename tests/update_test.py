"""Test sprawdzania i pobierania aktualizacji bez sieci (GitHub podstawiony): python tests/update_test.py"""
import io
import json
import os
import sys
import tempfile
import time

os.environ["LIQUIDERP_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import i18n
i18n.force("pl")
db.init_db()
with db.connect() as conn:
    import settings
    settings.save(conn, {"setup_done": "1"})
import app as m
import updates
from version import REPO, __version__

m.app.testing = True
c = m.app.test_client()
PAYLOAD = b"MZ" + b"x" * 300_000          # „instalator”
requests = []


def release(tag, size=len(PAYLOAD), url=None, name=None):
    name = name or f"LiquidERP-Setup-{tag.lstrip('v')}.exe"
    return {"tag_name": tag, "html_url": f"https://github.com/{REPO}/releases/tag/{tag}", "body": "- nowość A\n- nowość B",
            "assets": [{"name": name, "size": size,
                        "browser_download_url": url or f"https://github.com/{REPO}/releases/download/{tag}/{name}"}]}


current_release = {}


def fake_open(url):
    requests.append(url)
    if url == updates.API_URL:
        if current_release.get("offline"):
            raise OSError("brak sieci")
        return io.BytesIO(json.dumps(current_release).encode())
    assert url.startswith(updates.DOWNLOAD_PREFIX), url  # nic spoza wydań tego repozytorium
    return io.BytesIO(current_release.get("_payload", PAYLOAD))


updates._open = fake_open
major, minor, patch = updates.parse_version(__version__)

# porównanie wersji
assert updates.parse_version("v1.10.0") > updates.parse_version("1.9.3") and updates.parse_version("bzdura") is None

# brak sieci
current_release = {"offline": True}
j = c.post("/api/aktualizacje/sprawdz").get_json()
assert "Nie udało się połączyć" in j["error"], j

# ta sama wersja → nic do pobrania
current_release = release(f"v{__version__}")
j = c.post("/api/aktualizacje/sprawdz").get_json()
assert j["newer"] is False and j["current"] == __version__, j
assert "Najpierw sprawdź" in c.post("/api/aktualizacje/pobierz").get_json()["error"]

# starsza wersja na GitHubie też nie jest „nowsza”
current_release = release("v0.9.0")
assert c.post("/api/aktualizacje/sprawdz").get_json()["newer"] is False

# instalator spoza wydań repozytorium jest ignorowany
newer_tag = f"v{major}.{minor + 1}.0"
current_release = release(newer_tag, url="https://example.com/evil.exe")
j = c.post("/api/aktualizacje/sprawdz").get_json()
assert j["newer"] and j["asset"] is None, j
assert "Najpierw sprawdź" in c.post("/api/aktualizacje/pobierz").get_json()["error"]

# nowsza wersja → pobieranie z kontrolą rozmiaru → uruchomienie instalatora
current_release = release(newer_tag)
j = c.post("/api/aktualizacje/sprawdz").get_json()
assert j["newer"] and j["latest"] == newer_tag[1:] and j["asset"]["size"] == len(PAYLOAD) and "nowość A" in j["notes"], j
assert "nie jest jeszcze pobrany" in c.post("/api/aktualizacje/zainstaluj").get_json()["error"]
s = c.post("/api/aktualizacje/pobierz").get_json()
for _ in range(50):
    s = c.get("/api/aktualizacje/stan").get_json()
    if s["status"] != "downloading":
        break
    time.sleep(0.1)
assert s["status"] == "done" and s["done"] == len(PAYLOAD) and s["version"] == newer_tag[1:], s
assert open(s["path"], "rb").read() == PAYLOAD and not os.path.exists(s["path"] + ".part")
launched = []
updates._launch = lambda args: launched.append(args)
updates._close_app = lambda: None
assert c.post("/api/aktualizacje/zainstaluj").get_json() == {"ok": True, "silent": False} and launched == [[s["path"]]]
# w zainstalowanym programie: cicho, z ponownym uruchomieniem, w trybie zgodnym z folderem programu
mine = tempfile.mkdtemp()
args = updates.installer_args(s["path"], frozen=True, app_dir=mine)
assert args[0] == s["path"] and {"/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/restart=1", "/CURRENTUSER"} <= set(args), args
assert any(a.startswith("/LOG=") for a in args)
updates._writable = lambda folder: False
assert "/ALLUSERS" in updates.installer_args(s["path"], frozen=True, app_dir=mine)
print("pobieranie i instalacja OK")

# zły rozmiar pobranego pliku → błąd, bez instalatora
current_release = release(f"v{major}.{minor + 2}.0", size=len(PAYLOAD) + 5)
c.post("/api/aktualizacje/sprawdz")
c.post("/api/aktualizacje/pobierz")
for _ in range(50):
    s = c.get("/api/aktualizacje/stan").get_json()
    if s["status"] != "downloading":
        break
    time.sleep(0.1)
assert s["status"] == "error" and "nie powiodło się" in s["error"], s

# strona Informacje ma przycisk, po angielsku też
page = c.get("/ustawienia/informacje").get_data(as_text=True)
assert "Sprawdź aktualizacje" in page and 'id="updCheck"' in page
i18n.force("en")
assert "Check for updates" in c.get("/ustawienia/informacje").get_data(as_text=True)
current_release = release(f"v{__version__}")
assert c.post("/api/aktualizacje/sprawdz").get_json()["newer"] is False
assert all(u == updates.API_URL or u.startswith(updates.DOWNLOAD_PREFIX) for u in requests), requests
print("aktualizacje OK")
