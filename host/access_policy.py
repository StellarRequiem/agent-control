"""Harness access policy — operator plane switches + 0–4 privilege dial.

Conduit (Harness tab) writes a signed policy file; this module verifies it and
computes a CEILING. The ceiling only ever removes tools: the mcp-assure engine
(deny-by-default pack, max_blast, FREEZE/FREEZE_ALLOW), leash allowlists, arm
state and D4 dual-control all still apply underneath. FREEZE always wins.

Fail closed: missing / unreadable / bad-signature / wrong-version / expired
policy => level 0 (surface read). Not-yet-provisioned (no key / no policy file)
keeps plane switches ON so level-0 surface tools still answer; a policy that is
present but unreadable or badly signed switches every plane OFF.

File format (~/ops/access-policy/access.json):
  {"format": "conduit-access/1", "key_id": "<hex sha256(pub)[:16]>",
   "payload_b64": "<base64 of UTF-8 JSON payload bytes>",
   "sig_b64": "<base64 Ed25519 signature over the exact payload bytes>"}
Payload:
  {"version": 1, "level": 0..4, "planes": {"shell":bool,"browser":bool,
   "desktop":bool,"cua":bool}, "set_by": "operator", "set_at": epoch,
   "expires_at": epoch|null, "auth_method": "touchid|password|none",
   "nonce": str, "sudo": {"window_until": epoch|null, "allow": [[argv...]]}}
Public key (~/ops/access-policy/conduit_access.pub): base64 raw 32-byte Ed25519.
The private key lives only in Conduit's Keychain item.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

POLICY_DIR = Path(os.environ.get("CONDUIT_ACCESS_POLICY_DIR") or (Path.home() / "ops" / "access-policy"))
FORMAT = "conduit-access/1"
PLANES = ("shell", "browser", "desktop", "cua")
LEVEL_NAMES = {0: "surface", 1: "deep_read", 2: "interact", 3: "shell_rw", 4: "shell_sudo"}
#: Max lifetime the host will honour for elevated levels, whatever the file says.
MAX_TTL = {3: 3600, 4: 3600}
SUDO_WINDOW_MAX = 3600
APPROVAL_MAX_AGE = 120

#: Never on the dial — recovery / self-description must work at any level.
EXEMPT = frozenset({
    "plane.status", "plane.route", "plane.unfreeze", "plane.unfreeze_signed",
    "plane.receipts_status", "plane.receipts_rotate",
})

LEVEL0 = frozenset({
    "browser.status", "browser.tabs", "browser.screenshot", "browser.workspace",
    "desktop.status", "desktop.apps", "desktop.windows", "desktop.screenshot",
    "desktop.region_screenshot", "desktop.screenshot_window", "desktop.layout",
    "shell.roots", "shell.list_dir", "shell.stat",
    "cua.status",
})
LEVEL1 = frozenset({
    "browser.snapshot", "browser.page_info", "browser.find", "browser.links",
    "browser.wait", "browser.x_article_read", "browser.x_article_search",
    "desktop.ax", "desktop.cua_observe", "desktop.d4_session",
    "shell.read_file", "cua.observe",
})
LEVEL2 = frozenset({
    "browser.navigate", "browser.click", "browser.type", "browser.scroll",
    "browser.back", "browser.forward", "browser.reload", "browser.tab_create",
    "browser.tab_close", "browser.tab_activate", "browser.x_article_curate",
    "browser.x_draft", "browser.x_post",
    "desktop.click", "desktop.click_window", "desktop.ax_click", "desktop.focus",
    "desktop.type", "desktop.press", "desktop.scroll", "desktop.quit", "desktop.confirm",
    "cua.start", "cua.stop", "cua.step",
})
LEVEL3 = frozenset({
    "shell.run", "shell.exec", "shell.write_file", "shell.apply_patch",
    "plane.reload_handlers",
})
LEVEL4 = frozenset({"shell.sudo"})


def required_level(tool: str) -> int | None:
    """None = exempt. Unknown tools need level 3 (fail toward strict)."""
    if tool in EXEMPT:
        return None
    for lvl, s in ((0, LEVEL0), (1, LEVEL1), (2, LEVEL2), (3, LEVEL3), (4, LEVEL4)):
        if tool in s:
            return lvl
    return 3


def plane_of(tool: str) -> str | None:
    head = tool.split(".", 1)[0]
    if head == "desktop" and tool == "desktop.cua_observe":
        return "desktop"
    return head if head in PLANES else None


def _key_id(pub: bytes) -> str:
    return hashlib.sha256(pub).hexdigest()[:16]


def load_public_key(policy_dir: Path | None = None) -> bytes | None:
    p = (policy_dir or POLICY_DIR) / "conduit_access.pub"
    try:
        raw = base64.b64decode(p.read_text(encoding="utf-8").strip(), validate=True)
    except (OSError, ValueError):
        return None
    return raw if len(raw) == 32 else None


def verify_envelope(env: Any, pub: bytes) -> dict[str, Any] | None:
    """Return payload dict iff Ed25519 signature over payload bytes verifies."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not isinstance(env, dict) or env.get("format") != FORMAT:
        return None
    if env.get("key_id") != _key_id(pub):
        return None
    try:
        payload_bytes = base64.b64decode(str(env.get("payload_b64") or ""), validate=True)
        sig = base64.b64decode(str(env.get("sig_b64") or ""), validate=True)
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, payload_bytes)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, InvalidSignature, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _fallback(reason: str, planes: dict[str, bool] | None = None) -> dict[str, Any]:
    return {
        "valid": False, "level": 0, "level_name": LEVEL_NAMES[0],
        "planes": planes or {p: False for p in PLANES},
        "reason": reason, "sudo_window_until": None, "sudo_allow": [],
    }


