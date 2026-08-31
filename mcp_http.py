#!/usr/bin/env python3
"""Loopback MCP HTTP: Bearer passport → actor → AssuredPlaneHost.

Bind 127.0.0.1 only. Authenticate Authorization Bearer against receipts/
passport files (mcp-http.token = grok). Stamp the matching actor on every
dispatch, including UNKNOWN_TOOL denials. Invalid/missing bearer → 401 and
no passport actor (no receipt).

X-Actor, User-Agent, and JSON actor fields are not authority.

Logs print token prefixes only (token_prefix), never live secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path.home() / "mcp-assure"))

from host.passports import (  # noqa: E402
    DEFAULT_RECEIPTS_DIR,
    DEFAULT_ROSTER,
    extract_bearer,
    load_passports,
    mint_token,
    resolve_authorization,
    roster_public,
    token_prefix,
    write_passport,
)
from host.plane_host import AssuredPlaneHost, load_local_pack  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8762


def _token(receipts_dir: Path | str | None = None) -> str:
    """Grok passport (legacy single-token helper). Auth uses the full map."""
    return load_passports(receipts_dir).tokens.get("grok") or ""


@dataclass
class HttpContext:
    receipts_dir: Path
    host: AssuredPlaneHost | None = None
    host_factory: Callable[[], AssuredPlaneHost] | None = None

    def get_host(self) -> AssuredPlaneHost:
        if self.host is None:
            factory = self.host_factory
            if factory is not None:
                self.host = factory()
            else:
                self.host = AssuredPlaneHost(passports_dir=self.receipts_dir)
        return self.host


def authenticate(
    headers: Any,
    *,
    receipts_dir: Path | str | None = None,
    passports=None,
) -> str | None:
    """Return actor from Authorization Bearer, else None.

    Deliberately ignores X-Actor / User-Agent / other spoofable headers.
    """
    auth = None
    try:
        auth = headers.get("Authorization") or headers.get("authorization")
    except Exception:
        auth = None
    return resolve_authorization(
        auth,
        receipts_dir=receipts_dir,
        passports=passports,
    )


def _json_rpc_tool(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract tool name + arguments. Never take actor from JSON."""
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    name = (
        payload.get("name")
        or payload.get("tool")
        or params.get("name")
        or params.get("tool")
        or ""
    )
    arguments = payload.get("arguments")
    if arguments is None:
        arguments = params.get("arguments") or params.get("input") or {}
    if not isinstance(arguments, dict):
        arguments = {}
    # Strip spoofable keys from arguments so they cannot ride into the pack.
    cleaned = {k: v for k, v in arguments.items() if k not in ("actor", "agent", "agent_id")}
    return str(name), cleaned


def dispatch_authenticated(
    payload: dict[str, Any],
    *,
    actor: str,
    host: AssuredPlaneHost,
) -> dict[str, Any]:
    """Run a plane tool as the passport actor. JSON actor fields are ignored."""
    name, arguments = _json_rpc_tool(payload)
    if not name:
        # Still a dispatch: empty tool → gate DENY EMPTY_TOOL with this actor.
        name = ""
    out = host.call(name, arguments, actor=actor)
    return {
        "ok": bool(out.get("executed") or (out.get("verdict") or {}).get("allowed")),
        "actor": actor,
        "executed": out.get("executed"),
        "verdict": out.get("verdict"),
        "result": out.get("result"),
        "error": out.get("error"),
        "campaign": out.get("campaign"),
    }


def _tools_list() -> list[dict[str, str]]:
    pack = load_local_pack()
    out: list[dict[str, str]] = []
    for name in pack.names():
        policy = pack.get(name)
        desc = getattr(policy, "description", "") if policy is not None else ""
        out.append({"name": name, "description": desc or name})
    return out


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
    length = int(handler.headers.get("Content-Length") or 0)
    if length < 0 or length > 1_000_000:
        return None
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        obj = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _send_json(
    handler: BaseHTTPRequestHandler,
    code: int,
    body: dict[str, Any],
    *,
    actor: str | None = None,
) -> None:
    data = json.dumps(body, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    if actor:
        handler.send_header("X-Plane-Actor", actor)
    handler.end_headers()
    handler.wfile.write(data)


def _unauthorized(handler: BaseHTTPRequestHandler, presented: str | None) -> None:
    prefix = token_prefix(presented or "")
    sys.stderr.write(
        f"mcp_http 401 missing_or_invalid_bearer prefix={prefix or '(none)'}\n"
    )
    handler.send_response(401)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("WWW-Authenticate", 'Bearer realm="agent-control"')
    payload = json.dumps(
        {"ok": False, "code": "UNAUTHORIZED", "detail": "invalid or missing bearer"}
    ).encode("utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


def handle_request(handler: BaseHTTPRequestHandler, ctx: HttpContext) -> None:
    passports = load_passports(ctx.receipts_dir)
    presented = extract_bearer(
        handler.headers.get("Authorization") or handler.headers.get("authorization")
    )
    actor = authenticate(
        handler.headers,
        receipts_dir=ctx.receipts_dir,
        passports=passports,
    )
    if actor is None:
        _unauthorized(handler, presented)
        return

    parsed = urlparse(handler.path)
    path = parsed.path.rstrip("/") or "/"

    if handler.command == "GET" and path in ("/", "/mcp", "/v1/status"):
        _send_json(
            handler,
            200,
            {
                "ok": True,
                "service": "agent-control-mcp-http",
                "actor": actor,
                "actors": roster_public(ctx.receipts_dir),
            },
            actor=actor,
        )
        return

    if handler.command != "POST":
        _send_json(handler, 405, {"ok": False, "code": "METHOD_NOT_ALLOWED"}, actor=actor)
        return

    payload = _read_json_body(handler)
    if payload is None:
        _send_json(handler, 400, {"ok": False, "code": "BAD_JSON"}, actor=actor)
        return

    host = ctx.get_host()
    method = str(payload.get("method") or "")
    jsonrpc = payload.get("jsonrpc") == "2.0" or method.startswith("tools/") or method == "initialize"

    if method == "initialize":
        _send_json(
            handler,
            200,
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "agent-control", "version": "mcp-http"},
                    "actor": actor,
                },
            },
            actor=actor,
        )
        return

    if method == "tools/list":
        _send_json(
            handler,
            200,
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {"tools": _tools_list()},
            },
            actor=actor,
        )
        return

    if method in ("ping", "notifications/initialized"):
        if payload.get("id") is None:
            handler.send_response(204)
            handler.end_headers()
            return
        _send_json(
            handler,
            200,
            {"jsonrpc": "2.0", "id": payload.get("id"), "result": {}},
            actor=actor,
        )
        return

    is_call = (
        method == "tools/call"
        or path in ("/v1/call", "/call")
        or bool(payload.get("name") or payload.get("tool"))
    )
    if is_call:
        result = dispatch_authenticated(payload, actor=actor, host=host)
        if jsonrpc or method == "tools/call":
            _send_json(
                handler,
                200,
                {"jsonrpc": "2.0", "id": payload.get("id"), "result": result},
                actor=actor,
            )
            return
        _send_json(handler, 200, result, actor=actor)
        return

    _send_json(
        handler,
        200,
        {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "error": {"code": -32601, "message": "method not found"},
        },
        actor=actor,
    )


