#!/usr/bin/env python3
"""Local Ollama harness for the assured plane.

Launches ``mcp_server.py --actor ollama`` over stdio and drives
``POST /api/chat`` tool calls through that server. ``ollama`` is not a
built-in stdio actor; the operator adds it to ``receipts/stdio-actors``.
See docs/OLLAMA_AGENT.md.

The MCP client is imported only when a real server is started, so unit
tests can import this module without the ``mcp`` package.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

ROOT = Path(__file__).resolve().parent

ACTOR = "ollama"
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MAX_STEPS = 20
DEFAULT_TIMEOUT_S = 180.0
DEFAULT_MAX_ERRORS = 3
DEFAULT_MAX_SPRAY = 3
TOOL_RESULT_CHAR_CAP = 12_000
DEFAULT_PROMPT = ROOT / "docs" / "OLLAMA_AGENT_PROMPT.md"
DEFAULT_TRANSCRIPT_DIR = ROOT / "receipts" / "ollama-agent"
DEFAULT_SERVER = ROOT / "mcp_server.py"

# Pack names. list_tools advertises FastMCP names (dot → underscore).
# A candidate the server does not advertise is not exposed.
DEFAULT_TOOL_CANDIDATES: tuple[str, ...] = (
    "plane.status",
    "shell.read_file",
    "shell.list_dir",
    "shell.stat",
    "desktop.status",
    "desktop.screenshot",
    "desktop.layout",
    "cua.observe",
)

EXIT_CODES = {
    "answered": 0,
    "dry_run": 0,
    "ollama_error": 1,
    "freeze": 2,
    "deny": 3,
    "confirm": 4,
    "spray": 5,
    "max_steps": 6,
    "timeout": 7,
    "max_errors": 8,
}


class OllamaError(RuntimeError):
    """The Ollama daemon could not complete /api/chat."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class Config:
    model: str = DEFAULT_MODEL
    host: str = DEFAULT_HOST
    think: bool = False
    max_steps: int = DEFAULT_MAX_STEPS
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_consecutive_errors: int = DEFAULT_MAX_ERRORS
    max_spray: int = DEFAULT_MAX_SPRAY
    tool_candidates: tuple[str, ...] = DEFAULT_TOOL_CANDIDATES
    prompt_path: Path = DEFAULT_PROMPT
    rules: tuple[Path, ...] = ()
    transcript_dir: Path = DEFAULT_TRANSCRIPT_DIR
    dry_run: bool = False
    server: Path = DEFAULT_SERVER
    python: str = ""
    task: str = ""


@dataclass
class RunResult:
    reason: str
    answer: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    transcript_path: Path | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


def mcp_launch_command(cfg: Config) -> tuple[str, list[str]]:
    """Interpreter plus argv for ``mcp_server.py --actor ollama``."""
    python = cfg.python or sys.executable
    return python, [str(cfg.server), "--actor", ACTOR]


def resolve_advertised_name(requested: str, advertised: dict[str, ToolSpec]) -> str | None:
    """Exact list_tools name, or the same id with dots turned into underscores."""
    if requested in advertised:
        return requested
    underscored = requested.replace(".", "_")
    if underscored in advertised:
        return underscored
    return None


def select_tools(
    advertised: list[ToolSpec], allow: tuple[str, ...] | list[str]
) -> tuple[list[ToolSpec], list[str]]:
    """Intersection of the allowlist and names the server actually listed.

    Missing entries are names the operator asked for that ``list_tools``
    did not return. They are not given to the model.
    """
    by_name = {tool.name: tool for tool in advertised}
    exposed: list[ToolSpec] = []
    missing: list[str] = []
    seen: set[str] = set()
    for raw in allow:
        match = resolve_advertised_name(raw, by_name)
        if match is None:
            missing.append(raw)
            continue
        if match in seen:
            continue
        seen.add(match)
        exposed.append(by_name[match])
    return exposed, missing


def strip_operator_confirm(value: Any) -> tuple[Any, bool]:
    """Drop every ``operator_confirm`` key. The model cannot set it.

    A string under ``arguments_json`` or ``arguments`` that parses as a
    JSON object or array is cleaned and written back as JSON.
    """
    found = False

    def walk(item: Any) -> Any:
        nonlocal found
        if isinstance(item, dict):
            out: dict[str, Any] = {}
            for key, child in item.items():
                if isinstance(key, str) and key.lower() == "operator_confirm":
                    found = True
                    continue
                if (
                    key in ("arguments_json", "arguments")
                    and isinstance(child, str)
                ):
                    parsed = _json_container(child)
                    if parsed is not None:
                        out[key] = json.dumps(walk(parsed), default=str)
                        continue
                out[key] = walk(child)
            return out
        if isinstance(item, list):
            return [walk(child) for child in item]
        return item

    return walk(value), found


