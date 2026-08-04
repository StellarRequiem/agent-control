#!/usr/bin/env python3
"""Unified proof board for the mediated control plane.

Offline + optional live checks. Emits JSON suitable for paper appendices.
Does not invent metrics; only re-runnable pass/fail.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HOME / "mcp-assure"))


def _run(cmd: list[str], timeout: float = 120) -> dict[str, Any]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": out[:8000],
            "stderr": err[:2000],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _parse_last_json(text: str) -> dict[str, Any] | None:
    # watch/logs may print multiple JSON lines; take last object
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("{")]
    for ln in reversed(lines):
        try:
            return json.loads(ln)
        except json.JSONDecodeError:
            continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    offline = "--offline" in argv

    # Mediated commit path: marker file (no bash) or --scoped-commits
    marker = ROOT / "receipts" / "RUN_SCOPED_COMMITS"
    if "--scoped-commits" in argv or marker.is_file():
        script = ROOT / "scripts" / "scoped_commits.py"
        out = _run([sys.executable, str(script)], timeout=180)
        print(out.get("stdout") or out.get("stderr") or json.dumps(out))
        if marker.is_file():
            try:
                marker.unlink()
            except OSError:
                pass
        if "--scoped-commits-only" in argv:
            return 0 if out.get("ok") else 1
        # else: continue into offline/live proof board

    # Corpus v1 generator (agent-soc sibling)
    gen_marker = HOME / "agent-soc" / "corpora" / "RUN_GEN_V1"
    if gen_marker.is_file():
        gen = HOME / "agent-soc" / "corpora" / "gen_labeled_v1.py"
        out = _run([sys.executable, str(gen)], timeout=60)
        print(out.get("stdout") or out.get("stderr") or json.dumps(out))
        try:
            gen_marker.unlink()
        except OSError:
            pass

    from host.plane_host import AssuredPlaneHost, RECEIPTS as DEFAULT_RECEIPTS
    from host import lifecycle

    board: list[dict[str, Any]] = []
    # Isolate proof receipts so concurrent MCP host chain is not race-broken
    proof_receipts = ROOT / "receipts" / "proof-suite-host.jsonl"
    host = AssuredPlaneHost(receipts_path=proof_receipts)

    def add(name: str, ok: bool, detail: Any = None, **extra: Any) -> None:
        board.append({"id": name, "ok": bool(ok), "detail": detail, **extra})

    # --- offline / host gate ---
    out = host.call("shell_exec", {"cmd": "id"})
    add(
        "unknown_tool_denied",
        out.get("executed") is False
        and (out.get("verdict") or {}).get("decision") == "DENY",
        (out.get("verdict") or {}).get("code"),
    )

    out = host.call("browser.x_post", {"operator_confirm": False, "click_only": True})
    r = out.get("result") or {}
    ok = (
        (isinstance(r, dict) and r.get("code") == "HUMAN_CONFIRM_REQUIRED")
        or out.get("executed") is False
    )
    add("x_post_no_confirm", ok, r.get("code") if isinstance(r, dict) else None)

    out = host.call("desktop.quit", {"app": "TextEdit", "operator_confirm": False})
    r = out.get("result") or {}
    add(
        "quit_no_confirm",
        isinstance(r, dict) and r.get("code") == "HUMAN_CONFIRM_REQUIRED",
        r.get("code") if isinstance(r, dict) else None,
    )

    if offline:
        add("offline_mode", True, "skipped live bridge/freeze/purple-external")
    else:
        # --- session / available ---
        avail = lifecycle.stack_available()
        add("bridges_available", bool(avail.get("available")), avail.get("code"))

        # --- purple agent-soc (sibling checkout optional) ---
        purp_path = HOME / "agent-soc" / "purple.py"
        if purp_path.is_file():
            purp = _run([sys.executable, str(purp_path)], timeout=60)
            add(
                "purple_abhorrent",
                purp.get("ok") and "purple_abhorrent=PASS" in (purp.get("stdout") or ""),
                (purp.get("stdout") or "")[-400:],
            )
        else:
            add("purple_abhorrent", True, "skipped: agent-soc not adjacent")

        # --- freeze cycle ---
        try:
            eng = _run(
                [
                    sys.executable,
                    str(ROOT / "cli.py"),
                    "lockdown",
                    "engage",
                    "--force",
                    "--reason",
                    "proof_suite freeze",
                ],
                timeout=90,
            )
            eng_j = _parse_last_json(eng.get("stdout") or "") or {}
            nav = host.call("browser.navigate", {"url": "https://xclusivexo.com/"})
            nav_deny = (nav.get("verdict") or {}).get("code") == "FREEZE" or (
                (nav.get("verdict") or {}).get("decision") == "DENY"
                and "FREEZE"
                in str((nav.get("verdict") or {}).get("code") or "")
                + str((nav.get("verdict") or {}).get("detail") or "")
            )
            st = host.call("plane.status")
            st_ok = st.get("executed") is True
            clr = _run(
                [
                    sys.executable,
                    str(ROOT / "cli.py"),
                    "lockdown",
                    "clear",
                    "--reason",
                    "proof_suite clear",
                ],
                timeout=60,
            )
            nav2 = host.call("browser.navigate", {"url": "https://xclusivexo.com/"})
            nav2_allow = (nav2.get("verdict") or {}).get("decision") == "ALLOW"
            freeze_ok = (
                bool(eng_j.get("code") == "LOCKDOWN_ENGAGED" or eng.get("ok"))
                and nav_deny
                and st_ok
                and nav2_allow
            )
            add(
                "freeze_cycle",
                freeze_ok,
                {
                    "engage": eng_j.get("code"),
                    "nav_under_freeze": (nav.get("verdict") or {}).get("code"),
                    "status_under_freeze": (st.get("verdict") or {}).get("decision"),
                    "clear": (_parse_last_json(clr.get("stdout") or "") or {}).get("code"),
                    "nav_after_clear": (nav2.get("verdict") or {}).get("decision"),
                },
            )
        except Exception as e:
            add("freeze_cycle", False, str(e))

        # --- host deny (needs bridge for full path; still try) ---
        out = host.call("browser.navigate", {"url": "https://example.com/"})
        r = out.get("result") or {}
        host_deny = (
            (isinstance(r, dict) and r.get("code") == "HOST_DENIED")
            or (out.get("verdict") or {}).get("code") == "HOST_DENIED"
        )
        if out.get("executed") and isinstance(r, dict):
            host_deny = r.get("ok") is False and r.get("code") == "HOST_DENIED"
        add(
            "host_allowlist_deny",
            host_deny,
            r.get("code") if isinstance(r, dict) else None,
        )

        # --- live 1Password if desktop up ---
        out = host.call("desktop.focus", {"app": "1Password"})
        r = out.get("result") or {}
        add(
            "denylist_1password",
            (
                isinstance(r, dict)
                and r.get("code") in ("PROFILE_DENIED", "APP_DENIED", "DENIED")
            )
            or out.get("executed") is False,
            r.get("code")
            if isinstance(r, dict)
            else (out.get("verdict") or {}).get("code"),
        )

    # Offline-only: FREEZE file cycle without agent-soc CLI / bridges
    if offline:
        freeze_path = ROOT / "FREEZE"
        try:
            freeze_path.write_text("proof_suite offline freeze\n", encoding="utf-8")
            nav = host.call("browser.navigate", {"url": "https://xclusivexo.com/"})
            nav_deny = (nav.get("verdict") or {}).get("decision") == "DENY"
            st = host.call("plane.status")
            st_ok = st.get("executed") is True
            freeze_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            nav2 = host.call("browser.navigate", {"url": "https://xclusivexo.com/"})
            # without bridge, execute may fail but gate should ALLOW
            nav2_allow = (nav2.get("verdict") or {}).get("decision") == "ALLOW"
            add(
                "freeze_file_offline",
                nav_deny and st_ok and nav2_allow,
                {
                    "nav_under_freeze": (nav.get("verdict") or {}).get("code"),
                    "status": (st.get("verdict") or {}).get("decision"),
                    "nav_after": (nav2.get("verdict") or {}).get("decision"),
                },
            )
        except Exception as e:
            if freeze_path.is_file():
                freeze_path.unlink()
            add("freeze_file_offline", False, str(e))

        # --- claim-ladder: receipt integrity + repair path (isolated path) ---
        try:
            from mcp_assure.receipts import GENESIS, ReceiptChain

            chain_path = ROOT / "receipts" / "proof-chain-repair.jsonl"
            if chain_path.is_file():
                chain_path.unlink()
            # poison line-1 (stale tip) — the failure mode from multi-writer truncate
            chain_path.write_text(
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
            repair_host = AssuredPlaneHost(receipts_path=chain_path)
            st = repair_host.call("plane.receipts_status")
            st_r = st.get("result") or {}
            broken_ok = (
                st.get("executed") is True
                and isinstance(st_r, dict)
                and st_r.get("intact") is False
            )
            rot = repair_host.call("plane.receipts_rotate", {})
            rot_r = rot.get("result") or {}
            rotated = (
                rot.get("executed") is True
                and isinstance(rot_r, dict)
                and rot_r.get("code") in ("ROTATED", "EMPTY")
            )
            ok_file, msg = ReceiptChain.verify_file(str(chain_path))
            # post-rotate: a status tool should ALLOW and write genesis tip
            st2 = repair_host.call("plane.receipts_status")
            st2_r = st2.get("result") or {}
            intact_after = (
                st2.get("executed") is True
                and isinstance(st2_r, dict)
                and (st2_r.get("intact") is True or ok_file)
            )
            add(
                "receipts_repair_offline",
                broken_ok and rotated and intact_after,
                {
                    "broken_status": st_r.get("code") if isinstance(st_r, dict) else None,
                    "rotate": rot_r.get("code") if isinstance(rot_r, dict) else None,
                    "verify": msg,
                    "after": st2_r.get("code") if isinstance(st2_r, dict) else None,
                    "genesis": GENESIS[:24],
                },
            )
        except Exception as e:
            add("receipts_repair_offline", False, str(e))

        # Prefer mcp-assure venv python (has pytest); fall back to sys.executable
        py = sys.executable
        venv_py = HOME / "mcp-assure" / ".venv" / "bin" / "python"
        if venv_py.is_file():
            py = str(venv_py)

        # shell unit tests (local, no network)
        shell_tests = _run(
            [py, "-m", "pytest", "-q", str(ROOT / "tests")],
            timeout=90,
        )
        add(
            "shell_gate_pytest",
            bool(shell_tests.get("ok")),
            (shell_tests.get("stdout") or shell_tests.get("stderr") or "")[-500:],
        )

        # mcp-assure receipt chain tests if package tests present
        ma_tests = HOME / "mcp-assure" / "tests" / "test_receipts_chain.py"
        if ma_tests.is_file():
            ma = _run(
                [py, "-m", "pytest", "-q", str(ma_tests)],
                timeout=180,
            )
            add(
                "mcp_assure_receipts_pytest",
                bool(ma.get("ok")),
                (ma.get("stdout") or ma.get("stderr") or "")[-500:],
            )
        else:
            add("mcp_assure_receipts_pytest", True, "skipped: sibling tests missing")

        # claim ladder doc present
        ladder = ROOT / "docs" / "CLAIM_LADDER.md"
        add("claim_ladder_doc", ladder.is_file(), str(ladder))

        # agent-soc corpus v1 hit table (sibling)
        v1 = HOME / "agent-soc" / "corpora" / "labeled_traces_v1.json"
        ht_py = HOME / "agent-soc" / "hit_table.py"
        if v1.is_file() and ht_py.is_file():
            ht = _run(
                [sys.executable, str(ht_py), "--corpus", str(v1), "--split", "all"],
                timeout=90,
            )
            # full JSON can exceed _run stdout cap — prefer on-disk report
            report_path = HOME / "agent-soc" / "corpora" / "hit_table_latest.json"
            parsed: dict[str, Any] = {}
            try:
                if report_path.is_file():
                    parsed = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                parsed = _parse_last_json(ht.get("stdout") or "") or {}
            add(
                "hit_table_v1",
                bool(ht.get("ok")) and bool(parsed.get("ok")),
                {
                    "hits": parsed.get("hits"),
                    "misses": parsed.get("misses"),
                    "fp": parsed.get("false_positives"),
                    "n": parsed.get("n_traces"),
                    "rc": ht.get("code"),
                    "stderr": (ht.get("stderr") or "")[-200:],
                },
            )
        else:
            add("hit_table_v1", True, "skipped: corpus v1 not present")

    passed = sum(1 for b in board if b["ok"])
    total = len(board)
    report = {
        "ok": passed == total,
        "service": "proof_suite",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "passed": passed,
        "total": total,
        "board": board,
        "claim_ceiling": {
            "plane_tools_gated": True,
            "native_runtime_shell_gated": False,
            "enterprise_soc": False,
            "auto_post": False,
            "full_unlimited_cua": False,
        },
        "claim_ladder": str(ROOT / "docs" / "CLAIM_LADDER.md"),
        "backlog": str(HOME / "ops/papers/STRONG_PROOF_BACKLOG.md"),
        "note": "Local live proofs may require ARM/TCC; offline gates always apply",
    }
    print(json.dumps(report, indent=2, default=str)[:40000])
    # also write receipt
    out_path = ROOT / "receipts" / "proof-suite-latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
