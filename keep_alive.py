"""
AnimeNova Persistent Launcher
Run this Python script directly: python keep_alive.py
It starts the backend + cloudflare tunnel and keeps them running forever.
"""
import subprocess
import sys
import os
import re
import time
import threading
import signal
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(BASE, "backend")
PYTHON = os.path.join(BACKEND, "venv", "Scripts", "python.exe")
CLOUDFLARED = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
CF_LOG = os.path.join(BACKEND, "cloudflared.log")
ENV_PATH = os.path.join(BACKEND, ".env")

backend_proc = None
cf_proc = None
current_url = ""
stop_flag = threading.Event()


def log(msg):
    t = time.strftime("%H:%M:%S")
    print(f"[{t}] {msg}", flush=True)


def kill_port_8000():
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if ":8000" in line:
                parts = line.split()
                pid = parts[-1]
                if pid.isdigit() and int(pid) > 0:
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
    except Exception as e:
        log(f"kill_port warning: {e}")


def start_backend():
    global backend_proc
    kill_port_8000()
    time.sleep(1)
    backend_proc = subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=BACKEND,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )
    log(f"Backend started (PID {backend_proc.pid})")
    return backend_proc


def start_tunnel():
    global cf_proc
    # Kill old cloudflared
    subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)
    time.sleep(1)
    if os.path.exists(CF_LOG):
        os.remove(CF_LOG)
    cf_proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", "http://127.0.0.1:8000",
         "--edge-ip-version", "4", "--protocol", "http2", "--logfile", CF_LOG],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000,
    )
    log(f"Cloudflared started (PID {cf_proc.pid})")

    # Wait for URL
    url = ""
    deadline = time.time() + 50
    while time.time() < deadline and not url:
        time.sleep(2)
        if os.path.exists(CF_LOG):
            try:
                text = open(CF_LOG, encoding="utf-8", errors="replace").read()
                m = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', text)
                if m:
                    url = m.group()
            except Exception:
                pass
    return url


def update_env(url):
    media_url = f"{url}/api/media/output"
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r'(?m)^PUBLIC_MEDIA_BASE_URL=.*$', f'PUBLIC_MEDIA_BASE_URL={media_url}', text)
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(text)
        log(f".env updated => {media_url}")
    except Exception as e:
        log(f"update_env error: {e}")


def is_backend_alive():
    try:
        r = requests.get("http://127.0.0.1:8000/", timeout=4)
        return r.status_code == 200
    except Exception:
        return False


def main():
    global backend_proc, cf_proc, current_url

    log("=== AnimeNova Keep-Alive Launcher ===")

    # Initial start
    start_backend()
    time.sleep(5)

    url = start_tunnel()
    if url:
        current_url = url
        log(f"")
        log(f"=== SERVICES RUNNING ===")
        log(f"  Dashboard:   http://127.0.0.1:8000/app")
        log(f"  Webhook URL: {url}/webhook/instagram")
        log(f"  Verify Token: anime-nova-local-verify")
        log(f"")
        log(f"IMPORTANT: Register this webhook in Meta Developer Console!")
        log(f"  URL: {url}/webhook/instagram")
        log(f"  Token: anime-nova-local-verify")
        log(f"")
        update_env(url)

        # Restart backend to pick up new URL
        time.sleep(2)
        start_backend()
        time.sleep(5)
    else:
        log("WARNING: Could not get Cloudflare URL")

    log("Watchdog running... Press Ctrl+C to stop.")

    # Watchdog loop
    while not stop_flag.is_set():
        time.sleep(15)

        # Check backend
        if not is_backend_alive():
            log("Backend died - restarting...")
            start_backend()
            time.sleep(5)

        # Check cloudflared
        if cf_proc and cf_proc.poll() is not None:
            log("Cloudflared died - restarting tunnel...")
            new_url = start_tunnel()
            if new_url and new_url != current_url:
                log(f"New tunnel URL: {new_url}/webhook/instagram")
                current_url = new_url
                update_env(new_url)
                start_backend()
                time.sleep(5)


def on_signal(sig, frame):
    log("Stopping...")
    stop_flag.set()
    if backend_proc:
        backend_proc.terminate()
    if cf_proc:
        cf_proc.terminate()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    main()
