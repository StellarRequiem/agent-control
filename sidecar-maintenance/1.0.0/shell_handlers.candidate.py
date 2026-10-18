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

# Named commands only — no free-form argv
ALLOW_COMMANDS: dict[str, list[str]] = {
    # Operator sidecar maintenance: fixed argv, clean environment, pinned package only.
    "sidecar_status": ["/usr/bin/env","-i","PATH=/usr/bin:/bin","LANG=C.UTF-8","HOME=/Users/llm01","/opt/homebrew/Cellar/node/26.3.0/bin/node","/Users/llm01/agent-control/sidecar-maintenance/1.0.0/maintenance.mjs","status"],
    "sidecar_test_daily": ["/usr/bin/env","-i","PATH=/usr/bin:/bin","LANG=C.UTF-8","HOME=/Users/llm01","/opt/homebrew/Cellar/node/26.3.0/bin/node","/Users/llm01/agent-control/sidecar-maintenance/1.0.0/maintenance.mjs","daily"],
    "sidecar_test_weekly": ["/usr/bin/env","-i","PATH=/usr/bin:/bin","LANG=C.UTF-8","HOME=/Users/llm01","/opt/homebrew/Cellar/node/26.3.0/bin/node","/Users/llm01/agent-control/sidecar-maintenance/1.0.0/maintenance.mjs","weekly"],
    "git_status": ["git", "status", "--short"],
    "git_diff_stat": ["git", "diff", "--stat"],
    "git_log": ["git", "log", "-5", "--oneline"],
    "mcp_assure_status": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "mcp-assure"),
        "status",
    ],
    "mcp_assure_check": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "mcp-assure"),
        "check",
    ],
    # 10.10 probe rail — named argv only (no free-form python3)
    "probe_validate": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "ops" / "probes" / "validate_result.py"),
        str(Path.home() / "ops" / "probes" / "results" / "latest.json"),
    ],
    "probe_validate_ok": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "ops" / "probes" / "validate_result.py"),
        str(Path.home() / "ops" / "probes" / "fixtures" / "ok-soc-empty.json"),
    ],
    "probe_validate_bad": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "ops" / "probes" / "validate_result.py"),
        str(Path.home() / "ops" / "probes" / "fixtures" / "bad-apex-greenwash.json"),
    ],
    "probe_selftest": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "ops" / "probes" / "selftest.py"),
    ],
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
    "agent_soc_purple": [
        "python3",
        str(Path.home() / "agent-soc" / "purple.py"),
    ],
    "agent_soc_hit_table": [
        "python3",
        str(Path.home() / "agent-soc" / "hit_table.py"),
    ],
    # agent-soc verification surface (named only — interpreters not on shell.exec)
    "agent_soc_pytest": [
        # system python3 may lack pytest; reuse mcp-assure venv (has pytest)
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        str(Path.home() / "agent-soc" / "tests"),
    ],
    "agent_soc_agentic_cycle_dry": [
        "python3",
        str(Path.home() / "agent-soc" / "cli.py"),
        "agentic",
        "cycle",
        "--dry-run",
    ],
    "agent_soc_respond_dry": [
        "python3",
        str(Path.home() / "agent-soc" / "cli.py"),
        "respond",
        "--dry-run",
        "--reason",
        "test",
    ],
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
    "portfolio_nav_inject": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "portfolio" / "_nav" / "inject.py"),
    ],
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
    "portfolio_ship_crown_jewel": [
        "/bin/bash",
        str(Path.home() / "portfolio" / "scripts" / "ship_crown_jewel.sh"),
    ],
    "portfolio_git_push": [
        "git",
        "-C",
        str(Path.home() / "portfolio"),
        "push",
        "origin",
        "main",
    ],
    # session-bus median plane (Grok Build ↔ light clients)
    "session_bus_status": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "cli.py"),
        "status",
    ],
    "session_bus_token": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "session-bus" / "cli.py"),
        "token",
    ],
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
    "maw_install_gate_clear": [
        "/bin/bash",
        str(Path.home() / "maw" / "scripts" / "run_install_gate.sh"),
        "clear",
        "--operator-confirm",
    ],

    # Bridge / leash health (absolute paths — thin PATH safe)
    "browser_leash_status": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "browser-leash" / "bridge" / "client.py"),
        "status",
    ],
    "browser_leash_restart": [
        "/bin/bash",
        str(Path.home() / "browser-leash" / "scripts" / "restart_bridge.sh"),
    ],
    "desktop_leash_restart": [
        "/bin/bash",
        str(Path.home() / "desktop-leash" / "scripts" / "restart_bridge.sh"),
    ],
    "browser_leash_pytest": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        str(Path.home() / "browser-leash" / "tests"),
    ],
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
    "desktop_leash_status": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        str(Path.home() / "desktop-leash" / "bridge" / "client.py"),
        "status",
    ],
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
    def __init__(self, roots: tuple[Path, ...] | None = None) -> None:
        self.roots = tuple(r.resolve() for r in (roots or DEFAULT_ROOTS) if r.exists() or True)

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

    def roots_list(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "code": "SHELL_ROOTS",
            "data": {
                "roots": [str(r) for r in self.roots],
                "commands": sorted(ALLOW_COMMANDS),
                "note": "no ambient shell_exec — named commands only",
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
        resolved = self._resolve_under_root(str(args.get("path") or ""))
        if isinstance(resolved, dict):
            return resolved
        content = args.get("content")
        if not isinstance(content, str):
            return {"ok": False, "code": "CONTENT_REQUIRED", "detail": "content must be a string"}
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return {"ok": False, "code": "CONTENT_TOO_LARGE", "detail": f"max {MAX_WRITE_BYTES} bytes"}
        # never write onto a secret-shaped filename (mirror the read-side fence)
        name = resolved.name.lower()
        if any(x in name for x in (".pem", ".key", "id_rsa", "credentials", ".env", "secret")):
            return {"ok": False, "code": "SECRET_FILENAME", "detail": "path looks secret-shaped — refused by shell gate"}
        if resolved.exists() and resolved.is_dir():
            return {"ok": False, "code": "IS_DIR", "detail": str(resolved)}
        mode = str(args.get("mode") or "overwrite")
        if mode not in ("overwrite", "create"):
            return {"ok": False, "code": "BAD_MODE", "detail": "mode must be overwrite|create"}
        if mode == "create" and resolved.exists():
            return {"ok": False, "code": "EXISTS", "detail": "create mode: file exists"}
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except OSError as e:
            return {"ok": False, "code": "WRITE_FAIL", "detail": str(e)}
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
        resolved = self._resolve_under_root(str(args.get("path") or ""))
        if isinstance(resolved, dict):
            return resolved
        if not resolved.is_file():
            return {"ok": False, "code": "NOT_FILE", "detail": str(resolved)}
        name = resolved.name.lower()
        if any(x in name for x in (".pem", ".key", "id_rsa", "credentials", ".env", "secret")):
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
        try:
            resolved.write_text(out_text, encoding="utf-8")
        except OSError as e:
            return {"ok": False, "code": "WRITE_FAIL", "detail": str(e)}
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
            cwd = str(resolved)
        else:
            cwd = None
            for r in self.roots:
                if (r / ".git").exists():
                    cwd = str(r)
                    break
            if cwd is None:
                cwd = str(_PKG_ROOT)

        try:
            p = subprocess.run(
                list(argv), cwd=cwd, capture_output=True, text=True, timeout=60, shell=False
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
            # refuse magic pathspecs that escape
            for tok in argv[2:]:
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
