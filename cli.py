#!/usr/bin/env python3
"""agent-control CLI — assured plane host for browser-leash + desktop-leash.

Examples:
  python3 ~/agent-control/cli.py status
  python3 ~/agent-control/cli.py route --task "draft on X"
  python3 ~/agent-control/cli.py call plane.status
  python3 ~/agent-control/cli.py call browser.navigate --args-json '{"url":"https://xclusivexo.com"}'
  python3 ~/agent-control/cli.py call browser.x_post --args-json '{"operator_confirm":false}'
  python3 ~/agent-control/cli.py smoke
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path.home() / "mcp-assure"))

from host.plane_host import AssuredPlaneHost  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent-control")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="plane.status through the gate")
    r = sub.add_parser("route", help="classify a task")
    r.add_argument("--task", required=True)
    c = sub.add_parser("call", help="call a plane tool through AdaptiveGate")
    c.add_argument("tool")
    c.add_argument("--args-json", default="{}")
    c.add_argument("--auth-only", action="store_true", help="authorize without executing handler")
    sub.add_parser("smoke", help="offline + optional live cannot-bypass smoke")
    sub.add_parser("tools", help="list pack tools")

    args = p.parse_args(argv)
    host = AssuredPlaneHost()

    if args.cmd == "status":
        out = host.call("plane.status")
        print(json.dumps(out, indent=2)[:20000])
        return 0 if out.get("executed") or (out.get("verdict") or {}).get("allowed") else 1

    if args.cmd == "route":
        out = host.call("plane.route", {"task": args.task})
        print(json.dumps(out, indent=2)[:8000])
        return 0 if out.get("executed") else 1

    if args.cmd == "tools":
        from host.plane_host import load_local_pack

        names = load_local_pack().names()
        print(json.dumps({"tools": names, "count": len(names)}, indent=2))
        return 0

    if args.cmd == "call":
        try:
            arguments = json.loads(args.args_json)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "code": "BAD_JSON", "detail": str(e)}))
            return 2
        if not isinstance(arguments, dict):
            print(json.dumps({"ok": False, "code": "BAD_ARGS", "detail": "args must be object"}))
            return 2
        if args.auth_only:
            out = host.authorize_only(args.tool, arguments)
        else:
            out = host.call(args.tool, arguments)
        print(json.dumps(out, indent=2, default=str)[:20000])
        v = out.get("verdict") or out
        if out.get("executed"):
            return 0
        if v.get("decision") == "ALLOW" or v.get("allowed"):
            return 0
        return 1

    if args.cmd == "smoke":
        from smoke.cannot_bypass_planes import run_smoke

        return run_smoke(live=True)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
