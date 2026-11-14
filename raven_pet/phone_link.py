"""
Link between the Raven Prism app and the companion Android app.

The glasses run a tiny HTTP server (default port 8765). The phone POSTs a
heartbeat to /activity every few seconds and immediately when the foreground
app or screen state changes:

    POST /activity
    {"package": "com.instagram.android", "label": "Instagram",
     "screen_on": true, "steps_total": 12345}

The response is the raven's current stats so the phone can show them.
GET /status returns the same stats.

So the phone doesn't need an IP typed in, the glasses also broadcast a small
UDP beacon on port 47800 every 2 s:  {"service": "raven-pet", "port": 8765}
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from pet_state import PhoneReport

HTTP_PORT = 8765
BEACON_PORT = 47800
BEACON_INTERVAL_S = 2.0
MAX_BODY = 4096


class PhoneLink:
    def __init__(
        self,
        port: int = HTTP_PORT,
        pair_code: str = "",
        classifier: Optional[Callable[[PhoneReport], str]] = None,
    ) -> None:
        self._classifier = classifier  # must be thread-safe (pure function)
        self._port = port
        self._pair_code = pair_code
        self._lock = threading.Lock()
        self._pending: list[PhoneReport] = []
        self._latest: Optional[PhoneReport] = None
        self._server: Optional[ThreadingHTTPServer] = None
        self._stop = threading.Event()
        self._status_cache: dict = {}

    # -------------------------------------------------------------- main-thread API
    def drain(self) -> list[PhoneReport]:
        """Reports received since the last call (oldest first). Call from the UI thread."""
        with self._lock:
            out, self._pending = self._pending, []
            return out

    def publish_status(self, status: dict) -> None:
        """Called from the UI thread so HTTP threads never touch Qt / pet objects."""
        with self._lock:
            self._status_cache = dict(status)

    @property
    def latest(self) -> Optional[PhoneReport]:
        with self._lock:
            return self._latest

    # -------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        link = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # silence default stderr logging
                pass

            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorised(self) -> bool:
                return not link._pair_code or self.headers.get("X-Raven-Pair", "") == link._pair_code

            def do_GET(self) -> None:
                if self.path.rstrip("/") in ("/status", ""):
                    with link._lock:
                        self._send(200, link._status_cache)
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                if self.path.rstrip("/") != "/activity":
                    self._send(404, {"error": "not found"})
                    return
                if not self._authorised():
                    self._send(403, {"error": "bad pair code"})
                    return
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), MAX_BODY)
                    data = json.loads(self.rfile.read(length) or b"{}")
                    steps = data.get("steps_total")
                    report = PhoneReport(
                        package=str(data.get("package", ""))[:200],
                        label=str(data.get("label", ""))[:80],
                        screen_on=bool(data.get("screen_on", True)),
                        steps_total=int(steps) if isinstance(steps, (int, float)) else None,
                        received_at=time.time(),
                    )
                except (ValueError, TypeError):
                    self._send(400, {"error": "bad json"})
                    return
                prev = link._latest
                if prev is None or (prev.package, prev.screen_on) != (report.package, report.screen_on):
                    what = (report.label or report.package or "home screen") if report.screen_on else "screen off"
                    print(f"[raven-pet] phone {self.client_address[0]} -> {what}", flush=True)
                with link._lock:
                    link._pending.append(report)
                    link._latest = report
                    status = dict(link._status_cache)
                if link._classifier is not None:
                    # answer with how *this* report is classified, not the last published one
                    status["activity"] = link._classifier(report)
                self._send(200, status)

        try:
            self._server = ThreadingHTTPServer(("0.0.0.0", self._port), Handler)
        except OSError as e:
            print(f"[raven-pet] could not open port {self._port}: {e}")
            return False
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, name="raven-pet-http", daemon=True).start()
        threading.Thread(target=self._beacon_loop, name="raven-pet-beacon", daemon=True).start()
        print(f"[raven-pet] listening for the phone on {local_ip()}:{self._port}")
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _beacon_loop(self) -> None:
        payload = json.dumps({"service": "raven-pet", "port": self._port}).encode()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            return
        with sock:
            while not self._stop.wait(BEACON_INTERVAL_S):
                try:
                    sock.sendto(payload, ("255.255.255.255", BEACON_PORT))
                except OSError:
                    pass  # no network right now; try again next tick


def local_ip() -> str:
    """Best guess at this device's LAN (Wi-Fi/Ethernet) address, skipping VPN/docker interfaces."""
    try:
        import subprocess

        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=2).stdout
        for line in out.splitlines():
            parts = line.split()
            iface, addr = parts[1], parts[3].split("/")[0]
            if not iface.startswith(("lo", "docker", "br-", "veth", "tailscale", "wg", "tun", "virbr")):
                return addr
    except (OSError, IndexError, subprocess.SubprocessError):
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
