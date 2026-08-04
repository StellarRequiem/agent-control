#!/usr/bin/env python3
"""Scoped local commits for claim-ladder sprint (no push).

Runs under mediated path: invoked by proof_suite marker or CLI.
Never pushes. Never amends. Operator-owned repos under $HOME.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HOME = Path.home()

# (repo, paths relative to repo, commit message)
JOBS: list[tuple[Path, list[str], str]] = [
    (
        HOME / "mcp-assure",
        [
            "CLAIMS.md",
            "mcp_assure/engine.py",
            "mcp_assure/receipts.py",
            "tests/test_receipts_chain.py",
        ],
        "Harden receipt chain for multi-writer hosts and recovery\n\n"
        "Re-sync tip under flock on append, skip poison appends on CHAIN_BROKEN, "
        "and add rotate_if_broken so plane recovery can start a clean tip.",
    ),
    (
        HOME / "agent-control",
        [
            ".github/workflows/ci.yml",
            "CLAIMS.md",
            "README.md",
            "docs/CLAIM_LADDER.md",
            "docs/MEDIATED_AMBIENT.md",
            "docs/paper/STRONG_PROOF_BACKLOG.md",
            "host/plane_host.py",
            "host/shell_handlers.py",
            "mcp_server.py",
            "packs/local_planes.json",
            "smoke/proof_suite.py",
            "scripts/scoped_commits.py",
            "tests/test_shell_exec_gate.py",
        ],
        "Ship claim ladder Phase A: recovery tools, CI, mediated git write\n\n"
        "plane.receipts_status/rotate and unfreeze, offline proof board expansion, "
        "CLAIM_LADDER doc, gated git add/commit (no push), scoped commit helper.",
    ),
    (
        HOME / "agent-soc",
        [
            "hit_table.py",
            "corpora/HOLDOUT_DESIGN.md",
            "corpora/gen_labeled_v1.py",
            "corpora/labeled_traces_v1.json",
            "ops_log/README.md",
            "ops_log/TEMPLATE.md",
            "ops_log/2026-W31.md",
        ],
        "Expand synthetic corpus to N=100 and keep holdout tooling\n\n"
        "Add labeled_traces_v1 (v0 + highblast/expanded shapes) plus generator; "
        "ops_log and hit_table --split remain calibration-only, not a published rate.",
    ),
    (
        HOME / "agent-control",
        [
            "docs/THIRD_MACHINE.md",
            "docs/CLAIM_LADDER.md",
            "docs/paper/STRONG_PROOF_BACKLOG.md",
            "smoke/proof_suite.py",
            "scripts/scoped_commits.py",
            "host/shell_handlers.py",
            "tests/test_shell_exec_gate.py",
        ],
        "Document third-machine re-run and keep mediated commit helper current\n\n"
        "THIRD_MACHINE.md for claim ladder R5 evidence; proof_suite markers for "
        "corpus gen and scoped commits.",
    ),
    (
        HOME / "ops",
        [
            "papers/CLAIM_LADDER.md",
            "papers/STRONG_PROOF_BACKLOG.md",
        ],
        "Point ops papers at claim ladder and Phase A backlog completion\n\n"
        "Keep paper folder in sync with agent-control claim-ladder process.",
    ),
]


def _run(argv: list[str], cwd: Path) -> dict[str, Any]:
    p = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=120
    )
    return {
        "argv": argv,
        "cwd": str(cwd),
        "returncode": p.returncode,
        "stdout": (p.stdout or "")[:8000],
        "stderr": (p.stderr or "")[:4000],
    }


def commit_one(repo: Path, paths: list[str], message: str) -> dict[str, Any]:
    if not (repo / ".git").is_dir():
        return {"ok": False, "repo": str(repo), "code": "NOT_A_GIT_REPO"}
    existing = [p for p in paths if (repo / p).exists()]
    if not existing:
        return {"ok": True, "repo": str(repo), "code": "NOTHING_TO_ADD", "paths": paths}
    st = _run(["git", "status", "--short"], repo)
    add = _run(["git", "add", "--"] + existing, repo)
    if add["returncode"] != 0:
        return {"ok": False, "repo": str(repo), "code": "ADD_FAILED", "add": add, "status": st}
    # skip empty commit
    staged = _run(["git", "diff", "--cached", "--stat"], repo)
    if not (staged.get("stdout") or "").strip():
        return {
            "ok": True,
            "repo": str(repo),
            "code": "NOTHING_STAGED",
            "status": st,
            "paths": existing,
        }
    # HEREDOC-equivalent via -m (single paragraph + body)
    parts = message.strip().split("\n\n", 1)
    commit_argv = ["git", "commit", "-m", parts[0]]
    if len(parts) > 1:
        commit_argv.extend(["-m", parts[1]])
    cm = _run(commit_argv, repo)
    head = _run(["git", "log", "-1", "--oneline"], repo)
    return {
        "ok": cm["returncode"] == 0,
        "repo": str(repo),
        "code": "COMMITTED" if cm["returncode"] == 0 else "COMMIT_FAILED",
        "paths": existing,
        "commit": cm,
        "head": (head.get("stdout") or "").strip(),
        "status_before": st,
    }


def main() -> int:
    results = [commit_one(repo, paths, msg) for repo, paths, msg in JOBS]
    # ops pointer (may not be a git repo)
    ops = HOME / "ops"
    ops_note = {"path": str(ops), "git": (ops / ".git").is_dir()}
    report = {
        "ok": all(r.get("ok") for r in results),
        "service": "scoped_commits",
        "results": results,
        "ops": ops_note,
        "note": "local commits only — no push",
    }
    print(json.dumps(report, indent=2)[:50000])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
