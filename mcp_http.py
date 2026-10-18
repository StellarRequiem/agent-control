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

import json
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path.home() / "mcp-assure"))

from host.plane_host import AssuredPlaneHost, PACK_PATH  # noqa: E402

PORT = int(os.environ.get("AGENT_CONTROL_MCP_PORT", "8762"))
HOST = os.environ.get("AGENT_CONTROL_MCP_HOST", "127.0.0.1")
TOKEN_PATH = ROOT / "receipts" / "mcp-http.token"
PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "agent-control", "version": "0.5.0"}

_host: AssuredPlaneHost | None = None


def host() -> AssuredPlaneHost:
    global _host
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


def _call_plane(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    out = host().call(name, arguments or {})
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
        if tname == "plane_call":
            tool = str(args.get("tool") or "")
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
            result = _call_plane(tool, body if isinstance(body, dict) else {})
        else:
            plane = _plane_name(tname)
            result = _call_plane(plane, args)
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
        expect = _token()
        if not expect:
            return False
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer ") and auth[7:].strip() == expect:
            return True
        if (self.headers.get("X-Agent-Control-Token") or "").strip() == expect:
            return True
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
