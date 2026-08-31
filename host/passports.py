"""MCP HTTP passports: Bearer token → actor.

Internal agents (Grok, Claude, Codex) share the plane HTTP MCP. Identity is the
passport file that matches Authorization Bearer — not X-Actor, User-Agent, or a
JSON actor field from the model.

Token files live under receipts/ and are gitignored like mcp-http.token.
Do not log or document live tokens; use token_prefix() (first characters + ellipsis).
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECEIPTS_DIR = ROOT / "receipts"

# Default internal roster. Extra actors may be added as mcp-http.<id>.token.
DEFAULT_ROSTER: tuple[str, ...] = ("grok", "claude", "codex")

# Existing file remains the Grok passport — do not rename/rotate in this change.
GROK_TOKEN_FILENAME = "mcp-http.token"
NAMED_TOKEN_GLOB = "mcp-http.*.token"
NAMED_TOKEN_RE = re.compile(r"^mcp-http\.([a-z][a-z0-9_-]{0,31})\.token$")
ACTOR_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# Inbound fields that must never become actor (spoofable).
SPOOFABLE_HEADERS: tuple[str, ...] = (
    "X-Actor",
    "X-Agent",
    "X-Plane-Actor",
    "User-Agent",
)
SPOOFABLE_JSON_KEYS: tuple[str, ...] = ("actor", "agent", "agent_id")


def token_prefix(token: str, *, n: int = 8) -> str:
    """Log/doc-safe prefix. Never returns the full secret."""
    t = (token or "").strip()
    if not t:
        return ""
    keep = max(1, min(n, 8))
    if len(t) <= keep:
        return t[: max(1, keep // 2)] + "…"
    return t[:keep] + "…"


def is_actor_id(value: str) -> bool:
    return bool(ACTOR_RE.fullmatch(value or ""))


def token_path_for(actor: str, receipts_dir: Path | str | None = None) -> Path:
    """Operator-editable path for one actor's passport file."""
    d = Path(receipts_dir) if receipts_dir else DEFAULT_RECEIPTS_DIR
    if actor == "grok":
        return d / GROK_TOKEN_FILENAME
    if not is_actor_id(actor):
        raise ValueError(f"invalid actor id: {actor!r}")
    return d / f"mcp-http.{actor}.token"


def _read_token_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    # One secret per file. First non-empty, non-comment line.
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return s
    return text.strip()


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


@dataclass
class PassportMap:
    """actor id → token. Comparison is digest-based (equal-length)."""

    tokens: dict[str, str] = field(default_factory=dict)
    receipts_dir: Path = DEFAULT_RECEIPTS_DIR
    collisions: tuple[str, ...] = ()

    def actors(self) -> list[str]:
        return sorted(self.tokens)

    def resolve(self, presented: str) -> str | None:
        """Return actor if presented bearer matches a passport; else None."""
        token = (presented or "").strip()
        if not token:
            return None
        want = _digest(token)
        # Stable order: roster first, then extras.
        order = list(DEFAULT_ROSTER) + sorted(
            a for a in self.tokens if a not in DEFAULT_ROSTER
        )
        seen: set[str] = set()
        for actor in order:
            if actor in seen:
                continue
            seen.add(actor)
            stored = self.tokens.get(actor)
            if not stored:
                continue
            if hmac.compare_digest(want, _digest(stored)):
                return actor
        return None

    def present_actors(self) -> list[str]:
        return self.actors()

    def public_status(self) -> dict[str, Any]:
        """plane.status actors block — roster only, no secrets."""
        present = self.present_actors()
        return {
            "roster": list(DEFAULT_ROSTER),
            "internal": list(DEFAULT_ROSTER),
            "present": present,
            "binding": "mcp_http_bearer",
            "spoofable_ignored": list(SPOOFABLE_HEADERS) + list(SPOOFABLE_JSON_KEYS),
            "note": (
                "actor is the passport matching Authorization Bearer; "
                "X-Actor / User-Agent / JSON actor are not authority"
            ),
        }