def make_handler(ctx: HttpContext) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            handle_request(self, ctx)

        def do_POST(self) -> None:
            handle_request(self, ctx)

        def log_message(self, fmt: str, *args: Any) -> None:
            # Request line only — never dump headers (Authorization).
            sys.stderr.write("mcp_http " + (fmt % args) + "\n")

    return Handler


def serve(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    receipts_dir: Path | str | None = None,
    http_ctx: HttpContext | None = None,
) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("mcp_http binds loopback only")
    receipts = Path(receipts_dir) if receipts_dir else DEFAULT_RECEIPTS_DIR
    receipts.mkdir(parents=True, exist_ok=True)
    ctx = http_ctx or HttpContext(receipts_dir=receipts)
    httpd = ThreadingHTTPServer((host, port), make_handler(ctx))
    bound = httpd.server_address
    grok = _token(receipts)
    sys.stderr.write(
        f"agent-control mcp_http {bound[0]}:{bound[1]} "
        f"roster={list(DEFAULT_ROSTER)} grok_prefix={token_prefix(grok) or '(missing)'}\n"
    )
    httpd.serve_forever()


def _cmd_mint(args: argparse.Namespace) -> int:
    actor = str(args.actor or "").strip().lower()
    receipts = Path(args.receipts_dir) if args.receipts_dir else DEFAULT_RECEIPTS_DIR
    token = mint_token()
    try:
        path = write_passport(
            actor,
            token,
            receipts_dir=receipts,
            overwrite=bool(args.force),
        )
    except FileExistsError as e:
        print(str(e), file=sys.stderr)
        print("Refusing to rotate an existing passport (keep grok live). Use --force to overwrite.", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    # Issuance ceremony: print once to stdout so the operator can paste into
    # the connector. Logs and docs must keep using prefixes only.
    print(f"wrote {path}")
    print(f"actor {actor}")
    print(f"prefix {token_prefix(token)}")
    print("Authorization: Bearer " + token)
    print("Put that header on the Claude/Codex/Cursor connector. Do not commit the file.")
    return 0


def _cmd_roster(args: argparse.Namespace) -> int:
    receipts = Path(args.receipts_dir) if args.receipts_dir else DEFAULT_RECEIPTS_DIR
    status = roster_public(receipts)
    # prefixes only for present actors
    table = load_passports(receipts)
    present_prefixes = {
        actor: token_prefix(table.tokens[actor]) for actor in table.tokens
    }
    print(json.dumps({**status, "prefixes": present_prefixes}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mcp_http")
    sub = p.add_subparsers(dest="cmd")

    serve_p = sub.add_parser("serve", help="loopback MCP HTTP (default)")
    serve_p.add_argument("--host", default=os.environ.get("AGENT_CONTROL_MCP_HTTP_HOST", DEFAULT_HOST))
    serve_p.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AGENT_CONTROL_MCP_PORT", str(DEFAULT_PORT))),
    )
    serve_p.add_argument("--receipts-dir", default="")

    mint_p = sub.add_parser("mint", help="write a passport file and print the token once")
    mint_p.add_argument("--actor", required=True, help="claude | codex | grok | custom id")
    mint_p.add_argument("--force", action="store_true", help="overwrite existing file (not default)")
    mint_p.add_argument("--receipts-dir", default="")

    roster_p = sub.add_parser("roster", help="list actors (no secrets)")
    roster_p.add_argument("--receipts-dir", default="")

    args = p.parse_args(argv)
    cmd = args.cmd or "serve"
    if cmd == "mint":
        return _cmd_mint(args)
    if cmd == "roster":
        return _cmd_roster(args)
    receipts = Path(args.receipts_dir) if getattr(args, "receipts_dir", None) else DEFAULT_RECEIPTS_DIR
    if getattr(args, "receipts_dir", "") == "":
        receipts = DEFAULT_RECEIPTS_DIR
    serve(host=getattr(args, "host", DEFAULT_HOST), port=int(getattr(args, "port", DEFAULT_PORT)), receipts_dir=receipts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
