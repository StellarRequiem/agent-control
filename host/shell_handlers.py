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
    Path.home() / "desktop-leash",
    Path.home() / "browser-leash",
    Path.home() / "portfolio",
    Path.home() / "ops",
    Path.home() / "agent-soc",
    Path.home() / "Forest-Soul-Forge",
)

# Named commands only — no free-form argv
ALLOW_COMMANDS: dict[str, list[str]] = {
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
    "agent_control_session": [
        "python3",
        str(Path.home() / "agent-control" / "cli.py"),
        "session",
    ],
    "agent_control_pytest": [
        "python3",
        "-m",
        "pytest",
        "-q",
        str(Path.home() / "agent-control" / "tests"),
    ],
    "mcp_assure_pytest": [
        str(Path.home() / "mcp-assure" / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
        str(Path.home() / "mcp-assure" / "tests"),
    ],
}

MAX_READ_BYTES = 64_000
MAX_LIST = 200

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

        cmd = list(ALLOW_COMMANDS[name])
        # Skip if mcp-assure binary missing
        if name.startswith("mcp_assure") and not Path(cmd[0]).exists():
            cmd = ["python3", "-m", "mcp_assure", cmd[-1]]
            env = {**os.environ, "PYTHONPATH": str(Path.home() / "mcp-assure")}
        else:
            env = None

        try:
            p = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=120,
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
