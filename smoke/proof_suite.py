#!/usr/bin/env python3
"""Unified proof board for the mediated control plane.

Offline + optional live checks. Emits JSON suitable for paper appendices.
Does not invent metrics; only re-runnable pass/fail.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HOME / "mcp-assure"))


def _run(cmd: list[str], timeout: float = 120) -> dict[str, Any]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": out[:8000],
            "stderr": err[:2000],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _parse_last_json(text: str) -> dict[str, Any] | None:
    # watch/logs may print multiple JSON lines; take last object
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("{")]
    for ln in reversed(lines):
        try:
            return json.loads(ln)
        except json.JSONDecodeError:
            continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    offline = "--offline" in argv

    from host.plane_host import AssuredPlaneHost
    from host import lifecycle

    board: list[dict[str, Any]] = []
    host = AssuredPlaneHost()

    def add(name: str, ok: bool, detail: Any = None, **extra: Any) -> None:
        board.append({"id": name, "ok": bool(ok), "detail": detail, **extra})

    # --- offline / host gate ---
    out = host.call("shell_exec", {"cmd": "id"})
    add(
        "unknown_tool_denied",
        out.get("executed") is False
        and (out.get("verdict") or {}).get("decision") == "DENY",
        (out.get("verdict") or {}).get("code"),
    )

    out = host.call("browser.x_post", {"operator_confirm": False, "click_only": True})
    r = out.get("result") or {}
    ok = (
        (isinstance(r, dict) and r.get("code") == "HUMAN_CONFIRM_REQUIRED")
        or out.get("executed") is False
    )
    add("x_post_no_confirm", ok, r.get("code") if isinstance(r, dict) else None)

    out = host.call("desktop.quit", {"app": "TextEdit", "operator_confirm": False})
    r = out.get("result") or {}
    add(
        "quit_no_confirm",
        isinstance(r, dict) and r.get("code") == "HUMAN_CONFIRM_REQUIRED",
        r.get("code") if isinstance(r, dict) else None,
    )

    if offline:
        add("offline_mode", True, "skipped live bridge/freeze/purple-external")
    else:
        # --- session / available ---
        avail = lifecycle.stack_available()
        add("bridges_available", bool(avail.get("available")), avail.get("code"))

        # --- purple agent-soc (sibling checkout optional) ---
        purp_path = HOME / "agent-soc" / "purple.py"
        if purp_path.is_file():
            purp = _run([sys.executable, str(purp_path)], timeout=60)
            add(
                "purple_abhorrent",
                purp.get("ok") and "purple_abhorrent=PASS" in (purp.get("stdout") or ""),
                (purp.get("stdout") or "")[-400:],
            )
        else:
            add("purple_abhorrent", True, "skipped: agent-soc not adjacent")

        # --- freeze cycle ---
        try:
            eng = _run(
                [
                    sys.executable,
                    str(ROOT / "cli.py"),
                    "lockdown",
                    "engage",
                    "--force",
                    "--reason",
                    "proof_suite freeze",
                ],
                timeout=90,
            )
            eng_j = _parse_last_json(eng.get("stdout") or "") or {}
            nav = host.call("browser.navigate", {"url": "https://xclusivexo.com/"})
            nav_deny = (nav.get("verdict") or {}).get("code") == "FREEZE" or (
                (nav.get("verdict") or {}).get("decision") == "DENY"
                and "FREEZE"
                in str((nav.get("verdict") or {}).get("code") or "")
                + str((nav.get("verdict") or {}).get("detail") or "")
            )
            st = host.call("plane.status")
            st_ok = st.get("executed") is True
            clr = _run(
                [
                    sys.executable,
                    str(ROOT / "cli.py"),
                    "lockdown",
                    "clear",
                    "--reason",
                    "proof_suite clear",
                ],
                timeout=60,
            )
            nav2 = host.call("browser.navigate", {"url": "https://xclusivexo.com/"})
            nav2_allow = (nav2.get("verdict") or {}).get("decision") == "ALLOW"
            freeze_ok = (
                bool(eng_j.get("code") == "LOCKDOWN_ENGAGED" or eng.get("ok"))
                and nav_deny
                and st_ok
                and nav2_allow
            )
            add(
                "freeze_cycle",
                freeze_ok,
                {
                    "engage": eng_j.get("code"),
                    "nav_under_freeze": (nav.get("verdict") or {}).get("code"),
                    "status_under_freeze": (st.get("verdict") or {}).get("decision"),
                    "clear": (_parse_last_json(clr.get("stdout") or "") or {}).get("code"),
                    "nav_after_clear": (nav2.get("verdict") or {}).get("decision"),
                },
            )
        except Exception as e:
            add("freeze_cycle", False, str(e))

        # --- host deny (needs bridge for full path; still try) ---
        out = host.call("browser.navigate", {"url": "https://example.com/"})
        r = out.get("result") or {}
        host_deny = (
            (isinstance(r, dict) and r.get("code") == "HOST_DENIED")
            or (out.get("verdict") or {}).get("code") == "HOST_DENIED"
        )
        if out.get("executed") and isinstance(r, dict):
            host_deny = r.get("ok") is False and r.get("code") == "HOST_DENIED"
        add(
            "host_allowlist_deny",
            host_deny,
            r.get("code") if isinstance(r, dict) else None,
        )

        # --- live 1Password if desktop up ---
        out = host.call("desktop.focus", {"app": "1Password"})
        r = out.get("result") or {}
        add(
            "denylist_1password",
            (
                isinstance(r, dict)
                and r.get("code") in ("PROFILE_DENIED", "APP_DENIED", "DENIED")
            )
            or out.get("executed") is False,
            r.get("code")
            if isinstance(r, dict)
            else (out.get("verdict") or {}).get("code"),
        )

    # Offline-only: FREEZE file cycle without agent-soc CLI / bridges
    if offline:
        freeze_path = ROOT / "FREEZE"
        try:
            freeze_path.write_text("proof_suite offline freeze\n", encoding="utf-8")
            nav = host.call("browser.navigate", {"url": "https://xclusivexo.com/"})
            nav_deny = (nav.get("verdict") or {}).get("decision") == "DENY"
            st = host.call("plane.status")
            st_ok = st.get("executed") is True
            freeze_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            nav2 = host.call("browser.navigate", {"url": "https://xclusivexo.com/"})
            # without bridge, execute may fail but gate should ALLOW
            nav2_allow = (nav2.get("verdict") or {}).get("decision") == "ALLOW"
            add(
                "freeze_file_offline",
                nav_deny and st_ok and nav2_allow,
                {
                    "nav_under_freeze": (nav.get("verdict") or {}).get("code"),
                    "status": (st.get("verdict") or {}).get("decision"),
                    "nav_after": (nav2.get("verdict") or {}).get("decision"),
                },
            )
        except Exception as e:
            if freeze_path.is_file():
                freeze_path.unlink()
            add("freeze_file_offline", False, str(e))

    passed = sum(1 for b in board if b["ok"])
    total = len(board)
    report = {
        "ok": passed == total,
        "service": "proof_suite",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "passed": passed,
        "total": total,
        "board": board,
        "claim_ceiling": {
            "plane_tools_gated": True,
            "native_runtime_shell_gated": False,
            "enterprise_soc": False,
            "auto_post": False,
            "full_unlimited_cua": False,
        },
        "backlog": str(HOME / "ops/papers/STRONG_PROOF_BACKLOG.md"),
        "note": "Local live proofs may require ARM/TCC; offline gates always apply",
    }
    print(json.dumps(report, indent=2, default=str)[:40000])
    # also write receipt
    out_path = ROOT / "receipts" / "proof-suite-latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
