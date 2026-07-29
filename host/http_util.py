"""Tiny loopback HTTP helper for leash bridges."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def http_json(
    base: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 90.0,
) -> dict[str, Any]:
    url = base.rstrip("/") + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="GET" if body is None else "POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("ok", False)
                payload.setdefault("code", f"HTTP_{e.code}")
                return payload
        except Exception:
            pass
        return {"ok": False, "code": f"HTTP_{e.code}", "detail": str(e)}
    except urllib.error.URLError as e:
        return {"ok": False, "code": "BRIDGE_DOWN", "detail": str(e)}
    except Exception as e:
        return {"ok": False, "code": "HTTP_ERROR", "detail": str(e)}
