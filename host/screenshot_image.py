"""Publish a world-readable copy of a leash capture.

Inline PNG bytes stay with ``attach_inline_png`` in ``host.desktop_handlers``
(one encoder, cap ``MAX_INLINE_PNG_BYTES`` = 8_000_000). This module does not
define a second cap or a second base64 field. It copies the file the leash
already wrote to ``/Users/Shared/leash-captures/`` (mode 0644) and leaves the
private capture's mode alone.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
DEFAULT_SHARED_DIR = Path("/Users/Shared/leash-captures")


def shared_capture_dir() -> Path:
    raw = (os.environ.get("LEASH_SHARED_CAPTURES") or "").strip()
    return Path(raw) if raw else DEFAULT_SHARED_DIR


def png_size(data: bytes) -> tuple[int, int] | None:
    """Width and height from a PNG IHDR. None when the header is not a PNG."""
    if len(data) < 24 or not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def publish_shared_capture(src: Path, dest_dir: Path | None = None) -> dict[str, Any]:
    """Copy src into the shared capture dir as a world-readable file.

    Failures are reported on the dict and do not raise.
    """
    try:
        dest_root = dest_dir or shared_capture_dir()
        name = src.name
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            return {"shared_path_error": "capture name is not a single path segment"}
        dest_root.mkdir(parents=True, exist_ok=True)
        os.chmod(dest_root, 0o755)
        dest = dest_root / name
        try:
            if dest.resolve() == src.resolve():
                os.chmod(dest, 0o644)
                return {
                    "shared_path": str(dest),
                    "shared_bytes": dest.stat().st_size,
                    "shared_mode": "0644",
                }
        except OSError:
            pass
        payload = src.read_bytes()
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        os.chmod(dest, 0o644)
        return {
            "shared_path": str(dest),
            "shared_bytes": len(payload),
            "shared_mode": "0644",
        }
    except OSError as exc:
        return {"shared_path_error": str(exc)}


def enrich_screenshot(
    result: dict[str, Any],
    *,
    shared_dir: Path | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Attach #8's inline PNG, then add the shared capture path.

    ``max_bytes`` defaults to ``MAX_INLINE_PNG_BYTES`` (8_000_000), read at
    call time. ``image_png_base64`` / ``image_omitted`` / ``image_error`` are
    whatever ``attach_inline_png`` produced.
    """
    from host.desktop_handlers import MAX_INLINE_PNG_BYTES, attach_inline_png

    cap = MAX_INLINE_PNG_BYTES if max_bytes is None else max_bytes
    attached = attach_inline_png(result, max_bytes=cap)
    if attached is result:
        return result
    data = attached.get("data")
    if not isinstance(data, dict):
        return attached
    path_raw = data.get("path") or attached.get("path")
    if not isinstance(path_raw, str) or not path_raw.strip():
        return attached
    path = Path(path_raw)
    if not path.is_file():
        return attached
    data.update(publish_shared_capture(path, shared_dir))
    return attached
