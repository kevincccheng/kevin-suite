"""Kevin Suite — Windows system tray launcher."""

import os
import sys
import time
import socket
import subprocess
import webbrowser
import threading

import pystray
import requests
from PIL import Image, ImageDraw

# ── Constants ─────────────────────────────────────────────────────
PYTHON    = r"C:\Program Files\Python313\pythonw.exe"
STREAMLIT = r"C:\Users\kevin\AppData\Roaming\Python\Python313\Scripts\streamlit.exe"
APP_DIR   = r"C:\Users\kevin\projects\kevin-suite"
APP_PORT  = 8502
APP_URL   = f"http://localhost:{APP_PORT}"

process = None


# ── Helpers ───────────────────────────────────────────────────────

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def wait_for_server(timeout: int = 30) -> bool:
    for _ in range(timeout * 2):
        try:
            r = requests.get(APP_URL, timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def kill_port(port: int):
    os.system(
        f'for /f "tokens=5" %a in '
        f'(\'netstat -aon ^| find ":{port}"\') '
        f'do taskkill /f /pid %a 2>nul'
    )


def create_icon() -> Image.Image:
    img  = Image.new("RGB", (64, 64), color="#0a1628")
    draw = ImageDraw.Draw(img)
    draw.text((10, 18), "KS", fill="white")
    return img


# ── Streamlit process management ──────────────────────────────────

def start_streamlit():
    global process
    process = subprocess.Popen(
        [
            STREAMLIT, "run", "app.py",
            "--server.port",      str(APP_PORT),
            "--server.headless",  "true",
            "--server.runOnSave", "true",
        ],
        cwd=APP_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


# ── Tray menu actions ─────────────────────────────────────────────

def open_dashboard(icon, item):
    webbrowser.open(APP_URL)


def restart_app(icon, item):
    global process
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    kill_port(APP_PORT)
    time.sleep(2)
    start_streamlit()
    wait_for_server()
    webbrowser.open(APP_URL)


def quit_app(icon, item):
    icon.stop()
    if process and process.poll() is None:
        process.terminate()
    kill_port(APP_PORT)
    sys.exit(0)


# ── Main ──────────────────────────────────────────────────────────

def main():
    already_running = is_port_in_use(APP_PORT)

    if not already_running:
        start_streamlit()
        ready = wait_for_server()
        if ready:
            webbrowser.open(APP_URL)
    else:
        webbrowser.open(APP_URL)

    menu = pystray.Menu(
        pystray.MenuItem("📊 Open Dashboard", open_dashboard),
        pystray.MenuItem("🔄 Restart App",    restart_app),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Quit",            quit_app),
    )

    icon = pystray.Icon(
        "Kevin Suite",
        create_icon(),
        "Kevin Suite — Investment Dashboard",
        menu,
    )

    # Double-click on tray icon also opens dashboard
    icon.default_action = open_dashboard

    icon.run()


if __name__ == "__main__":
    main()
