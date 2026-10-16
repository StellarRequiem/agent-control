#!/usr/bin/env python3
"""Managed static preview for ~/portfolio — named-command surface (no free-form python -c).

Usage:
  portfolio_preview.py start   # bind 127.0.0.1:8765, background
  portfolio_preview.py stop
  portfolio_preview.py status
  portfolio_preview.py url     # print URL only

Security: loopback only. Serves static files from PORTFOLIO root. No uploads.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
PORTFOLIO = HOME / "portfolio"
STATE_DIR = HOME / "ops" / "awareness" / "audits"
PID_FILE = STATE_DIR / "portfolio-preview.pid"
META_FILE = STATE_DIR / "portfolio-preview.json"
HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/"


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        return None
    return pid if _running(pid) else None


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.4):
            return True
    except OSError:
        return False


def cmd_status() -> int:
    pid = _read_pid()
    open_ = _port_open()
    http_code = None
    if open_:
        try:
            req = urllib.request.Request(URL, method="HEAD")
            with urllib.request.urlopen(req, timeout=2.0) as r:
                http_code = getattr(r, "status", None) or r.getcode()
        except urllib.error.HTTPError as e:
            http_code = e.code
        except Exception:  # noqa: BLE001
            http_code = None
    body = {
        "ok": True,
        "code": "PREVIEW_STATUS",
        "url": URL,
        "pid": pid,
        "port_open": open_,
        "http_code": http_code,
        "root": str(PORTFOLIO),
        "running": bool(pid and open_),
    }
    print(json.dumps(body, indent=2))
    return 0 if body["running"] else 1


def cmd_start() -> int:
    if not PORTFOLIO.is_dir():
        print(json.dumps({"ok": False, "code": "NO_PORTFOLIO", "path": str(PORTFOLIO)}))
        return 2
    existing = _read_pid()
    if existing and _port_open():
        print(
            json.dumps(
                {
                    "ok": True,
                    "code": "ALREADY_RUNNING",
                    "pid": existing,
                    "url": URL,
                },
                indent=2,
            )
        )
        return 0
    if _port_open() and not existing:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "PORT_BUSY",
                    "detail": f"{HOST}:{PORT} in use by another process",
                    "url": URL,
                }
            )
        )
        return 3
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = STATE_DIR / "portfolio-preview.log"
    # Detach: serve only loopback; fixed root
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(PORT),
            "--bind",
            HOST,
            "--directory",
            str(PORTFOLIO),
        ],
        cwd=str(PORTFOLIO),
        stdout=log.open("a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid) + "\n")
    META_FILE.write_text(
        json.dumps(
            {
                "pid": proc.pid,
                "url": URL,
                "root": str(PORTFOLIO),
                "started": time.time(),
            },
            indent=2,
        )
        + "\n"
    )
    # wait briefly for bind
    for _ in range(20):
        if _port_open():
            break
        time.sleep(0.1)
    print(
        json.dumps(
            {
                "ok": True,
                "code": "PREVIEW_STARTED",
                "pid": proc.pid,
                "url": URL,
                "log": str(log),
                "port_open": _port_open(),
            },
            indent=2,
        )
    )
    return 0 if _port_open() else 4


def cmd_stop() -> int:
    pid = _read_pid()
    if not pid:
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)
        print(json.dumps({"ok": True, "code": "NOT_RUNNING"}))
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        print(json.dumps({"ok": False, "code": "KILL_FAIL", "detail": str(e), "pid": pid}))
        return 5
    for _ in range(30):
        if not _running(pid):
            break
        time.sleep(0.05)
    if _running(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    PID_FILE.unlink(missing_ok=True)
    print(json.dumps({"ok": True, "code": "PREVIEW_STOPPED", "pid": pid}))
    return 0


def cmd_url() -> int:
    print(URL)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    op = argv[1].strip().lower()
    if op == "start":
        return cmd_start()
    if op == "stop":
        return cmd_stop()
    if op == "status":
        return cmd_status()
    if op == "url":
        return cmd_url()
    print(json.dumps({"ok": False, "code": "BAD_OP", "detail": op}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
