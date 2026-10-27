import base64, json, time
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from host import access_policy as ap

ALLOW = frozenset({"plane.status", "shell.read_file", "shell.list_dir"})


def _pub(k):
    return k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _env(k, payload):
    b = json.dumps(payload).encode()
    return {"format": ap.FORMAT, "key_id": ap._key_id(_pub(k)),
            "payload_b64": base64.b64encode(b).decode(), "sig_b64": base64.b64encode(k.sign(b)).decode()}


@pytest.fixture
def d(tmp_path):
    k = Ed25519PrivateKey.generate()
    (tmp_path / "conduit_access.pub").write_text(base64.b64encode(_pub(k)).decode())
    return tmp_path, k


def write(d, level, planes=None, ttl=600, sudo=None, **kw):
    path, k = d
    now = time.time()
    p = {"version": 1, "level": level, "planes": planes or {x: True for x in ap.PLANES},
         "set_by": "operator", "set_at": now, "expires_at": now + ttl if ttl else None,
         "auth_method": "touchid", "nonce": "n", "sudo": sudo or {}}
    p.update(kw)
    (path / "access.json").write_text(json.dumps(_env(k, p)))


def chk(d, tool, frozen=False):
    return ap.check(tool, frozen=frozen, freeze_allow=ALLOW, policy_dir=d[0])


def test_missing_policy_is_level0(d):
    assert chk(d, "shell.list_dir") is None
    assert chk(d, "shell.read_file")["code"] == "ACCESS_LEVEL_DENIED"
    assert chk(d, "shell.run")["required"] == 3


@pytest.mark.parametrize("level,ok,bad", [
    (0, "desktop.screenshot", "browser.snapshot"),
    (1, "shell.read_file", "desktop.click"),
    (2, "browser.click", "shell.run"),
    (3, "shell.write_file", "shell.sudo"),
])
def test_ladder(d, level, ok, bad):
    write(d, level)
    assert chk(d, ok) is None
    assert chk(d, bad)["code"] == "ACCESS_LEVEL_DENIED"


def test_plane_switch_off(d):
    write(d, 3, planes={"shell": False, "browser": True, "desktop": True, "cua": True})
    assert chk(d, "shell.list_dir")["code"] == "PLANE_SWITCHED_OFF"
    assert chk(d, "browser.click") is None


def test_freeze_always_wins(d):
    write(d, 3)
    assert chk(d, "shell.run", frozen=True)["code"] == "FREEZE_DENIED"
    assert chk(d, "plane.unfreeze", frozen=True)["code"] == "FREEZE_DENIED"  # not in this ALLOW
    assert chk(d, "shell.read_file", frozen=True) is None


def test_exempt_recovery(d):
    write(d, 0, planes={x: False for x in ap.PLANES})
    assert chk(d, "plane.status") is None


def test_expired_and_ttl_cap(d):
    write(d, 3, ttl=-1)
    assert ap.effective_policy(policy_dir=d[0])["reason"] == "expired"
    write(d, 3, ttl=None)
    assert ap.effective_policy(policy_dir=d[0])["reason"] == "elevated_without_expiry"
    write(d, 3, ttl=10 * 3600, set_at=time.time() - 3601)
    assert ap.effective_policy(policy_dir=d[0])["level"] == 0


def test_tampered_or_foreign_key(d):
    write(d, 3)
    f = d[0] / "access.json"
    env = json.loads(f.read_text())
    p = json.loads(base64.b64decode(env["payload_b64"])); p["level"] = 4
    env["payload_b64"] = base64.b64encode(json.dumps(p).encode()).decode()
    f.write_text(json.dumps(env))
    pol = ap.effective_policy(policy_dir=d[0])
    assert pol["reason"] == "bad_signature" and not any(pol["planes"].values())
    other = Ed25519PrivateKey.generate()
    write((d[0], other), 3)
    assert ap.effective_policy(policy_dir=d[0])["reason"] == "bad_signature"


def test_unknown_tool_needs_level3(d):
    write(d, 2)
    assert chk(d, "shell.mystery")["required"] == 3


def test_sudo_flow(d):
    argv = ["/usr/bin/true"]
    write(d, 4, sudo={"window_until": time.time() + 3600, "allow": [argv]})
    assert ap.sudo_preflight(["/bin/rm", "-rf", "/"], policy_dir=d[0])["code"] == "SUDO_NOT_ALLOWLISTED"
    assert ap.sudo_preflight(argv, policy_dir=d[0]) is None
    assert ap.consume_sudo_approval(argv, policy_dir=d[0]) == (False, "no_approval")
    path, k = d
    (path / "sudo-approvals").mkdir()
    appr = {"kind": "sudo-approval", "argv_sha256": ap.argv_hash(argv), "nonce": "abc", "issued_at": time.time()}
    (path / "sudo-approvals" / "abc.json").write_text(json.dumps(_env(k, appr)))
    assert ap.consume_sudo_approval(argv, policy_dir=d[0]) == (True, "ok")
    assert ap.consume_sudo_approval(argv, policy_dir=d[0]) == (False, "no_approval")  # one-use
    (path / "sudo-approvals" / "abc.json").write_text(json.dumps(_env(k, appr)))
    assert ap.consume_sudo_approval(argv, policy_dir=d[0]) == (False, "approval_replayed")


def test_sudo_window_closed_and_off_switch(d):
    write(d, 4, sudo={"window_until": time.time() - 1, "allow": [["/usr/bin/true"]]})
    assert ap.sudo_preflight(["/usr/bin/true"], policy_dir=d[0])["code"] == "SUDO_WINDOW_CLOSED"
    write(d, 4, planes={"shell": False, "browser": True, "desktop": True, "cua": True},
          sudo={"window_until": time.time() + 60, "allow": [["/usr/bin/true"]]})
    assert ap.sudo_preflight(["/usr/bin/true"], policy_dir=d[0])["code"] == "PLANE_SWITCHED_OFF"


def test_host_applies_ceiling_before_engine(d, tmp_path, monkeypatch):
    from host import plane_host
    monkeypatch.setattr(ap, "POLICY_DIR", d[0])
    monkeypatch.setattr(plane_host, "ACCESS_RECEIPTS", tmp_path / "access.jsonl")
    write(d, 1, planes={"shell": True, "browser": False, "desktop": True, "cua": True})
    h = plane_host.AssuredPlaneHost(receipts_path=tmp_path / "r.jsonl", freeze_path=tmp_path / "FREEZE")
    out = h.call("shell.run", {"cmd": "x"})
    assert out["result"]["code"] == "ACCESS_LEVEL_DENIED" and out["verdict"]["source"] == "access_policy"
    assert h.call("browser.tabs", {})["result"]["code"] == "PLANE_SWITCHED_OFF"
    assert h.authorize_only("shell.write_file", {})["result"]["code"] == "ACCESS_LEVEL_DENIED"
    assert (tmp_path / "access.jsonl").read_text().count("DENY") == 3
    # pack v17 adds shell.sudo: at level 4 with an open window the ceiling and engine
    # allow dispatch, but the handler still refuses without a one-use signed approval.
    write(d, 4, sudo={"window_until": time.time() + 600, "allow": [["/usr/bin/true"]]})
    v = h.call("shell.sudo", {"argv": ["/usr/bin/true"]})
    assert v.get("verdict", {}).get("source") != "access_policy"
    assert v.get("result", {}).get("ok") is not True
    assert v.get("result", {}).get("code") == "SUDO_APPROVAL_REQUIRED"
