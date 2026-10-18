"""Loopback HTTP plane: auth before the body, OAuth codes, actor=http.

The previous handler read Content-Length with no cap before checking the
bearer, redirected any redirect_uri with code=agent_control_ok, and returned
the long-lived bearer from POST /oauth/token. These tests pin the replacement.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from mcp_assure.receipts import ReceiptChain

from host.stdio_actor import DEFAULT_ROSTER, HTTP_ACTOR, resolve_stdio_actor
from mcp_http import (
    REJECTED_STATIC_CODE,
    HttpPlane,
    OAuthError,
    PlaneHTTPServer,
    build_http_host,
    normalize_bind_host,
    secrets_equal,
)

ROOT = Path(__file__).resolve().parent.parent
BEARER = "long-lived-bearer-not-for-echo"
REDIRECT = "http://127.0.0.1:9/callback"
OTHER_REDIRECT = "http://127.0.0.1:9/other"


def _plane(tmp_path: Path, **kwargs) -> HttpPlane:
    receipts = tmp_path / "receipts.jsonl"
    host = build_http_host(
        receipts_dir=tmp_path,
        receipts_path=receipts,
        freeze_path=tmp_path / "FREEZE",
    )
    allow = kwargs.pop("redirect_allowlist", (REDIRECT, OTHER_REDIRECT))
    return HttpPlane(plane_host=host, bearer=BEARER, redirect_allowlist=allow, **kwargs)


def _start(plane: HttpPlane) -> tuple[PlaneHTTPServer, threading.Thread]:
    httpd = PlaneHTTPServer(("127.0.0.1", 0), plane)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            if resp.status == 200:
                return httpd, thread
        except OSError:
            time.sleep(0.02)
    raise RuntimeError("mcp_http did not accept /health")


def _stop(httpd: PlaneHTTPServer, thread: threading.Thread) -> None:
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=8)


@pytest.fixture
def httpd(tmp_path):
    plane = _plane(tmp_path)
    server, thread = _start(plane)
    try:
        yield server
    finally:
        _stop(server, thread)


def _port(server: PlaneHTTPServer) -> int:
    return int(server.server_address[1])


def _rpc(task: str = "git status", rpc_id: int = 1) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "tools/call",
            "params": {"name": "plane_route", "arguments": {"task": task}},
        }
    ).encode("utf-8")


def _post(port: int, body: bytes, headers: dict[str, str] | None = None, path: str = "/mcp"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    merged = {"Content-Type": "application/json"}
    if headers:
        merged.update(headers)
    conn.request("POST", path, body=body, headers=merged)
    resp = conn.getresponse()
    payload = resp.read()
    status = resp.status
    hdrs = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return status, hdrs, payload


def _raw(port: int, payload: bytes, timeout: float = 2.0) -> bytes:
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        sock.sendall(payload)
        chunks: list[bytes] = []
        while True:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)
        return b"".join(chunks)
    finally:
        sock.close()


def test_bind_stays_on_loopback():
    assert normalize_bind_host("127.0.0.1") == "127.0.0.1"
    assert normalize_bind_host("localhost") == "127.0.0.1"
    with pytest.raises(SystemExit):
        normalize_bind_host("0.0.0.0")
    with pytest.raises(SystemExit):
        normalize_bind_host("10.0.0.8")


def test_http_actor_is_admitted_without_changing_stdio_default(tmp_path, capsys):
    assert HTTP_ACTOR not in DEFAULT_ROSTER
    assert DEFAULT_ROSTER == ("grok", "claude", "codex")
    with pytest.raises(SystemExit):
        resolve_stdio_actor(["--actor", "http"], {}, receipts_dir=tmp_path)
    assert "Refusing to start" in capsys.readouterr().err
    plane = _plane(tmp_path)
    assert plane.host.actor == "http"
    assert plane.host.actor_binding == "http_process"
    assert resolve_stdio_actor(["--actor", "http"], {}, receipts_dir=tmp_path) == "http"
    assert resolve_stdio_actor([], {}, receipts_dir=tmp_path) == "grok"


def test_bearer_compare_rejects_unequal_lengths():
    assert secrets_equal(BEARER, BEARER) is True
    assert secrets_equal("x", BEARER) is False
    assert secrets_equal(BEARER + "-nope", BEARER) is False
    assert secrets_equal("", BEARER) is False


def test_unauthenticated_post_does_not_read_the_body(httpd, tmp_path):
    """Content-Length is under the cap, but the body is never sent.

    A handler that reads before auth blocks here. Auth must answer 401 first.
    """
    port = _port(httpd)
    raw = (
        "POST /mcp HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: 1000000\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    data = _raw(port, raw)
    assert b"401" in data.split(b"\r\n", 1)[0]
    assert b"UNAUTHORIZED" in data
    assert not (tmp_path / "receipts.jsonl").exists()


def test_oversized_content_length_is_rejected_without_reading(httpd, tmp_path):
    port = _port(httpd)
    raw = (
        "POST /mcp HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Authorization: Bearer {BEARER}\r\n"
        "Content-Length: 999999999\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    data = _raw(port, raw)
    assert b"413" in data.split(b"\r\n", 1)[0]
    assert b"BODY_TOO_LARGE" in data
    assert not (tmp_path / "receipts.jsonl").exists()


def test_missing_length_and_chunked_are_rejected(httpd):
    port = _port(httpd)
    missing = (
        "POST /mcp HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Authorization: Bearer {BEARER}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    assert b"411" in _raw(port, missing).split(b"\r\n", 1)[0]
    chunked = (
        "POST /mcp HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Authorization: Bearer {BEARER}\r\n"
        "Transfer-Encoding: chunked\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    assert b"411" in _raw(port, chunked).split(b"\r\n", 1)[0]


def test_authenticated_call_stamps_http_actor(httpd, tmp_path):
    port = _port(httpd)
    status, _, payload = _post(port, _rpc(), {"Authorization": f"Bearer {BEARER}"})
    assert status == 200
    body = json.loads(payload)
    result = json.loads(body["result"]["content"][0]["text"])
    assert result["executed"] is True
    rows = [
        json.loads(ln)
        for ln in (tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert rows[-1]["actor"] == "http"
    assert rows[-1]["tool"] == "plane.route"
    denied_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "plane_call",
                "arguments": {"tool": "not.a.real.tool", "arguments_json": "{}"},
            },
        }
    ).encode("utf-8")
    status, _, payload = _post(
        port,
        denied_body,
        {"X-Agent-Control-Token": BEARER},
    )
    assert status == 200
    rows = [
        json.loads(ln)
        for ln in (tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert rows[-1]["actor"] == "http"
    assert rows[-1]["code"] == "UNKNOWN_TOOL"
    names = []
    listed, _, list_payload = _post(
        port,
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}).encode(),
        {"Authorization": f"Bearer {BEARER}"},
    )
    assert listed == 200
    for tool in json.loads(list_payload)["result"]["tools"]:
        names.append(tool["name"])
    assert "plane_reload_handlers" not in names


def test_parallel_http_calls_keep_the_receipt_chain(httpd, tmp_path):
    port = _port(httpd)
    errors: list = []

    def one(i: int) -> None:
        try:
            status, _, payload = _post(
                port,
                _rpc(task=f"git status {i}", rpc_id=i),
                {"Authorization": f"Bearer {BEARER}"},
            )
            if status != 200:
                errors.append((status, payload))
                return
            result = json.loads(json.loads(payload)["result"]["content"][0]["text"])
            if not result.get("executed"):
                errors.append(result)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == []
    path = tmp_path / "receipts.jsonl"
    ok, msg = ReceiptChain.verify_file(str(path))
    assert ok, msg
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 12
    assert {row["actor"] for row in rows} == {"http"}


def test_authorize_rejects_unlisted_redirects(httpd):
    port = _port(httpd)
    evil = urlencode({"redirect_uri": "https://evil.example/cb", "state": "s", "client_id": "agent-control"})
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/oauth/authorize?" + evil)
    resp = conn.getresponse()
    body = resp.read()
    assert resp.status == 400
    assert resp.getheader("Location") is None
    assert REJECTED_STATIC_CODE.encode() not in body
    assert b"allowlist" in body
    conn.close()


def test_oauth_code_is_single_use_and_does_not_return_the_bearer(httpd, tmp_path):
    port = _port(httpd)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    qs = urlencode({"redirect_uri": REDIRECT, "state": "xyz", "client_id": "agent-control"})
    conn.request("GET", "/oauth/authorize?" + qs)
    resp = conn.getresponse()
    assert resp.status == 302
    location = resp.getheader("Location") or ""
    resp.read()
    assert REJECTED_STATIC_CODE not in location
    assert BEARER not in location
    code = parse_qs(urlparse(location).query)["code"][0]
    assert code != BEARER
    assert "state=xyz" in location or parse_qs(urlparse(location).query)["state"] == ["xyz"]

    form = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": "agent-control",
            "client_secret": BEARER,
        }
    ).encode()
    conn.request(
        "POST",
        "/oauth/token",
        body=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token_resp = conn.getresponse()
    raw = token_resp.read()
    assert token_resp.status == 200
    issued = json.loads(raw)
    assert issued["token_type"] == "bearer"
    assert issued["expires_in"] == 600
    assert issued["access_token"] != BEARER
    assert BEARER not in raw.decode("utf-8")

    conn.request(
        "POST",
        "/oauth/token",
        body=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    again = conn.getresponse()
    again_body = again.read()
    assert again.status == 400
    assert json.loads(again_body)["error"] == "invalid_grant"
    assert BEARER not in again_body.decode("utf-8")

    status, _, payload = _post(
        port,
        _rpc("git status via access token"),
        {"Authorization": f"Bearer {issued['access_token']}"},
    )
    assert status == 200
    result = json.loads(json.loads(payload)["result"]["content"][0]["text"])
    assert result["executed"] is True
    conn.close()
    text = (ROOT / "mcp_http.py").read_text(encoding="utf-8")
    assert "hmac.compare_digest" in text
    assert "auth[7:].strip() ==" not in text
    assert "secret != expect" not in text


def test_expired_and_mismatched_codes_do_not_issue_tokens(tmp_path):
    clock = {"t": 1000.0}
    plane = _plane(tmp_path, now=lambda: clock["t"], code_ttl_s=60)
    location = plane.begin_authorization(REDIRECT, "s", "agent-control")
    code = parse_qs(urlparse(location).query)["code"][0]
    with pytest.raises(OAuthError) as mismatch:
        plane.exchange(
            grant_type="authorization_code",
            code=code,
            redirect_uri=OTHER_REDIRECT,
            client_id="agent-control",
            client_secret=BEARER,
        )
    assert mismatch.value.error == "invalid_grant"
    # Presented code is spent even when the redirect does not match.
    with pytest.raises(OAuthError):
        plane.exchange(
            grant_type="authorization_code",
            code=code,
            redirect_uri=REDIRECT,
            client_id="agent-control",
            client_secret=BEARER,
        )

    location = plane.begin_authorization(REDIRECT, "s", "agent-control")
    code = parse_qs(urlparse(location).query)["code"][0]
    clock["t"] = 1060.0
    with pytest.raises(OAuthError) as expired:
        plane.exchange(
            grant_type="authorization_code",
            code=code,
            redirect_uri=REDIRECT,
            client_id="agent-control",
            client_secret=BEARER,
        )
    assert expired.value.error == "invalid_grant"

    with pytest.raises(OAuthError) as static:
        plane.exchange(
            grant_type="authorization_code",
            code=REJECTED_STATIC_CODE,
            redirect_uri=REDIRECT,
            client_id="agent-control",
            client_secret=BEARER,
        )
    assert static.value.error == "invalid_grant"
    with pytest.raises(OAuthError) as client:
        plane.exchange(
            grant_type="authorization_code",
            code=code,
            redirect_uri=REDIRECT,
            client_id="agent-control",
            client_secret="not-the-bearer",
        )
    assert client.value.status == 401


def test_wrong_client_secret_does_not_burn_the_code(tmp_path):
    plane = _plane(tmp_path)
    location = plane.begin_authorization(REDIRECT, "s", "agent-control")
    code = parse_qs(urlparse(location).query)["code"][0]
    with pytest.raises(OAuthError) as exc:
        plane.exchange(
            grant_type="authorization_code",
            code=code,
            redirect_uri=REDIRECT,
            client_id="agent-control",
            client_secret="nope",
        )
    assert exc.value.status == 401
    issued = plane.exchange(
        grant_type="authorization_code",
        code=code,
        redirect_uri=REDIRECT,
        client_id="agent-control",
        client_secret=BEARER,
    )
    assert issued["access_token"] != BEARER
    assert plane.token_ok(issued["access_token"]) is True
    assert plane.token_ok(BEARER) is True
    assert plane.token_ok("nope") is False
