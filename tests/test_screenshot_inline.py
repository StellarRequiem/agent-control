"""Screenshot results include the PNG the leash already wrote.

desktop.screenshot, desktop.screenshot_window, and desktop.region_screenshot
keep the on-disk file and also return standard base64 of those bytes, plus
width/height read from the PNG header. Over the inline cap the bytes stay on
disk and the result says why they were left out. Gate and leash request
bodies are not part of this change.
"""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

from host.desktop_handlers import (
    MAX_INLINE_PNG_BYTES,
    DesktopHandlers,
    attach_inline_png,
)


def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _png(width: int, height: int, rgb: tuple[int, int, int] = (12, 34, 56)) -> bytes:
    """A real RGB PNG: signature, IHDR, one IDAT, IEND."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def _decode_png(blob: bytes) -> tuple[int, int, bytes]:
    """Return width, height, and the uncompressed image rows (filter bytes included)."""
    assert blob.startswith(b"\x89PNG\r\n\x1a\n")
    pos = 8
    width = height = None
    idat = b""
    saw_iend = False
    while pos < len(blob):
        (length,) = struct.unpack(">I", blob[pos : pos + 4])
        tag = blob[pos + 4 : pos + 8]
        data = blob[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", blob[pos + 8 + length : pos + 12 + length])
        assert crc == (zlib.crc32(tag + data) & 0xFFFFFFFF)
        if tag == b"IHDR":
            width, height, bit, color, *_ = struct.unpack(">IIBBBBB", data)
            assert bit == 8 and color == 2
        elif tag == b"IDAT":
            idat += data
        elif tag == b"IEND":
            saw_iend = True
        pos += 12 + length
    assert saw_iend and width and height
    return width, height, zlib.decompress(idat)


def test_base64_round_trips_to_the_same_png(tmp_path: Path):
    png = _png(2, 3, (9, 8, 7))
    path = tmp_path / "shot.png"
    path.write_bytes(png)
    leash = {
        "ok": True,
        "code": "SCREENSHOT",
        "id": "job-1",
        "action": "desktop.screenshot",
        "tier": 1,
        "data": {"path": str(path), "bytes": len(png), "ts": 1.5},
    }

    out = attach_inline_png(leash)

    assert out["ok"] is True and out["code"] == "SCREENSHOT"
    assert out["id"] == "job-1" and out["action"] == "desktop.screenshot" and out["tier"] == 1
    assert out["data"]["path"] == str(path)
    assert out["data"]["bytes"] == len(png)
    assert out["data"]["ts"] == 1.5
    assert out["data"]["mime"] == "image/png"
    assert out["data"]["width"] == 2 and out["data"]["height"] == 3
    assert "image_omitted" not in out["data"]
    decoded = base64.b64decode(out["data"]["image_png_base64"], validate=True)
    assert decoded == png
    assert decoded == path.read_bytes()
    width, height, rows = _decode_png(decoded)
    assert (width, height) == (2, 3)
    assert rows == b"".join(b"\x00" + bytes((9, 8, 7)) * 2 for _ in range(3))


def test_existing_width_and_height_are_kept(tmp_path: Path):
    path = tmp_path / "shot.png"
    path.write_bytes(_png(4, 5))
    out = attach_inline_png(
        {"ok": True, "data": {"path": str(path), "width": 4, "height": 5, "mime": "image/png"}}
    )
    assert out["data"]["width"] == 4 and out["data"]["height"] == 5
    assert out["data"]["mime"] == "image/png"
    assert base64.b64decode(out["data"]["image_png_base64"]) == path.read_bytes()


def test_over_cap_keeps_the_file_and_names_the_limit(tmp_path: Path):
    png = _png(1, 1)
    path = tmp_path / "big.png"
    path.write_bytes(png)
    before = path.read_bytes()
    cap = len(png) - 1

    out = attach_inline_png(
        {"ok": True, "code": "WINDOW_SCREENSHOT", "data": {"path": str(path), "bytes": len(png)}},
        max_bytes=cap,
    )

    assert path.read_bytes() == before
    assert "image_png_base64" not in out["data"]
    assert out["data"]["path"] == str(path)
    assert out["data"]["bytes"] == len(png)
    assert out["data"]["width"] == 1 and out["data"]["height"] == 1
    assert str(len(png)) in out["data"]["image_omitted"]
    assert str(cap) in out["data"]["image_omitted"]
    assert "data.path" in out["data"]["image_omitted"]


def test_default_cap_is_eight_million_bytes():
    assert MAX_INLINE_PNG_BYTES == 8_000_000


def test_failure_and_missing_path_are_unchanged(tmp_path: Path):
    failed = {"ok": False, "code": "SCREENSHOT_FAIL", "path": str(tmp_path / "missing.png")}
    assert attach_inline_png(failed) is failed
    no_path = {"ok": True, "code": "SCREENSHOT", "data": {"bytes": 0}}
    assert attach_inline_png(no_path) is no_path


def test_directory_path_is_not_read_as_png(tmp_path: Path):
    out = attach_inline_png({"ok": True, "data": {"path": str(tmp_path)}})
    assert "image_png_base64" not in out["data"]
    assert out["data"]["image_error"] == "png read failed: not a regular file"


def test_unreadable_or_not_png_does_not_invent_bytes(tmp_path: Path):
    missing = attach_inline_png(
        {"ok": True, "data": {"path": str(tmp_path / "nope.png")}}
    )
    assert "image_png_base64" not in missing["data"]
    assert missing["data"]["image_error"].startswith("png read failed:")

    text = tmp_path / "notes.png"
    text.write_text("not a png", encoding="utf-8")
    bad = attach_inline_png({"ok": True, "data": {"path": str(text)}})
    assert "image_png_base64" not in bad["data"]
    assert bad["data"]["image_error"] == "saved file is not a PNG"
    assert text.read_text(encoding="utf-8") == "not a png"


def test_top_level_path_is_read_when_data_has_none(tmp_path: Path):
    path = tmp_path / "region.png"
    path.write_bytes(_png(1, 1, (1, 2, 3)))
    out = attach_inline_png({"ok": True, "code": "REGION_SCREENSHOT", "path": str(path)})
    assert out["path"] == str(path)
    decoded = base64.b64decode(out["data"]["image_png_base64"])
    width, height, rows = _decode_png(decoded)
    assert (width, height) == (1, 1)
    assert rows == b"\x00" + bytes((1, 2, 3))


def test_handlers_attach_png_without_changing_the_leash_request(tmp_path: Path, monkeypatch):
    png = _png(3, 1, (255, 128, 0))
    shot = tmp_path / "captures" / "shot.png"
    window = tmp_path / "captures" / "win.png"
    region = tmp_path / "captures" / "region.png"
    for path in (shot, window, region):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)

    seen: list[tuple[str, str, dict]] = []

    def fake_post(self, url: str, body: dict | None = None):
        seen.append((self.base, url, dict(body or {})))
        action = (body or {}).get("action")
        saved = {
            "desktop.screenshot": shot,
            "desktop.screenshot_window": window,
            "desktop.region_screenshot": region,
        }[action]
        return {
            "ok": True,
            "code": "SCREENSHOT",
            "action": action,
            "tier": 1,
            "data": {"path": str(saved), "bytes": saved.stat().st_size},
        }

    monkeypatch.setattr(DesktopHandlers, "_post", fake_post)
    desktop = DesktopHandlers(base="http://127.0.0.1:8757")

    full = desktop.screenshot({"out": str(tmp_path / "custom.png")})
    win = desktop.screenshot_window({"app": "TextEdit", "title": "Untitled", "path": str(window)})
    reg = desktop.region_screenshot({"x": 10, "y": 20, "w": 30, "h": 40, "path": str(region)})

    assert seen == [
        (
            "http://127.0.0.1:8757",
            "/v1/action",
            {"action": "desktop.screenshot", "out": str(tmp_path / "custom.png")},
        ),
        (
            "http://127.0.0.1:8757",
            "/v1/action",
            {
                "action": "desktop.screenshot_window",
                "app": "TextEdit",
                "title": "Untitled",
                "path": str(window),
            },
        ),
        (
            "http://127.0.0.1:8757",
            "/v1/action",
            {
                "action": "desktop.region_screenshot",
                "x": 10,
                "y": 20,
                "w": 30,
                "h": 40,
                "path": str(region),
            },
        ),
    ]
    for result, saved in ((full, shot), (win, window), (reg, region)):
        assert result["tier"] == 1 and result["ok"] is True
        decoded = base64.b64decode(result["data"]["image_png_base64"], validate=True)
        assert decoded == saved.read_bytes() == png
        width, height, rows = _decode_png(decoded)
        assert (width, height) == (3, 1)
        assert rows == b"\x00" + bytes((255, 128, 0)) * 3
        assert result["data"]["width"] == 3 and result["data"]["height"] == 1
