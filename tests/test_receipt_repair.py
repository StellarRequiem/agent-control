"""Receipt diagnose/rotate when mcp-assure denies a broken chain.

mcp-assure 0.3.2 has no chain_repair_allow and no ReceiptChain.rotate_if_broken.
evaluate() denies plane.receipts_status and plane.receipts_rotate with
CHAIN_BROKEN and appends that deny onto the poison file, so the handlers never
run. The host runs those two tools itself, archives the file, and replaces the
in-memory tip so the next gated append starts at genesis.
"""
from __future__ import annotations

import json
from pathlib import Path

from mcp_assure.receipts import GENESIS, ReceiptChain

from host.plane_host import AssuredPlaneHost


def _host(tmp_path: Path) -> AssuredPlaneHost:
    return AssuredPlaneHost(
        receipts_path=tmp_path / "chain.jsonl",
        freeze_path=tmp_path / "FREEZE",
        roster_dir=tmp_path,
    )


def _poison(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "id": "poison",
                "ts": 1.0,
                "decision": "ALLOW",
                "tool": "plane.status",
                "actor": "proof",
                "source": "proof",
                "code": "OK",
                "detail": "poison",
                "metadata": {},
                "prev_hash": "not-genesis",
                "hash": "deadbeef",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _lines(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_installed_engine_has_no_repair_hook():
    assert not hasattr(ReceiptChain, "rotate_if_broken")


def test_broken_chain_status_does_not_append_and_rotate_resets_tip(tmp_path):
    host = _host(tmp_path)
    path = tmp_path / "chain.jsonl"
    _poison(path)
    before = path.read_text(encoding="utf-8")

    status = host.call("plane.receipts_status")
    assert status["executed"] is True
    assert status["result"]["intact"] is False
    assert status["result"]["code"] == "BROKEN"
    assert path.read_text(encoding="utf-8") == before

    rotated = host.call("plane.receipts_rotate", {})
    assert rotated["executed"] is True
    assert rotated["result"]["code"] == "ROTATED"
    archive = Path(rotated["result"]["archived"])
    assert archive.is_file()
    assert "deadbeef" in archive.read_text(encoding="utf-8")
    ok, msg = ReceiptChain.verify_file(str(path))
    assert ok, msg
    assert host._dispatcher.engine.chain.tip == GENESIS

    again = host.call("plane.receipts_status")
    assert again["executed"] is True
    assert again["result"]["intact"] is True
    assert again["result"]["code"] == "INTACT"
    ok, msg = ReceiptChain.verify_file(str(path))
    assert ok, msg
    recs = _lines(path)
    assert recs[0]["prev_hash"] == GENESIS
    assert recs[-1]["tool"] == "plane.receipts_status"


def test_other_tools_stay_denied_while_the_chain_is_broken(tmp_path):
    host = _host(tmp_path)
    path = tmp_path / "chain.jsonl"
    _poison(path)
    denied = host.call("plane.route", {"task": "git status"})
    assert denied["executed"] is False
    assert denied["verdict"]["code"] == "CHAIN_BROKEN"


def test_intact_rotate_without_force_leaves_the_file(tmp_path):
    host = _host(tmp_path)
    path = tmp_path / "chain.jsonl"
    assert host.call("plane.route", {"task": "git status"})["executed"] is True
    rotated = host.call("plane.receipts_rotate", {})
    assert rotated["executed"] is True
    assert rotated["result"]["code"] == "INTACT"
    ok, msg = ReceiptChain.verify_file(str(path))
    assert ok, msg
    assert not list(tmp_path.glob("*.broken"))


def test_force_rotate_of_an_intact_chain_restarts_at_genesis(tmp_path):
    host = _host(tmp_path)
    path = tmp_path / "chain.jsonl"
    assert host.call("plane.route", {"task": "git status"})["executed"] is True
    rotated = host.call("plane.receipts_rotate", {"force": True})
    assert rotated["executed"] is True
    assert rotated["result"]["code"] == "ROTATED"
    assert host._dispatcher.engine.chain.tip == GENESIS
    assert host.call("plane.route", {"task": "git status"})["executed"] is True
    ok, msg = ReceiptChain.verify_file(str(path))
    assert ok, msg
    assert _lines(path)[0]["prev_hash"] == GENESIS


def test_missing_file_is_an_intact_gated_call(tmp_path):
    """A missing file is not a broken chain, so the gate runs and writes the receipt.

    The handler then sees that new line and reports INTACT. EMPTY_OR_NEW is only
    what the handler returns when it itself observes no file.
    """
    host = _host(tmp_path)
    path = tmp_path / "chain.jsonl"
    status = host.call("plane.receipts_status")
    assert status["executed"] is True
    assert status["result"]["code"] == "INTACT"
    assert status["result"]["intact"] is True
    ok, msg = ReceiptChain.verify_file(str(path))
    assert ok, msg
    assert _lines(path)[0]["prev_hash"] == GENESIS

    rotated = host.call("plane.receipts_rotate", {})
    assert rotated["executed"] is True
    assert rotated["result"]["code"] == "INTACT"


def test_handler_reports_empty_when_it_sees_no_file(tmp_path):
    host = _host(tmp_path)
    status = host._plane_receipts_status()
    assert status["code"] == "EMPTY_OR_NEW"
    assert status["intact"] is True
    rotated = host._plane_receipts_rotate({})
    assert rotated["code"] == "EMPTY"
