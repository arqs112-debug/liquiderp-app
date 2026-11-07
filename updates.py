"""Sprawdzanie aktualizacji w GitHub Releases, pobieranie instalatora i jego uruchomienie.

Pytamy tylko o ostatnie wydanie publicznego repozytorium (bez żadnych danych użytkownika).
Instalator pobieramy wyłącznie z adresu wydania tego repozytorium, sprawdzamy rozmiar
i zapisujemy w folderze tymczasowym. W zainstalowanym programie instalator działa w tle (bez okien),
program sam się zamyka, a instalator po podmianie plików uruchamia nową wersję (parametr /restart=1).
"""
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.request

from i18n import _
from version import REPO, __version__

API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
TIMEOUT = 15
CHUNK = 64 * 1024

_lock = threading.Lock()
_latest = None   # ostatnio sprawdzone wydanie (instalator pobieramy tylko z niego)
_state = {"status": "idle", "done": 0, "total": 0, "path": None, "error": None, "version": None}


def parse_version(text):
    """'v1.10.2' → (1, 10, 2); nieczytelne → None."""
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?", (text or "").strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def _ssl_context():
    """Certyfikaty z dołączonego certifi i z magazynu Windows (Windows dociąga główne certyfikaty
    dopiero na żądanie, więc na części komputerów sam magazyn nie wystarcza)."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    ctx.load_default_certs()
    return ctx


def _open(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"LiquidERP/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context())


def _installer_asset(release):
    for asset in release.get("assets") or []:
        name, url = asset.get("name", ""), asset.get("browser_download_url", "")
        if name.lower().endswith(".exe") and "setup" in name.lower() and url.startswith(DOWNLOAD_PREFIX):
            return {"name": os.path.basename(name), "url": url, "size": int(asset.get("size") or 0)}
    return None


def check():
    """Najnowsze wydanie i czy jest nowsze od tej wersji; przy braku sieci – komunikat w polu error."""
    global _latest
    try:
        with _open(API_URL) as r:
            release = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # brak sieci, limit zapytań GitHuba, zła odpowiedź
        logging.warning("Nie udało się sprawdzić aktualizacji: %s", exc)
        return {"current": __version__, "error": _("Nie udało się połączyć z GitHubem. Sprawdź internet i spróbuj później.")}
    latest = parse_version(release.get("tag_name"))
    current = parse_version(__version__)
    newer = bool(latest and current and latest > current)
    asset = _installer_asset(release)
    result = {"current": __version__, "latest": (release.get("tag_name") or "").lstrip("v"), "newer": newer,
              "page": release.get("html_url") or f"https://github.com/{REPO}/releases/latest",
              "notes": (release.get("body") or "").strip()[:4000], "asset": asset}
    with _lock:
        _latest = result if newer and asset else None
    return result


def state():
    with _lock:
        return dict(_state)


def start_download():
    """Pobiera instalator ostatnio sprawdzonego, nowszego wydania (w tle)."""
    with _lock:
        if _latest is None:
            return {"error": _("Najpierw sprawdź, czy jest nowsza wersja.")}
        if _state["status"] == "downloading":
            return dict(_state)
        asset, version = _latest["asset"], _latest["latest"]
        _state.update(status="downloading", done=0, total=asset["size"], path=None, error=None, version=version)
    threading.Thread(target=_download, args=(asset,), daemon=True).start()
    return state()


def _download(asset):
    folder = os.path.join(tempfile.gettempdir(), "LiquidERP-aktualizacja")
    path = os.path.join(folder, asset["name"])
    try:
        os.makedirs(folder, exist_ok=True)
        part = path + ".part"
        with _open(asset["url"]) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                with _lock:
                    _state["done"] += len(chunk)
        size = os.path.getsize(part)
        if asset["size"] and size != asset["size"]:
            raise OSError(f"rozmiar {size} zamiast {asset['size']}")
        os.replace(part, path)
        with _lock:
            _state.update(status="done", path=path)
    except Exception as exc:
        logging.warning("Nie udało się pobrać aktualizacji: %s", exc)
        with _lock:
            _state.update(status="error", error=_("Pobieranie nie powiodło się. Spróbuj ponownie albo pobierz instalator ze strony wydania."))


def installer_args(path, frozen=None, app_dir=None):
    """Polecenie instalatora. W zainstalowanym programie: cicho, do tego samego folderu i w tym samym trybie
    (dla bieżącego użytkownika albo dla wszystkich – wtedy Windows zapyta o uprawnienia), z ponownym uruchomieniem."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:  # wersja źródłowa: zwykły instalator z oknami (nie instalujemy po cichu obok kodu)
        return [path]
    app_dir = app_dir or os.path.dirname(sys.executable)
    log = os.path.join(os.path.dirname(path), "instalacja.log")
    return [path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/restart=1", f"/LOG={log}",
            "/CURRENTUSER" if _writable(app_dir) else "/ALLUSERS"]


def _writable(folder):
    """Czy bieżący użytkownik może pisać w folderze programu (instalacja „dla mnie” vs w Program Files)."""
    try:
        fd, test = tempfile.mkstemp(dir=folder)
        os.close(fd)
        os.remove(test)
        return True
    except OSError:
        return False


def install():
    """Uruchamia pobrany instalator (w tle) i zamyka program, żeby instalator mógł podmienić pliki."""
    with _lock:
        path = _state["path"] if _state["status"] == "done" else None
    if not path or not os.path.exists(path):
        return {"error": _("Instalator nie jest jeszcze pobrany.")}
    args = installer_args(path)
    _launch(args)
    threading.Timer(2.0, _close_app).start()
    return {"ok": True, "silent": len(args) > 1}


def _launch(args):
    subprocess.Popen(args, close_fds=True)


def _close_app():
    try:
        import webview
        for window in list(webview.windows):
            window.destroy()
    except Exception:
        logging.exception("Nie udało się zamknąć okna przed instalacją")
