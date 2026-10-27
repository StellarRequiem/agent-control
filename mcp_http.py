#!/usr/bin/env python3
"""Streamable-HTTP MCP for agent-control (browser-leash + desktop-leash).

Grok Connectors (xAI cloud / grok.com bot) cannot reach 127.0.0.1 or Tailscale
100.x. Tunnel this process (default :8762) with cloudflared / funnel.

Auth: Authorization: Bearer <token> from receipts/mcp-http.token
All tools still go through AssuredPlaneHost (FREEZE, ARM, AdaptiveGate).

Env:
  AGENT_CONTROL_MCP_PORT  default 8762
  AGENT_CONTROL_MCP_HOST  default 127.0.0.1
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path.home() / "mcp-assure"))

from host.plane_host import AssuredPlaneHost, PACK_PATH  # noqa: E402
from host.stdio_actor import DEFAULT_ROSTER, NAMED_TOKEN_RE, STDIO_ROSTER_FILENAME, _roster_lines  # noqa: E402

PORT = int(os.environ.get("AGENT_CONTROL_MCP_PORT", "8762"))
HOST = os.environ.get("AGENT_CONTROL_MCP_HOST", "127.0.0.1")
TOKEN_PATH = ROOT / "receipts" / "mcp-http.token"
PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "agent-control", "version": "0.5.0"}

_host: AssuredPlaneHost | None = None



def _plane_call_denied(tool: str):
    """C1d: plane.* (incl. underscore forms) may not be reached via plane_call."""
    t = (tool or "").strip().lower()
    if t.startswith("plane.") or t.startswith("plane_"):
        return {"ok": False, "code": "PLANE_CALL_DENIED",
                "detail": f"{tool!r} must be invoked via its first-class tool, not plane_call"}
    return None


# --- Per-actor HTTP passports (additive) -------------------------------------
# receipts/mcp-http.token keeps resolving to the historical default actor (grok)
# exactly as before. Named files receipts/mcp-http.<actor>.token map their bearer
# to <actor> when <actor> is on the stdio roster. Tokens are never logged/printed.
_req = threading.local()
_actor_hosts: dict[str, AssuredPlaneHost] = {}
_actor_hosts_lock = threading.Lock()


def _named_tokens() -> list[tuple[str, str]]:
    """(actor, token) for roster-valid named passport files. Bodies stay in memory only."""
    out: list[tuple[str, str]] = []
    try:
        # Stricter than load_stdio_roster(): a token filename alone must not
        # self-enroll an actor — it must be built-in or listed in stdio-actors.
        roster = set(DEFAULT_ROSTER) | set(_roster_lines(TOKEN_PATH.parent / STDIO_ROSTER_FILENAME))
        paths = sorted(TOKEN_PATH.parent.glob("mcp-http.*.token"))
    except OSError:
        return out
    for p in paths:
        m = NAMED_TOKEN_RE.fullmatch(p.name)
        if not m:
            continue
        actor = m.group(1)
        if actor == "grok" or actor not in roster:
            continue
        try:
            t = p.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if len(t) >= 32:
            out.append((actor, t))
    return out


def _resolve_bearer(presented: str) -> str | None:
    """Return None for the default (grok) token, an actor name for a named token,
    or raise LookupError when nothing matches. Constant-time compares."""
    presented = (presented or "").strip()
    if not presented:
        raise LookupError
    expect = _token()
    if expect and hmac.compare_digest(presented.encode(), expect.encode()):
        return None  # historical default host (grok)
    for actor, tok in _named_tokens():
        if hmac.compare_digest(presented.encode(), tok.encode()):
            return actor
    raise LookupError


def host() -> AssuredPlaneHost:
    global _host
    actor = getattr(_req, "actor", None)
    if actor is not None:
        with _actor_hosts_lock:
            h = _actor_hosts.get(actor)
            if h is None:
                h = AssuredPlaneHost(actor=actor)  # roster-validated in __init__
                _actor_hosts[actor] = h
            return h
    if _host is None:
        _host = AssuredPlaneHost()
    return _host


def _ensure_token() -> str:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.is_file():
        t = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if t:
            return t
    t = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(t + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return t


def _token() -> str:
    return _ensure_token()


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
        props: dict[str, Any] = {}
        for a in allowed:
            props[a] = {"type": "string"}
        if name == "shell.sudo":
            # handler requires a real argv list (sudo_preflight rejects strings)
            props["argv"] = {"type": "array", "items": {"type": "string"}, "minItems": 1,
                             "description": "allowlisted argv, e.g. [\"launchctl\",\"list\"]; run via sudo -n"}
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


# --- Self-declared agent name (report-only, grants nothing) -----------------
# A client may pass `_agent` as a tool argument or an `X-Agent-Name` header.
# It is stripped BEFORE the gate/policy/handlers see the arguments, never changes
# the actor, decision, scores, or freeze, and is recorded in a SIDE LOG keyed by
# receipt_id (the hash-chained receipt body is untouched). The side log lives
# outside receipts/ so agent-soc's receipts/*.jsonl glob never ingests it.
RESERVED_AGENT_ARG = "_agent"
CLAIMS_LOG = ROOT / "claims" / "claimed-agents.jsonl"
AGENT_REGISTRY = Path.home() / "agent-soc" / "registry" / "registry.json"
_claims_lock = threading.Lock()


def _agent_allowlist() -> dict[str, str] | None:
    """name -> canonical registry agent_id, from the agent-soc registry (non-revoked)."""
    try:
        db = json.loads(AGENT_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    out: dict[str, str] = {}
    for aid, rec in (db.get("agents") or {}).items():
        if rec.get("status") == "revoked":
            continue
        names = {aid, aid.replace("-", "_")}
        for rule in rec.get("match") or []:
            if rule.get("plane") == "agent-control" and rule.get("actor"):
                names.add(str(rule["actor"]))
        for n in names:
            out[n.lower()] = aid
    return out


def _sanitize(v: Any) -> str:
    return "".join(c for c in str(v)[:48].lower() if c.isalnum() or c in "-_") or "empty"


def classify_claim(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    name = _sanitize(raw)
    allow = _agent_allowlist()
    if allow is None:
        return f"unverified:{name}"
    return allow.get(name) or f"invalid:{name}"


def _record_claim(claim: str, raw_source: str, tool: str, out: dict[str, Any]) -> None:
    try:
        v = out.get("verdict") or {}
        row = {
            "ts": __import__("time").time(),
            "receipt_id": v.get("receipt_id"),
            "receipt_hash": v.get("receipt_hash"),
            "actor": getattr(host(), "actor", None),
            "claimed_agent": claim,
            "via": raw_source,
            "tool": tool,
            "decision": v.get("decision"),
        }
        CLAIMS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _claims_lock, CLAIMS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception:  # report-only: never affect the call
        pass


def _call_plane(name: str, arguments: dict[str, Any] | None, claim_raw: Any = None,
                claim_via: str = "") -> dict[str, Any]:
    args = dict(arguments or {})
    if RESERVED_AGENT_ARG in args:  # strip before gate / ARG_POLICY / handlers
        inner = args.pop(RESERVED_AGENT_ARG)
        if claim_raw in (None, ""):
            claim_raw, claim_via = inner, "arg"
    if claim_raw in (None, ""):
        hdr = getattr(_req, "agent_name", None)
        if hdr:
            claim_raw, claim_via = hdr, "header"
    out = host().call(name, args)
    claim = classify_claim(claim_raw)
    if claim:
        _record_claim(claim, claim_via, name, out)
    return {
        "executed": out.get("executed"),
        "verdict": out.get("verdict"),
        "result": out.get("result"),
        "error": out.get("error"),
        "campaign": out.get("campaign"),
    }


def handle_rpc(msg: dict[str, Any]) -> dict[str, Any] | None:
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
    if method == "notifications/initialized" or method == "initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": _tools()}}
    if method == "tools/call":
        tname = str(params.get("name") or "")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        args = dict(args)
        claim_raw = args.pop(RESERVED_AGENT_ARG, None)
        claim_via = "arg" if claim_raw not in (None, "") else ""
        if tname == "plane_call":
            tool = str(args.get("tool") or "")
            denied = _plane_call_denied(tool)
            if denied:
                return {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": json.dumps(denied)}], "isError": True}}
            raw = args.get("arguments_json") or "{}"
            try:
                body = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
            except json.JSONDecodeError as e:
                body = {}
                result = {"ok": False, "code": "BAD_JSON", "detail": str(e)}
                return {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result)}],
                        "isError": True,
                    },
                }
            result = _call_plane(tool, body if isinstance(body, dict) else {}, claim_raw, claim_via)
        else:
            plane = _plane_name(tname)
            if plane == "shell.sudo" and isinstance(args.get("argv"), str):
                try:  # tolerate clients that send argv as a JSON string
                    args["argv"] = json.loads(args["argv"])
                except json.JSONDecodeError:
                    pass  # preflight will reject it
            result = _call_plane(plane, args, claim_raw, claim_via)
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


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write("mcp_http: " + (fmt % args) + "\n")

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, status: int, obj: Any) -> None:
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth_ok(self) -> bool:
        """Authenticate and bind the request actor (thread-local). Unknown → False."""
        _req.actor = None
        _req.agent_name = (self.headers.get("X-Agent-Name") or "").strip() or None
        expect = _token()
        if not expect:
            return False
        auth = self.headers.get("Authorization") or ""
        candidates = []
        if auth.startswith("Bearer "):
            candidates.append(auth[7:])
        candidates.append(self.headers.get("X-Agent-Control-Token") or "")
        for c in candidates:
            try:
                _req.actor = _resolve_bearer(c)
                return True
            except LookupError:
                continue
        _req.actor = None
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/health/"):
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "agent-control-mcp",
                    "transport": "streamable-http",
                    "plane": "browser+desktop via AssuredPlaneHost",
                },
            )
            return
        if path in ("/mcp", "/mcp/"):
            self._send_json(
                200,
                {
                    "ok": True,
                    "transport": "streamable-http",
                    "post": "POST JSON-RPC to /mcp with Authorization: Bearer <token>",
                    "oauth_token": "/oauth/token",
                },
            )
            return
        if path in ("/oauth/authorize", "/oauth/authorize/"):
            q = parse_qs(urlparse(self.path).query)
            redirect_uri = (q.get("redirect_uri") or [""])[0]
            state = (q.get("state") or [""])[0]
            if not redirect_uri:
                self._send_json(400, {"ok": False, "code": "NO_REDIRECT"})
                return
            sep = "&" if "?" in redirect_uri else "?"
            loc = f"{redirect_uri}{sep}code=agent_control_ok&state={state}"
            self.send_response(302)
            self.send_header("Location", loc)
            self._cors()
            self.end_headers()
            return
        self._send_json(404, {"ok": False, "code": "NOT_FOUND"})

    def _read_body(self) -> bytes:
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            n = 0
        return self.rfile.read(n) if n else b""

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        raw = self._read_body()
        if path in ("/oauth/token", "/oauth/token/"):
            form: dict[str, str] = {}
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "application/json" in ctype:
                try:
                    obj = json.loads(raw.decode("utf-8") or "{}")
                    if isinstance(obj, dict):
                        form = {str(k): str(v) for k, v in obj.items()}
                except json.JSONDecodeError:
                    form = {}
            else:
                try:
                    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                    form = {k: (v[0] if v else "") for k, v in parsed.items()}
                except Exception:
                    form = {}
            auth = self.headers.get("Authorization") or ""
            if auth.startswith("Basic "):
                import base64

                try:
                    decoded = base64.b64decode(auth[6:].strip()).decode("utf-8")
                    if ":" in decoded:
                        _cid, csec = decoded.split(":", 1)
                        form.setdefault("client_secret", csec)
                except Exception:
                    pass
            secret = form.get("client_secret") or ""
            expect = _token()
            if not expect or secret != expect:
                self._send_json(401, {"error": "invalid_client"})
                return
            self._send_json(
                200,
                {
                    "access_token": expect,
                    "token_type": "bearer",
                    "expires_in": 86400 * 30,
                },
            )
            return

        if path not in ("/mcp", "/mcp/"):
            self._send_json(404, {"ok": False, "code": "NOT_FOUND"})
            return
        if not self._auth_ok():
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("WWW-Authenticate", 'Bearer realm="agent-control-mcp"')
            self._cors()
            body = json.dumps({"ok": False, "code": "UNAUTHORIZED"}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, _jsonrpc_error(None, -32700, "Parse error"))
            return
        if isinstance(body, list):
            outs = []
            for item in body:
                if isinstance(item, dict):
                    r = handle_rpc(item)
                    if r is not None:
                        outs.append(r)
            self._send_json(200, outs)
            return
        if not isinstance(body, dict):
            self._send_json(400, _jsonrpc_error(None, -32600, "Invalid Request"))
            return
        resp = handle_rpc(body)
        if resp is None:
            self.send_response(202)
            self._cors()
            self.end_headers()
            return
        self._send_json(200, resp)


def main() -> int:
    tok = _ensure_token()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        json.dumps(
            {
                "ok": True,
                "code": "MCP_LISTEN",
                "url": f"http://{HOST}:{PORT}/mcp",
                "health": f"http://{HOST}:{PORT}/health",
                "token_path": str(TOKEN_PATH),
                "token_prefix": tok[:6] + "…",
                "note": "Tunnel this port for Grok Connectors. ARM leashes on the Mac.",
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