def effective_policy(now: float | None = None, policy_dir: Path | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    d = policy_dir or POLICY_DIR
    pub = load_public_key(d)
    if pub is None:
        return _fallback("no_public_key", {k: True for k in PLANES})
    try:
        env = json.loads((d / "access.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _fallback("no_policy", {k: True for k in PLANES})
    except (OSError, ValueError):
        return _fallback("unreadable_policy")
    p = verify_envelope(env, pub)
    if p is None:
        return _fallback("bad_signature")
    if p.get("version") != 1:
        return _fallback("bad_version")
    raw_planes = p.get("planes") if isinstance(p.get("planes"), dict) else {}
    planes = {k: raw_planes.get(k) is True for k in PLANES}
    try:
        level = int(p.get("level"))
        set_at = float(p.get("set_at"))
    except (TypeError, ValueError):
        return _fallback("bad_fields")
    if level not in LEVEL_NAMES or set_at > now + 60:
        return _fallback("bad_fields", planes)
    exp = p.get("expires_at")
    if level >= 3:
        if not isinstance(exp, (int, float)):
            return _fallback("elevated_without_expiry", planes)
        exp = min(float(exp), set_at + MAX_TTL[level])
    if isinstance(exp, (int, float)) and now >= float(exp):
        return _fallback("expired", planes)
    sudo = p.get("sudo") if isinstance(p.get("sudo"), dict) else {}
    win = sudo.get("window_until")
    win = min(float(win), set_at + SUDO_WINDOW_MAX) if isinstance(win, (int, float)) else None
    if win is not None and now >= win:
        win = None
    allow = [a for a in (sudo.get("allow") or []) if isinstance(a, list) and a and all(isinstance(x, str) for x in a)]
    return {
        "valid": True, "level": level, "level_name": LEVEL_NAMES[level], "planes": planes,
        "reason": "ok", "expires_at": exp, "set_at": set_at,
        "auth_method": p.get("auth_method"), "nonce": p.get("nonce"),
        "sudo_window_until": win if level == 4 else None,
        "sudo_allow": allow if level == 4 else [],
    }


def check(tool: str, *, frozen: bool, freeze_allow: frozenset[str],
          now: float | None = None, policy_dir: Path | None = None) -> dict[str, Any] | None:
    """None = ceiling permits (engine still decides). Dict = structured denial."""
    if frozen and tool not in freeze_allow:
        # FREEZE always wins, even over exempt tools and any level.
        return {"ok": False, "code": "FREEZE_DENIED", "tool": tool,
                "detail": "FREEZE engaged — access policy cannot override"}
    req = required_level(tool)
    if req is None:
        return None
    pol = effective_policy(now, policy_dir)
    plane = plane_of(tool)
    if plane is not None and not pol["planes"].get(plane, False):
        return {"ok": False, "code": "PLANE_SWITCHED_OFF", "tool": tool, "plane": plane,
                "policy": pol["reason"], "detail": f"{plane} plane is switched off in Conduit Harness"}
    if req > pol["level"]:
        return {"ok": False, "code": "ACCESS_LEVEL_DENIED", "tool": tool,
                "level": pol["level"], "required": req, "policy": pol["reason"],
                "detail": f"needs level {req} ({LEVEL_NAMES[req]}); current {pol['level']} ({pol['level_name']})"}
    return None


def write_access_receipt(path: Path, record: dict[str, Any]) -> None:
    """Separate, unchained log — never touches the mcp-assure receipt chain."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), **record}, sort_keys=True) + "\n")
    except OSError:
        pass


# ---- level 4: per-call sudo approvals --------------------------------------

def argv_hash(argv: list[str]) -> str:
    return hashlib.sha256(json.dumps(argv, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def consume_sudo_approval(argv: list[str], *, now: float | None = None,
                          policy_dir: Path | None = None) -> tuple[bool, str]:
    """One-use, Conduit-signed approval bound to the exact argv, <=120 s old.

    Approval envelope = same FORMAT/signature as access.json, payload:
      {"kind": "sudo-approval", "argv_sha256": ..., "nonce": ..., "issued_at": epoch,
       "auth_method": "touchid|password"}
    Stored at <dir>/sudo-approvals/<nonce>.json; deleted on use; nonce recorded.
    """
    now = time.time() if now is None else now
    d = policy_dir or POLICY_DIR
    pub = load_public_key(d)
    if pub is None:
        return False, "no_public_key"
    want = argv_hash(argv)
    used_path = d / "sudo-used-nonces.txt"
    try:
        used = set(used_path.read_text(encoding="utf-8").split())
    except OSError:
        used = set()
    adir = d / "sudo-approvals"
    for f in sorted(adir.glob("*.json")) if adir.is_dir() else []:
        try:
            env = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        p = verify_envelope(env, pub)
        if not p or p.get("kind") != "sudo-approval" or p.get("argv_sha256") != want:
            continue
        nonce = str(p.get("nonce") or "")
        try:
            issued = float(p.get("issued_at"))
        except (TypeError, ValueError):
            continue
        try:
            f.unlink()  # one-use regardless of outcome
        except OSError:
            return False, "approval_not_consumable"
        if not nonce or nonce in used:
            return False, "approval_replayed"
        if not (now - APPROVAL_MAX_AGE <= issued <= now + 5):
            return False, "approval_stale"
        try:
            with used_path.open("a", encoding="utf-8") as fh:
                fh.write(nonce + "\n")
        except OSError:
            return False, "nonce_store_unwritable"
        return True, "ok"
    return False, "no_approval"


def sudo_preflight(argv: Any, *, now: float | None = None,
                   policy_dir: Path | None = None) -> dict[str, Any] | None:
    """Every level-4 gate except the per-call approval. None = may proceed."""
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        return {"ok": False, "code": "BAD_ARGV", "detail": "argv must be a non-empty list of strings"}
    pol = effective_policy(now, policy_dir)
    if pol["level"] < 4:
        return {"ok": False, "code": "ACCESS_LEVEL_DENIED", "required": 4, "level": pol["level"]}
    if not pol["planes"].get("shell"):
        return {"ok": False, "code": "PLANE_SWITCHED_OFF", "plane": "shell"}
    if not pol["sudo_window_until"]:
        return {"ok": False, "code": "SUDO_WINDOW_CLOSED",
                "detail": "activate the 1-hour sudo window in Conduit (Mac password)"}
    if argv not in pol["sudo_allow"]:
        return {"ok": False, "code": "SUDO_NOT_ALLOWLISTED", "argv": argv}
    return None