def _json_container(text: str) -> dict | list | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def classify_plane_payload(payload: Any) -> str:
    """Classify a plane/MCP result.

    Returns ``ok``, ``error``, ``deny``, ``freeze``, or ``confirm``.
    A successful ``plane_status`` that *mentions* a freeze in its body is
    ``ok``. FREEZE here means the gate denied this call.
    """
    if not isinstance(payload, dict):
        return "error"
    verdict = payload.get("verdict") if isinstance(payload.get("verdict"), dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    codes = [
        str(verdict.get("code") or ""),
        str(result.get("code") or ""),
        str(payload.get("code") or ""),
    ]
    if any("HUMAN_CONFIRM_REQUIRED" in code for code in codes):
        return "confirm"
    if str(verdict.get("code") or "").upper() == "FREEZE":
        return "freeze"
    if str(result.get("code") or "").upper() == "FREEZE":
        return "freeze"
    decision = str(verdict.get("decision") or payload.get("decision") or "").upper()
    if decision == "DENY" or verdict.get("allowed") is False:
        return "deny"
    if payload.get("is_error") is True or payload.get("isError") is True:
        return "error"
    if result.get("ok") is False or (
        payload.get("ok") is False and "verdict" not in payload and "result" not in payload
    ):
        return "error"
    if payload.get("executed") is False and decision != "ALLOW":
        return "error"
    return "ok"


def parse_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse ``message.tool_calls`` into ``{name, arguments}`` dicts.

    Arguments may be a JSON object or a JSON string. A non-object is left
    as ``None`` so the loop can refuse it locally.
    """
    raw = message.get("tool_calls") or []
    if not isinstance(raw, list):
        return []
    calls: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        fn = entry.get("function") if isinstance(entry.get("function"), dict) else entry
        name = str(fn.get("name") or "")
        args = fn.get("arguments")
        if isinstance(args, str):
            parsed = _json_container(args)
            args = parsed if isinstance(parsed, dict) else None
        elif args is None:
            args = {}
        elif not isinstance(args, dict):
            args = None
        calls.append({"name": name, "arguments": args})
    return calls


def ollama_tool_schema(tool: ToolSpec) -> dict[str, Any]:
    parameters = tool.parameters if isinstance(tool.parameters, dict) else {}
    if not parameters:
        parameters = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": parameters,
        },
    }


def chat_request_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    think: bool,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "think": think,
    }


def load_system_prompt(
    prompt_path: Path, rules: tuple[Path, ...], exposed: list[ToolSpec]
) -> str:
    if not prompt_path.is_file():
        raise SystemExit(f"operator prompt missing: {prompt_path}")
    parts = [prompt_path.read_text(encoding="utf-8").rstrip()]
    for path in rules:
        if not path.is_file():
            raise SystemExit(f"rules file missing: {path}")
        parts.append(
            f"# Operator protocol ({path})\n\n" + path.read_text(encoding="utf-8").rstrip()
        )
    if exposed:
        lines = "\n".join(
            f"- {tool.name}: {tool.description}" if tool.description else f"- {tool.name}"
            for tool in exposed
        )
    else:
        lines = "(none)"
    parts.append(
        "# Exposed tools\n\n"
        "You may call only these exact names. Any other name is rejected locally "
        "and is not sent to the plane:\n"
        f"{lines}"
    )
    return "\n\n".join(parts) + "\n"


def ensure_actor_or_exit() -> None:
    """Refuse to start unless the operator roster admits ``ollama``."""
    from host.stdio_actor import UnknownActorError, validate_actor

    try:
        validate_actor(ACTOR)
    except UnknownActorError as exc:
        print(str(exc), file=sys.stderr)
        print(
            "\nThe ollama harness does not add itself to the built-in roster "
            "(grok, claude, codex).\n"
            "On the operator machine, from the agent-control repo:\n"
            "  mkdir -p receipts\n"
            "  printf 'ollama\\n' >> receipts/stdio-actors\n"
            "See docs/OLLAMA_AGENT.md.\n",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


class HttpOllama:
    """POST /api/chat. No streaming."""

    def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        host: str,
        think: bool,
        timeout: float,
    ) -> dict[str, Any]:
        url = host.rstrip("/") + "/api/chat"
        body = chat_request_body(model=model, messages=messages, tools=tools, think=think)
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise OllamaError(f"ollama HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaError(f"ollama unreachable at {url}: {exc}") from exc
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OllamaError(f"ollama returned non-JSON from {url}") from exc
        if isinstance(parsed, dict) and parsed.get("error"):
            raise OllamaError(str(parsed["error"]))
        if not isinstance(parsed, dict) or not isinstance(parsed.get("message"), dict):
            raise OllamaError("ollama response has no message object")
        return parsed


def _import_mcp():
    try:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except ImportError as exc:
        raise SystemExit(
            "The mcp Python client is not installed for this interpreter. "
            "Use the same interpreter that already runs mcp_server.py "
            "(mcp 1.x, which provides mcp.server.fastmcp). "
            "On the operator machine, if the client import is missing:\n"
            "  ~/mcp-assure/.venv/bin/python -m pip install 'mcp>=1,<2'\n"
            "Do not install mcp 2: it renames FastMCP and this server will not start."
        ) from exc
    return ClientSession, StdioServerParameters, stdio_client


def spec_from_mcp_tool(tool: Any) -> ToolSpec:
    name = getattr(tool, "name", None)
    if name is None and isinstance(tool, dict):
        name = tool.get("name")
    description = getattr(tool, "description", None)
    if description is None and isinstance(tool, dict):
        description = tool.get("description")
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = getattr(tool, "inputSchema", None)
    if schema is None and isinstance(tool, dict):
        schema = tool.get("input_schema") or tool.get("inputSchema")
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump(by_alias=True, exclude_none=True)
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return ToolSpec(name=str(name or ""), description=str(description or ""), parameters=schema)


def payload_from_call_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and structured:
        payload = dict(structured)
    else:
        texts: list[str] = []
        for block in getattr(result, "content", None) or []:
            if isinstance(block, dict):
                text = block.get("text")
            else:
                text = getattr(block, "text", None)
            if text:
                texts.append(str(text))
        raw = "\n".join(texts).strip()
        if not raw:
            payload = {}
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
            else:
                payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
    is_error = getattr(result, "is_error", None)
    if is_error is None:
        is_error = getattr(result, "isError", False)
    if is_error:
        payload.setdefault("ok", False)
        payload["is_error"] = True
    return payload


class StdioMcpPlane:
    """One stdio MCP session, used synchronously by the agent loop."""

    def __init__(self, command: str, args: list[str], cwd: str) -> None:
        self.command = command
        self.args = args
        self.cwd = cwd
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="ollama-mcp", daemon=True)
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._session: Any = None
        self._stop: asyncio.Event | None = None
        # Server stderr (FastMCP "Processing request" lines included). Kept off
        # the operator trace; surfaced if the session fails to start.
        self._err = tempfile.TemporaryFile(mode="w+", encoding="utf-8")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session_main())
        finally:
            if not self._ready.is_set():
                self._ready.set()

    async def _session_main(self) -> None:
        ClientSession, StdioServerParameters, stdio_client = _import_mcp()
        params = StdioServerParameters(command=self.command, args=self.args, cwd=self.cwd)
        try:
            async with stdio_client(params, errlog=self._err) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._stop = asyncio.Event()
                    self._ready.set()
                    await self._stop.wait()
        except BaseException as exc:
            self._error = exc
            self._ready.set()

    def __enter__(self) -> StdioMcpPlane:
        self._thread.start()
        if not self._ready.wait(timeout=30):
            raise TimeoutError("mcp_server.py did not become ready within 30s")
        if self._error is not None:
            tail = self.stderr_tail()
            if tail:
                raise RuntimeError(f"{self._error}\n--- mcp_server.py stderr ---\n{tail}") from self._error
            raise self._error
        if self._session is None:
            raise RuntimeError("mcp_server.py exited before the session started")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._stop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=8)
        if not self._thread.is_alive() and not self._loop.is_closed():
            self._loop.close()
        try:
            self._err.close()
        except OSError:
            pass
        return False

    def stderr_tail(self, limit: int = 4000) -> str:
        try:
            self._err.seek(0)
            text = self._err.read()
        except (OSError, ValueError):
            return ""
        return text[-limit:]

    def _submit(self, coro: Any, timeout: float) -> Any:
        if self._session is None or not self._loop.is_running():
            raise RuntimeError("MCP session is not running")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=max(timeout, 0.1))

    def list_tools(self) -> list[ToolSpec]:
        return self._submit(self._list_all(), 30)

    async def _list_all(self) -> list[ToolSpec]:
        tools: list[Any] = []
        cursor: str | None = None
        while True:
            if cursor:
                from mcp.types import PaginatedRequestParams

                result = await self._session.list_tools(
                    params=PaginatedRequestParams(cursor=cursor)
                )
            else:
                result = await self._session.list_tools()
            tools.extend(result.tools or [])
            cursor = getattr(result, "next_cursor", None) or getattr(result, "nextCursor", None)
            if not cursor:
                break
        return [spec_from_mcp_tool(tool) for tool in tools]

    def call_tool(self, name: str, arguments: dict[str, Any], timeout: float) -> dict[str, Any]:
        return self._submit(self._call(name, arguments, timeout), timeout + 1)

    async def _call(self, name: str, arguments: dict[str, Any], timeout: float) -> dict[str, Any]:
        # mcp 1.x (the FastMCP this server imports) takes a timedelta.
        # A float is applied as ``timeout.total_seconds()`` and raises before the
        # tool runs. mcp 2 renamed FastMCP, so this server does not start there.
        result = await self._session.call_tool(
            name,
            arguments=arguments,
            read_timeout_seconds=timedelta(seconds=max(float(timeout), 0.1)),
        )
        return payload_from_call_result(result)


class Transcript:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.path = directory / f"{stamp}.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")
        self.events: list[dict[str, Any]] = []

    def write(self, event: dict[str, Any]) -> None:
        row = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        self.events.append(row)
        self._fh.write(json.dumps(row, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def _cap(text: str, limit: int = TOOL_RESULT_CHAR_CAP) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…[truncated]"


def _dump(payload: Any) -> str:
    return _cap(json.dumps(payload, default=str))


def _jsonable(payload: Any) -> Any:
    """A JSON-safe copy. Oversized payloads become a preview, not broken JSON."""
    text = json.dumps(payload, default=str)
    if len(text) <= TOOL_RESULT_CHAR_CAP:
        return json.loads(text)
    return {"truncated": True, "preview": text[:TOOL_RESULT_CHAR_CAP]}


def _short(payload: Any, limit: int = 400) -> str:
    text = json.dumps(payload, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


class AgentLoop:
    def __init__(
        self,
        cfg: Config,
        plane: Any,
        ollama: Any,
        out: TextIO,
    ) -> None:
        self.cfg = cfg
        self.plane = plane
        self.ollama = ollama
        self.out = out
        self.deadline = time.monotonic() + cfg.timeout_s

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def timed_out(self) -> bool:
        return self.remaining() <= 0

    def run(self, task: str) -> RunResult:
        advertised = list(self.plane.list_tools())
        exposed, missing = select_tools(advertised, self.cfg.tool_candidates)
        prompt = load_system_prompt(self.cfg.prompt_path, self.cfg.rules, exposed)
        transcript = Transcript(self.cfg.transcript_dir)
        names = [tool.name for tool in exposed]
        try:
            transcript.write(
                {
                    "kind": "start",
                    "task": task,
                    "model": self.cfg.model,
                    "host": self.cfg.host,
                    "actor": ACTOR,
                    "think": self.cfg.think,
                    "exposed": names,
                    "not_advertised": missing,
                    "dry_run": self.cfg.dry_run,
                    "prompt": prompt,
                }
            )
            self._print_header(names, missing)
            if self.cfg.dry_run:
                print("dry-run (no model call)", file=self.out)
                print("system prompt:", file=self.out)
                print(prompt, file=self.out)
                transcript.write({"kind": "stop", "reason": "dry_run"})
                return self._finish(transcript, "dry_run")
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": task},
            ]
            tools = [ollama_tool_schema(tool) for tool in exposed]
            exposed_names = set(names)
            spray = 0
            consecutive_errors = 0
            for step in range(1, self.cfg.max_steps + 1):
                if self.timed_out():
                    return self._stop(transcript, "timeout", step=step)
                try:
                    response = self.ollama.chat(
                        messages=messages,
                        tools=tools,
                        model=self.cfg.model,
                        host=self.cfg.host,
                        think=self.cfg.think,
                        timeout=max(self.remaining(), 0.1),
                    )
                except OllamaError as exc:
                    print(f"ollama error: {exc}", file=self.out)
                    return self._stop(transcript, "ollama_error", error=str(exc), step=step)
                message = response.get("message") or {}
                messages.append(_assistant_message(message))
                calls = parse_tool_calls(message)
                transcript.write(
                    {
                        "kind": "model",
                        "step": step,
                        "content": message.get("content") or "",
                        "tool_calls": calls,
                    }
                )
                if not calls:
                    answer = str(message.get("content") or "")
                    print(answer, file=self.out)
                    return self._stop(transcript, "answered", answer=answer, step=step)
                print(
                    f"[step {step}] model tool_calls: "
                    + ", ".join(call["name"] or "(unnamed)" for call in calls),
                    file=self.out,
                )
                for call in calls:
                    if self.timed_out():
                        return self._stop(transcript, "timeout", step=step)
                    outcome = self._dispatch(
                        call,
                        exposed_names,
                        transcript,
                        step,
                    )
                    messages.append(outcome["tool_message"])
                    kind = outcome["kind"]
                    if kind == "spray":
                        spray += 1
                        if spray >= self.cfg.max_spray:
                            return self._stop(
                                transcript,
                                "spray",
                                step=step,
                                spray=spray,
                                valid_tools=sorted(exposed_names),
                            )
                        continue
                    if kind in {"freeze", "deny", "confirm"}:
                        return self._stop(
                            transcript,
                            kind,
                            step=step,
                            tool=call["name"],
                            arguments=outcome.get("original_arguments"),
                            sent_arguments=outcome.get("sent_arguments"),
                            result=outcome.get("payload"),
                            stripped_operator_confirm=outcome.get("stripped"),
                        )
                    if kind == "error":
                        consecutive_errors += 1
                        if consecutive_errors >= self.cfg.max_consecutive_errors:
                            return self._stop(
                                transcript,
                                "max_errors",
                                step=step,
                                consecutive_errors=consecutive_errors,
                            )
                    else:
                        consecutive_errors = 0
            return self._stop(transcript, "max_steps", step=self.cfg.max_steps)
        finally:
            transcript.close()

    def _dispatch(
        self,
        call: dict[str, Any],
        exposed_names: set[str],
        transcript: Transcript,
        step: int,
    ) -> dict[str, Any]:
        name = call["name"]
        original = call["arguments"]
        if name not in exposed_names or original is None:
            if name not in exposed_names:
                payload = {
                    "ok": False,
                    "code": "TOOL_NOT_EXPOSED",
                    "detail": (
                        f"{name!r} is not in the exposed tool list. "
                        "Not forwarded to the plane. Exact names only."
                    ),
                    "valid_tools": sorted(exposed_names),
                }
                kind = "spray"
            else:
                payload = {
                    "ok": False,
                    "code": "BAD_ARGS",
                    "detail": "tool arguments must be a JSON object. Not forwarded to the plane.",
                }
                kind = "error"
            print(f"[step {step}] local {payload['code']} {name!r}", file=self.out)
            transcript.write(
                {
                    "kind": "tool",
                    "step": step,
                    "name": name,
                    "forwarded": False,
                    "classification": kind,
                    "result": payload,
                }
            )
            return {"kind": kind, "tool_message": _tool_message(name, payload), "payload": payload}

        sent, stripped = strip_operator_confirm(original)
        if stripped:
            print(
                f"[step {step}] stripped operator_confirm from {name} before dispatch",
                file=self.out,
            )
        try:
            payload = self.plane.call_tool(name, sent, timeout=max(self.remaining(), 0.1))
        except Exception as exc:
            payload = {"ok": False, "code": "MCP_ERROR", "detail": str(exc)}
            kind = "error"
        else:
            if not isinstance(payload, dict):
                payload = {"raw": payload}
            kind = classify_plane_payload(payload)
        print(f"[step {step}] tool {name} → {kind} {_short(payload)}", file=self.out)
        transcript.write(
            {
                "kind": "tool",
                "step": step,
                "name": name,
                "forwarded": True,
                "stripped_operator_confirm": stripped,
                "arguments": sent,
                "classification": kind,
                "result": _jsonable(payload),
            }
        )
        if kind == "confirm":
            print(
                f"[step {step}] HUMAN_CONFIRM_REQUIRED — stopping.\n"
                f"The model wanted {name} with arguments {json.dumps(original, default=str)}.\n"
                "operator_confirm was stripped and was not sent. "
                "The model cannot set it. Run the action yourself if you approve it.",
                file=self.out,
            )
        elif kind in {"freeze", "deny"}:
            print(
                f"[step {step}] plane {kind} on {name} — stopping, not retrying.\n"
                f"arguments sent: {json.dumps(sent, default=str)}",
                file=self.out,
            )
        return {
            "kind": kind,
            "tool_message": _tool_message(name, payload),
            "payload": payload,
            "original_arguments": original,
            "sent_arguments": sent,
            "stripped": stripped,
        }

    def _print_header(self, names: list[str], missing: list[str]) -> None:
        print(
            f"ollama-agent model={self.cfg.model} host={self.cfg.host} actor={ACTOR} "
            f"think={str(self.cfg.think).lower()}",
            file=self.out,
        )
        print("exposed: " + (", ".join(names) if names else "(none)"), file=self.out)
        if missing:
            print("not advertised, not exposed: " + ", ".join(missing), file=self.out)

    def _stop(self, transcript: Transcript, reason: str, **detail: Any) -> RunResult:
        answer = str(detail.pop("answer", "") or "")
        transcript.write({"kind": "stop", "reason": reason, "answer": answer, **detail})
        if reason != "answered":
            print(f"stop: {reason}", file=self.out)
        else:
            print("stop: answered", file=self.out)
        print(f"transcript: {transcript.path}", file=self.out)
        return RunResult(
            reason=reason,
            answer=answer,
            detail=detail,
            transcript_path=transcript.path,
            events=list(transcript.events),
        )

    def _finish(self, transcript: Transcript, reason: str) -> RunResult:
        print(f"stop: {reason}", file=self.out)
        print(f"transcript: {transcript.path}", file=self.out)
        return RunResult(
            reason=reason,
            transcript_path=transcript.path,
            events=list(transcript.events),
        )


def _assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "role": "assistant",
        "content": message.get("content") or "",
    }
    if message.get("tool_calls"):
        out["tool_calls"] = message["tool_calls"]
    if message.get("thinking"):
        out["thinking"] = message["thinking"]
    return out


def _tool_message(name: str, payload: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_name": name,
        "content": _dump(payload),
    }


def run_task(
    task: str,
    cfg: Config,
    *,
    plane: Any,
    ollama: Any,
    stdout: TextIO | None = None,
) -> RunResult:
    loop = AgentLoop(cfg, plane, ollama, stdout or sys.stdout)
    return loop.run(task)


def _split_csv(values: list[str] | None) -> tuple[str, ...]:
    out: list[str] = []
    for value in values or []:
        for part in value.split(","):
            part = part.strip()
            if part:
                out.append(part)
    return tuple(out)


def parse_config(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        prog="ollama_agent.py",
        description="Drive a local Ollama model through the assured plane over stdio MCP.",
    )
    parser.add_argument("task", help="task for the model")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="wall-clock seconds")
    parser.add_argument("--max-errors", type=int, default=DEFAULT_MAX_ERRORS)
    parser.add_argument(
        "--tools",
        action="append",
        default=[],
        help="comma-separated MCP tool names to add to the default allowlist",
    )
    parser.add_argument(
        "--rules",
        action="append",
        default=[],
        help="operator protocol file appended to the system prompt (repeatable)",
    )
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exposed tool list and prompt; do not call the model",
    )
    args = parser.parse_args(argv)
    extra = _split_csv(args.tools)
    prompt = args.prompt if args.prompt.is_absolute() else (Path.cwd() / args.prompt)
    if args.prompt == DEFAULT_PROMPT:
        prompt = DEFAULT_PROMPT
    rules = tuple(Path(path).expanduser() for path in args.rules)
    return Config(
        model=args.model,
        host=args.host,
        max_steps=args.max_steps,
        timeout_s=args.timeout,
        max_consecutive_errors=args.max_errors,
        tool_candidates=DEFAULT_TOOL_CANDIDATES + extra,
        prompt_path=prompt,
        rules=rules,
        dry_run=args.dry_run,
        task=args.task,
    )


def exit_code(result: RunResult) -> int:
    return EXIT_CODES.get(result.reason, 1)


def main(argv: list[str] | None = None) -> int:
    cfg = parse_config(argv)
    ensure_actor_or_exit()
    command, args = mcp_launch_command(cfg)
    try:
        with StdioMcpPlane(command, args, cwd=str(ROOT)) as plane:
            result = run_task(cfg.task, cfg, plane=plane, ollama=HttpOllama())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"failed to run mcp_server.py --actor {ACTOR}: {exc}", file=sys.stderr)
        print(
            "If the server refused the actor, add ollama to receipts/stdio-actors. "
            "See docs/OLLAMA_AGENT.md.",
            file=sys.stderr,
        )
        return 1
    return exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
