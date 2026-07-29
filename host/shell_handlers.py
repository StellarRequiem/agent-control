"""Gated shell subset — never ambient bash.

Only workspace-rooted filesystem reads and named allowlisted commands.
Arbitrary shell_exec is intentionally absent from the pack.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

# Roots agents may read/list (expand carefully)
DEFAULT_ROOTS = (
    Path.home() / "mcp-assure",
    Path.home() / "agent-control",
    Path.home() / "desktop-leash",
    Path.home() / "browser-leash",
    Path.home() / "portfolio",
    Path.home() / "ops",
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
}

MAX_READ_BYTES = 64_000
MAX_LIST = 200


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
