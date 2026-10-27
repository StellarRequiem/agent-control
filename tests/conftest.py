"""Put the repo root on sys.path so `host.*` imports work under pytest."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import base64 as _b64
import json as _json
import time as _time

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _open_access_ceiling(request, tmp_path_factory, monkeypatch):
    """Pre-existing host tests predate the Harness access dial: give them a signed
    level-3, all-planes-on policy in a temp dir so they exercise the engine as before.
    test_access_policy.py manages its own policies."""
    if request.node.fspath.basename == "test_access_policy.py":
        yield
        return
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from host import access_policy as ap
    except ImportError:
        yield
        return
    d = tmp_path_factory.mktemp("access")
    k = Ed25519PrivateKey.generate()
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    (d / "conduit_access.pub").write_text(_b64.b64encode(pub).decode())
    now = _time.time()
    payload = _json.dumps({"version": 1, "level": 3, "planes": {p: True for p in ap.PLANES},
                           "set_by": "operator", "set_at": now, "expires_at": now + 3600,
                           "auth_method": "test", "nonce": "t", "sudo": {}}).encode()
    (d / "access.json").write_text(_json.dumps({
        "format": ap.FORMAT, "key_id": ap._key_id(pub),
        "payload_b64": _b64.b64encode(payload).decode(), "sig_b64": _b64.b64encode(k.sign(payload)).decode()}))
    monkeypatch.setattr(ap, "POLICY_DIR", d)
    yield
