"""X publish pipeline — explicit state machine (human gate stays).

Architecture toward *reliable* publish under control — never ambient auto-post.
States:

  IDLE → DRAFTING → DRAFTED → AWAITING_HUMAN → POSTING → POSTED
                 ↘ FAILED
  AWAITING_HUMAN can only leave via operator_confirm=true (host) + leash arm/post confirm.

We do not claim auto-post. We claim a real pipeline with hard human gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PubState(str, Enum):
    IDLE = "IDLE"
    DRAFTING = "DRAFTING"
    DRAFTED = "DRAFTED"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    POSTING = "POSTING"
    POSTED = "POSTED"
    FAILED = "FAILED"


@dataclass
class PublishPipeline:
    state: PubState = PubState.IDLE
    last_draft_len: int = 0
    last_error: str = ""
    post_disabled: bool | None = None
    history: list[str] = field(default_factory=list)

    def _log(self, msg: str) -> None:
        self.history.append(f"{self.state.value}: {msg}")

    def begin_draft(self, text: str) -> dict[str, Any]:
        if not (text or "").strip():
            self.state = PubState.FAILED
            self.last_error = "EMPTY_TEXT"
            return self.snapshot(ok=False, code="EMPTY_TEXT")
        self.state = PubState.DRAFTING
        self.last_draft_len = len(text)
        self.last_error = ""
        self._log(f"draft begin len={self.last_draft_len}")
        return self.snapshot(ok=True, code="DRAFTING")

    def mark_drafted(self, *, post_disabled: bool | None, got_len: int | None = None) -> dict[str, Any]:
        self.post_disabled = post_disabled
        if post_disabled is False:
            self.state = PubState.AWAITING_HUMAN
            self._log(f"draft ready post_disabled=false got_len={got_len}")
            return self.snapshot(ok=True, code="AWAITING_HUMAN")
        self.state = PubState.DRAFTED
        self._log(f"draft filled but post may be disabled got_len={got_len}")
        # Still may need human to type/nudge or confirm click path later
        self.state = PubState.AWAITING_HUMAN
        return self.snapshot(ok=True, code="AWAITING_HUMAN_OR_NUDGE")

    def mark_failed(self, code: str, detail: str = "") -> dict[str, Any]:
        self.state = PubState.FAILED
        self.last_error = code
        self._log(f"failed {code} {detail}")
        return self.snapshot(ok=False, code=code, detail=detail)

    def try_post(self, *, operator_confirm: bool) -> dict[str, Any]:
        """Host-level human gate — must be True before leash is even called."""
        if not operator_confirm:
            self._log("post blocked: operator_confirm not true")
            return self.snapshot(ok=False, code="HUMAN_CONFIRM_REQUIRED")
        if self.state not in (PubState.AWAITING_HUMAN, PubState.DRAFTED, PubState.DRAFTING, PubState.IDLE):
            if self.state == PubState.POSTED:
                return self.snapshot(ok=False, code="ALREADY_POSTED")
        self.state = PubState.POSTING
        self._log("operator_confirm=true → POSTING (leash still has its own gate)")
        return self.snapshot(ok=True, code="POSTING")

    def mark_posted(self) -> dict[str, Any]:
        self.state = PubState.POSTED
        self._log("posted")
        return self.snapshot(ok=True, code="POSTED")

    def snapshot(self, **extra: Any) -> dict[str, Any]:
        out: dict[str, Any] = {
            "pipeline_state": self.state.value,
            "last_draft_len": self.last_draft_len,
            "post_disabled": self.post_disabled,
            "last_error": self.last_error,
            "history_tail": self.history[-8:],
        }
        out.update(extra)
        return out
