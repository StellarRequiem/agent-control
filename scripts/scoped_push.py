#!/usr/bin/env python3
"""Push claim-ladder repos to origin (no force). Mediated path only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

HOME = Path.home()

# Public product repos on main only
JOBS: list[tuple[Path, str]] = [
    (HOME / "mcp-assure", "main"),
    (HOME / "agent-control", "main"),
    (HOME / "agent-soc", "main"),
]


def _run(argv: list[str], cwd: Path, timeout: float = 180) -> dict[str, Any]:
    p = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
    )
    return {
        "argv": argv,
        "cwd": str(cwd),
        "returncode": p.returncode,
        "stdout": (p.stdout or "")[:12000],
        "stderr": (p.stderr or "")[:8000],
    }


def push_one(repo: Path, branch: str) -> dict[str, Any]:
    if not (repo / ".git").is_dir():
        return {"ok": False, "repo": str(repo), "code": "NOT_A_GIT_REPO"}
    st = _run(["git", "status", "-sb"], repo)
    # refuse force; plain push of current branch to origin
    # ensure we are on expected branch
    br = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    head = (br.get("stdout") or "").strip()
    if head != branch:
        return {
            "ok": False,
            "repo": str(repo),
            "code": "WRONG_BRANCH",
            "head": head,
            "expected": branch,
            "status": st,
        }
    # never --force
    out = _run(["git", "push", "origin", branch], repo, timeout=300)
    ok = out["returncode"] == 0
    after = _run(["git", "status", "-sb"], repo)
    return {
        "ok": ok,
        "repo": str(repo),
        "code": "PUSHED" if ok else "PUSH_FAILED",
        "branch": branch,
        "push": out,
        "status_before": st,
        "status_after": after,
    }


def main() -> int:
    results = [push_one(repo, branch) for repo, branch in JOBS]
    report = {
        "ok": all(r.get("ok") for r in results),
        "service": "scoped_push",
        "results": results,
        "note": "no force-push; ops chore branch skipped",
    }
    print(json.dumps(report, indent=2)[:60000])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
