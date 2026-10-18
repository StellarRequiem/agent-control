"""browser-leash handlers — only reachable via AssuredPlaneHost."""

from __future__ import annotations

import re
from typing import Any

from host.http_util import http_json
from host.publish_pipeline import PublishPipeline

BROWSER = "http://127.0.0.1:8756"


def _tokenize_query(query: str) -> list[str]:
    toks = re.findall(r"[a-z0-9_#@.+-]{2,}", (query or "").lower())
    # drop pure noise
    stop = {"the", "and", "for", "with", "from", "that", "this", "into", "about", "a", "an", "or", "of", "on", "to", "in"}
    return [t for t in toks if t not in stop]


def _score_card(card: dict[str, Any], tokens: list[str]) -> float:
    """Heuristic curation score: keyword hits + kind + light engagement."""
    text = f"{card.get('text') or ''} {card.get('author') or ''} {card.get('handle') or ''}".lower()
    score = 0.0
    for t in tokens:
        if t in text:
            score += 2.0
            # bonus for exact word-ish boundary
            if re.search(rf"(?:^|\W){re.escape(t)}(?:$|\W)", text):
                score += 0.5
    kind = str(card.get("kind") or "")
    if kind in ("article", "article_card"):
        score += 4.0
    elif kind == "status":
        score += 1.0
    eng = card.get("engagement") if isinstance(card.get("engagement"), dict) else {}
    for key, weight in (("likes", 0.002), ("reposts", 0.004), ("views", 0.00005), ("replies", 0.001)):
        try:
            n = float(eng.get(key) or 0)
            score += min(n * weight, 5.0)
        except (TypeError, ValueError):
            pass
    # Prefer longer snippets (more substance)
    score += min(len(text) / 400.0, 3.0)
    return round(score, 3)


def _coerce_tab_id(args: dict[str, Any] | None) -> int | None:
    """Accept tabId / tab_id / id from agent args (multi-tab targeting)."""
    if not args:
        return None
    for key in ("tabId", "tab_id", "id"):
        if args.get(key) is not None and key != "id":
            try:
                return int(args[key])
            except (TypeError, ValueError):
                return None
    # bare "id" only when clearly a tab id (numeric), not a selector id
    if args.get("id") is not None and args.get("selector") is None:
        try:
            return int(args["id"])
        except (TypeError, ValueError):
            return None
    return None


