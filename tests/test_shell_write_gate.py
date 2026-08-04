"""Re-runnable proof for the gated shell.write_file — the mediated file-mutation
plane that closes the "native edit tools bypass the gate" hole (GAP_BRIDGE G1).

Two layers are asserted:

  1. Handler guards (ShellHandlers.write_file, in isolation): writes are confined
     to allowed roots (no traversal, no absolute-outside-root), refuse
     secret-shaped filenames, cap size, honor overwrite|create, and require a
     string body. These are the same pillars as read_file's read-side fence,
     applied to the write side.

  2. Gate integration (AssuredPlaneHost): shell.write_file is deliberately NOT in
     freeze_allow, so under FREEZE the gate denies it and NOTHING is written —
     the whole point of the mediated write plane is that a freeze stops edits the
     native tools would still perform. Not frozen, the same call authorizes and
     the file actually appears on disk.

Everything runs offline against tmp dirs; no network, no real receipts log.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from host.shell_handlers import MAX_WRITE_BYTES, ShellHandlers


# ---- handler guards: the write-side fence ---------------------------------

def test_write_under_root_allows_and_persists(tmp_path):
    sh = ShellHandlers(roots=(tmp_path,))
    target = tmp_path / "src" / "note.txt"
    out = sh.write_file({"path": str(target), "content": "hello gate"})
    assert out["ok"] is True and out["code"] == "WROTE"
    assert target.read_text() == "hello gate"
    assert out["data"]["bytes"] == len("hello gate")


def test_parent_traversal_denied(tmp_path):
    sh = ShellHandlers(roots=(tmp_path,))
    out = sh.write_file({"path": "../escape.txt", "content": "x"})
    assert out["ok"] is False and out["code"] == "PATH_TRAVERSAL"


def test_absolute_outside_root_denied(tmp_path):
    sh = ShellHandlers(roots=(tmp_path,))
    out = sh.write_file({"path": "/etc/cron.d/pwn", "content": "x"})
    assert out["ok"] is False and out["code"] == "PATH_OUTSIDE_ROOTS"
    assert not Path("/etc/cron.d/pwn").exists()  # never attempted


def test_secret_shaped_filename_refused(tmp_path):
    sh = ShellHandlers(roots=(tmp_path,))
    for name in ("id_rsa", "server.pem", "signing.key", ".env", "aws_credentials", "secret.txt"):
        out = sh.write_file({"path": str(tmp_path / name), "content": "x"})
        assert out["ok"] is False and out["code"] == "SECRET_FILENAME", name
        assert not (tmp_path / name).exists(), name


def test_oversize_content_denied(tmp_path):
    sh = ShellHandlers(roots=(tmp_path,))
    big = "a" * (MAX_WRITE_BYTES + 1)
    out = sh.write_file({"path": str(tmp_path / "blob.bin"), "content": big})
    assert out["ok"] is False and out["code"] == "CONTENT_TOO_LARGE"
    assert not (tmp_path / "blob.bin").exists()


def test_missing_or_nonstring_content_denied(tmp_path):
    sh = ShellHandlers(roots=(tmp_path,))
    assert sh.write_file({"path": str(tmp_path / "a")})["code"] == "CONTENT_REQUIRED"
    assert sh.write_file({"path": str(tmp_path / "a"), "content": 123})["code"] == "CONTENT_REQUIRED"


def test_create_mode_refuses_existing(tmp_path):
    sh = ShellHandlers(roots=(tmp_path,))
    target = tmp_path / "once.txt"
    assert sh.write_file({"path": str(target), "content": "1", "mode": "create"})["ok"] is True
    out = sh.write_file({"path": str(target), "content": "2", "mode": "create"})
    assert out["ok"] is False and out["code"] == "EXISTS"
    assert target.read_text() == "1"  # untouched


def test_bad_mode_denied(tmp_path):
    sh = ShellHandlers(roots=(tmp_path,))
    out = sh.write_file({"path": str(tmp_path / "a"), "content": "x", "mode": "append"})
    assert out["ok"] is False and out["code"] == "BAD_MODE"


def test_overwrite_is_the_default(tmp_path):
    sh = ShellHandlers(roots=(tmp_path,))
    target = tmp_path / "doc.txt"
    sh.write_file({"path": str(target), "content": "first"})
    out = sh.write_file({"path": str(target), "content": "second"})  # no mode -> overwrite
    assert out["ok"] is True and target.read_text() == "second"


# ---- gate integration: FREEZE blocks the write plane ----------------------

def _host(tmp_path, frozen: bool):
    """AssuredPlaneHost wired to tmp receipts/freeze, shell rooted at tmp_path."""
    from host.plane_host import AssuredPlaneHost

    freeze = tmp_path / "FREEZE"
    if frozen:
        freeze.write_text("frozen for test")
    host = AssuredPlaneHost(
        receipts_path=tmp_path / "receipts.jsonl",
        freeze_path=freeze,
        adaptive=True,
    )
    host.shell.roots = (tmp_path.resolve(),)  # confine the host's shell to tmp
    return host


def test_freeze_blocks_write_nothing_persists(tmp_path):
    host = _host(tmp_path, frozen=True)
    target = tmp_path / "should_not_exist.txt"
    out = host.call("shell.write_file", {"path": str(target), "content": "blocked"})
    assert out["executed"] is False
    assert out["verdict"]["decision"] != "ALLOW"
    assert not target.exists()  # the whole point: freeze stops the edit


def test_not_frozen_write_authorizes_and_persists(tmp_path):
    host = _host(tmp_path, frozen=False)
    target = tmp_path / "wrote_via_gate.txt"
    out = host.call("shell.write_file", {"path": str(target), "content": "via gate"})
    assert out["executed"] is True
    assert out["result"]["ok"] is True and out["result"]["code"] == "WROTE"
    assert target.read_text() == "via gate"


def test_write_is_not_in_freeze_allow(tmp_path):
    """Belt-and-suspenders: prove shell.write_file is absent from freeze_allow so a
    future refactor that accidentally adds it fails loudly here."""
    host = _host(tmp_path, frozen=True)
    # shell.roots IS a freeze_allow recovery tool and must still work while frozen;
    # shell.write_file must not.
    assert host.call("shell.roots", {})["executed"] is True
    assert host.call("shell.write_file", {"path": str(tmp_path / "x"), "content": "y"})["executed"] is False
