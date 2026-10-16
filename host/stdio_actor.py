"""Stdio process actor — one name for the life of mcp_server.py.

The launching client's config chooses the name (`--actor` or
`AGENT_CONTROL_ACTOR`). That name is checked against the roster at process
start. An unknown name refuses startup. There is no substitution of `grok`.

Built-in roster: grok, claude, codex. Operators extend it under `receipts/`
the same way HTTP passport files extend that roster, without importing the
passport module (that change is a separate branch):

- `receipts/mcp-http.<actor>.token` — filename only. The body is never read,
  so a live bearer is not loaded or logged here.
- `receipts/stdio-actors` — one actor id per line. Use this for a stdio-only
  name so the file does not become a bearer secret if HTTP passports land.

Per-call JSON `actor` / `agent` / `agent_id` fields are not authority.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECEIPTS_DIR = ROOT / "receipts"

# Same closed set the HTTP passport roster starts from.
DEFAULT_ROSTER: tuple[str, ...] = ("grok", "claude", "codex")

ENV_ACTOR = "AGENT_CONTROL_ACTOR"
STDIO_ROSTER_FILENAME = "stdio-actors"

# Passport files use this shape. We match the name only.
NAMED_TOKEN_RE = re.compile(r"^mcp-http\.([a-z][a-z0-9_-]{0,31})\.token$")
ACTOR_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# Inbound JSON keys that must never become the receipt actor.
SPOOFABLE_JSON_KEYS: tuple[str, ...] = ("actor", "agent", "agent_id")


class UnknownActorError(ValueError):
    """Name is not on the stdio roster. Callers that are starting a process
    should exit. Do not substitute a default actor."""

    def __init__(self, actor: str, roster: tuple[str, ...]) -> None:
        self.actor = actor
        self.roster = roster
        shown = ", ".join(roster) if roster else "(empty)"
        super().__init__(
            f"unknown stdio actor {actor!r}; roster is {shown}. "
            "Refusing to start. "
            f"Pass --actor or set {ENV_ACTOR} to a roster name. "
            "Built-in names: grok, claude, codex. "
            f"Operator extras: receipts/{STDIO_ROSTER_FILENAME} (one id per line) "
            "or a receipts/mcp-http.<actor>.token filename (the file body is ignored)."
        )


def normalize_actor_name(value: str | None) -> str:
    return (value or "").strip().lower()


def is_actor_id(value: str) -> bool:
    return bool(ACTOR_RE.fullmatch(value or ""))


def _roster_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[str] = []
    for line in text.splitlines():
        s = line.split("#", 1)[0].strip().lower()
        if s:
            out.append(s)
    return out


def load_stdio_roster(receipts_dir: Path | str | None = None) -> tuple[str, ...]:
    """Built-in names, then operator extras. Stable order, no secrets."""
    d = Path(receipts_dir) if receipts_dir else DEFAULT_RECEIPTS_DIR
    seen = set(DEFAULT_ROSTER)
    extras: list[str] = []

    def _add(actor: str) -> None:
        if actor in seen or not is_actor_id(actor):
            return
        seen.add(actor)
        extras.append(actor)

    try:
        named = sorted(d.glob("mcp-http.*.token"))
    except OSError:
        named = []
    for path in named:
        m = NAMED_TOKEN_RE.fullmatch(path.name)
        if m:
            _add(m.group(1))

    for actor in _roster_lines(d / STDIO_ROSTER_FILENAME):
        _add(actor)

    extras.sort()
    return tuple(DEFAULT_ROSTER) + tuple(extras)


def validate_actor(actor: str, *, receipts_dir: Path | str | None = None) -> str:
    """Return the normalized name, or raise UnknownActorError."""
    name = normalize_actor_name(actor)
    roster = load_stdio_roster(receipts_dir)
    if not name or name not in roster:
        raise UnknownActorError(name or (actor or ""), roster)
    return name


def strip_spoofable_actor_fields(arguments: dict | None) -> dict:
    """Drop JSON identity keys before they reach the gate or a handler."""
    raw = dict(arguments or {})
    return {k: v for k, v in raw.items() if k not in SPOOFABLE_JSON_KEYS}


def _drop_actor_from_sys_argv() -> None:
    """Remove the flag we consumed so a later MCP transport parser does not see it."""
    kept = [sys.argv[0]] if sys.argv else []
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--actor":
            i += 2
            continue
        if arg.startswith("--actor="):
            i += 1
            continue
        kept.append(arg)
        i += 1
    sys.argv[:] = kept


def resolve_stdio_actor(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    receipts_dir: Path | str | None = None,
) -> str:
    """Actor for this process.

    `--actor` wins. Otherwise `AGENT_CONTROL_ACTOR` when it is non-blank.
    Otherwise `grok`. Unknown names raise SystemExit(2) after a stderr line.
    """
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog="mcp_server.py")
    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "process actor stamped on every receipt "
            f"(default grok, or ${ENV_ACTOR}; roster: grok, claude, codex)"
        ),
    )
    if argv is None:
        args = parser.parse_args()
        _drop_actor_from_sys_argv()
    else:
        args = parser.parse_args(argv)

    if args.actor is not None:
        chosen = args.actor
    else:
        env_val = env.get(ENV_ACTOR)
        if env_val is None or not str(env_val).strip():
            chosen = "grok"
        else:
            chosen = env_val

    try:
        return validate_actor(str(chosen), receipts_dir=receipts_dir)
    except UnknownActorError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
