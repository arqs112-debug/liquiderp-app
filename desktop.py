"""LiquidERP jako aplikacja okienkowa: serwer w tle + własne okno (WebView2), bez konsoli.

Punkt wejścia LiquidERP.exe (PyInstaller); w wersji źródłowej: pythonw.exe desktop.py.
Zamknięcie okna kończy program. Dane i log (liquiderp.log) są w folderze %AppData%/LiquidERP.
"""
import ctypes
import json
import logging
import os
import socket
import sys
import threading
import urllib.request

import db
import paths

ICON = paths.ICON
LOG = paths.LOG_PATH
WINDOW_STATE = paths.WINDOW_STATE
PORT = int(os.environ.get("LIQUIDERP_PORT", 5077))
TITLE = "LiquidERP"


def setup_logging():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(filename=LOG, level=logging.WARNING, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # bez wpisu za każde kliknięcie
    if sys.stdout is None:  # pythonw nie ma konsoli
        sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/magazyn", timeout=1) as r:
            return b"LiquidERP" in r.read(4000)
    except OSError:
        return False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port):
    from werkzeug.serving import make_server
    import app
    server = make_server("127.0.0.1", port, app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def own_window():
    """Uchwyt okna LiquidERP tego procesu (druga kopia programu ma okno o tym samym tytule)."""
    user32, found = ctypes.windll.user32, []
    pid = os.getpid()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def check(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        title = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, title, 64)
        if owner.value == pid and title.value == TITLE and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(check, 0)
    return found[0] if found else None


def set_window_icon():
    """Ikona okna i paska zadań (pythonw ma własną, więc podmieniamy ją po otwarciu okna)."""
    user32 = ctypes.windll.user32
    hwnd = own_window()
    if not hwnd or not os.path.exists(ICON):
        return
    for size, which in ((16, 0), (32, 1)):  # ICON_SMALL, ICON_BIG
        icon = user32.LoadImageW(None, ICON, 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        user32.SendMessageW(hwnd, 0x80, which, icon)  # WM_SETICON


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint), ("flags", ctypes.c_uint), ("showCmd", ctypes.c_uint),
                ("ptMinPosition", ctypes.c_long * 2), ("ptMaxPosition", ctypes.c_long * 2),
                ("rcNormalPosition", ctypes.c_long * 4)]


def load_window_state():
    """Stan okna z poprzedniego zamknięcia; domyślnie zmaksymalizowane."""
    state = {"maximized": True, "width": 1400, "height": 900, "x": None, "y": None}
    try:
        with open(WINDOW_STATE, encoding="utf-8") as f:
            state.update(json.load(f))
    except (OSError, ValueError):
        return state
    # Położenie tylko, jeśli mieści się na obecnych monitorach (np. po odłączeniu drugiego ekranu).
    m = ctypes.windll.user32.GetSystemMetrics
    left, top, width, height = m(76), m(77), m(78), m(79)  # wirtualny ekran: wszystkie monitory
    if state["x"] is None or not (left <= state["x"] < left + width - 100 and top <= state["y"] < top + height - 100):
        state["x"] = state["y"] = None
    return state


def save_window_state():
    """Zapamiętuje, czy okno było zmaksymalizowane, oraz jego zwykły rozmiar i położenie."""
    user32 = ctypes.windll.user32
    hwnd = own_window()
    if not hwnd:
        return
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if not user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        return
    scale = (user32.GetDpiForWindow(hwnd) or 96) / 96
    l, t, r, b = wp.rcNormalPosition
    state = {"maximized": wp.showCmd == 3,  # SW_SHOWMAXIMIZED
             "x": int(l / scale), "y": int(t / scale), "width": int((r - l) / scale), "height": int((b - t) / scale)}
    try:
        with open(WINDOW_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        logging.warning("Nie udało się zapisać stanu okna", exc_info=True)


def main():
    setup_logging()
    if sys.platform == "win32":
        # Własna grupa na pasku zadań zamiast „Python”.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LiquidERP.App")

    import webview
    webview.settings["ALLOW_DOWNLOADS"] = True  # pobieranie kopii zapasowych

    server = None
    if already_running(PORT):
        port = PORT  # druga kopia: tylko okno do działającego programu
    else:
        db.init_db()
        import backup
        import phone_export
        backup.daily()
        if phone_export.enabled():
            phone_export.schedule(2)
        port = PORT
        try:
            server = start_server(port)
        except OSError:
            port = free_port()
            server = start_server(port)

    state = load_window_state()
    window = webview.create_window(TITLE, f"http://127.0.0.1:{port}/", width=max(state["width"], 1000),
                                   height=max(state["height"], 650), x=state["x"], y=state["y"],
                                   maximized=state["maximized"], min_size=(1000, 650), text_select=True)
    window.events.shown += set_window_icon
    window.events.closing += save_window_state
    webview.start(private_mode=False, storage_path=paths.WEBVIEW_DIR)
    if server:
        server.shutdown()
        import phone_export
        phone_export.flush()  # PDF na telefon z ostatnim stanem (gdy włączony)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("LiquidERP nie uruchomił się")
        from i18n import _
        ctypes.windll.user32.MessageBoxW(None, _("LiquidERP nie uruchomił się.") + "\n" + _("Szczegóły: {path}", path=LOG), TITLE, 0x10)
        raise
