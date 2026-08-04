# Third-machine re-run (claim ladder R5)

**Goal:** A stranger with a Mac can reproduce offline gates without your secrets.  
**Not claimed:** Linux/Windows desktop plane; live ARM without human steps.

## Prerequisites

| Need | Notes |
|------|--------|
| macOS | Desktop-leash is macOS-only today |
| Python 3.10+ | 3.11/3.12 preferred |
| Git | Clone public repos |
| Chrome (optional live) | Soft Reload extension + ARM for live browser proofs |

## Install (offline-capable core)

```bash
# 1) assurance core
git clone https://github.com/StellarRequiem/mcp-assure.git
cd mcp-assure && python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
mcp-assure check
pytest -q

# 2) agent-control (plane host)
git clone https://github.com/StellarRequiem/agent-control.git
cd agent-control
# point PYTHONPATH or install mcp-assure editable as above
pip install pytest "mcp-assure>=0.3.2"
python smoke/proof_suite.py --offline
python -m pytest -q tests

# 3) agent-soc (optional purple / hit table)
git clone https://github.com/StellarRequiem/agent-soc.git
cd agent-soc
python3 purple.py
python3 hit_table.py
python3 hit_table.py --corpus corpora/labeled_traces_v1.json
python3 hit_table.py --corpus corpora/labeled_traces_v1.json --split holdout
```

## Expected offline results

| Check | Expected |
|-------|----------|
| `mcp-assure check` | OK |
| `proof_suite.py --offline` | all board items `ok: true` (gates + freeze file + receipts repair if present) |
| `hit_table.py` (v0) | hits=25 misses=0 fp=0 |
| `hit_table.py` (v1) | hits=N_abh misses=0 fp=0 when corpus shipped |

## Live matrix (operator machine only)

Requires browser-leash + desktop-leash bridges, Soft Reload, **human ARM**:

```bash
python3 ~/agent-control/cli.py session
python3 ~/agent-control/cli.py smoke   # may include live steps
```

Document host: OS version, extension version, TCC grants (Accessibility).

## What failure means

| Failure | Interpretation |
|---------|----------------|
| Import errors for mcp_assure | Install path / PYTHONPATH |
| TCC / AX denials | macOS privacy — not a logic bug |
| CHAIN_BROKEN mid-run | Multi-writer race — upgrade mcp-assure receipts flock; rotate if needed |
| Hit table FP after corpus edit | Detector or label bug — fix before claiming |

## Report template (paste into ops_log)

```
Date:
Machine:
Repos:
mcp-assure check:
proof_suite --offline:
hit_table v0/v1:
Gaps:
```

## Claim language after a successful third-machine run

> Offline cannot-bypass board and synthetic hit table re-ran on an independent machine (date, OS). Live ARM proofs remain operator-dependent.

**Still not allowed:** enterprise SOC, unlimited CUA, every OS process gated.
