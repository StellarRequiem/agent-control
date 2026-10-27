"""Gated shell subset — never ambient bash.

Only workspace-rooted filesystem reads and named allowlisted commands.
Arbitrary shell_exec is intentionally absent from the pack.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

# This package's own install dir — so "read my own tree" works wherever the
# repo is checked out (e.g. a CI runner where it is not under $HOME/agent-control).
# Reading one's own source is benign and on the operator's machine this resolves
# to the same path as Path.home()/"agent-control" below.
_PKG_ROOT = Path(__file__).resolve().parents[1]

# Roots agents may read/list (expand carefully)
DEFAULT_ROOTS = (
    _PKG_ROOT,
    Path.home() / "mcp-assure",
    Path.home() / "agent-control",
    Path.home() / "OPERATOR_PROTOCOL.md",  # exact bootstrap authority file only
    Path.home() / "desktop-leash",
    Path.home() / "browser-leash",
    Path.home() / "portfolio",
    Path.home() / "ops",
    Path.home() / "agent-soc",
    Path.home() / "Forest-Soul-Forge",
    Path.home() / "warrant",  # coordinated-disclosure hunt + local PoC sandbox
    Path.home() / "Documents" / "Codex" / "2026-09-01" / "work-from-security-md-on-origin",
)

# C1 (KOH 2026-10-20): writes use a narrower root set. Authority trees stay readable
# but are not writable through shell.write_file / apply_patch / git writes.
# Same-uid note: ownership/schg still required from operator (see blue review).
WRITE_ROOTS = (
    # C1b (KOH 2026-10-20, PROPOSED): ~/ops, ~/agent-soc, ~/portfolio, ~/desktop-leash,
    # ~/browser-leash removed — they host scripts executed by named commands, so being
    # writable = arbitrary llm01 code via shell.write_file + shell.run (blue verify #14).
    Path.home() / "Forest-Soul-Forge",
    Path.home() / "Documents" / "Codex" / "2026-09-01" / "work-from-security-md-on-origin",
)

# Basename / path fragments that must never be agent-writable even under WRITE_ROOTS.
_WRITE_DENY_NAME_PREFIXES = ("authorize-", "authorize_")
_WRITE_DENY_NAMES = frozenset(
    {
        "authorizations.yaml",
        "allowed_signers",
        "local_planes.json",
        "mcp-http.token",
        "OPERATOR_PROTOCOL.md",
    }
)
_WRITE_DENY_DIR_NAMES = frozenset({".git", "host", "packs", "receipts", "warrant", "mcp-assure", "agent-control"})


def _path_is_write_denied(path: Path) -> str | None:
    """Return a deny code detail if path must not be written, else None."""
    parts = set(path.parts)
    if ".git" in parts:
        return ".git/ path denied for writes"
    name = path.name
    if name in _WRITE_DENY_NAMES:
        return f"authority filename {name!r} not writable"
    if name.startswith(_WRITE_DENY_NAME_PREFIXES):
        return f"authorize script {name!r} not writable"
    # block writes under agent-control / mcp-assure / warrant even if somehow rooted
    home = Path.home()
    for blocked in (
        home / "agent-control",
        home / "mcp-assure",
        home / "warrant",
        _PKG_ROOT,
    ):
        try:
            path.resolve().relative_to(blocked.resolve())
            return f"writes under {blocked} denied (C1 authority tree)"
        except ValueError:
            continue
    return None


# Named commands only — no free-form argv
ALLOW_COMMANDS: dict[str, list[str]] = {
    # Operator-approved offline schema qualification; fixed argv and source pin.
    "qwen_schema_qualify_v7": ["/usr/bin/env","-i","PATH=/usr/bin:/bin","LANG=C.UTF-8","/Users/llm01/mcp-assure/.venv/bin/python","-I","-B","-c","import hashlib, os, stat, sys\nfrom pathlib import Path\np = Path(\"/Users/llm01/Documents/Codex/2026-09-06/plugin-creator-users-llm01-codex-skills-2/outputs/qwen-batch-evaluator-20261011/qualify_schema_v7.py\")\nexpected = \"5a1ee7b5ad6f90326c9ae374ea1ceb8c3eb7f2eef2258ce717c05ed6916fd67b\"\nif len(sys.argv) != 1 or os.getuid() == 0 or p.resolve(strict=True) != p:\n    raise SystemExit(\"NAMED_QUALIFIER_PREFLIGHT_REFUSED\")\nfd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)\ntry:\n    before = os.fstat(fd)\n    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1 or before.st_mode & 0o022 or before.st_size > 65536:\n        raise SystemExit(\"NAMED_QUALIFIER_METADATA_REFUSED\")\n    source = b\"\"\n    while len(source) < 65536:\n        chunk = os.read(fd, 65536-len(source))\n        if not chunk:\n            break\n        source += chunk\n    after = os.fstat(fd)\n    signature = lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_uid,s.st_mode,s.st_nlink)\n    if signature(before) != signature(after) or len(source) != before.st_size:\n        raise SystemExit(\"NAMED_QUALIFIER_CHANGED_DURING_READ\")\nfinally:\n    os.close(fd)\nif hashlib.sha256(source).hexdigest() != expected:\n    raise SystemExit(\"NAMED_QUALIFIER_CHECKSUM_REFUSED\")\nsys.argv = [str(p), \"--self-sha\", expected]\nexec(compile(source, str(p), \"exec\"), {\n    \"__name__\": \"__main__\", \"__file__\": str(p),\n    \"__verified_sha256__\": expected,\n})\n"],
    # Operator sidecar maintenance: fixed argv, clean environment, pinned package only.
    "sidecar_status": ["/usr/bin/env","-i","PATH=/usr/bin:/bin","LANG=C.UTF-8","HOME=/Users/llm01","/opt/homebrew/Cellar/node/26.3.0/bin/node","/Users/llm01/agent-control/sidecar-maintenance/1.0.0/maintenance.mjs","status"],
    "sidecar_test_daily": ["/usr/bin/env","-i","PATH=/usr/bin:/bin","LANG=C.UTF-8","HOME=/Users/llm01","/opt/homebrew/Cellar/node/26.3.0/bin/node","/Users/llm01/agent-control/sidecar-maintenance/1.0.0/maintenance.mjs","daily"],
    "sidecar_test_weekly": ["/usr/bin/env","-i","PATH=/usr/bin:/bin","LANG=C.UTF-8","HOME=/Users/llm01","/opt/homebrew/Cellar/node/26.3.0/bin/node","/Users/llm01/agent-control/sidecar-maintenance/1.0.0/maintenance.mjs","weekly"],
    "git_status": ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=", "-c", "diff.external=", "status", "--short"],
    "git_diff_stat": ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=", "-c", "diff.external=", "diff", "--no-ext-diff", "--no-textconv", "--stat"],
    "git_log": ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=", "-c", "diff.external=", "log", "--no-ext-diff", "--no-textconv", "-5", "--oneline"],
    "mcp_assure_status": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "mcp-assure"),
        "status",
    ],
    "mcp_assure_check": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "mcp-assure"),
        "check",
    ],
    # 10.10 probe rail — named argv only (no free-form python3)
    # C1b removed: "probe_validate" — executed script under former WRITE_ROOTS
    # C1b removed: "probe_validate_ok" — executed script under former WRITE_ROOTS
    # C1b removed: "probe_validate_bad" — executed script under former WRITE_ROOTS
    # C1b removed: "probe_selftest" — executed script under former WRITE_ROOTS
    "blue_apex_tail": [
        "tail",
        "-n",
        "5",
        str(Path.home() / "blue-vaccine" / "incidents" / "daily-scan.log"),
    ],
    "soc_latest": [
        "ls",
        "-1",
        str(Path.home() / "agent-soc" / "incidents"),
    ],
    "agent_control_smoke": [
        "python3",
        str(Path.home() / "agent-control" / "cli.py"),
        "smoke",
    ],
    "agent_control_proof_offline": [
        "python3",
        str(Path.home() / "agent-control" / "smoke" / "proof_suite.py"),
        "--offline",
    ],
    # C1b removed: "agent_soc_purple" — executed script under former WRITE_ROOTS
    # C1b removed: "agent_soc_hit_table" — executed script under former WRITE_ROOTS
    # agent-soc verification surface (named only — interpreters not on shell.exec)
    # C1b removed: "agent_soc_pytest" — executed script under former WRITE_ROOTS
    # C1b removed: "agent_soc_agentic_cycle_dry" — executed script under former WRITE_ROOTS
    # C1b removed: "agent_soc_respond_dry" — executed script under former WRITE_ROOTS
    "agent_control_session": [
        "python3",
        str(Path.home() / "agent-control" / "cli.py"),
        "session",
    ],
    "agent_control_pytest": [
        # system python3 may lack pytest; reuse mcp-assure venv (has pytest)
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        str(Path.home() / "agent-control" / "tests"),
    ],
    "claude_control_verify": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "claude-control" / "scripts" / "verify_slice.py"),
    ],
    "claude_control_pytest": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        str(Path.home() / "claude-control" / "tests"),
    ],
    "mcp_assure_pytest": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
        str(Path.home() / "mcp-assure" / "tests"),
    ],
    # Local site preview (loopback static server for ~/portfolio) — visual pass without file://
    # C1b removed: "portfolio_nav_inject" — executed script under former WRITE_ROOTS
    "portfolio_preview_start": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "agent-control" / "scripts" / "portfolio_preview.py"),
        "start",
    ],
    "portfolio_preview_stop": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "agent-control" / "scripts" / "portfolio_preview.py"),
        "stop",
    ],
    "portfolio_preview_status": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "agent-control" / "scripts" / "portfolio_preview.py"),
        "status",
    ],
    # Pages deploy: push portfolio main only (no force). Operator must have approved ship.
    # C1 removed: "portfolio_ship_crown_jewel" — script/token path was agent-reachable
    # C1 removed: "portfolio_git_push" — script/token path was agent-reachable
    # session-bus median plane (Grok Build ↔ light clients)
    "session_bus_status": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "cli.py"),
        "status",
    ],
    # C1 removed: "session_bus_token" — script/token path was agent-reachable
    "session_bus_prepare_phone": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "prepare_phone_session.py"),
    ],
    "session_bus_build_reply": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "build_reply.py"),
    ],
    "session_bus_ack_ios": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "ack_last_ios.py"),
    ],
    "session_bus_monitor": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "monitor.py"),
        "--lines",
        "30",
    ],
    "session_bus_monitor_alerts": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "monitor.py"),
        "--alerts",
        "--lines",
        "40",
    ],
    "session_bus_sensor_up": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "sensor_up.sh"),
    ],
    "session_bus_sensor_down": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "sensor_down.sh"),
    ],
    "session_bus_sensor_status": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "access_sensor.py"),
        "status",
        "--window",
        "86400",
    ],
    "session_bus_watch_up": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "watch_up.sh"),
    ],
    "session_bus_watch_down": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "watch_down.sh"),
    ],
    "session_bus_rebind_v2": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "rebind_v2_skills.py"),
    ],
    "session_bus_watch_restart": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "watch_restart.sh"),
    ],
    "session_bus_create": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "cli.py"),
        "create",
        "--actor",
        "build",
        "--label",
        "agent-control",
    ],
    "session_bus_list": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "cli.py"),
        "list",
    ],
    "session_bus_pytest": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        str(Path.home() / "session-bus" / "tests"),
    ],
    "session_bus_up": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "up.sh"),
    ],
    "session_bus_smoke": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "smoke_http.py"),
    ],
    "session_bus_smoke_v2": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "smoke_v2_propose.py"),
    ],
    "session_bus_device_enroll": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "device_enroll.py"),
    ],
    # Alias: operator language is "session bind" (not rewind)
    "session_bus_bind": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "device_enroll.py"),
    ],
    "session_bus_totp_setup": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "totp_setup.py"),
        "--open",
    ],
    "session_bus_mail_status": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "mail_status.py"),
    ],
    "session_bus_mail_diagnose": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "mail_diagnose.py"),
    ],
    "session_bus_mcp_up": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "mcp_up.sh"),
    ],
    "session_bus_mcp_restart": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "mcp_restart.sh"),
    ],
    "session_bus_mcp_tunnel": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "mcp_tunnel.sh"),
    ],
    "session_bus_mcp_smoke": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "smoke_mcp.py"),
    ],
    "session_bus_smoke_work": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "smoke_session_work.py"),
    ],
    "session_bus_mcp_public_smoke": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "smoke_mcp_public.py"),
    ],
    "session_bus_rewind": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "session_rewind.py"),
    ],
    "session_bus_rewind_full": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "session_rewind.py"),
        "full",
    ],
    "tailscale_ip": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "tailscale_ip.sh"),
    ],
    "session_bus_up_tailscale": [
        "/bin/bash",
        str(Path.home() / "session-bus" / "scripts" / "restart_tailscale.sh"),
    ],
    "session_bus_resolve_bind": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "scripts" / "resolve_bind.py"),
    ],
    # Maw Detect (T1) — local blue-team; read-only
    "maw_pytest": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        str(Path.home() / "maw" / "tests"),
    ],
    "maw_detect_smoke": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "maw" / "scripts" / "detect_smoke.py"),
    ],
    "maw_install_gate_status": [
        "/bin/bash",
        str(Path.home() / "maw" / "scripts" / "run_install_gate.sh"),
        "status",
    ],
    # C1 removed: "maw_install_gate_clear" — script/token path was agent-reachable

    # Bridge / leash health (absolute paths — thin PATH safe)
    # C1b removed: "browser_leash_status" — executed script under former WRITE_ROOTS
    # C1b removed: "browser_leash_restart" — executed script under former WRITE_ROOTS
    # C1b removed: "desktop_leash_restart" — executed script under former WRITE_ROOTS
    # C1b removed: "browser_leash_pytest" — executed script under former WRITE_ROOTS
    "open_grok_connectors": [
        "open",
        "-a",
        "Google Chrome",
        "https://grok.com/connectors",
    ],
    "open_chrome_extensions": [
        "open",
        "-a",
        "Google Chrome",
        "chrome://extensions",
    ],
    # C1b removed: "desktop_leash_status" — executed script under former WRITE_ROOTS
    "agent_control_stack": [
        "python3",
        str(Path.home() / "agent-control" / "cli.py"),
        "stack",
    ],
    # warrant SEQ2 — local fastapi_mcp PoC matrix (TestClient / 127.0.0.1 only)
    "warrant_fastapi_mcp_poc": [
        str(Path.home() / "warrant" / ".venv" / "bin" / "python"),
        str(Path.home() / "warrant" / "bughunt" / "sandbox" / "fastapi-mcp-poc" / "run_all.py"),
    ],
}

MAX_READ_BYTES = 64_000
MAX_LIST = 200
MAX_WRITE_BYTES = 1_000_000  # gated writes are for source/config, not blobs

# --- gated shell.exec: validated argv, never a shell string -----------------
# The whole point is to give Grok a *host-gated* path for the file/test/git work
# the router used to send to its ungated NATIVE shell. Security is by
# construction, not by blocklisting a shell string:
#   * shell=False always — argv is passed to execve, so ; | & $ ` are inert
#     literals, not operators. There is no shell to interpret them.
#   * INTERPRETERS ARE INTENTIONALLY ABSENT. Allowlisting python/node/bash would
#     make `python3 -c "..."` a total bypass, so an executable allowlist that
#     included them would be a false gate.
#   * only read/inspect binaries, with per-binary escape hatches denied.
SAFE_EXECUTABLES = frozenset(
    {"git", "ls", "cat", "head", "tail", "wc", "rg", "grep", "find", "echo", "true"}
)
# blocked even if someone adds them — these run arbitrary code from an arg
INTERPRETERS = frozenset(
    {"python", "python3", "node", "bash", "sh", "zsh", "ruby", "perl",
     "awk", "gawk", "env", "xargs", "eval", "make", "npm", "pip", "pip3"}
)
# arg-level escape hatches on otherwise-safe binaries (find -exec, git -c, …)
DANGEROUS_FLAGS = frozenset(
    {"-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprintf", "-fprint",
     "-c", "-C", "--exec-path", "--upload-pack", "--receive-pack",
     "-e", "--eval", "-o", "--output", "-O"}
)
# git read — inspection only
GIT_READ_SUBCMDS = frozenset(
    {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files",
     "describe", "blame", "shortlog", "tag", "remote"}
)
# local write only — never push/fetch/config/reset/clean (claim ladder: mediated commits)
GIT_LOCAL_WRITE_SUBCMDS = frozenset({"add", "commit"})
GIT_ALLOWED_SUBCMDS = GIT_READ_SUBCMDS | GIT_LOCAL_WRITE_SUBCMDS
# commit flags we refuse (history rewrite / hooks / signing via custom)
GIT_COMMIT_DENIED_FLAGS = frozenset(
    {
        "--amend",
        "--no-verify",
        "-n",
        "--allow-empty",
        "--allow-empty-message",
        "-F",
        "--file",
        "-t",
        "--template",
        "--exec",
        "-e",
        "--edit",
        "--author",
        "--date",
        "-S",
        "--gpg-sign",
        "--no-gpg-sign",
    }
)
MAX_ARGV = 40
MAX_TOKEN = 512
MAX_COMMIT_MSG = 2000


class ShellHandlers:
    def __init__(self, roots: tuple[Path, ...] | None = None, write_roots: tuple[Path, ...] | None = None) -> None:
        self.roots = tuple(r.resolve() for r in (roots or DEFAULT_ROOTS) if r.exists() or True)
        self.write_roots = tuple(
            r.resolve() for r in (write_roots or WRITE_ROOTS) if r.exists() or True
        )

    def _resolve_under_root(self, path_str: str) -> Path | dict[str, Any]:
        raw = (path_str or "").strip()
        if not raw:
            return {"ok": False, "code": "PATH_REQUIRED", "detail": "path required"}
        if ".." in Path(raw).parts:
            return {"ok": False, "code": "PATH_TRAVERSAL", "detail": "parent segments denied"}
        p = Path(raw).expanduser()
        if not p.is_absolute():
            # relative → try under each root
            for root in self.roots:
                cand = (root / p).resolve()
                try:
                    cand.relative_to(root.resolve())
                except ValueError:
                    continue
                if cand.exists() or cand.parent.exists():
                    return cand
            return {
                "ok": False,
                "code": "PATH_OUTSIDE_ROOTS",
                "detail": f"relative path not under allowed roots",
                "roots": [str(r) for r in self.roots],
            }
        p = p.resolve()
        for root in self.roots:
            try:
                p.relative_to(root.resolve())
                return p
            except ValueError:
                continue
        return {
            "ok": False,
            "code": "PATH_OUTSIDE_ROOTS",
            "detail": f"{p} not under allowed roots",
            "roots": [str(r) for r in self.roots],
        }

    def _resolve_under_write_root(self, path_str: str) -> Path | dict[str, Any]:
        """Like _resolve_under_root but confined to WRITE_ROOTS + C1 denylist."""
        resolved = self._resolve_under_root(path_str)
        if isinstance(resolved, dict):
            return resolved
        # Must also sit under a write root
        ok_write = False
        for root in self.write_roots:
            try:
                resolved.relative_to(root.resolve())
                ok_write = True
                break
            except ValueError:
                continue
        if not ok_write:
            return {
                "ok": False,
                "code": "PATH_OUTSIDE_WRITE_ROOTS",
                "detail": f"{resolved} not under write roots (C1)",
                "write_roots": [str(r) for r in self.write_roots],
                "read_roots": [str(r) for r in self.roots],
            }
        denied = _path_is_write_denied(resolved)
        if denied:
            return {"ok": False, "code": "WRITE_DENIED_AUTHORITY", "detail": denied}
        return resolved

    def _atomic_write_text(self, path: Path, content: str) -> dict[str, Any] | None:
        """Write via O_NOFOLLOW on final component; refuse nlink>1. Returns error dict or None."""
        import stat as statmod

        parent = path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "code": "WRITE_FAIL", "detail": str(e)}
        # Refuse if existing path is a symlink
        if path.exists() or path.is_symlink():
            try:
                st = path.lstat()
            except OSError as e:
                return {"ok": False, "code": "WRITE_FAIL", "detail": str(e)}
            if statmod.S_ISLNK(st.st_mode):
                return {"ok": False, "code": "SYMLINK_DENIED", "detail": "refusing write through symlink"}
            if st.st_nlink > 1:
                return {"ok": False, "code": "HARDLINK_DENIED", "detail": "st_nlink > 1"}
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(str(path), flags, 0o644)
        except OSError as e:
            return {"ok": False, "code": "WRITE_FAIL", "detail": f"open: {e}"}
        try:
            st = os.fstat(fd)
            if st.st_nlink > 1:
                return {"ok": False, "code": "HARDLINK_DENIED", "detail": "st_nlink > 1 after open"}
            # Confirm realpath still under write root (TOCTOU narrow)
            real = Path(os.path.realpath(str(path)))
            denied = _path_is_write_denied(real)
            if denied:
                return {"ok": False, "code": "WRITE_DENIED_AUTHORITY", "detail": denied}
            data = content.encode("utf-8")
            os.write(fd, data)
        except OSError as e:
            return {"ok": False, "code": "WRITE_FAIL", "detail": str(e)}
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        return None

    def roots_list(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "code": "SHELL_ROOTS",
            "data": {
                "roots": [str(r) for r in self.roots],
                "write_roots": [str(r) for r in self.write_roots],
                "commands": sorted(ALLOW_COMMANDS),
                "note": "C1: read roots vs write_roots split; no ambient shell_exec — named commands only",
                "native_edit_bypass": "file_edit_tools_native must be false in client config (operator) — plane cannot close native edits alone",
            },
        }

    def list_dir(self, args: dict[str, Any]) -> dict[str, Any]:
        resolved = self._resolve_under_root(str(args.get("path") or ""))
        if isinstance(resolved, dict):
            return resolved
        if not resolved.is_dir():
            return {"ok": False, "code": "NOT_DIR", "detail": str(resolved)}
        entries = []
        try:
            for i, child in enumerate(sorted(resolved.iterdir(), key=lambda x: x.name.lower())):
                if i >= MAX_LIST:
                    break
                entries.append(
                    {
                        "name": child.name,
                        "is_dir": child.is_dir(),
                        "size": child.stat().st_size if child.is_file() else None,
                    }
                )
        except OSError as e:
            return {"ok": False, "code": "LIST_FAIL", "detail": str(e)}
        return {
            "ok": True,
            "code": "LISTED",
            "data": {"path": str(resolved), "entries": entries, "count": len(entries)},
        }

    def read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        resolved = self._resolve_under_root(str(args.get("path") or ""))
        if isinstance(resolved, dict):
            return resolved
        if not resolved.is_file():
            return {"ok": False, "code": "NOT_FILE", "detail": str(resolved)}
        # block obvious secret filenames
        name = resolved.name.lower()
        if any(x in name for x in (".pem", ".key", "id_rsa", "credentials", ".env", "secret")):
            return {
                "ok": False,
                "code": "SECRET_FILENAME",
                "detail": "path looks secret-shaped — refused by shell gate",
            }
        try:
            data = resolved.read_bytes()[:MAX_READ_BYTES]
            text = data.decode("utf-8", errors="replace")
        except OSError as e:
            return {"ok": False, "code": "READ_FAIL", "detail": str(e)}
        return {
            "ok": True,
            "code": "READ",
            "data": {
                "path": str(resolved),
                "bytes": len(data),
                "truncated": resolved.stat().st_size > MAX_READ_BYTES,
                "text": text,
            },
        }

    def write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        """Write content to a file UNDER an allowed root only.

        The mediated alternative to native edit tools (G1): path-confined (no
        traversal, no absolute-outside-root), secret-filename-refused, size-capped,
        and — because `shell.write_file` is deliberately NOT in freeze_allow — blocked
        under FREEZE. Adding this closes the "file edits bypass the gate" hole; it
        does not weaken deny-by-default (writes stay inside the same rooted policy as
        reads).
        """
        resolved = self._resolve_under_write_root(str(args.get("path") or ""))
        if isinstance(resolved, dict):
            return resolved
        content = args.get("content")
        if not isinstance(content, str):
            return {"ok": False, "code": "CONTENT_REQUIRED", "detail": "content must be a string"}
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return {"ok": False, "code": "CONTENT_TOO_LARGE", "detail": f"max {MAX_WRITE_BYTES} bytes"}
        # never write onto a secret-shaped filename (mirror the read-side fence)
        name = resolved.name.lower()
        if any(x in name for x in (".pem", ".key", "id_rsa", "credentials", ".env", "secret", "token")):
            return {"ok": False, "code": "SECRET_FILENAME", "detail": "path looks secret-shaped — refused by shell gate"}
        if resolved.exists() and resolved.is_dir():
            return {"ok": False, "code": "IS_DIR", "detail": str(resolved)}
        mode = str(args.get("mode") or "overwrite")
        if mode not in ("overwrite", "create"):
            return {"ok": False, "code": "BAD_MODE", "detail": "mode must be overwrite|create"}
        if mode == "create" and resolved.exists():
            return {"ok": False, "code": "EXISTS", "detail": "create mode: file exists"}
        err = self._atomic_write_text(resolved, content)
        if err is not None:
            return err
        return {
            "ok": True,
            "code": "WROTE",
            "data": {"path": str(resolved), "bytes": len(content.encode("utf-8")), "mode": mode},
        }

    def apply_patch(self, args: dict[str, Any]) -> dict[str, Any]:
        """Single-file str replace under an allowed root (mediated StrReplace analog).

        Requires exact one match of old_string unless replace_all=true.
        Same path/secret/size fences as write_file; blocked under FREEZE (not freeze_allow).
        """
        resolved = self._resolve_under_write_root(str(args.get("path") or ""))
        if isinstance(resolved, dict):
            return resolved
        if not resolved.is_file():
            return {"ok": False, "code": "NOT_FILE", "detail": str(resolved)}
        name = resolved.name.lower()
        if any(x in name for x in (".pem", ".key", "id_rsa", "credentials", ".env", "secret", "token")):
            return {
                "ok": False,
                "code": "SECRET_FILENAME",
                "detail": "path looks secret-shaped — refused by shell gate",
            }
        old = args.get("old_string")
        new = args.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return {
                "ok": False,
                "code": "PATCH_REQUIRED",
                "detail": "old_string and new_string must be strings",
            }
        if old == "":
            return {"ok": False, "code": "EMPTY_OLD", "detail": "old_string must be non-empty"}
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as e:
            return {"ok": False, "code": "READ_FAIL", "detail": str(e)}
        count = text.count(old)
        replace_all = bool(args.get("replace_all"))
        if count == 0:
            return {"ok": False, "code": "NO_MATCH", "detail": "old_string not found"}
        if count > 1 and not replace_all:
            return {
                "ok": False,
                "code": "AMBIGUOUS_MATCH",
                "detail": f"old_string matches {count} times — set replace_all=true or narrow context",
            }
        if replace_all:
            out_text = text.replace(old, new)
            n = count
        else:
            out_text = text.replace(old, new, 1)
            n = 1
        if len(out_text.encode("utf-8")) > MAX_WRITE_BYTES:
            return {"ok": False, "code": "CONTENT_TOO_LARGE", "detail": f"max {MAX_WRITE_BYTES} bytes"}
        err = self._atomic_write_text(resolved, out_text)
        if err is not None:
            return err
        return {
            "ok": True,
            "code": "PATCHED",
            "data": {
                "path": str(resolved),
                "replacements": n,
                "bytes": len(out_text.encode("utf-8")),
            },
        }

    def stat(self, args: dict[str, Any]) -> dict[str, Any]:
        resolved = self._resolve_under_root(str(args.get("path") or ""))
        if isinstance(resolved, dict):
            return resolved
        if not resolved.exists():
            return {"ok": False, "code": "NOT_FOUND", "detail": str(resolved)}
        st = resolved.stat()
        return {
            "ok": True,
            "code": "STAT",
            "data": {
                "path": str(resolved),
                "is_dir": resolved.is_dir(),
                "is_file": resolved.is_file(),
                "size": st.st_size,
                "mtime": st.st_mtime,
            },
        }

    def exec(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run a validated argv (never a shell string) through the gate.

        Deny-by-default: interpreter-free executable allowlist, per-binary
        dangerous-flag denylist, git read + local add/commit only (no push),
        path confinement (no absolute paths, no parent traversal), rooted cwd,
        shell=False. NOT a general bash.
        """
        argv = args.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(t, str) for t in argv):
            return {"ok": False, "code": "ARGV_REQUIRED", "detail": "argv must be a non-empty list of strings"}
        if len(argv) > MAX_ARGV:
            return {"ok": False, "code": "ARGV_TOO_LONG", "detail": f"max {MAX_ARGV} tokens"}
        if any(len(t) > MAX_TOKEN for t in argv):
            return {"ok": False, "code": "TOKEN_TOO_LONG", "detail": f"max {MAX_TOKEN} bytes/token"}

        exe = Path(argv[0]).name
        if exe in INTERPRETERS:
            return {"ok": False, "code": "INTERPRETER_DENIED",
                    "detail": f"{exe!r} can run arbitrary code from an argument — not gatable via exec"}
        if exe not in SAFE_EXECUTABLES:
            return {"ok": False, "code": "EXECUTABLE_NOT_ALLOWLISTED",
                    "detail": f"{exe!r} not allowlisted", "allowed": sorted(SAFE_EXECUTABLES)}

        # per-token: dangerous flags, absolute paths, parent traversal, newlines
        for tok in argv[1:]:
            if tok in DANGEROUS_FLAGS:
                return {"ok": False, "code": "DANGEROUS_FLAG", "detail": f"flag {tok!r} can execute or escape scope"}
            if "\n" in tok or "\r" in tok:
                return {"ok": False, "code": "NEWLINE_IN_ARG", "detail": "newline in argument"}
            if tok.startswith("/"):
                return {"ok": False, "code": "ABSOLUTE_PATH_DENIED",
                        "detail": f"absolute path {tok!r} — args must be relative to a rooted cwd"}
            if ".." in Path(tok).parts:
                return {"ok": False, "code": "PATH_TRAVERSAL", "detail": f"parent segment in {tok!r}"}

        if exe == "git":
            git_err = self._validate_git_argv(argv)
            if git_err is not None:
                return git_err

        # cwd: explicit (rooted) or first git root / package root
        cwd_arg = str(args.get("cwd") or "").strip()
        if cwd_arg:
            resolved = self._resolve_under_root(cwd_arg)
            if isinstance(resolved, dict):
                return resolved
            if not resolved.is_dir():
                return {"ok": False, "code": "CWD_NOT_DIR", "detail": str(resolved)}
            # C1c: fixed C1b NameError (`name` undefined in exec). Only git (hardened
            # below) may run with a cwd inside an agent-writable root.
            if exe != "git":
                for wr in self.write_roots:
                    try:
                        resolved.resolve().relative_to(wr)
                        return {"ok": False, "code": "CWD_IN_WRITE_ROOT", "detail": str(resolved)}
                    except ValueError:
                        continue
            cwd = str(resolved)
        else:
            cwd = None
            for r in self.roots:
                if (r / ".git").exists():
                    cwd = str(r)
                    break
            if cwd is None:
                cwd = str(_PKG_ROOT)

        run_argv = list(argv)
        if exe == "git":
            # C1: neutralize hooks / fsmonitor even if .git was somehow writable
            # C1c: also blank fsmonitor / diff.external; no ext-diff / textconv for diff/log/show
            run_argv = [argv[0], "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=",
                        "-c", "diff.external=", argv[1]]
            if argv[1] in ("diff", "log", "show"):
                run_argv += ["--no-ext-diff", "--no-textconv"]
            run_argv += argv[2:]
        try:
            p = subprocess.run(
                run_argv, cwd=cwd, capture_output=True, text=True, timeout=60, shell=False
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "code": "TIMEOUT", "detail": " ".join(argv[:3])}
        except FileNotFoundError as e:
            return {"ok": False, "code": "EXEC_MISSING", "detail": str(e)}

        return {
            "ok": p.returncode == 0,
            "code": "RAN" if p.returncode == 0 else "NONZERO",
            "data": {
                "argv": list(argv),
                "cwd": cwd,
                "returncode": p.returncode,
                "stdout": (p.stdout or "")[:20000],
                "stderr": (p.stderr or "")[:5000],
            },
        }

    def _validate_git_argv(self, argv: list[str]) -> dict[str, Any] | None:
        """Allow read + local add/commit; hard-deny push and escape hatches."""
        sub = argv[1] if len(argv) > 1 else ""
        if sub not in GIT_ALLOWED_SUBCMDS:
            return {
                "ok": False,
                "code": "GIT_SUBCOMMAND_DENIED",
                "detail": f"git {sub!r} not allowed (read + local add/commit only; no push)",
                "allowed": sorted(GIT_ALLOWED_SUBCMDS),
            }
        if sub == "commit":
            if "-m" not in argv:
                return {
                    "ok": False,
                    "code": "GIT_COMMIT_MSG_REQUIRED",
                    "detail": "git commit requires -m <message> (no editor / -F)",
                }
            for tok in argv[2:]:
                if tok in GIT_COMMIT_DENIED_FLAGS or tok.startswith("--amend"):
                    return {
                        "ok": False,
                        "code": "GIT_COMMIT_FLAG_DENIED",
                        "detail": f"commit flag {tok!r} denied",
                    }
            # message length after each -m
            i = 0
            while i < len(argv):
                if argv[i] == "-m" and i + 1 < len(argv):
                    if len(argv[i + 1]) > MAX_COMMIT_MSG:
                        return {
                            "ok": False,
                            "code": "GIT_COMMIT_MSG_TOO_LONG",
                            "detail": f"max {MAX_COMMIT_MSG} chars",
                        }
                    i += 2
                    continue
                i += 1
        if sub == "add":
            # refuse magic pathspecs that escape; deny .git writes
            for tok in argv[2:]:
                if ".git" in Path(tok).parts or tok.startswith(".git"):
                    return {
                        "ok": False,
                        "code": "GIT_DOTGIT_DENIED",
                        "detail": ".git pathspecs denied (C1)",
                    }
                if tok.startswith(":") or tok.startswith("-") and tok not in (
                    "-A",
                    "--all",
                    "-u",
                    "--update",
                    "-n",
                    "--dry-run",
                    "-v",
                    "--verbose",
                    "-f",
                    "--force",
                ):
                    if tok.startswith("-"):
                        return {
                            "ok": False,
                            "code": "GIT_ADD_FLAG_DENIED",
                            "detail": f"git add flag {tok!r} denied",
                        }
        return None

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run a *named* allowlisted command only."""
        name = str(args.get("name") or "").strip()
        if name == "qwen_schema_qualify_v7" and (set(args) != {"name"} or args.get("name") != name):
            return {"ok": False, "code": "FIXED_JOB_ARGUMENTS_REQUIRED"}
        if name not in ALLOW_COMMANDS:
            return {
                "ok": False,
                "code": "COMMAND_NOT_ALLOWLISTED",
                "detail": f"unknown command {name!r}",
                "allowed": sorted(ALLOW_COMMANDS),
            }
        cwd_arg = str(args.get("cwd") or "").strip()
        cwd: str | None = None
        if cwd_arg:
            resolved = self._resolve_under_root(cwd_arg)
            if isinstance(resolved, dict):
                return resolved
            if not resolved.is_dir():
                return {"ok": False, "code": "CWD_NOT_DIR", "detail": str(resolved)}
            # C1b: cwd inside an agent-writable root lets `python -m pytest` / `python -m X`
            # import agent-planted modules (cwd is on sys.path). Only git_* may use it.
            if not name.startswith("git_"):
                for wr in self.write_roots:
                    try:
                        resolved.resolve().relative_to(wr)
                        return {"ok": False, "code": "CWD_IN_WRITE_ROOT", "detail": str(resolved)}
                    except ValueError:
                        continue
            cwd = str(resolved)
        else:
            # default cwd for git_* → first existing project root
            if name.startswith("git_"):
                for r in self.roots:
                    if (r / ".git").exists():
                        cwd = str(r)
                        break
            if name.startswith("mcp_assure"):
                cwd = str(Path.home() / "mcp-assure")
            if name.startswith("warrant_"):
                cwd = str(Path.home() / "warrant")

        cmd = list(ALLOW_COMMANDS[name])
        # Skip if mcp-assure binary missing
        if name.startswith("mcp_assure") and not Path(cmd[0]).exists():
            cmd = ["python3", "-m", "mcp_assure", cmd[-1]]
            env = {**os.environ, "PYTHONPATH": str(Path.home() / "mcp-assure")}
        elif name == "warrant_fastapi_mcp_poc":
            # Prefer warrant venv; fall back to system python3 if missing
            if not Path(cmd[0]).exists():
                cmd[0] = "python3"
            hunt = str(Path.home() / "warrant" / "hunts" / "fastapi_mcp")
            warrant = str(Path.home() / "warrant")
            pp = os.pathsep.join([hunt, warrant, os.environ.get("PYTHONPATH", "")]).strip(
                os.pathsep
            )
            env = {**os.environ, "PYTHONPATH": pp}
            cwd = str(Path.home() / "warrant" / "bughunt" / "sandbox" / "fastapi-mcp-poc")
        else:
            env = None

        # PoC matrix may bootstrap a throwaway venv — allow longer runtime
        timeout = 300 if name == "warrant_fastapi_mcp_poc" else 120

        try:
            p = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "code": "TIMEOUT", "detail": name}
        except FileNotFoundError as e:
            return {"ok": False, "code": "EXEC_MISSING", "detail": str(e)}

        return {
            "ok": p.returncode == 0,
            "code": "RAN" if p.returncode == 0 else "NONZERO",
            "data": {
                "name": name,
                "cmd": cmd,
                "cwd": cwd,
                "returncode": p.returncode,
                "stdout": (p.stdout or "")[:20000],
                "stderr": (p.stderr or "")[:5000],
            },
        }
