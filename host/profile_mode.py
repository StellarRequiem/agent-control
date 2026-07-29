"""Load CUA profile mode and extra allow apps for plane.status."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROFILES = Path(__file__).resolve().parent.parent / "profiles" / "desktop_apps.json"


def profile_summary() -> dict[str, Any]:
    if not PROFILES.is_file():
        return {"mode": "unknown", "extra_count": 0}
    data = json.loads(PROFILES.read_text(encoding="utf-8"))
    mode = str(data.get("mode") or "strict")
    modes = data.get("modes") or {}
    extra = (modes.get(mode) or {}).get("extra_allowlist") or []
    return {
        "mode": mode,
        "extra_allowlist": list(extra),
        "extra_count": len(extra),
        "denylist_hard": list(data.get("denylist_hard") or []),
        "path": str(PROFILES),
    }
