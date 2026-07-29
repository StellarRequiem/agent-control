#!/usr/bin/env python3
"""Cannot-bypass + human-gate smoke for agent-control plane host.

Offline proofs (no bridge required for gate path):
  1. Unknown tools never execute
  2. browser.x_post without operator_confirm does not publish (handler refuse)
  3. desktop.quit without operator_confirm refuses
  4. desktop.press return without operator_confirm refuses
  5. plane.route executes through gate

Live proofs (if bridges up):
  6. plane.status returns both leash health
  7. desktop focus 1Password denied by leash/profile
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path.home() / "mcp-assure"))

from host.plane_host import AssuredPlaneHost  # noqa: E402


def run_smoke(*, live: bool = True) -> int:
    host = AssuredPlaneHost()
    results: list[tuple[str, bool, str]] = []

    # 1 unknown tool
    out = host.call("shell_exec", {"cmd": "id"})
    ok = out.get("executed") is False and (out.get("verdict") or {}).get("decision") == "DENY"
    results.append(("unknown_tool_denied", ok, json.dumps(out.get("verdict"))[:120]))

    # 2 x_post human gate (handler path — only if ALLOW by pack)
    out = host.call("browser.x_post", {"operator_confirm": False, "click_only": True})
    # Pack requires operator_confirm arg — False is present so may ALLOW into handler
    result = out.get("result") or {}
    code = result.get("code") if isinstance(result, dict) else None
    # Also accept DENY from gate if adaptive smells
    ok = out.get("executed") is False or code == "HUMAN_CONFIRM_REQUIRED"
    if out.get("executed") and isinstance(result, dict):
        ok = result.get("ok") is False and result.get("code") == "HUMAN_CONFIRM_REQUIRED"
    results.append(("x_post_no_confirm", ok, str(code or (out.get("verdict") or {}).get("code"))))

    # 3 quit no confirm
    out = host.call("desktop.quit", {"app": "TextEdit", "operator_confirm": False})
    result = out.get("result") or {}
    if out.get("executed") and isinstance(result, dict):
        ok = result.get("code") == "HUMAN_CONFIRM_REQUIRED"
    else:
        ok = out.get("executed") is False
    results.append(("quit_no_confirm", ok, str((result or out.get("verdict") or {}).get("code"))))

    # 4 press return no confirm
    out = host.call("desktop.press", {"key": "return"})
    result = out.get("result") or {}
    if out.get("executed") and isinstance(result, dict):
        ok = result.get("code") == "HUMAN_CONFIRM_REQUIRED"
    else:
        # missing operator_confirm still allowed by pack (optional arg) — handler must refuse
        ok = False
    results.append(("return_no_confirm", ok, str((result or {}).get("code"))))

    # 5 route
    out = host.call("plane.route", {"task": "open github.com in chrome"})
    result = out.get("result") or {}
    ok = out.get("executed") is True and isinstance(result, dict) and result.get("plane") == "browser"
    results.append(("route_browser", ok, str((result or {}).get("plane"))))

    # 5b shell route
    out = host.call("plane.route", {"task": "run pytest and git commit"})
    result = out.get("result") or {}
    ok = out.get("executed") is True and isinstance(result, dict) and result.get("plane") == "shell"
    results.append(("route_shell", ok, str((result or {}).get("plane"))))

    # 5c shell: free-form not in pack
    out = host.call("shell_exec", {"cmd": "id"})
    ok = out.get("executed") is False
    results.append(("no_shell_exec_tool", ok, str((out.get("verdict") or {}).get("code"))))

    # 5d shell: unknown named command
    out = host.call("shell.run", {"name": "rm_rf_slash"})
    result = out.get("result") or {}
    if out.get("executed") and isinstance(result, dict):
        ok = result.get("code") == "COMMAND_NOT_ALLOWLISTED"
    else:
        ok = out.get("executed") is False
    results.append(("shell_run_unknown_name", ok, str((result or out.get("verdict") or {}).get("code"))))

    # 5e shell: path outside roots
    out = host.call("shell.read_file", {"path": "/etc/passwd"})
    result = out.get("result") or {}
    if out.get("executed") and isinstance(result, dict):
        ok = result.get("ok") is False and result.get("code") in (
            "PATH_OUTSIDE_ROOTS",
            "SECRET_FILENAME",
            "NOT_FILE",
        )
    else:
        ok = out.get("executed") is False
    results.append(("shell_read_outside_root", ok, str((result or {}).get("code"))))

    # 5f shell: list under agent-control
    out = host.call("shell.list_dir", {"path": str(ROOT)})
    result = out.get("result") or {}
    ok = out.get("executed") is True and isinstance(result, dict) and result.get("ok") is True
    results.append(("shell_list_agent_control", ok, str((result or {}).get("code"))))

    if live:
        out = host.call("plane.status")
        result = out.get("result") or {}
        ok = out.get("executed") is True and isinstance(result, dict) and result.get("ok") is True
        results.append(("plane_status_live", ok, json.dumps(result.get("claim_ceiling"))[:100] if ok else str(out.get("verdict"))))

        out = host.call("desktop.focus", {"app": "1Password"})
        result = out.get("result") or {}
        # profile or leash deny
        if out.get("executed") and isinstance(result, dict):
            ok = result.get("ok") is False or result.get("code") in (
                "APP_DENIED",
                "PROFILE_DENIED",
                "APP_NOT_ALLOWLISTED",
                "NOT_ARMED",
            )
        else:
            ok = out.get("executed") is False
        results.append(("focus_1password_denied", ok, str((result or out.get("verdict") or {}).get("code"))))

    print("=== agent-control cannot-bypass smoke ===\n")
    all_ok = True
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"  [{mark}] {name}: {detail}")

    print(f"\ncannot_bypass_planes={'PASS' if all_ok else 'FAIL'}")
    print(
        "claim_note: plane tools gated through AssuredPlaneHost; "
        "gated shell.exec (interpreter-free, read-only git, path-confined) now covers "
        "file/test/git inspection; Grok's NATIVE runtime shell is still outside the host "
        "— disable it or route through the host for full coverage."
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(run_smoke(live="--offline" not in sys.argv))
