"""Control-stack lifecycle — bring bridges up/down with low ceremony.

V1 ambient feel: one command starts local loopback planes.
Does not arm browser (extension popup), invent operator_confirm, or open public ports.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HOME = Path.home()
BROWSER_ROOT = HOME / "browser-leash"
DESKTOP_ROOT = HOME / "desktop-leash"
BROWSER_SERVER = BROWSER_ROOT / "bridge" / "server.py"
DESKTOP_SERVER = DESKTOP_ROOT / "bridge" / "server.py"
BROWSER_URL = "http://127.0.0.1:8756"
DESKTOP_URL = "http://127.0.0.1:8757"
PID_DIR = HOME / "agent-control" / "receipts" / "pids"
BROWSER_PID = PID_DIR / "browser-leash.pid"
DESKTOP_PID = PID_DIR / "desktop-leash.pid"
BROWSER_LOG = BROWSER_ROOT / "receipts" / "bridge.log"
DESKTOP_LOG = DESKTOP_ROOT / "receipts" / "bridge.log"


def _http_get_json(base: str, path: str = "/v1/status", timeout: float = 1.5) -> dict[str, Any]:
    url = base.rstrip("/") + path
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        if isinstance(data, dict):
            data.setdefault("ok", True)
            return data
        return {"ok": True, "raw": data}
    except urllib.error.HTTPError as e:
        # Some bridges use POST /v1/action only — try that for status
        return {"ok": False, "code": "HTTP_ERROR", "detail": str(e)}
    except Exception as e:
        return {"ok": False, "code": "BRIDGE_DOWN", "detail": str(e)}


def _http_post_json(base: str, path: str, body: dict[str, Any], timeout: float = 3.0) -> dict[str, Any]:
    url = base.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        out = json.loads(raw) if raw else {}
        return out if isinstance(out, dict) else {"ok": True, "raw": out}
    except Exception as e:
        return {"ok": False, "code": "REQUEST_FAILED", "detail": str(e)}


def probe_browser() -> dict[str, Any]:
    # browser-leash: GET /v1/status or POST status action
    st = _http_get_json(BROWSER_URL, "/v1/status")
    if st.get("ok") is not False and st.get("code") != "BRIDGE_DOWN":
        return {
            "up": True,
            "armed": st.get("armed"),
            "extension": st.get("extension") or st.get("extension_version"),
            "version": st.get("version"),
            "require_post_confirm": st.get("require_post_confirm"),
            "raw_keys": sorted(st.keys())[:20],
        }
    # fallback action probe
    act = _http_post_json(BROWSER_URL, "/v1/action", {"action": "status"})
    if act.get("ok") is False and act.get("code") in ("BRIDGE_DOWN", "REQUEST_FAILED"):
        return {"up": False, "code": "BRIDGE_DOWN", "detail": act.get("detail")}
    if act.get("code") == "BRIDGE_DOWN":
        return {"up": False, "code": "BRIDGE_DOWN", "detail": act.get("detail")}
    # connection worked
    return {
        "up": True,
        "armed": act.get("armed"),
        "extension": (act.get("extension") or {}).get("version")
        if isinstance(act.get("extension"), dict)
        else act.get("extension"),
        "version": act.get("version"),
        "require_post_confirm": act.get("require_post_confirm"),
        "probe": "action",
    }


def probe_desktop() -> dict[str, Any]:
    st = _http_get_json(DESKTOP_URL, "/v1/status")
    if st.get("ok") is not False and st.get("code") != "BRIDGE_DOWN":
        return {
            "up": True,
            "armed": st.get("armed"),
            "version": st.get("version"),
            "phase": st.get("phase"),
            "require_d4_confirm": st.get("require_d4_confirm"),
        }
    act = _http_post_json(DESKTOP_URL, "/v1/action", {"action": "desktop.status"})
    if act.get("ok") is False and act.get("code") in ("BRIDGE_DOWN", "REQUEST_FAILED"):
        return {"up": False, "code": "BRIDGE_DOWN", "detail": act.get("detail")}
    if "Connection refused" in str(act.get("detail") or ""):
        return {"up": False, "code": "BRIDGE_DOWN", "detail": act.get("detail")}
    return {
        "up": True,
        "armed": act.get("armed"),
        "version": act.get("version"),
        "phase": act.get("phase"),
        "require_d4_confirm": act.get("require_d4_confirm"),
        "probe": "action",
    }


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid) + "\n", encoding="utf-8")


def _start_server(script: Path, log_path: Path, pid_path: Path, label: str) -> dict[str, Any]:
    if not script.is_file():
        return {"ok": False, "code": "MISSING_SERVER", "path": str(script), "label": label}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # If already up, do not spawn a second listener
    existing = _read_pid(pid_path)
    if existing and _pid_alive(existing):
        return {"ok": True, "code": "ALREADY_RUNNING", "pid": existing, "label": label}
    try:
        logf = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            [os.environ.get("PYTHON", "python3"), str(script)],
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(script.parent),
        )
        _write_pid(pid_path, proc.pid)
        return {
            "ok": True,
            "code": "STARTED",
            "pid": proc.pid,
            "label": label,
            "log": str(log_path),
        }
    except Exception as e:
        return {"ok": False, "code": "START_FAILED", "detail": str(e), "label": label}


def _stop_pid(pid_path: Path, label: str) -> dict[str, Any]:
    pid = _read_pid(pid_path)
    if not pid:
        return {"ok": True, "code": "NO_PID", "label": label}
    if not _pid_alive(pid):
        try:
            pid_path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            if pid_path.is_file():
                pid_path.unlink()
        return {"ok": True, "code": "STALE_PID", "pid": pid, "label": label}
    try:
        os.kill(pid, signal.SIGTERM)
        # brief wait then escalate
        for _ in range(20):
            time.sleep(0.05)
            if not _pid_alive(pid):
                break
        else:
            os.kill(pid, signal.SIGKILL)
        try:
            pid_path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            if pid_path.is_file():
                pid_path.unlink()
        return {"ok": True, "code": "STOPPED", "pid": pid, "label": label}
    except Exception as e:
        return {"ok": False, "code": "STOP_FAILED", "detail": str(e), "pid": pid, "label": label}


def arm_desktop() -> dict[str, Any]:
    """Sticky CLI arm for desktop-leash. Browser arm remains extension popup."""
    # Prefer client if present
    client = DESKTOP_ROOT / "bridge" / "client.py"
    if client.is_file():
        try:
            p = subprocess.run(
                ["python3", str(client), "arm"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            text = (p.stdout or "").strip()
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {"raw": text[:2000], "stderr": (p.stderr or "")[:500]}
            return {
                "ok": p.returncode == 0,
                "code": "DESKTOP_ARM",
                "result": data,
            }
        except Exception as e:
            return {"ok": False, "code": "ARM_FAILED", "detail": str(e)}
    return _http_post_json(DESKTOP_URL, "/v1/action", {"action": "desktop.arm"})


def disarm_desktop() -> dict[str, Any]:
    client = DESKTOP_ROOT / "bridge" / "client.py"
    if client.is_file():
        try:
            p = subprocess.run(
                ["python3", str(client), "disarm"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            text = (p.stdout or "").strip()
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {"raw": text[:2000]}
            return {"ok": p.returncode == 0, "code": "DESKTOP_DISARM", "result": data}
        except Exception as e:
            return {"ok": False, "code": "DISARM_FAILED", "detail": str(e)}
    return _http_post_json(DESKTOP_URL, "/v1/action", {"action": "desktop.disarm"})


def stack_status() -> dict[str, Any]:
    browser = probe_browser()
    desktop = probe_desktop()
    ready = bool(browser.get("up") and desktop.get("up"))
    ambient_ready = ready and bool(desktop.get("armed"))
    return {
        "ok": True,
        "code": "STACK_STATUS",
        "v1": "ambient_under_leash",
        "ready": ready,
        "ambient_ready": ambient_ready,
        "browser_leash": browser,
        "desktop_leash": desktop,
        "operator_actions": {
            "browser_arm": "Chrome popup → ARM (sticky) when extension polls",
            "desktop_arm": "cli.py up arms by default; or desktop-leash client arm",
            "high_blast": "never invent operator_confirm=true",
        },
        "claim": "session multi-plane control under arm — not unlimited ambient OS",
    }


def stack_available() -> dict[str, Any]:
    """Always-available posture: bridges up + extension hello. Does not require ARM.

    Distinguishes infrastructure readiness from session authority (ARM).
    """
    browser = probe_browser()
    desktop = probe_desktop()
    bridges_up = bool(browser.get("up") and desktop.get("up"))
    ext = browser.get("extension") if isinstance(browser.get("extension"), dict) else {}
    # probe_browser may put version at top level too
    ext_ver = None
    if isinstance(ext, dict):
        ext_ver = ext.get("version")
    if not ext_ver:
        ext_ver = browser.get("version")
    # nested in raw status via probe
    hello_ok = bool(browser.get("up") and (ext_ver or browser.get("armed") is not None))
    # Prefer explicit last_hello when present
    last_hello = None
    if isinstance(ext, dict):
        last_hello = ext.get("last_hello")
    extension_connected = bool(ext_ver) and (last_hello is None or float(last_hello or 0) > 0)

    # Re-probe browser with full status for expect version
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8756/v1/status", timeout=2) as resp:
            import json as _json

            full = _json.loads(resp.read().decode())
        ext_full = full.get("extension") or {}
        extension_connected = bool(ext_full.get("version")) and float(
            ext_full.get("last_hello") or 0
        ) > 0
        ext_ver = ext_full.get("version")
        expect = full.get("expect_extension_version")
        browser_armed = bool(full.get("armed"))
        require_post = full.get("require_post_confirm")
    except Exception:
        expect = None
        browser_armed = bool(browser.get("armed"))
        require_post = None

    available = bridges_up  # infra only
    work_session_ready = (
        available
        and extension_connected
        and browser_armed
        and bool(desktop.get("armed"))
    )

    return {
        "ok": True,
        "code": "STACK_AVAILABLE",
        "available": available,
        "work_session_ready": work_session_ready,
        "bridges_up": bridges_up,
        "extension_connected": extension_connected,
        "extension_version": ext_ver,
        "expect_extension_version": expect,
        "browser_armed": browser_armed,
        "desktop_armed": bool(desktop.get("armed")),
        "require_post_confirm": require_post,
        "browser_leash": browser,
        "desktop_leash": desktop,
        "always_on_policy": {
            "bridges": "may run always (launchd KeepAlive)",
            "arm": "NEVER auto — operator/extension intentional",
            "auto_post": False,
            "abhorrent_lockdown": "phase C — not enabled",
        },
        "how_to": {
            "install_launchd": "bash ~/agent-control/scripts/always_available.sh install",
            "work_session": "Soft Reload if needed → Chrome popup ARM → desktop arm (cli.py up) → work → DISARM / down",
            "soc_watch_optional": "INSTALL_SOC_WATCH=1 bash ~/agent-control/scripts/always_available.sh install",
        },
        "claim": "always-available bridges — not always-armed ambient authority",
    }


def stack_up(
    *,
    arm_desktop_plane: bool = True,
    wait_sec: float = 2.5,
) -> dict[str, Any]:
    """Start both bridges if down. Optionally sticky-arm desktop."""
    actions: list[dict[str, Any]] = []
    b = probe_browser()
    if not b.get("up"):
        actions.append(_start_server(BROWSER_SERVER, BROWSER_LOG, BROWSER_PID, "browser-leash"))
    else:
        actions.append({"ok": True, "code": "ALREADY_UP", "label": "browser-leash"})

    d = probe_desktop()
    if not d.get("up"):
        actions.append(_start_server(DESKTOP_SERVER, DESKTOP_LOG, DESKTOP_PID, "desktop-leash"))
    else:
        actions.append({"ok": True, "code": "ALREADY_UP", "label": "desktop-leash"})

    # Wait for ports
    deadline = time.time() + max(0.5, wait_sec)
    browser = b
    desktop = d
    while time.time() < deadline:
        browser = probe_browser()
        desktop = probe_desktop()
        if browser.get("up") and desktop.get("up"):
            break
        time.sleep(0.15)

    arm_result = None
    if arm_desktop_plane and desktop.get("up"):
        if not desktop.get("armed"):
            arm_result = arm_desktop()
            desktop = probe_desktop()
        else:
            arm_result = {"ok": True, "code": "ALREADY_ARMED"}

    return {
        "ok": bool(browser.get("up") and desktop.get("up")),
        "code": "STACK_UP",
        "actions": actions,
        "desktop_arm": arm_result,
        "browser_leash": browser,
        "desktop_leash": desktop,
        "next": [
            "Soft Reload browser-leash extension if extension.version is null",
            "ARM browser via Chrome popup for Chrome plane work",
            "python3 ~/agent-control/cli.py call cua.start --args-json '{\"max_steps\":40,\"max_seconds\":1800}'",
        ],
        "claim": "bridges up under leash — browser ARM still human/extension",
    }


def stack_down(*, disarm_desktop_plane: bool = True) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    if disarm_desktop_plane:
        results.append(disarm_desktop())
    results.append(_stop_pid(BROWSER_PID, "browser-leash"))
    results.append(_stop_pid(DESKTOP_PID, "desktop-leash"))
    # Re-probe — if still up, we didn't own the pid (manual start); report only
    browser = probe_browser()
    desktop = probe_desktop()
    return {
        "ok": True,
        "code": "STACK_DOWN",
        "actions": results,
        "browser_still_up": bool(browser.get("up")),
        "desktop_still_up": bool(desktop.get("up")),
        "note": "If still up, bridges were started outside this pid file — stop manually or kill :8756/:8757",
        "claim": "disarm + stop owned pids — not a kill-all guarantee",
    }
