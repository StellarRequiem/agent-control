"""Receipt appends stay one chain under concurrent writers.

PyPI mcp-assure 0.3.2 keeps the tip in memory and locks only with
threading.Lock. Two AssuredPlaneHost objects (the HTTP process and a stdio
process, or two hosts in this file) would otherwise append from the same
stale tip and break the hash chain. The host adds a sidecar flock and a tip
reload when the library does not already, and an RLock around call so one
thread can re-enter (CUA) without letting another thread interleave.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from mcp_assure.receipts import ReceiptChain

from host.plane_host import AssuredPlaneHost
from host.receipt_lock import install_receipt_file_lock, library_appends_under_flock
from host.stdio_actor import HTTP_ACTOR, ensure_actor_on_roster

ROOT = Path(__file__).resolve().parent.parent


def _host(tmp_path: Path, *, actor: str = "grok") -> AssuredPlaneHost:
    return AssuredPlaneHost(
        receipts_path=tmp_path / "plane-host.jsonl",
        freeze_path=tmp_path / "FREEZE",
        roster_dir=tmp_path,
        actor=actor,
    )


def _lines(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


class _FlockingChain:
    """Stand-in whose append source mentions flock, so we must not wrap it."""

    def __init__(self, path: str) -> None:
        self.path = path

    def append(self, **kwargs):
        import fcntl

        fcntl.flock(0, fcntl.LOCK_EX)
        return kwargs


def test_library_flock_is_not_wrapped_again(tmp_path):
    chain = _FlockingChain(str(tmp_path / "chain.jsonl"))
    assert library_appends_under_flock(chain) is True
    assert install_receipt_file_lock(chain) is False
    assert getattr(chain, "_agent_control_flock", False) is False


def test_installed_chain_is_file_locked_or_already_flocks(tmp_path):
    host = _host(tmp_path)
    chain = host._dispatcher.engine.chain
    # Class method, not the wrapper: upstream flock lives on ReceiptChain.append.
    assert library_appends_under_flock(chain) or chain._agent_control_flock is True


def test_reentrant_call_does_not_deadlock(tmp_path):
    """cua.step calls host.call on the same thread. A plain Lock would stick."""
    host = _host(tmp_path)
    handlers = host._dispatcher.runner.handlers
    original = handlers["plane.route"]

    def wrapped(args):
        inner = host.call("shell.roots", {})
        assert inner.get("executed") is True
        return original(args)

    handlers["plane.route"] = wrapped
    box: dict = {}

    def run() -> None:
        box["out"] = host.call("plane.route", {"task": "git status"})

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    assert box["out"]["executed"] is True
    ok, msg = ReceiptChain.verify_file(str(tmp_path / "plane-host.jsonl"))
    assert ok, msg


def test_two_hosts_sharing_a_file_keep_the_chain(tmp_path):
    """Separate chain objects are the cross-process failure mode, in one process."""
    path = tmp_path / "shared.jsonl"
    roster = tmp_path / "roster"
    roster.mkdir()
    ensure_actor_on_roster(HTTP_ACTOR, roster)

    def make() -> AssuredPlaneHost:
        return AssuredPlaneHost(
            actor=HTTP_ACTOR,
            actor_binding="http_process",
            receipts_path=path,
            freeze_path=tmp_path / "FREEZE",
            roster_dir=roster,
        )

    hosts = [make(), make()]
    errors: list = []

    def hammer(host: AssuredPlaneHost, n0: int) -> None:
        try:
            for i in range(12):
                out = host.call("plane.route", {"task": f"git status {n0}-{i}"})
                if not out.get("executed"):
                    errors.append(out)
        except Exception as exc:  # noqa: BLE001 — fail the test with the error
            errors.append(exc)

    threads = [
        threading.Thread(target=hammer, args=(host, i)) for i, host in enumerate(hosts)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    ok, msg = ReceiptChain.verify_file(str(path))
    assert ok, msg
    rows = _lines(path)
    assert len(rows) == 24
    assert {row["actor"] for row in rows} == {"http"}


def test_two_processes_keep_the_chain(tmp_path):
    chain = tmp_path / "plane-host.jsonl"
    roster = tmp_path / "roster"
    roster.mkdir()
    script = """
import os, sys
sys.path.insert(0, os.environ["REPO"])
from host.plane_host import AssuredPlaneHost
from host.stdio_actor import HTTP_ACTOR, ensure_actor_on_roster
ensure_actor_on_roster(HTTP_ACTOR, os.environ["ROSTER"])
host = AssuredPlaneHost(
    actor=HTTP_ACTOR,
    actor_binding="http_process",
    receipts_path=os.environ["CHAIN"],
    freeze_path=os.environ["FREEZE"],
    roster_dir=os.environ["ROSTER"],
)
for i in range(int(os.environ["N"])):
    out = host.call("plane.route", {"task": "git status %s %s" % (os.getpid(), i)})
    if not out.get("executed"):
        raise SystemExit("denied")
"""
    env = os.environ.copy()
    env.update(
        {
            "REPO": str(ROOT),
            "ROSTER": str(roster),
            "CHAIN": str(chain),
            "FREEZE": str(tmp_path / "FREEZE"),
            "N": "8",
        }
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", script], env=env) for _ in range(2)
    ]
    try:
        codes = [proc.wait(timeout=60) for proc in procs]
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
    assert codes == [0, 0]
    ok, msg = ReceiptChain.verify_file(str(chain))
    assert ok, msg
    rows = _lines(chain)
    assert len(rows) == 16
    assert {row["actor"] for row in rows} == {HTTP_ACTOR}
