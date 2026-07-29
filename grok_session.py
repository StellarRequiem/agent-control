#!/usr/bin/env python3
"""Grok session preflight — default path: SOC posture + plane host + optional CUA.

Run at session start:
  python3 ~/agent-control/grok_session.py
  python3 ~/agent-control/grok_session.py --start-cua
  python3 ~/agent-control/grok_session.py --start-watch   # prints watch command; does not block
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
    ap.add_argument("--cua-steps", type=int, default=20)
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
        "default_path": "agent-soc → agent-control → cua/browser/desktop → human high-blast",
        "doc": str(AC / "docs" / "GROK_DEFAULT_PATH.md"),
    }

    # SOC
    soc = _run([sys.executable, str(SOC / "cli.py"), "status"])
    out["agent_soc"] = soc.get("json") or soc

    # Plane host
    plane = _run(
        [sys.executable, str(AC / "cli.py"), "status"],
    )
    out["agent_control"] = plane.get("json") or plane

    if args.start_cua:
        cua = _run(
            [
                sys.executable,
                str(AC / "cli.py"),
                "call",
                "cua.start",
                "--args-json",
                json.dumps({"max_steps": args.cua_steps, "max_seconds": 900}),
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
        "full_cua_unlimited": False,
        "enterprise_soc": False,
        "auto_post": False,
    }

    print(json.dumps(out, indent=2, default=str)[:24000])
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
