"""Utilities to start and manage simulator servers during tests."""

import socket
import threading
import time

import httpx
import uvicorn

from simulators.core_bank.app import app as core_bank_app
from simulators.documents.app import app as docs_app
from simulators.processor.app import app as proc_app


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def start_server_in_thread(app, port: int) -> None:
    if is_port_open(port):
        return  # Already running

    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config=config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Poll until ready
    for _ in range(30):
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/", timeout=1.0)
            if resp.status_code in (200, 401, 404):
                return
        except Exception:
            time.sleep(0.1)


def ensure_simulators_running() -> None:
    """Ensure core bank (8001), processor (8003), and documents (8004) are running."""
    start_server_in_thread(core_bank_app, 8001)
    start_server_in_thread(proc_app, 8003)
    start_server_in_thread(docs_app, 8004)