def load_passports(receipts_dir: Path | str | None = None) -> PassportMap:
    """Load actor→token files. Missing files are omitted (not an error)."""
    d = Path(receipts_dir) if receipts_dir else DEFAULT_RECEIPTS_DIR
    tokens: dict[str, str] = {}
    by_digest: dict[bytes, str] = {}
    collisions: list[str] = []

    def _register(actor: str, token: str, *, path: Path) -> None:
        if not token or not is_actor_id(actor):
            return
        digest = _digest(token)
        prior = by_digest.get(digest)
        if prior and prior != actor:
            collisions.append(f"{prior}~{actor}")
            return
        tokens[actor] = token
        by_digest[digest] = actor

    grok_path = d / GROK_TOKEN_FILENAME
    grok_alt = d / "mcp-http.grok.token"
    grok_token = _read_token_file(grok_path)
    if not grok_token:
        grok_token = _read_token_file(grok_alt)
    if grok_token:
        _register("grok", grok_token, path=grok_path)

    try:
        named = sorted(d.glob(NAMED_TOKEN_GLOB))
    except OSError:
        named = []
    for path in named:
        m = NAMED_TOKEN_RE.fullmatch(path.name)
        if not m:
            continue
        actor = m.group(1)
        if actor == "grok" and grok_token:
            # Live grok passport stays mcp-http.token.
            continue
        token = _read_token_file(path)
        if token:
            _register(actor, token, path=path)

    return PassportMap(tokens=tokens, receipts_dir=d, collisions=tuple(collisions))


def roster_public(receipts_dir: Path | str | None = None) -> dict[str, Any]:
    """Always lists grok/claude/codex. Never includes token material."""
    return load_passports(receipts_dir).public_status()


def extract_bearer(authorization: str | None) -> str | None:
    """Parse Authorization: Bearer <token>. Other schemes → None."""
    raw = (authorization or "").strip()
    if not raw:
        return None
    parts = raw.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts[0], parts[1].strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def resolve_authorization(
    authorization: str | None,
    *,
    receipts_dir: Path | str | None = None,
    passports: PassportMap | None = None,
) -> str | None:
    """Actor for a valid bearer, else None (caller must 401)."""
    presented = extract_bearer(authorization)
    if presented is None:
        return None
    table = passports if passports is not None else load_passports(receipts_dir)
    return table.resolve(presented)


def json_actor_ignored(payload: Mapping[str, Any] | None) -> bool:
    """True when a spoofable actor-shaped key is present (must not bind)."""
    if not isinstance(payload, Mapping):
        return False
    for key in SPOOFABLE_JSON_KEYS:
        if key in payload:
            return True
    params = payload.get("params")
    if isinstance(params, Mapping):
        for key in SPOOFABLE_JSON_KEYS:
            if key in params:
                return True
        arguments = params.get("arguments")
        if isinstance(arguments, Mapping):
            for key in SPOOFABLE_JSON_KEYS:
                if key in arguments:
                    return True
    arguments = payload.get("arguments")
    if isinstance(arguments, Mapping):
        for key in SPOOFABLE_JSON_KEYS:
            if key in arguments:
                return True
    return False


def mint_token() -> str:
    import secrets

    return secrets.token_urlsafe(32)


def write_passport(
    actor: str,
    token: str,
    *,
    receipts_dir: Path | str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write a passport file (0o600). Refuses overwrite unless overwrite=True."""
    if not is_actor_id(actor):
        raise ValueError(f"invalid actor id: {actor!r}")
    path = token_path_for(actor, receipts_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and not overwrite:
        raise FileExistsError(f"passport exists: {path.name} (prefix {token_prefix(_read_token_file(path))})")
    path.write_text(token.strip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def iter_roster() -> Iterable[str]:
    return DEFAULT_ROSTER
