#!/usr/bin/env python3
"""Loopback HTTP plane for agent-control.

The listen socket stays on loopback. Tool calls go through one
``AssuredPlaneHost`` whose receipts are stamped ``actor=http`` (admitted via
``receipts/stdio-actors``, the same roster file stdio extras use). The default
receipt file is the stdio chain; appends take the host lock plus, when the
installed ``ReceiptChain`` has no sidecar flock, the file lock in
``host.receipt_lock``.

Auth
----
``/mcp`` checks ``Authorization: Bearer`` or ``X-Agent-Control-Token`` with
``hmac.compare_digest`` **before** the body is read. ``Content-Length`` above
``MAX_BODY_BYTES`` (and any ``Transfer-Encoding``) is rejected without reading
the body. The long-lived bearer lives in ``receipts/mcp-http.token`` and is
never written into a response.

OAuth
-----
The previous handler redirected any ``redirect_uri`` with the static code
``agent_control_ok`` and ``POST /oauth/token`` returned that same long-lived
bearer. This process does not. ``GET /oauth/authorize`` accepts only an exact
``redirect_uri`` from ``receipts/oauth-redirects`` (one URI per line) and
redirects with a random single-use code that expires in 60 seconds. ``POST
/oauth/token`` requires ``grant_type=authorization_code``, that code, the same
``redirect_uri``, and ``client_secret`` equal to the long-lived bearer. The
response is a different access token that expires in 10 minutes. ``/mcp``
accepts either the long-lived bearer or an unexpired access token.

An empty allowlist denies every redirect. The code is useless without the
client secret, and the secret is an input to the token endpoint, not an output.

Env
---
``AGENT_CONTROL_MCP_PORT`` default 8762.
``AGENT_CONTROL_MCP_HOST`` default ``127.0.0.1``. Any other bind is refused.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path.home() / "mcp-assure"))

from host.plane_host import FREEZE, RECEIPTS, AssuredPlaneHost, PACK_PATH  # noqa: E402
from host.stdio_actor import HTTP_ACTOR, ensure_actor_on_roster  # noqa: E402

# Pack max_arg_bytes for shell.write_file is 1 MiB. JSON-RPC framing and
# escaping sit on top of that. 4 MiB stops the reader; the pack still rejects
# an argument the catalog does not allow.
MAX_BODY_BYTES = 4 * 1024 * 1024
CODE_TTL_S = 60.0
ACCESS_TTL_S = 600.0
MAX_LIVE_CODES = 32
PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "agent-control", "version": "0.5.0"}
DEFAULT_CLIENT_ID = "agent-control"
# The static code the previous handler minted. Never issued.
REJECTED_STATIC_CODE = "agent_control_ok"
LOOPBACK_BINDS = frozenset({"127.0.0.1", "localhost", "::1"})
TOKEN_FILENAME = "mcp-http.token"
REDIRECTS_FILENAME = "oauth-redirects"

_CLIENT_ID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class OAuthError(Exception):
    def __init__(self, status: int, error: str, description: str) -> None:
        super().__init__(description)
        self.status = status
        self.error = error
        self.description = description

    def as_dict(self) -> dict[str, str]:
        return {"error": self.error, "error_description": self.description}


def secrets_equal(presented: str, expected: str) -> bool:
    """Constant-time compare. Unequal lengths are not equal and do not raise."""
    a = presented.encode("utf-8")
    b = expected.encode("utf-8")
    if len(a) != len(b):
        hmac.compare_digest(a, a)
        return False
    return hmac.compare_digest(a, b)


def normalize_bind_host(host: str) -> str:
    """Refuse a non-loopback listen address. ``localhost`` binds as 127.0.0.1."""
    cleaned = (host or "").strip().lower()
    if cleaned not in LOOPBACK_BINDS:
        raise SystemExit(
            f"mcp_http: refusing bind host {host!r}; listen stays on loopback "
            "(127.0.0.1, localhost, or ::1)"
        )
    if cleaned == "localhost":
        return "127.0.0.1"
    return cleaned


def client_is_loopback(addr: str) -> bool:
    host = (addr or "").strip().lower()
    if host.startswith("::ffff:"):
        host = host[7:]
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")


def ensure_bearer(path: Path) -> str:
    """Read or create the long-lived bearer. Never log the value."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8").strip()
        except OSError:
            existing = ""
        if existing:
            return existing
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def load_redirect_allowlist(path: Path) -> tuple[str, ...]:
    """Exact redirect URIs, one per line. ``#`` starts a comment. Missing file is empty."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        item = line.split("#", 1)[0].strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def redirect_uri_allowed(uri: str, allowlist: tuple[str, ...]) -> bool:
    """Exact allowlist match plus a structural reject of open-redirect shapes."""
    if uri not in allowlist:
        return False
    if not uri or len(uri) > 2048:
        return False
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in uri):
        return False
    parts = urlsplit(uri)
    if parts.scheme not in ("http", "https"):
        return False
    if parts.fragment or parts.username is not None or parts.password is not None:
        return False
    if not parts.hostname:
        return False
    return True


def _safe_state(state: str) -> bool:
    if len(state) > 512:
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in state)


def _location_with(redirect_uri: str, params: dict[str, str]) -> str:
    parts = urlsplit(redirect_uri)
    query = parse_qs(parts.query, keep_blank_values=True)
    # parse_qs gives lists. Rebuild in order, then add the code parameters.
    pairs: list[tuple[str, str]] = []
    for key, values in query.items():
        for value in values:
            pairs.append((key, value))
    pairs.extend(params.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), ""))


@dataclass
class _AuthCode:
    code: str
    redirect_uri: str
    client_id: str
    expires_at: float


@dataclass
class _AccessToken:
    token: str
    expires_at: float


class HttpPlane:
    """Bearer, authorization codes, and the assured host for one HTTP process."""

    def __init__(
        self,
        *,
        plane_host: AssuredPlaneHost,
        bearer: str,
        redirect_allowlist: tuple[str, ...] = (),
        max_body_bytes: int = MAX_BODY_BYTES,
        code_ttl_s: float = CODE_TTL_S,
        access_ttl_s: float = ACCESS_TTL_S,
        now: Callable[[], float] | None = None,
    ) -> None:
        if not bearer or not bearer.strip():
            raise ValueError("HTTP bearer must be non-empty")
        self.host = plane_host
        self.bearer = bearer.strip()
        self.redirect_allowlist = tuple(redirect_allowlist)
        self.max_body_bytes = int(max_body_bytes)
        self.code_ttl_s = float(code_ttl_s)
        self.access_ttl_s = float(access_ttl_s)
        self._now = now or time.monotonic
        self._oauth_lock = threading.Lock()
        self._codes: list[_AuthCode] = []
        self._access: list[_AccessToken] = []

    def token_ok(self, presented: str) -> bool:
        """True for the long-lived bearer or an unexpired access token."""
        if not presented or not self.bearer:
            return False
        ok = secrets_equal(presented, self.bearer)
        now = self._now()
        with self._oauth_lock:
            self._access = [item for item in self._access if item.expires_at > now]
            for item in self._access:
                if secrets_equal(presented, item.token):
                    ok = True
        return ok

    def begin_authorization(self, redirect_uri: str, state: str, client_id: str) -> str:
        """Mint a single-use code and return the redirect Location. Raises OAuthError."""
        if not _safe_state(state):
            raise OAuthError(400, "invalid_request", "state is missing or not safe to reflect")
        cid = client_id or DEFAULT_CLIENT_ID
        if not _CLIENT_ID_OK.fullmatch(cid):
            raise OAuthError(400, "invalid_request", "client_id is not accepted")
        if not redirect_uri_allowed(redirect_uri, self.redirect_allowlist):
            raise OAuthError(
                400,
                "invalid_request",
                "redirect_uri is not on the allowlist",
            )
        code = self._mint_secret()
        now = self._now()
        with self._oauth_lock:
            self._codes = [item for item in self._codes if item.expires_at > now]
            if len(self._codes) >= MAX_LIVE_CODES:
                raise OAuthError(429, "temporarily_unavailable", "too many outstanding codes")
            self._codes.append(
                _AuthCode(
                    code=code,
                    redirect_uri=redirect_uri,
                    client_id=cid,
                    expires_at=now + self.code_ttl_s,
                )
            )
        params = {"code": code}
        if state:
            params["state"] = state
        return _location_with(redirect_uri, params)

    def exchange(
        self,
        *,
        grant_type: str,
        code: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
    ) -> dict[str, Any]:
        """Trade a code for a short-lived access token. Never returns the bearer."""
        if not client_secret or not secrets_equal(client_secret, self.bearer):
            raise OAuthError(401, "invalid_client", "client authentication failed")
        if grant_type != "authorization_code":
            raise OAuthError(400, "unsupported_grant_type", "grant_type must be authorization_code")
        if not code or code == REJECTED_STATIC_CODE:
            raise OAuthError(400, "invalid_grant", "authorization code is not valid")
        cid = client_id or DEFAULT_CLIENT_ID
        now = self._now()
        with self._oauth_lock:
            found: _AuthCode | None = None
            for item in self._codes:
                if secrets_equal(code, item.code):
                    if found is None:
                        found = item
            if found is None:
                raise OAuthError(400, "invalid_grant", "authorization code is not valid")
            self._codes = [item for item in self._codes if item is not found]
            if now >= found.expires_at:
                raise OAuthError(400, "invalid_grant", "authorization code expired")
            if found.redirect_uri != redirect_uri or found.client_id != cid:
                raise OAuthError(400, "invalid_grant", "redirect_uri or client_id does not match")
            token = self._mint_secret()
            expires_in = int(self.access_ttl_s)
            self._access = [item for item in self._access if item.expires_at > now]
            self._access.append(_AccessToken(token=token, expires_at=now + self.access_ttl_s))
            if len(self._access) > 64:
                self._access = self._access[-64:]
        if secrets_equal(token, self.bearer):
            raise OAuthError(500, "server_error", "refusing to issue the long-lived bearer")
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_in,
        }

    def _mint_secret(self) -> str:
        for _ in range(4):
            value = secrets.token_urlsafe(32)
            if value != REJECTED_STATIC_CODE and not secrets_equal(value, self.bearer):
                return value
        raise OAuthError(500, "server_error", "could not mint a secret")


def build_http_host(
    *,
    receipts_dir: Path,
    receipts_path: Path | None = None,
    freeze_path: Path | None = None,
) -> AssuredPlaneHost:
    """Admit ``http`` on the roster, then build a host that stamps that actor."""
    ensure_actor_on_roster(HTTP_ACTOR, receipts_dir)
    return AssuredPlaneHost(
        actor=HTTP_ACTOR,
        actor_binding="http_process",
        receipts_path=receipts_path if receipts_path is not None else RECEIPTS,
        freeze_path=freeze_path if freeze_path is not None else FREEZE,
        roster_dir=receipts_dir,
    )


def _mcp_name(plane: str) -> str:
    return str(plane).replace(".", "_")


def _plane_name(mcp: str) -> str:
    if mcp == "plane_call":
        return "plane.call"
    return str(mcp).replace("_", ".", 1) if "_" in mcp else mcp


def _tools() -> list[dict[str, Any]]:
    raw = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    tools_map = raw.get("tools") or {}
    out: list[dict[str, Any]] = []
    for name, spec in tools_map.items():
        if not isinstance(spec, dict):
            continue
        allowed = list(spec.get("allowed_args") or [])
        required = list(spec.get("required_args") or [])
        props: dict[str, Any] = {a: {"type": "string"} for a in allowed}
        out.append(
            {
                "name": _mcp_name(name),
                "description": str(spec.get("description") or name),
                "inputSchema": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                    "additionalProperties": True,
                },
            }
        )
    out.append(
        {
            "name": "plane_call",
            "description": (
                "Call any pack tool by dotted name through AssuredPlaneHost. "
                "tool e.g. browser.tabs, desktop.apps; arguments_json object string."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "arguments_json": {"type": "string", "description": "JSON object"},
                },
                "required": ["tool"],
            },
        }
    )
    return out


def _call_plane(plane: HttpPlane, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    out = plane.host.call(name, arguments or {})
    return {
        "executed": out.get("executed"),
        "verdict": out.get("verdict"),
        "result": out.get("result"),
        "error": out.get("error"),
        "campaign": out.get("campaign"),
    }


def handle_rpc(plane: HttpPlane, msg: dict[str, Any]) -> dict[str, Any] | None:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Mediated plane: browser-leash + desktop-leash via AssuredPlaneHost. "
                    "ARM Chrome/desktop on the Mac. FREEZE may block non-status tools. "
                    "Never invent operator_confirm=true."
                ),
            },
        }
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": _tools()}}
    if method == "tools/call":
        tname = str(params.get("name") or "")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            if tname == "plane_call":
                tool = str(args.get("tool") or "")
                raw = args.get("arguments_json") or "{}"
                try:
                    body = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
                except json.JSONDecodeError as exc:
                    result = {"ok": False, "code": "BAD_JSON", "detail": str(exc)}
                    return {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result)}],
                            "isError": True,
                        },
                    }
                result = _call_plane(plane, tool, body if isinstance(body, dict) else {})
            else:
                result = _call_plane(plane, _plane_name(tname), args)
        except Exception as exc:
            sys.stderr.write(f"mcp_http: tool call failed: {type(exc).__name__}\n")
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "error": {"code": -32603, "message": "internal error"},
            }
        err = bool(result.get("error") or (result.get("verdict") or {}).get("decision") == "DENY")
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "isError": err,
            },
        }
    if mid is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _jsonrpc_error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _parse_token_fields(raw: bytes, content_type: str) -> dict[str, str]:
    ctype = (content_type or "").lower()
    if "application/json" in ctype:
        try:
            obj = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(obj, dict):
            return {}
        return {str(k): v for k, v in obj.items() if isinstance(v, str)}
    try:
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return {}
    return {k: (v[0] if v else "") for k, v in parsed.items()}


class PlaneHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], plane: HttpPlane) -> None:
        self.plane = plane
        super().__init__(server_address, Handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        try:
            request.settimeout(5.0)
        except OSError:
            pass
        super().process_request(request, client_address)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "agent-control-mcp"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write("mcp_http: " + (fmt % args) + "\n")

    def _plane(self) -> HttpPlane:
        return self.server.plane  # type: ignore[attr-defined]

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Agent-Control-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, status: int, obj: Any, *, close: bool = False) -> None:
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _unauthorized(self) -> None:
        body = {"ok": False, "code": "UNAUTHORIZED"}
        raw = json.dumps(body).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("WWW-Authenticate", 'Bearer realm="agent-control-mcp"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.close_connection = True
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _bearer_header(self) -> str:
        auth = self.headers.get("Authorization") or ""
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return ""

    def _presented_token(self) -> str:
        bearer = self._bearer_header()
        if bearer:
            return bearer
        return (self.headers.get("X-Agent-Control-Token") or "").strip()

    def _basic_client(self) -> tuple[str, str] | None:
        """``(client_id, secret)`` from Authorization Basic, or None if the header is absent."""
        auth = self.headers.get("Authorization") or ""
        parts = auth.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "basic":
            return None
        try:
            decoded = base64.b64decode(parts[1].strip(), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ("", "")
        if ":" not in decoded:
            return ("", "")
        client_id, secret = decoded.split(":", 1)
        return client_id, secret

    def _body_rejected(self, max_body: int) -> bool:
        """Enforce the size cap before any socket read. True when a response was sent.

        Missing length, chunked encoding, and an over-cap Content-Length all
        close the connection without reading ``rfile``.
        """
        if (self.headers.get("Transfer-Encoding") or "").strip():
            self._send_json(
                411,
                {"ok": False, "code": "LENGTH_REQUIRED", "max_body_bytes": max_body},
                close=True,
            )
            return True
        raw = self.headers.get("Content-Length")
        if raw is None:
            self._send_json(
                411,
                {"ok": False, "code": "LENGTH_REQUIRED", "max_body_bytes": max_body},
                close=True,
            )
            return True
        try:
            n = int(raw)
        except ValueError:
            self._send_json(400, {"ok": False, "code": "BAD_CONTENT_LENGTH"}, close=True)
            return True
        if n < 0:
            self._send_json(400, {"ok": False, "code": "BAD_CONTENT_LENGTH"}, close=True)
            return True
        if n > max_body:
            self._send_json(
                413,
                {"ok": False, "code": "BODY_TOO_LARGE", "max_body_bytes": max_body},
                close=True,
            )
            return True
        self._content_length = n
        return False

    def _read_exact(self, n: int) -> bytes | None:
        if n == 0:
            return b""
        buf = bytearray()
        while len(buf) < n:
            chunk = self.rfile.read(n - len(buf))
            if not chunk:
                return None
            # Cap is already enforced; this loop cannot pass n.
            buf.extend(chunk)
        return bytes(buf)

    def _require_loopback(self) -> bool:
        addr = self.client_address[0] if self.client_address else ""
        if client_is_loopback(addr):
            return True
        self._send_json(403, {"ok": False, "code": "LOOPBACK_ONLY"}, close=True)
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._require_loopback():
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._require_loopback():
            return
        path = urlparse(self.path).path.rstrip("/") or "/"
        plane = self._plane()
        if path == "/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "agent-control-mcp",
                    "transport": "streamable-http",
                    "bind": "loopback",
                    "actor": plane.host.actor,
                },
            )
            return
        if path == "/mcp":
            self._send_json(
                200,
                {
                    "ok": True,
                    "transport": "streamable-http",
                    "post": "POST JSON-RPC to /mcp with Authorization: Bearer",
                    "oauth_authorize": "/oauth/authorize",
                    "oauth_token": "/oauth/token",
                    "note": (
                        "Authorization codes are single-use. The token endpoint "
                        "does not return the long-lived bearer."
                    ),
                },
            )
            return
        if path == "/oauth/authorize":
            self._authorize(plane)
            return
        self._send_json(404, {"ok": False, "code": "NOT_FOUND"})

    def _authorize(self, plane: HttpPlane) -> None:
        q = parse_qs(urlparse(self.path).query)
        redirect_uri = (q.get("redirect_uri") or [""])[0]
        state = (q.get("state") or [""])[0]
        client_id = (q.get("client_id") or [""])[0]
        try:
            location = plane.begin_authorization(redirect_uri, state, client_id)
        except OAuthError as exc:
            self._send_json(exc.status, exc.as_dict())
            return
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        # Loopback, then the size cap, then auth. /mcp does not read rfile
        # until the bearer check has succeeded. /oauth/token has to read a
        # capped body because client_secret and the code are in it; that read
        # never exceeds max_body_bytes and never happens for an over-cap length.
        if not self._require_loopback():
            return
        plane = self._plane()
        if self._body_rejected(plane.max_body_bytes):
            return
        path = urlparse(self.path).path.rstrip("/") or "/"
        n = self._content_length
        if path == "/oauth/token":
            raw = self._read_exact(n)
            if raw is None:
                self._send_json(400, {"error": "invalid_request", "error_description": "truncated body"}, close=True)
                return
            self._oauth_token(plane, raw)
            return
        if path != "/mcp":
            self._send_json(404, {"ok": False, "code": "NOT_FOUND"}, close=True)
            return
        if not plane.token_ok(self._presented_token()):
            self._unauthorized()
            return
        raw = self._read_exact(n)
        if raw is None:
            self._send_json(400, _jsonrpc_error(None, -32700, "truncated body"), close=True)
            return
        self._mcp(plane, raw)

    def _oauth_token(self, plane: HttpPlane, raw: bytes) -> None:
        fields = _parse_token_fields(raw, self.headers.get("Content-Type") or "")
        basic = self._basic_client()
        if basic is not None:
            basic_id, secret = basic
            client_id = fields.get("client_id") or basic_id
        elif fields.get("client_secret"):
            secret = fields.get("client_secret") or ""
            client_id = fields.get("client_id") or ""
        else:
            secret = self._bearer_header()
            client_id = fields.get("client_id") or ""
        try:
            issued = plane.exchange(
                grant_type=fields.get("grant_type") or "",
                code=fields.get("code") or "",
                redirect_uri=fields.get("redirect_uri") or "",
                client_id=client_id,
                client_secret=secret,
            )
        except OAuthError as exc:
            self._send_json(exc.status, exc.as_dict())
            return
        # Defense: the long-lived bearer must not ride out in the JSON body.
        issued_token = str(issued.get("access_token") or "")
        if secrets_equal(issued_token, plane.bearer):
            self._send_json(
                500,
                {"error": "server_error", "error_description": "refusing to echo the bearer"},
            )
            return
        self._send_json(200, issued)

    def _mcp(self, plane: HttpPlane, raw: bytes) -> None:
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, _jsonrpc_error(None, -32700, "Parse error"))
            return
        if isinstance(body, list):
            outs = []
            for item in body:
                if isinstance(item, dict):
                    resp = handle_rpc(plane, item)
                    if resp is not None:
                        outs.append(resp)
            self._send_json(200, outs)
            return
        if not isinstance(body, dict):
            self._send_json(400, _jsonrpc_error(None, -32600, "Invalid Request"))
            return
        resp = handle_rpc(plane, body)
        if resp is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()
            return
        self._send_json(200, resp)


def main() -> int:
    bind = normalize_bind_host(os.environ.get("AGENT_CONTROL_MCP_HOST", "127.0.0.1"))
    try:
        port = int(os.environ.get("AGENT_CONTROL_MCP_PORT", "8762"))
    except ValueError:
        print("mcp_http: AGENT_CONTROL_MCP_PORT is not an integer", file=sys.stderr)
        return 2
    receipts = ROOT / "receipts"
    bearer = ensure_bearer(receipts / TOKEN_FILENAME)
    host = build_http_host(receipts_dir=receipts)
    plane = HttpPlane(
        plane_host=host,
        bearer=bearer,
        redirect_allowlist=load_redirect_allowlist(receipts / REDIRECTS_FILENAME),
    )
    try:
        httpd = PlaneHTTPServer((bind, port), plane)
    except OSError as exc:
        print(f"mcp_http: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "code": "MCP_LISTEN",
                "url": f"http://{bind}:{port}/mcp",
                "health": f"http://{bind}:{port}/health",
                "token_path": str(receipts / TOKEN_FILENAME),
                "redirect_allowlist": str(receipts / REDIRECTS_FILENAME),
                "actor": host.actor,
                "max_body_bytes": MAX_BODY_BYTES,
                "note": "Loopback only. Tunnel from this host if a remote client must reach it.",
            }
        ),
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
