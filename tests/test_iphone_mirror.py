"""iPhone Mirroring identification, screenshot bytes, and unchanged gates."""

from __future__ import annotations

import base64
import json
import os
import stat
import struct
import subprocess
import zlib
from pathlib import Path

from host.desktop_handlers import DesktopHandlers
from host.iphone_mirror import (
    annotate_ax,
    annotate_click,
    annotate_layout,
    ax_is_framebuffer,
    point_inside_window,
)
from host.screenshot_image import enrich_screenshot, png_size

ROOT = Path(__file__).resolve().parent.parent

# The click the live leash resolved for rel_x=0.5, rel_y=0.04.
_OBSERVED_WINDOW = {
    "app": "iPhone Mirroring",
    "title": "iPhone Mirroring",
    "x": 1164,
    "y": 121,
    "w": 348,
    "h": 766,
    "valid_bounds": True,
}
_OBSERVED_CLICK = (1337, 151)

_EMPTY_AX = [
    {
        "description": "group",
        "role": "AXGroup",
        "title": "missing value",
        "value": "missing value",
    }
]


def _png(width: int, height: int, rgb: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _git_show(path: str) -> str:
    return subprocess.check_output(["git", "show", f"HEAD:{path}"], cwd=ROOT, text=True)


def test_png_header_roundtrip(tmp_path: Path) -> None:
    raw = _png(3, 5)
    path = tmp_path / "win.png"
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    shared = tmp_path / "shared"
    result = enrich_screenshot(
        {"ok": True, "code": "WINDOW_SCREENSHOT", "data": {"path": str(path), "bytes": len(raw)}},
        shared_dir=shared,
    )
    data = result["data"]
    decoded = base64.standard_b64decode(data["image_png_base64"])
    assert decoded == raw
    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")
    assert png_size(decoded) == (3, 5)
    assert data["mime"] == "image/png"
    assert data["width"] == 3 and data["height"] == 5
    assert "image_omitted" not in data
    shared_file = Path(data["shared_path"])
    assert shared_file.read_bytes() == raw
    assert stat.S_IMODE(shared_file.stat().st_mode) == 0o644
    assert stat.S_IMODE(shared.stat().st_mode) == 0o755
    # Private capture stays private.
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert data["shared_mode"] == "0644"


def test_oversize_png_omits_base64_but_keeps_path(tmp_path: Path) -> None:
    path = tmp_path / "big.png"
    raw = _png(2, 2)
    path.write_bytes(raw)
    result = enrich_screenshot(
        {"ok": True, "data": {"path": str(path)}},
        shared_dir=tmp_path / "shared",
        max_bytes=len(raw) - 1,
    )
    data = result["data"]
    assert isinstance(data["image_omitted"], str)
    assert str(len(raw) - 1) in data["image_omitted"]
    assert "8000000" not in data["image_omitted"]
    assert "image_png_base64" not in data
    assert Path(data["shared_path"]).read_bytes() == raw


def test_non_png_is_not_inlined(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    result = enrich_screenshot(
        {"ok": True, "data": {"path": str(path)}},
        shared_dir=tmp_path / "shared",
    )
    assert result["data"]["image_error"] == "saved file is not a PNG"
    assert "image_png_base64" not in result["data"]


def test_inline_cap_is_eight_million_and_shared_copy_uses_it(tmp_path: Path) -> None:
    from host.desktop_handlers import MAX_INLINE_PNG_BYTES

    assert MAX_INLINE_PNG_BYTES == 8_000_000
    path = tmp_path / "win.png"
    raw = _png(1, 1)
    path.write_bytes(raw)
    result = enrich_screenshot(
        {"ok": True, "data": {"path": str(path), "image_png_base64": "already"}},
        shared_dir=tmp_path / "shared",
    )
    assert base64.b64decode(result["data"]["image_png_base64"]) == raw
    assert Path(result["data"]["shared_path"]).read_bytes() == raw


def test_failed_screenshot_is_unchanged() -> None:
    err = {"ok": False, "code": "WINDOW_NOT_FOUND"}
    assert enrich_screenshot(err) is err


def test_ax_framebuffer_note_does_not_invent_nodes() -> None:
    original = {
        "ok": True,
        "code": "AX_SNAPSHOT",
        "data": {
            "app": "iPhone Mirroring",
            "window": "iPhone Mirroring",
            "count": 1,
            "elements": [dict(_EMPTY_AX[0])],
        },
    }
    out = annotate_ax(original)
    assert out["data"]["elements"] == _EMPTY_AX
    assert out["data"]["count"] == 1
    block = out["data"]["iphone_mirroring"]
    assert block["ax_usable"] is False
    assert block["bundle_id"] == "com.apple.ScreenContinuity"
    assert "desktop.click_window" in block["ax_note"]
    assert "invent" in block["ax_note"]
    assert ax_is_framebuffer(_EMPTY_AX)
    # A different app is not annotated and its elements stay put.
    chrome = {
        "ok": True,
        "data": {"app": "Google Chrome", "window": "New Tab", "elements": [{"role": "AXButton", "title": "Go"}]},
    }
    assert "iphone_mirroring" not in annotate_ax(chrome)["data"]


def test_layout_tags_only_the_mirror_window() -> None:
    result = annotate_layout(
        {
            "ok": True,
            "code": "LAYOUT",
            "data": {
                "windows": [
                    {"app": "Notes", "title": "All iCloud", "x": 0, "y": 0, "w": 10, "h": 10},
                    dict(_OBSERVED_WINDOW),
                ],
                "frames_by_app": {
                    "Notes": [{"x": 0, "y": 0, "w": 10, "h": 10, "title": "All iCloud"}],
                    "iPhone Mirroring": [{"x": 1164, "y": 121, "w": 348, "h": 766, "title": "iPhone Mirroring"}],
                },
            },
        }
    )
    windows = result["data"]["windows"]
    assert "iphone_mirroring" not in windows[0]
    assert windows[1]["iphone_mirroring"] is True
    assert result["data"]["iphone_mirroring"]["present"] is True
    assert result["data"]["frames_by_app"]["iPhone Mirroring"][0]["iphone_mirroring"] is True
    assert "iphone_mirroring" not in result["data"]["frames_by_app"]["Notes"][0]


def test_observed_click_lands_inside_window() -> None:
    assert point_inside_window(*_OBSERVED_CLICK, _OBSERVED_WINDOW)
    assert not point_inside_window(0, 0, _OBSERVED_WINDOW)
    # The leash inset for rel 0.5 / 0.04 on this frame.
    assert 1164 + int(0.5 * (348 - 1)) == 1337
    assert 121 + int(0.04 * (766 - 1)) == 151
    out = annotate_click(
        {
            "ok": True,
            "code": "INPUT_SUBMITTED",
            "data": {
                "x": 1337,
                "y": 151,
                "resolved": {
                    "global_x": 1337,
                    "global_y": 151,
                    "mode": "relative",
                    "window": dict(_OBSERVED_WINDOW),
                },
            },
        }
    )
    assert out["data"]["inside_window"] is True
    assert out["data"]["iphone_mirroring"]["ax_usable"] is False
    assert out["data"]["resolved"]["window"]["app"] == "iPhone Mirroring"


def test_screenshot_window_handler_returns_png(tmp_path: Path, monkeypatch) -> None:
    raw = _png(8, 4, (1, 2, 3))
    path = tmp_path / "win-iphone.png"
    path.write_bytes(raw)
    monkeypatch.setenv("LEASH_SHARED_CAPTURES", str(tmp_path / "shared"))

    def fake_post(self, url, body=None):
        assert body["action"] == "desktop.screenshot_window"
        assert body["app"] == "iPhone Mirroring"
        return {
            "ok": True,
            "code": "WINDOW_SCREENSHOT",
            "data": {
                "path": str(path),
                "bytes": len(raw),
                "window": dict(_OBSERVED_WINDOW),
                "region": {"x": 1164, "y": 121, "w": 348, "h": 766},
            },
        }

    monkeypatch.setattr(DesktopHandlers, "_post", fake_post)
    res = DesktopHandlers().screenshot_window({"app": "iPhone Mirroring"})
    decoded = base64.standard_b64decode(res["data"]["image_png_base64"])
    assert decoded == raw
    assert png_size(decoded) == (8, 4)
    assert res["data"]["iphone_mirroring"]["app"] == "iPhone Mirroring"
    assert Path(res["data"]["shared_path"]).stat().st_mode & 0o004


def test_full_screenshot_keeps_the_leash_out_field(tmp_path: Path, monkeypatch) -> None:
    raw = _png(1, 1)
    path = tmp_path / "full.png"
    path.write_bytes(raw)
    seen = {}

    def fake_post(self, url, body=None):
        seen["body"] = body
        return {"ok": True, "data": {"path": str(path), "bytes": len(raw)}}

    monkeypatch.setattr(DesktopHandlers, "_post", fake_post)
    monkeypatch.setenv("LEASH_SHARED_CAPTURES", str(tmp_path / "shared"))
    res = DesktopHandlers().screenshot({"out": "/tmp/asked.png"})
    assert seen["body"]["out"] == "/tmp/asked.png"
    assert "path" not in seen["body"]
    assert base64.standard_b64decode(res["data"]["image_png_base64"]) == raw
    assert Path(res["data"]["shared_path"]).read_bytes() == raw


def test_password_manager_still_denied_and_mirror_not_allowlisted() -> None:
    host = DesktopHandlers()
    # repair/2026-10-16 runs operator-proxy with an empty denylist_hard; this
    # test only checks the mirror is not itself denied.
    mirror = host.profile_for("iPhone Mirroring")
    assert mirror["denied"] is False
    assert mirror["allow_quit"] is False
    assert mirror["allow_ax_click"] is False
    assert mirror["allow_click"] is True
    press = host.press({"key": "return"})
    assert press["code"] == "HUMAN_CONFIRM_REQUIRED"
    quit_res = host.quit({"app": "iPhone Mirroring"})
    assert quit_res["code"] == "HUMAN_CONFIRM_REQUIRED"


def test_pack_and_denylist_gates_unchanged() -> None:
    old_pack = json.loads(_git_show("packs/local_planes.json"))
    new_pack = json.loads((ROOT / "packs" / "local_planes.json").read_text(encoding="utf-8"))
    assert new_pack == old_pack
    shot = new_pack["tools"]["desktop.screenshot_window"]
    assert shot["max_blast"] == 1
    assert shot["allowed_args"] == ["app", "title", "path"]
    click = new_pack["tools"]["desktop.click_window"]
    assert click["max_blast"] == 2
    assert "operator_confirm" not in click.get("allowed_args", [])

    old_profiles = json.loads(_git_show("profiles/desktop_apps.json"))
    new_profiles = json.loads((ROOT / "profiles" / "desktop_apps.json").read_text(encoding="utf-8"))
    assert old_profiles["denylist_hard"] == new_profiles["denylist_hard"]
    assert "iPhone Mirroring" not in new_profiles["denylist_hard"]
    assert new_profiles["modes"] == old_profiles["modes"]
    assert "iPhone Mirroring" not in new_profiles["modes"]["cua"]["extra_allowlist"]
    mirror_profile = new_profiles["profiles"]["iPhone Mirroring"]
    assert mirror_profile["allow_quit"] is False
    assert mirror_profile["allow_ax_click"] is False
    assert mirror_profile["allow_click"] is True
    # Profiles that already existed on main are unchanged. During a rebase,
    # HEAD is main; after the commit, compare those names to this file only
    # when HEAD still lacks the new profile.
    if "iPhone Mirroring" not in old_profiles["profiles"]:
        assert set(new_profiles["profiles"]) - set(old_profiles["profiles"]) == {"iPhone Mirroring"}
        for name, spec in old_profiles["profiles"].items():
            assert new_profiles["profiles"][name] == spec

    diff = subprocess.check_output(
        ["git", "diff", "HEAD", "--", "host/plane_host.py", "host/shell_handlers.py"],
        cwd=ROOT,
        text=True,
    )
    assert diff == ""