class BrowserHandlers:
    def __init__(self, base: str = BROWSER) -> None:
        self.base = base
        self.pipeline = PublishPipeline()

    def _action(self, action: str, **extra: Any) -> dict[str, Any]:
        body = {"action": action, **extra}
        return http_json(self.base, "/v1/action", body)

    def _with_tab(self, args: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
        body = dict(extra)
        tid = _coerce_tab_id(args)
        if tid is not None:
            body["tabId"] = tid
        return body

    def status(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return http_json(self.base, "/v1/status")

    def navigate(self, args: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"url": args["url"]}
        tid = _coerce_tab_id(args)
        if tid is not None:
            body["tabId"] = tid
        if args.get("active") is not None:
            body["active"] = bool(args["active"])
        return self._action("tab.navigate", **body)

    def tabs(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._action("tab.list")

    def tab_create(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {}
        if args.get("url"):
            body["url"] = str(args["url"]).strip()
        if args.get("active") is not None:
            body["active"] = bool(args["active"])
        return self._action("tab.create", **body)

    def tab_close(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {}
        tid = _coerce_tab_id(args)
        if tid is not None:
            body["tabId"] = tid
        return self._action("tab.close", **body)

    def tab_activate(self, args: dict[str, Any]) -> dict[str, Any]:
        tid = _coerce_tab_id(args)
        if tid is None:
            return {"ok": False, "code": "TAB_ID_REQUIRED", "detail": "tabId required for tab_activate"}
        return self._action("tab.activate", tabId=tid)

    def page_info(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Active or targeted tab url/title (multi-tab orient)."""
        return self._action("page.info", **self._with_tab(args))

    def snapshot(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Visible text; pass tabId to read a non-active tab without activating."""
        return self._action("page.snapshot", **self._with_tab(args))

    def screenshot(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Capture visible tab PNG. Prefer `out` path — dataUrl is large; write + strip when set."""
        import base64
        import re
        from pathlib import Path

        args = args or {}
        # captureVisibleTab is active-window only; activate first if tabId given
        tid = _coerce_tab_id(args)
        body: dict[str, Any] = {}
        if tid is not None:
            act = self._action("tab.activate", tabId=tid)
            if not act.get("ok"):
                return {
                    "ok": False,
                    "code": "SCREENSHOT_ACTIVATE_FAIL",
                    "detail": "screenshot needs active tab; activate failed",
                    "activate": act,
                }
            body["tabId"] = tid
        out = self._action("page.screenshot", **body)
        path = (args.get("out") or "").strip()
        data = out.get("data") if isinstance(out.get("data"), dict) else {}
        data_url = (data or {}).get("dataUrl") or ""
        if path and out.get("ok") and data_url:
            # write PNG under allowlisted capture roots (ops / agent-control / /tmp)
            p = Path(path).expanduser()
            try:
                p = p.resolve()
            except OSError:
                return {
                    "ok": False,
                    "code": "SCREENSHOT_PATH",
                    "detail": f"bad out path: {path}",
                }
            allowed_parents = (
                Path.home() / "ops",
                Path.home() / "agent-control",
                Path.home() / "browser-leash",
                Path("/tmp"),
                Path("/private/tmp"),
            )
            if not any(
                str(p).startswith(str(root.resolve()) + "/")
                or str(p).startswith(str(root.resolve()))
                for root in allowed_parents
                if root.exists() or str(root).startswith("/tmp") or str(root).startswith("/private")
            ):
                # also allow explicit /tmp even if exists check is weird on mac
                if not (str(p).startswith("/tmp/") or str(p).startswith("/private/tmp/")):
                    return {
                        "ok": False,
                        "code": "SCREENSHOT_PATH_DENIED",
                        "detail": "out must be under ~/ops, ~/agent-control, ~/browser-leash, or /tmp",
                        "path": str(p),
                    }
            m = re.match(r"^data:image/png;base64,(.+)$", data_url, re.DOTALL)
            if not m:
                return {
                    "ok": False,
                    "code": "SCREENSHOT_BAD_DATAURL",
                    "detail": "expected data:image/png;base64,...",
                }
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                raw = base64.b64decode(m.group(1), validate=False)
                if len(raw) < 32:
                    return {"ok": False, "code": "SCREENSHOT_EMPTY", "detail": "decoded PNG too small"}
                p.write_bytes(raw)
            except Exception as e:  # noqa: BLE001 — surface write errors to agent
                return {
                    "ok": False,
                    "code": "SCREENSHOT_WRITE_FAIL",
                    "detail": str(e)[:300],
                    "path": str(p),
                }
            # strip huge payload from result (agents re-read via path / read_file image)
            slim = dict(out)
            slim_data = {k: v for k, v in (data or {}).items() if k != "dataUrl"}
            slim_data["path"] = str(p)
            slim_data["bytes"] = len(raw)
            slim_data["mime"] = "image/png"
            slim["data"] = slim_data
            if tid is not None:
                slim["data"]["tabId"] = tid
            return slim
        if path and out.get("ok") and not data_url:
            # Extension <0.5.2 stripped dataUrl in report() — surface actionable hint
            out.setdefault("data", {})
            if isinstance(out["data"], dict):
                out["data"]["out_requested"] = path
                out["data"]["hint"] = (
                    "dataUrl missing — Soft Reload Browser Leash to 0.5.2+ so screenshots "
                    "deliver PNG for disk write"
                )
        if tid is not None and out.get("ok"):
            out.setdefault("data", {})["tabId"] = tid
        return out

    def click(self, args: dict[str, Any]) -> dict[str, Any]:
        body = self._with_tab(args, selector=args["selector"])
        return self._action("page.click", **body)

    def type(self, args: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"action": "page.type", "text": args["text"]}
        if args.get("selector"):
            body["selector"] = args["selector"]
        tid = _coerce_tab_id(args)
        if tid is not None:
            body["tabId"] = tid
        return http_json(self.base, "/v1/action", body)

    def scroll(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body = self._with_tab(
            args,
            dy=int(args.get("dy", 600)),
            dx=int(args.get("dx", 0)),
        )
        return self._action("page.scroll", **body)

    def wait(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {"action": "page.wait"}
        for k in ("mode", "selector", "ms", "timeout_ms", "timeout"):
            if args.get(k) is not None:
                body[k] = args[k]
        tid = _coerce_tab_id(args)
        if tid is not None:
            body["tabId"] = tid
        return http_json(self.base, "/v1/action", body, timeout=float(args.get("timeout_ms") or args.get("timeout") or 20) + 5)

    def find(self, args: dict[str, Any]) -> dict[str, Any]:
        body = self._with_tab(args, selector=args["selector"])
        if args.get("limit") is not None:
            body["limit"] = int(args["limit"])
        return self._action("page.find", **body)

    def links(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body = self._with_tab(args)
        if args.get("limit") is not None:
            body["limit"] = int(args["limit"])
        return self._action("page.links", **body)

    def back(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._action("page.back", **self._with_tab(args))

    def forward(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._action("page.forward", **self._with_tab(args))

    def reload(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body = self._with_tab(args)
        if args.get("bypass_cache"):
            body["bypass_cache"] = True
        return self._action("page.reload", **body)

    def workspace(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Multi-tab orient: list tabs, optional page.info + short snapshot of one tab.

        Args:
          tabId: prefer this tab for info/snapshot (else active)
          snapshot: bool (default true) — include text preview
          snapshot_chars: int cap (default 2500)
          match: substring to pick tab by url/title when tabId omitted
        """
        args = args or {}
        tabs_out = self.tabs()
        tabs_data = tabs_out.get("data") if isinstance(tabs_out, dict) else None
        tab_list: list[dict[str, Any]] = []
        if isinstance(tabs_data, dict):
            raw = tabs_data.get("tabs") or tabs_data.get("items") or []
            if isinstance(raw, list):
                tab_list = [t for t in raw if isinstance(t, dict)]
        elif isinstance(tabs_data, list):
            tab_list = [t for t in tabs_data if isinstance(t, dict)]

        match = str(args.get("match") or "").strip().lower()
        tid = _coerce_tab_id(args)
        chosen: dict[str, Any] | None = None
        if tid is not None:
            for t in tab_list:
                if int(t.get("id") or t.get("tabId") or -1) == tid:
                    chosen = t
                    break
        elif match:
            for t in tab_list:
                blob = f"{t.get('url') or ''} {t.get('title') or ''}".lower()
                if match in blob:
                    chosen = t
                    tid = int(t.get("id") or t.get("tabId") or 0) or None
                    break

        info = self.page_info({"tabId": tid} if tid is not None else {})
        snap_preview = None
        do_snap = args.get("snapshot", True)
        if do_snap is True or do_snap == "true" or do_snap == 1:
            snap = self.snapshot({"tabId": tid} if tid is not None else {})
            text = ""
            if isinstance(snap.get("data"), dict):
                text = str(snap["data"].get("text") or snap["data"].get("body") or "")
            elif snap.get("text"):
                text = str(snap.get("text") or "")
            # Honor explicit snapshot_chars; default 2500; hard max 12000; floor 40
            raw_cap = args.get("snapshot_chars")
            cap = int(raw_cap) if raw_cap is not None else 2500
            cap = max(40, min(cap, 12000))
            snap_preview = {
                "ok": snap.get("ok"),
                "code": snap.get("code"),
                "chars": len(text),
                "text_preview": text[:cap],
                "tabId": tid,
            }

        return {
            "ok": True,
            "code": "WORKSPACE",
            "tab_count": len(tab_list),
            "tabs": [
                {
                    "id": t.get("id") or t.get("tabId"),
                    "url": t.get("url"),
                    "title": t.get("title"),
                    "active": t.get("active"),
                }
                for t in tab_list[:40]
            ],
            "focus": {
                "tabId": tid,
                "matched": chosen,
                "page_info": info,
            },
            "snapshot": snap_preview,
            "hint": (
                "Pass tabId on navigate/snapshot/click/scroll/find/links to work multi-tab "
                "without losing other pages. Prefer tab_create for parallel research."
            ),
            "claim": "multi-tab orient under leash — not multi-display OS control",
        }

    def x_article_read(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fetch full X article / status / thread body (T1 observe — arm required)."""
        args = args or {}
        body: dict[str, Any] = {"action": "x.article_read"}
        url = (args.get("url") or "").strip()
        if url:
            body["url"] = url
        if args.get("max_scrolls") is not None:
            body["max_scrolls"] = int(args["max_scrolls"])
        if args.get("max_chars") is not None:
            body["max_chars"] = int(args["max_chars"])
        if args.get("timeout") is not None:
            body["timeout"] = float(args["timeout"])
        # Scroll extract can take >90s; default host HTTP timeout is 90
        http_timeout = float(args.get("timeout") or 130.0)
        res = http_json(self.base, "/v1/action", body, timeout=http_timeout)
        # Normalize for agent: promote data fields
        if res.get("ok") and isinstance(res.get("data"), dict):
            data = res["data"]
            return {
                "ok": True,
                "code": res.get("code") or "ARTICLE_READ",
                "kind": data.get("kind"),
                "url": data.get("url"),
                "title": data.get("title"),
                "author": data.get("author"),
                "handle": data.get("handle"),
                "headline": data.get("headline"),
                "body": data.get("body"),
                "char_count": data.get("char_count"),
                "word_count": data.get("word_count"),
                "truncated": data.get("truncated"),
                "leash": {k: v for k, v in res.items() if k != "data"},
                "meta": {
                    "expand_clicks": data.get("expand_clicks"),
                    "blocks_found": data.get("blocks_found"),
                },
            }
        return {
            "ok": False,
            "code": res.get("code") or "ARTICLE_READ_FAIL",
            "detail": res.get("detail"),
            "leash": res,
        }

    def x_article_search(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Keyword search X → result cards (posts + article links)."""
        args = args or {}
        query = str(args.get("query") or args.get("q") or "").strip()
        body: dict[str, Any] = {"action": "x.article_search"}
        if query:
            body["query"] = query
        if args.get("url"):
            body["url"] = str(args["url"]).strip()
        if args.get("sort"):
            body["sort"] = str(args["sort"])
        if args.get("max_results") is not None:
            body["max_results"] = int(args["max_results"])
        if args.get("max_scrolls") is not None:
            body["max_scrolls"] = int(args["max_scrolls"])
        if args.get("articles_only") is not None:
            body["articles_only"] = bool(args["articles_only"])
        http_timeout = float(args.get("timeout") or 120.0)
        res = http_json(self.base, "/v1/action", body, timeout=http_timeout)
        if res.get("ok") and isinstance(res.get("data"), dict):
            data = res["data"]
            return {
                "ok": True,
                "code": res.get("code") or "ARTICLE_SEARCH",
                "query": data.get("query") or query,
                "sort": data.get("sort"),
                "search_url": data.get("search_url") or data.get("url"),
                "count": data.get("count") or len(data.get("results") or []),
                "results": data.get("results") or [],
                "leash": {k: v for k, v in res.items() if k != "data"},
            }
        return {
            "ok": False,
            "code": res.get("code") or "SEARCH_FAIL",
            "detail": res.get("detail"),
            "leash": res,
        }

    def x_article_curate(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Search X by keywords, rank results, optionally deep-read top N bodies.

        Args:
          query: keywords
          sort: latest|top
          max_results: search card cap (default 15)
          top_n: curated list size (default 5)
          read_top: how many top cards to full-read (default 0; set 1–3 for substance)
          max_scrolls: search scroll budget
        """
        args = args or {}
        query = str(args.get("query") or args.get("q") or "").strip()
        if not query:
            return {"ok": False, "code": "QUERY_REQUIRED", "detail": "query required"}

        max_results = int(args.get("max_results") or 15)
        top_n = max(1, min(int(args.get("top_n") or 5), 20))
        read_top = max(0, min(int(args.get("read_top") or 0), 5))
        sort = str(args.get("sort") or "latest")

        search = self.x_article_search(
            {
                "query": query,
                "sort": sort,
                "max_results": max_results,
                "max_scrolls": args.get("max_scrolls") or 8,
                "articles_only": args.get("articles_only"),
                "timeout": args.get("timeout") or 120,
            }
        )
        if not search.get("ok"):
            return {
                "ok": False,
                "code": search.get("code") or "CURATE_SEARCH_FAIL",
                "detail": search.get("detail"),
                "search": search,
            }

        tokens = _tokenize_query(query)
        cards = list(search.get("results") or [])
        ranked: list[dict[str, Any]] = []
        for c in cards:
            if not isinstance(c, dict):
                continue
            item = dict(c)
            item["score"] = _score_card(item, tokens)
            ranked.append(item)
        ranked.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
        curated = ranked[:top_n]

        reads: list[dict[str, Any]] = []
        for item in curated[:read_top]:
            url = str(item.get("article_url") or item.get("url") or "").strip()
            if not url:
                continue
            body = self.x_article_read(
                {
                    "url": url,
                    "max_scrolls": int(args.get("read_max_scrolls") or 8),
                    "max_chars": int(args.get("read_max_chars") or 40000),
                    "timeout": float(args.get("read_timeout") or 100),
                }
            )
            reads.append(
                {
                    "url": url,
                    "score": item.get("score"),
                    "ok": body.get("ok"),
                    "kind": body.get("kind"),
                    "headline": body.get("headline"),
                    "author": body.get("author"),
                    "handle": body.get("handle"),
                    "word_count": body.get("word_count"),
                    "body_preview": (body.get("body") or "")[:1500],
                    "body": body.get("body") if body.get("ok") else None,
                    "error": None if body.get("ok") else body.get("code"),
                }
            )

        return {
            "ok": True,
            "code": "ARTICLE_CURATED",
            "query": query,
            "tokens": tokens,
            "sort": sort,
            "search_count": search.get("count"),
            "search_url": search.get("search_url"),
            "curated": curated,
            "reads": reads,
            "claim": "keyword search + heuristic rank under leash — not X API / not full editorial AI",
        }

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
