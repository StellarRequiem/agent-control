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
        body: dict[str, Any] = {"url": args["url"]}
        if args.get("tabId") is not None:
            body["tabId"] = int(args["tabId"])
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
        if args.get("tabId") is not None:
            body["tabId"] = int(args["tabId"])
        elif args.get("id") is not None:
            body["tabId"] = int(args["id"])
        return self._action("tab.close", **body)

    def tab_activate(self, args: dict[str, Any]) -> dict[str, Any]:
        tid = args.get("tabId") if args.get("tabId") is not None else args.get("id")
        return self._action("tab.activate", tabId=int(tid))

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

    def wait(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {"action": "page.wait"}
        for k in ("mode", "selector", "ms", "timeout_ms", "timeout", "tabId"):
            if args.get(k) is not None:
                body[k] = args[k]
        return http_json(self.base, "/v1/action", body, timeout=float(args.get("timeout_ms") or args.get("timeout") or 20) + 5)

    def find(self, args: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"selector": args["selector"]}
        if args.get("limit") is not None:
            body["limit"] = int(args["limit"])
        return self._action("page.find", **body)

    def links(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {}
        if args.get("limit") is not None:
            body["limit"] = int(args["limit"])
        return self._action("page.links", **body)

    def back(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._action("page.back")

    def forward(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._action("page.forward")

    def reload(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {}
        if args.get("bypass_cache"):
            body["bypass_cache"] = True
        return self._action("page.reload", **body)

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
