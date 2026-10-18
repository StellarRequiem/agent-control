"""Per-actor signed transport for desktop-leash's assurance-desktop-v2 gateway.

Mirrors desktop-leash/bridge/desktop_client.py (HMAC-SHA256 action envelopes in
X-Assurance-Auth). Each plane actor signs with its OWN key; the Codex direct key
is never used. Missing/unsafe keys fail closed: no unsigned request is sent.

Key path resolution (first match wins):
  1. AGENT_CONTROL_DESKTOP_KEY_<ACTOR>   (e.g. AGENT_CONTROL_DESKTOP_KEY_GROK)
  2. AGENT_CONTROL_DESKTOP_KEYS -> JSON file {"<actor>": "/abs/path", ...}
  3. ~/Library/Application Support/AssuranceMesh/DesktopProxy-v5/plane-<actor>-action-key
Only action routes (GET /v1/status, POST /v1/action) are signed; arm, confirm and
d4-session need the operator's signature and are refused here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

VERSION = "assurance-desktop-v2"
MAX_BODY = 65536
ACTION_PATHS = frozenset({("GET", "/v1/status"), ("POST", "/v1/action")})
DEFAULT_KEY_DIR = Path.home() / "Library" / "Application Support" / "AssuranceMesh" / "DesktopProxy-v5"
FORBIDDEN_KEY_NAMES = frozenset({"codex-action-key"})
ACTOR_RE = re.compile(r"[a-z0-9_-]{1,32}")


class SigningRefused(ValueError):
    pass


def _need(cond: bool, code: str) -> None:
    if not cond:
        raise SigningRefused(code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def key_id_for(actor: str) -> str:
    """Gateway client_id for a plane actor. Codex-via-plane is distinct from Codex direct."""
    _need(bool(ACTOR_RE.fullmatch(actor or "")), "DESKTOP_ACTOR_INVALID")
    return "codex-plane" if actor == "codex" else actor


def resolve_key_path(actor: str, env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    kid = key_id_for(actor)
    direct = env.get("AGENT_CONTROL_DESKTOP_KEY_" + actor.upper().replace("-", "_"))
    if direct:
        return Path(direct)
    mapping = env.get("AGENT_CONTROL_DESKTOP_KEYS")
    if mapping:
        try:
            data = json.loads(Path(mapping).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise SigningRefused("DESKTOP_KEYS_CONFIG_UNREADABLE")
        _need(isinstance(data, dict), "DESKTOP_KEYS_CONFIG_INVALID")
        if data.get(actor):
            return Path(str(data[actor]))
    return DEFAULT_KEY_DIR / f"plane-{kid}-action-key"


def read_private_key(path: Path) -> bytes:
    _need(path.is_absolute(), "DESKTOP_KEY_PATH_NOT_ABSOLUTE")
    _need(path.name not in FORBIDDEN_KEY_NAMES, "DESKTOP_KEY_CODEX_REUSE_REFUSED")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise SigningRefused("DESKTOP_KEY_MISSING")
    except OSError:
        raise SigningRefused("DESKTOP_KEY_UNREADABLE")
    try:
        s = os.fstat(fd)
        _need(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, "DESKTOP_KEY_FILE_TYPE")
        _need(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o600, "DESKTOP_KEY_FILE_MODE")
        raw = os.read(fd, 33)
    finally:
        os.close(fd)
    _need(len(raw) == 32, "DESKTOP_KEY_LENGTH")
    return raw


def action_envelope(key: bytes, epoch: str, method: str, path: str, body: dict[str, Any], key_id: str,
                    issued: int | None = None, nonce: str | None = None) -> dict[str, Any]:
    m = {"version": VERSION, "epoch": epoch, "method": method, "path": path, "role": "action",
         "key_id": key_id, "body_sha256": digest(body),
         "issued": int(time.time()) if issued is None else issued,
         "nonce": secrets.token_hex(24) if nonce is None else nonce}
    return {"message": m, "signature": base64.b64encode(hmac.digest(key, canonical(m), "sha256")).decode()}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # noqa: D401
        raise SigningRefused("HTTP_REDIRECT_REFUSED")


Transport = Callable[[str, str, "bytes | None", dict[str, str], float], tuple[int, bytes]]


def _urllib_transport(method: str, url: str, data: bytes | None, headers: dict[str, str], timeout: float):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read(MAX_BODY + 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read(MAX_BODY + 1)


class SignedDesktopClient:
    def __init__(self, base: str, actor: str, *, env: dict[str, str] | None = None,
                 transport: Transport | None = None) -> None:
        self.base = base.rstrip("/")
        self.actor = actor
        self.key_id = key_id_for(actor)
        self.key_path = resolve_key_path(actor, env)
        self.transport = transport or _urllib_transport

    def _exchange(self, method: str, path: str, body: dict[str, Any] | None, headers: dict[str, str],
                  timeout: float) -> dict[str, Any]:
        data = None if body is None else canonical(body)
        h = {"Content-Type": "application/json", "Accept": "application/json", **headers}
        status, raw = self.transport(method, self.base + path, data, h, timeout)
        try:
            out = json.loads(raw)
        except ValueError:
            return {"ok": False, "code": f"HTTP_{status}", "detail": "non-JSON reply"}
        if not isinstance(out, dict):
            return {"ok": False, "code": f"HTTP_{status}"}
        if status >= 400:
            out.setdefault("ok", False)
            out.setdefault("code", f"HTTP_{status}")
        return out

    def call(self, path: str, body: dict[str, Any] | None = None, *, timeout: float = 90.0) -> dict[str, Any]:
        method = "GET" if body is None else "POST"
        try:
            _need((method, path) in ACTION_PATHS, "OPERATOR_SIGNATURE_REQUIRED")
            key = read_private_key(self.key_path)  # before any network I/O: fail closed
            health = self._exchange("GET", "/health", None, {}, timeout)
            _need(health.get("auth_protocol") == VERSION and isinstance(health.get("epoch"), str),
                  "AUTH_BRIDGE_REQUIRED")
            env = action_envelope(key, health["epoch"], method, path, {} if body is None else body, self.key_id)
            hdr = {"X-Assurance-Auth": base64.b64encode(canonical(env)).decode()}
            return self._exchange(method, path, body, hdr, timeout)
        except SigningRefused as exc:
            return {"ok": False, "code": str(exc), "retry": False, "actor": self.actor,
                    "key_id": self.key_id, "detail": _detail(str(exc), self)}
        except (urllib.error.URLError, OSError) as exc:
            return {"ok": False, "code": "BRIDGE_DOWN", "detail": type(exc).__name__}


def _detail(code: str, c: SignedDesktopClient) -> str:
    if code == "DESKTOP_KEY_MISSING":
        return (f"no desktop action key for actor '{c.actor}' (client_id '{c.key_id}') at {c.key_path}; "
                "operator must mint it and register it in desktop-leash profiles/desktop_auth.json")
    if code == "OPERATOR_SIGNATURE_REQUIRED":
        return "arm/confirm/d4-session need the operator's OperatorSigner signature; not available to the plane"
    if code == "DESKTOP_KEY_CODEX_REUSE_REFUSED":
        return "the plane never signs with Codex's direct key; mint a per-actor key"
    return code
