"""browser-leash handlers — only reachable via AssuredPlaneHost."""

from __future__ import annotations

from typing import Any

from host.http_util import http_json
from host.publish_pipeline import PublishPipeline

BROWSER = "http://127.0.0.1:8756"


class BrowserHandlers:
    def __init__(self, base: str = BROWSER) -> None:
        self.base = base
        self.pipeline = PublishPipeline()

    def _action(self, action: str, **extra: Any) -> dict[str, Any]:
        body = {"action": action, **extra}
        return http_json(self.base, "/v1/action", body)

    def status(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return http_json(self.base, "/v1/status")

    def navigate(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._action("tab.navigate", url=args["url"])

    def snapshot(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._action("page.snapshot")

    def screenshot(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        out = self._action("page.screenshot")
        path = (args.get("out") or "").strip()
        if path and out.get("ok") and out.get("data", {}).get("dataUrl"):
            # optional write left to caller; return path hint
            out.setdefault("data", {})["out_hint"] = path
        return out

    def click(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._action("page.click", selector=args["selector"])

    def type(self, args: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"action": "page.type", "text": args["text"]}
        if args.get("selector"):
            body["selector"] = args["selector"]
        return http_json(self.base, "/v1/action", body)

    def scroll(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        return self._action(
            "page.scroll",
            dy=int(args.get("dy", 600)),
            dx=int(args.get("dx", 0)),
        )

    def x_draft(self, args: dict[str, Any]) -> dict[str, Any]:
        text = args.get("text") or ""
        self.pipeline.begin_draft(text)
        res = self._action("x.compose_draft", text=text)
        if not res.get("ok"):
            return {**self.pipeline.mark_failed(res.get("code") or "DRAFT_FAIL", res.get("detail") or ""), "leash": res}
        data = res.get("data") or res
        post_disabled = data.get("postDisabled")
        if post_disabled is None:
            post_disabled = data.get("post_disabled")
        got = data.get("gotLen") or data.get("got_len")
        pipe = self.pipeline.mark_drafted(post_disabled=post_disabled, got_len=got)
        return {"ok": True, "pipeline": pipe, "leash": res}

    def x_post(self, args: dict[str, Any]) -> dict[str, Any]:
        """Dual human gate: host operator_confirm + leash require_post_confirm/arm."""
        confirm = args.get("operator_confirm")
        if confirm is not True and confirm != "true" and confirm != 1:
            pipe = self.pipeline.try_post(operator_confirm=False)
            return {
                "ok": False,
                "code": "HUMAN_CONFIRM_REQUIRED",
                "detail": "browser.x_post requires operator_confirm=true (explicit this turn)",
                "pipeline": pipe,
            }
        pipe = self.pipeline.try_post(operator_confirm=True)
        if not pipe.get("ok"):
            return {"ok": False, **pipe}

        body: dict[str, Any] = {"action": "x.post"}
        if args.get("click_only") is True or args.get("click_only") == "true":
            body["click_only"] = True
            body["text"] = ""
        else:
            body["text"] = args.get("text") or ""

        res = http_json(self.base, "/v1/action", body)
        if res.get("ok"):
            return {"ok": True, "pipeline": self.pipeline.mark_posted(), "leash": res}
        return {
            "ok": False,
            "code": res.get("code") or "POST_FAIL",
            "pipeline": self.pipeline.mark_failed(res.get("code") or "POST_FAIL", str(res.get("detail") or "")),
            "leash": res,
        }
