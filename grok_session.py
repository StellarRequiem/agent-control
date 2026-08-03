#!/usr/bin/env python3
"""Grok session preflight — V1 ambient-under-leash default path.

Run at session start:
  python3 ~/agent-control/grok_session.py              # stack up + SOC + plane status
  python3 ~/agent-control/grok_session.py --start-cua
  python3 ~/agent-control/grok_session.py --no-up      # status only (do not start bridges)
  python3 ~/agent-control/grok_session.py --start-watch  # prints watch command
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
AC = HOME / "agent-control"
SOC = HOME / "agent-soc"


def _run(cmd: list[str], timeout: float = 60.0) -> dict:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        text = (p.stdout or "").strip()
        try:
            return {"ok": p.returncode == 0, "json": json.loads(text), "raw": text[:4000]}
        except json.JSONDecodeError:
            return {"ok": p.returncode == 0, "raw": text[:4000], "stderr": (p.stderr or "")[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="grok-session")
    ap.add_argument("--start-cua", action="store_true", help="start budgeted CUA session")
    ap.add_argument("--cua-steps", type=int, default=40, help="V1 default 40")
    ap.add_argument("--cua-seconds", type=float, default=1800.0, help="V1 default 30m")
    ap.add_argument(
        "--no-up",
        action="store_true",
        help="do not start bridges (status-only preflight)",
    )
    ap.add_argument(
        "--no-arm-desktop",
        action="store_true",
        help="when bringing stack up, skip desktop sticky arm",
    )
    ap.add_argument("--start-watch", action="store_true", help="print continuous watch command")
    ap.add_argument("--watch-interval", type=float, default=30.0)
    args = ap.parse_args(argv)

    env = {
        "PYTHONPATH": f"{HOME / 'mcp-assure'}:{AC}",
    }
    import os

    os.environ["PYTHONPATH"] = env["PYTHONPATH"]

    out: dict = {
        "ok": True,
        "service": "grok_session_preflight",
        "v1": "ambient_under_leash",
        "default_path": "stack up → agent-soc → agent-control → cua/browser/desktop → human high-blast",
        "doc": str(AC / "docs" / "GROK_DEFAULT_PATH.md"),
        "pursuit": str(HOME / "ops" / "CONTROL_STACK_V1_PURSUIT.md"),
    }

    # V1: bring planes up by default (low ceremony)
    if not args.no_up:
        up_cmd = [sys.executable, str(AC / "cli.py"), "up"]
        if args.no_arm_desktop:
            up_cmd.append("--no-arm-desktop")
        up = _run(up_cmd, timeout=30.0)
        out["stack_up"] = up.get("json") or up
        if not (up.get("json") or {}).get("ok") and not up.get("ok"):
            out["ok"] = False

    # SOC
    soc = _run([sys.executable, str(SOC / "cli.py"), "status"])
    out["agent_soc"] = soc.get("json") or soc

    # Lifecycle stack surface
    stack = _run([sys.executable, str(AC / "cli.py"), "stack"])
    out["stack"] = stack.get("json") or stack

    # Plane host (gated status)
    plane = _run([sys.executable, str(AC / "cli.py"), "status"])
    out["agent_control"] = plane.get("json") or plane

    if args.start_cua:
        cua = _run(
            [
                sys.executable,
                str(AC / "cli.py"),
                "call",
                "cua.start",
                "--args-json",
                json.dumps(
                    {"max_steps": args.cua_steps, "max_seconds": args.cua_seconds}
                ),
            ]
        )
        out["cua"] = cua.get("json") or cua

    if args.start_watch:
        out["watch_command"] = (
            f"python3 {SOC}/cli.py watch --interval {args.watch_interval}"
        )
        out["watch_note"] = (
            "Run in a separate terminal or background. "
            "--auto-respond-high freezes only unless AGENT_SOC_AUTO_DISARM=1"
        )

    # Claim ceiling always
    out["claim_ceiling"] = {
        "session_cua": True,
        "agent_plane_soc": True,
        "stack_lifecycle": True,
        "full_cua_unlimited": False,
        "enterprise_soc": False,
        "auto_post": False,
        "browser_arm_still_human": True,
    }

    # Ambient readiness signal
    stack_json = out.get("stack") if isinstance(out.get("stack"), dict) else {}
    out["ambient_ready"] = bool(stack_json.get("ambient_ready"))
    if not stack_json.get("ready"):
        out["ok"] = False

    print(json.dumps(out, indent=2, default=str)[:24000])
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
