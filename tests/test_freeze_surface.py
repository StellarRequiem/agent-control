"""The status surface must report the one condition it is named for.

A freeze was invisible from every status tool. `plane.status` reported leash arm state
and never looked at the markers; `lockdown_status` was a bare alias for it. So a
pre-flight check returned "armed, no freeze field" while the plane was frozen, and the
only way to find out was to trip it with a call that then got denied.

That is worse than an absent feature. A status tool that cannot report a freeze does not
merely fail to help — it tells a careful caller the opposite of the truth, and rewards
checking first with a wrong answer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from host import plane_host  # noqa: E402
from host.plane_host import FREEZE_ALLOW, FREEZE_PATHS, freeze_surface  # noqa: E402


@pytest.fixture
def markers(tmp_path, monkeypatch):
    """Point the freeze markers at a scratch directory, never the live ones."""
    paths = (tmp_path / "a" / "FREEZE", tmp_path / "b" / "FREEZE")
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(plane_host, "FREEZE_PATHS", paths)
    return paths


def test_no_markers_reads_as_not_engaged(markers):
    s = freeze_surface()
    assert s["engaged"] is False and s["markers"] == []
    assert "no freeze" in s["detail"]


def test_a_marker_makes_it_engaged(markers):
    markers[0].write_text("agent-soc freeze\n", encoding="utf-8")
    assert freeze_surface()["engaged"] is True


def test_the_reason_and_timestamp_survive(markers):
    """The marker already carries who froze it, why and when. Discarding that was the
    substance of the blindspot — a caller who knows only 'frozen' cannot tell a
    deliberate operator hold from an automated trip."""
    markers[0].write_text(
        "agent-soc freeze\n"
        "reason=agent-soc watch: abhorrent severity=critical rules=['ABHORRENT_TOOL_SPRAY']\n"
        "ts=2026-09-02T03:43:21Z\n",
        encoding="utf-8")
    (m,) = freeze_surface()["markers"]
    assert m["source"] == "agent-soc freeze"
    assert "ABHORRENT_TOOL_SPRAY" in m["reason"]
    assert m["ts"] == "2026-09-02T03:43:21Z"


def test_every_marker_is_reported_not_just_the_first(markers):
    for p in markers:
        p.write_text("agent-soc freeze\n", encoding="utf-8")
    assert len(freeze_surface()["markers"]) == 2


def test_an_unreadable_marker_is_reported_rather_than_skipped(markers, monkeypatch):
    """Silently skipping an unreadable marker would under-report a freeze, which is
    the exact failure direction this whole fix exists to close."""
    markers[0].write_text("agent-soc freeze\n", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", boom)
    (m,) = freeze_surface()["markers"]
    assert "unreadable" in m
    assert freeze_surface()["engaged"] is True     # still engaged, not swallowed


def test_a_malformed_marker_still_counts_as_engaged(markers):
    markers[0].write_text("\x00\x01 not a freeze file at all", encoding="utf-8")
    assert freeze_surface()["engaged"] is True


def test_the_allowlist_is_reported_alongside(markers):
    """A caller should learn what still works at the same moment it learns it is
    frozen, rather than discovering the allowlist one denial at a time."""
    markers[0].write_text("agent-soc freeze\n", encoding="utf-8")
    s = freeze_surface()
    assert "plane.unfreeze" in s["allowed_while_frozen"]
    assert "plane.status" in s["allowed_while_frozen"]
    assert sorted(FREEZE_ALLOW) == s["allowed_while_frozen"]


def test_status_and_unfreeze_share_one_path_list():
    """They used to disagree: unfreeze knew three paths, status knew none. One list
    means they cannot drift apart again."""
    import inspect
    src = inspect.getsource(plane_host.AssuredPlaneHost._plane_unfreeze)
    assert "FREEZE_PATHS" in src
    assert 'ROOT / "FREEZE"' not in src        # no second, private copy of the list


def test_the_path_list_has_no_duplicates():
    """ROOT is usually ~/agent-control, so the literal list carried that path twice.
    unfreeze hid it behind a set(); a status surface would have reported one marker
    as two."""
    assert len(FREEZE_PATHS) == len(set(FREEZE_PATHS))


def test_freeze_surface_reads_only(markers):
    markers[0].write_text("agent-soc freeze\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in markers if p.exists()}
    freeze_surface()
    after = {p: p.read_bytes() for p in markers if p.exists()}
    assert before == after
    assert not markers[1].exists()             # nothing created either


def test_plane_status_carries_the_freeze_block():
    """The fix lives in plane.status, not in lockdown_status, so every caller of
    either gets it — including anyone who pre-flights with plane_status the way the
    default path document tells them to."""
    import inspect
    src = inspect.getsource(plane_host.AssuredPlaneHost._plane_status)
    assert '"freeze": freeze_surface()' in src
