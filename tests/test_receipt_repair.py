"""Receipt diagnose/rotate when the receipt chain is broken.

Older mcp-assure (PyPI 0.3.2, what CI installs) has no chain_repair_allow.
evaluate() then denies plane.receipts_status and plane.receipts_rotate with
CHAIN_BROKEN before the pack, argument, dry_run, and AdaptiveGate checks, and
appends that deny onto the poison file. Newer engines accept the hook and let
those tools through the rest of the gate, but the decision receipt would still
be chained off the poison tip.

The host runs the repair tools through the dispatcher either way. It skips only
that append. DENY and DRY_RUN leave the file untouched and create no archive.
ALLOW archives the file and replaces the in-memory tip so the next gated
append starts at genesis.

The old/new fixtures subclass the installed engine so both paths run here even
when the environment has only one of them. Installed-engine tests stay
capability-aware: they must not assume rotate_if_broken is absent.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest
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


def _engine_accepts_chain_repair_allow() -> bool:
    from mcp_assure import AssureEngine

    try:
        params = inspect.signature(AssureEngine.__init__).parameters
    except (TypeError, ValueError):
        return False
    return "chain_repair_allow" in params


def test_host_follows_the_installed_repair_hook(tmp_path):
    """CI installs mcp-assure>=0.3.2, which today rejects chain_repair_allow.

    A newer engine accepts the kwarg and may also ship rotate_if_broken.
    The host has to follow whichever library is installed.
    """
    host = _host(tmp_path)
    accepts = _engine_accepts_chain_repair_allow()
    assert host._engine_chain_repair is accepts
    if accepts:
        allow = host._dispatcher.engine.chain_repair_allow
        assert "plane.receipts_status" in allow
        assert "plane.receipts_rotate" in allow
    else:
        assert not hasattr(host._dispatcher.engine, "chain_repair_allow")


def _install_engine(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    """Force the host down the old or new repair path.

    ``old`` rejects chain_repair_allow the way PyPI 0.3.2 does. ``new`` accepts
    it and does not short-circuit those tools with CHAIN_BROKEN, the way a
    newer AssureEngine.evaluate does. The subclass sits on the installed
    engine, so the rest of the gate is the real one.
    """
    import host.plane_host as plane_host

    real = plane_host.AssureEngine

    class FixtureEngine(real):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            repair = kwargs.pop("chain_repair_allow", None)
            if kind == "old" and repair is not None:
                raise TypeError("unexpected keyword argument 'chain_repair_allow'")
            super().__init__(*args, **kwargs)
            if kind == "new":
                self.chain_repair_allow = frozenset(repair or ())

        def evaluate(self, call):
            allow = getattr(self, "chain_repair_allow", ())
            tool = (getattr(call, "tool", "") or "").strip()
            if kind == "new" and tool in allow:
                previous = self.require_intact_chain
                self.require_intact_chain = False
                try:
                    return super().evaluate(call)
                finally:
                    self.require_intact_chain = previous
            return super().evaluate(call)

    monkeypatch.setattr(plane_host, "AssureEngine", FixtureEngine)


@pytest.fixture
def repair_case(tmp_path, monkeypatch, request):
    kind = request.param
    _install_engine(monkeypatch, kind)
    host = _host(tmp_path)
    path = tmp_path / "chain.jsonl"
    _poison(path)
    if kind == "old":
        assert host._engine_chain_repair is False
    else:
        assert host._engine_chain_repair is True
        assert "plane.receipts_rotate" in host._dispatcher.engine.chain_repair_allow
    return kind, host, path


def _watch(host: AssuredPlaneHost, name: str) -> list:
    """Record handler invocations. A denied repair must not enter this list."""
    handlers = host._dispatcher.runner.handlers
    original = handlers[name]
    called: list = []

    def wrapped(args):
        called.append(dict(args or {}))
        return original(args)

    handlers[name] = wrapped
    return called


def _assert_untouched(path: Path, before: str) -> None:
    assert path.read_text(encoding="utf-8") == before
    archives = [p.name for p in path.parent.iterdir() if p != path and "broken" in p.name]
    assert archives == []


def _direct_verdict(host: AssuredPlaneHost, name: str, arguments: dict):
    """Engine decision with the receipt append silenced, so the probe does not
    grow the poison file the host call is about to be measured against."""
    engine = host._dispatcher.engine
    original = engine.chain.append

    def _silent(**_kwargs):
        return None

    engine.chain.append = _silent
    try:
        return engine.evaluate(host._bound_call(name, arguments))
    finally:
        engine.chain.append = original


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
    # rotate_if_broken names archives "*.broken-<ts>", the host helper
    # "*.broken". Neither may appear when the chain is intact and force is off.
    assert not any("broken" in p.name for p in tmp_path.iterdir())


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


_BOTH = pytest.mark.parametrize(
    "repair_case",
    ["old", "new"],
    indirect=True,
    ids=["old-engine", "new-engine"],
)


def _catalog_without(host: AssuredPlaneHost, tool: str) -> None:
    from mcp_assure.policy import ToolPolicyRegistry

    reg = host._dispatcher.engine.registry
    kept = [reg.get(name) for name in reg.names() if name != tool]
    host._dispatcher.engine.registry = ToolPolicyRegistry(
        [policy for policy in kept if policy is not None]
    )


def _chain_denial_appends(host: AssuredPlaneHost) -> bool:
    """PyPI 0.3.2 appends a CHAIN_BROKEN deny. Newer engines skip that write."""
    try:
        params = inspect.signature(host._dispatcher.engine._finish).parameters
    except (TypeError, ValueError):
        return True
    return "skip_receipt" not in params


@_BOTH
@pytest.mark.parametrize("tool", ["plane.receipts_rotate", "plane.receipts_status"])
def test_repair_permission_absent_from_the_pack(repair_case, tool):
    _kind, host, path = repair_case
    before = path.read_text(encoding="utf-8")
    _catalog_without(host, tool)
    called = _watch(host, tool)

    denied = host.call(tool, {})
    assert denied["executed"] is False
    assert denied["result"] is None
    assert denied["verdict"]["decision"] == "DENY"
    assert denied["verdict"]["code"] == "UNKNOWN_TOOL"
    assert denied["verdict"]["allowed"] is False
    assert "chain repair ran locally" not in denied["verdict"]["detail"]
    assert called == []
    _assert_untouched(path, before)


@_BOTH
def test_dry_run_only_rotate_does_not_archive(repair_case):
    _kind, host, path = repair_case
    before = path.read_text(encoding="utf-8")
    registry = host._dispatcher.engine.registry
    policy = registry.get("plane.receipts_rotate")
    registry.register(replace(policy, dry_run_only=True))
    called = _watch(host, "plane.receipts_rotate")

    denied = host.call("plane.receipts_rotate", {"force": True})
    assert denied["executed"] is False
    assert denied["result"] is None
    assert denied["verdict"]["decision"] == "DRY_RUN"
    assert denied["verdict"]["code"] == "DRY_RUN_ONLY"
    assert denied["verdict"]["allowed"] is False
    assert called == []
    _assert_untouched(path, before)

    registry.register(replace(policy, dry_run_only=False))
    repaired = host.call("plane.receipts_rotate", {})
    assert repaired["executed"] is True
    assert repaired["result"]["code"] == "ROTATED"
    assert called and called[-1] == {}


@_BOTH
@pytest.mark.parametrize("tool", ["plane.receipts_rotate", "plane.receipts_status"])
def test_invalid_repair_arguments_do_not_rotate(repair_case, tool):
    kind, host, path = repair_case
    before = path.read_text(encoding="utf-8")
    arguments = {"extra": 1}
    called = _watch(host, tool)

    # The engine itself, before the host lifts anything: an old engine stops
    # at the broken chain and never sees the arguments. A new engine already
    # applies argument policy to repair tools.
    direct = _direct_verdict(host, tool, arguments)
    if kind == "old":
        assert direct.code == "CHAIN_BROKEN"
    else:
        assert direct.code == "ARG_POLICY"

    denied = host.call(tool, arguments)
    assert denied["executed"] is False
    assert denied["result"] is None
    assert denied["verdict"]["decision"] == "DENY"
    assert denied["verdict"]["code"] == "ARG_POLICY"
    assert denied["verdict"]["allowed"] is False
    assert called == []
    _assert_untouched(path, before)

    if tool == "plane.receipts_rotate":
        repaired = host.call(tool, {})
        assert repaired["executed"] is True
        assert repaired["result"]["code"] == "ROTATED"
        assert Path(repaired["result"]["archived"]).is_file()


@_BOTH
def test_adaptive_gate_denial_does_not_rotate(repair_case):
    """A critical argument smell is AdaptiveGate's pre-block, not arg policy.

    ``force`` is an allowed key, so a synthesized ALLOW would archive the file.
    """
    _kind, host, path = repair_case
    before = path.read_text(encoding="utf-8")
    called = _watch(host, "plane.receipts_rotate")

    denied = host.call("plane.receipts_rotate", {"force": "{{ exec }}"})
    assert denied["executed"] is False
    assert denied["result"] is None
    assert denied["verdict"]["decision"] == "DENY"
    assert denied["verdict"]["code"] == "PROACTIVE_ARG_BLOCK"
    assert denied.get("adapted") is True
    assert denied["verdict"]["allowed"] is False
    assert called == []
    _assert_untouched(path, before)

    repaired = host.call("plane.receipts_rotate", {})
    assert repaired["executed"] is True
    assert repaired["result"]["code"] == "ROTATED"


@_BOTH
def test_allowed_repair_resets_the_chain_for_the_next_gated_call(repair_case):
    _kind, host, path = repair_case
    before = path.read_text(encoding="utf-8")

    status = host.call("plane.receipts_status")
    assert status["executed"] is True
    assert status["verdict"]["decision"] == "ALLOW"
    assert status["result"]["code"] == "BROKEN"
    assert path.read_text(encoding="utf-8") == before

    rotated = host.call("plane.receipts_rotate", {})
    assert rotated["executed"] is True
    assert rotated["verdict"]["decision"] == "ALLOW"
    assert rotated["result"]["code"] == "ROTATED"
    archive = Path(rotated["result"]["archived"])
    assert archive.is_file()
    assert "deadbeef" in archive.read_text(encoding="utf-8")
    ok, msg = ReceiptChain.verify_file(str(path))
    assert ok, msg
    assert host._dispatcher.engine.chain.tip == GENESIS

    again = host.call("plane.receipts_status")
    assert again["executed"] is True
    assert again["result"]["code"] == "INTACT"
    ok, msg = ReceiptChain.verify_file(str(path))
    assert ok, msg
    recs = _lines(path)
    assert recs[0]["prev_hash"] == GENESIS
    assert recs[-1]["tool"] == "plane.receipts_status"


@_BOTH
def test_other_tools_stay_denied_on_a_broken_chain(repair_case):
    _kind, host, path = repair_case
    before = path.read_text(encoding="utf-8")
    denied = host.call("plane.route", {"task": "git status"})
    assert denied["executed"] is False
    assert denied["verdict"]["code"] == "CHAIN_BROKEN"
    # The repair bypass is only the two receipt tools. Other tools keep the
    # engine's own chain handling: 0.3.2 appends the deny, newer engines
    # skip that write.
    grew = path.read_text(encoding="utf-8") != before
    assert grew is _chain_denial_appends(host)
