"""Cross-process lock around receipt-chain append.

PyPI mcp-assure 0.3.2 serializes ``ReceiptChain.append`` with a
``threading.Lock`` and an in-memory tip. That is enough for one chain object.
It is not enough when two processes share ``receipts/plane-host.jsonl``:
the HTTP server and ``mcp_server.py`` each load the tip at startup and then
append from their own copy, so the hash chain splits.

Upstream mcp-assure (not yet what ``mcp-assure>=0.3.2`` resolves to) flocks a
sidecar ``<path>.lock`` and reloads the tip inside that lock before every
append. When the installed ``ReceiptChain.append`` already does that, this
module leaves it alone. A second ``flock`` on another file descriptor in the
same thread deadlocks on Linux. When it does not, ``AssuredPlaneHost`` wraps
``append`` the same way: exclusive sidecar lock, reload the tip from disk,
then the library write.

The wrapper covers only ``append``. ``host.call`` is serialized separately
with an ``RLock`` because ``cua.observe`` / ``cua.step`` call back into
``host.call`` on the same thread, and holding ``flock`` across that re-entry
would deadlock the same way.
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover — non-POSIX
    fcntl = None  # type: ignore


def library_appends_under_flock(chain: Any) -> bool:
    """True when ReceiptChain.append already takes an OS file lock."""
    try:
        src = inspect.getsource(type(chain).append)
    except (OSError, TypeError):
        return False
    return "flock" in src


def resync_receipt_tip(chain: Any) -> None:
    """Point ``chain`` at the last complete line on disk.

    Does not call ``ReceiptChain._load_tip``. The 0.3.2 method accumulates
    ``_count`` on every call and leaves a stale tip when the file is gone.
    A missing, empty, or unreadable file becomes genesis so the next append
    does not chain off a tip that is no longer in the file.
    """
    from mcp_assure.receipts import GENESIS

    path = getattr(chain, "path", None)
    if not path or not os.path.isfile(path):
        chain._prev = GENESIS
        chain._count = 0
        return
    last = None
    n = 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                last = json.loads(line)
                n += 1
    except (OSError, ValueError):
        chain._prev = GENESIS
        chain._count = 0
        return
    chain._count = n
    if isinstance(last, dict) and isinstance(last.get("hash"), str):
        chain._prev = last["hash"]
    else:
        chain._prev = GENESIS


def install_receipt_file_lock(chain: Any) -> bool:
    """Wrap ``chain.append`` with sidecar flock + tip re-sync.

    Returns True when this process installed the wrapper. Returns False when
    there is no path, no ``fcntl``, the wrapper is already installed, or the
    library append already flocks (wrapping again would deadlock).
    """
    if getattr(chain, "_agent_control_flock", False):
        return False
    if library_appends_under_flock(chain):
        return False
    path = getattr(chain, "path", None)
    if not path or fcntl is None:
        return False

    original = chain.append
    lock_path = f"{path}.lock"

    def append(**kwargs: Any) -> Any:
        lock_f = open(lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            # Reload under the lock. The library append then hashes from this
            # tip and writes before we unlock, so the next writer sees the line.
            resync_receipt_tip(chain)
            return original(**kwargs)
        finally:
            try:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
            finally:
                lock_f.close()

    chain.append = append  # type: ignore[method-assign]
    chain._agent_control_flock = True
    return True
