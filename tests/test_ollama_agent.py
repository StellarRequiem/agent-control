"""Ollama harness loop. Ollama and the MCP session are fakes.

The real stdio client is not started here: CI does not install the mcp
package, and mcp_server.py imports mcp-assure. These tests cover the
decisions the harness makes before a call would reach the plane.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import ollama_agent as agent
from host.stdio_actor import DEFAULT_ROSTER, resolve_stdio_actor

ROOT = Path(__file__).resolve().parent.parent


def _spec(name: str, description: str = "") -> agent.ToolSpec:
    return agent.ToolSpec(
        name=name,
        description=description or name,
        parameters={"type": "object", "properties": {}},
    )


ADVERTISED = [
    _spec("plane_status", "plane status"),
    _spec("shell_read_file", "read a file"),
    _spec("shell_list_dir", "list a directory"),
    _spec("shell_stat", "stat a path"),
    _spec("desktop_status", "desktop status"),
    _spec("desktop_screenshot", "desktop screenshot"),
    _spec("desktop_layout", "window layout"),
    _spec("cua_observe", "multi-plane observe"),
    _spec("shell_exec", "gated exec"),
    _spec("plane_call", "call any pack tool"),
]


class FakePlane:
    def __init__(self, handler, tools=None):
        self.tools = list(ADVERTISED if tools is None else tools)
        self.calls: list[tuple[str, dict]] = []
        self.handler = handler

    def list_tools(self):
        return list(self.tools)

    def call_tool(self, name, arguments, timeout=0):
        if name not in {tool.name for tool in self.tools}:
            raise AssertionError(f"plane saw a name it did not advertise: {name}")
        if name in {"shell_exec", "plane_call"}:
            raise AssertionError(f"{name} must not be forwarded by the default harness")
        self.calls.append((name, arguments))
        return self.handler(name, arguments)


class FakeOllama:
    def __init__(self, messages: list[dict]):
        self._messages = list(messages)
        self.requests: list[dict] = []

    def chat(self, *, messages, tools, model, host, think, timeout):
        self.requests.append(
            {
                "messages": json.loads(json.dumps(messages)),
                "tools": json.loads(json.dumps(tools)),
                "model": model,
                "host": host,
                "think": think,
                "timeout": timeout,
            }
        )
        if not self._messages:
            raise AssertionError("ollama was called more times than scripted")
        return {"message": self._messages.pop(0)}


def _cfg(tmp_path: Path, **overrides) -> agent.Config:
    cfg = agent.Config(
        prompt_path=ROOT / "docs" / "OLLAMA_AGENT_PROMPT.md",
        transcript_dir=tmp_path / "transcripts",
        timeout_s=30,
        max_steps=8,
        max_consecutive_errors=3,
        max_spray=3,
        preflight=False,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _run(tmp_path, ollama_messages, handler, **cfg_overrides):
    plane = FakePlane(handler)
    ollama = FakeOllama(ollama_messages)
    out = io.StringIO()
    result = agent.run_task(
        "do the task",
        _cfg(tmp_path, **cfg_overrides),
        plane=plane,
        ollama=ollama,
        stdout=out,
    )
    return result, plane, ollama, out.getvalue()


def _tool_call(name: str, arguments: dict | None):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "type": "function",
                "function": {"name": name, "arguments": arguments if arguments is not None else {}},
            }
        ],
    }


def _ok(_name, _args):
    return {
        "executed": True,
        "verdict": {"decision": "ALLOW", "code": "ALLOW"},
        "result": {"ok": True, "code": "READ", "data": "hello"},
    }


def test_tool_call_round_trip(tmp_path):
    result, plane, ollama, text = _run(
        tmp_path,
        [
            _tool_call("shell_read_file", {"path": "README.md"}),
            {"role": "assistant", "content": "README starts with hello\n\nVERIFIED\n- Tested: shell_read_file"},
        ],
        _ok,
    )
    assert result.reason == "answered"
    assert plane.calls == [("shell_read_file", {"path": "README.md"})]
    assert len(ollama.requests) == 2
    follow = ollama.requests[1]["messages"]
    assert follow[-2]["role"] == "assistant"
    assert follow[-2]["tool_calls"]
    assert follow[-1]["role"] == "tool"
    assert follow[-1]["tool_name"] == "shell_read_file"
    body = json.loads(follow[-1]["content"])
    assert body["result"]["data"] == "hello"
    exposed = [tool["function"]["name"] for tool in ollama.requests[0]["tools"]]
    assert "shell_read_file" in exposed
    assert "shell_exec" not in exposed
    assert "plane_call" not in exposed
    assert ollama.requests[0]["think"] is False
    assert "VERIFIED" in text
    assert result.transcript_path is not None
    assert result.transcript_path.is_file()
    rows = [
        json.loads(line)
        for line in result.transcript_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["kind"] == "start"
    assert rows[-1]["reason"] == "answered"


def test_unknown_tool_is_blocked_locally(tmp_path):
    result, plane, ollama, text = _run(
        tmp_path,
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"type": "function", "function": {"name": "shell_exec", "arguments": {"argv": ["id"]}}},
                    {
                        "type": "function",
                        "function": {
                            "name": "shell_read_file",
                            "arguments": {"path": "README.md"},
                        },
                    },
                ],
            },
            {"role": "assistant", "content": "read it"},
        ],
        _ok,
    )
    # shell_read_file is allowed; shell_exec must not appear in plane.calls.
    # The handler above is only reached for forwarded calls. shell_exec raises
    # inside FakePlane before the handler if it is forwarded.
    assert plane.calls == [("shell_read_file", {"path": "README.md"})]
    assert result.reason == "answered"
    tool_msgs = [m for m in ollama.requests[1]["messages"] if m["role"] == "tool"]
    blocked = json.loads(tool_msgs[0]["content"])
    assert blocked["code"] == "TOOL_NOT_EXPOSED"
    assert "shell_read_file" in blocked["valid_tools"]
    assert "shell_exec" not in blocked["valid_tools"]
    assert "Not forwarded" in blocked["detail"]
    assert "TOOL_NOT_EXPOSED" in text


def test_three_unknown_tools_stop_without_reaching_the_plane(tmp_path):
    def handler(name, _args):
        raise AssertionError(f"plane was called for {name}")

    calls = [
        {
            "type": "function",
            "function": {"name": f"nope_{i}", "arguments": {}},
        }
        for i in range(3)
    ]
    result, plane, ollama, _text = _run(
        tmp_path,
        [{"role": "assistant", "content": "", "tool_calls": calls}],
        handler,
    )
    assert plane.calls == []
    assert result.reason == "spray"
    assert len(ollama.requests) == 1


def test_operator_confirm_is_stripped_before_dispatch(tmp_path):
    result, plane, _ollama, text = _run(
        tmp_path,
        [
            _tool_call(
                "shell_read_file",
                {
                    "path": "README.md",
                    "operator_confirm": True,
                    "arguments_json": json.dumps(
                        {"path": "README.md", "operator_confirm": True, "nested": {"operator_confirm": 1}}
                    ),
                },
            ),
            {"role": "assistant", "content": "done"},
        ],
        _ok,
    )
    assert result.reason == "answered"
    assert len(plane.calls) == 1
    sent = plane.calls[0][1]
    assert "operator_confirm" not in sent
    assert sent["path"] == "README.md"
    inner = json.loads(sent["arguments_json"])
    assert "operator_confirm" not in inner
    assert "operator_confirm" not in inner["nested"]
    assert "stripped operator_confirm" in text


def test_human_confirm_stops_and_reports_the_request(tmp_path):
    def handler(_name, args):
        assert "operator_confirm" not in args
        return {
            "executed": True,
            "verdict": {"decision": "ALLOW", "code": "ALLOW"},
            "result": {
                "ok": False,
                "code": "HUMAN_CONFIRM_REQUIRED",
                "detail": "desktop.quit requires operator_confirm=true",
            },
        }

    result, plane, ollama, text = _run(
        tmp_path,
        [
            _tool_call(
                "shell_read_file",
                {"path": "README.md", "operator_confirm": True},
            ),
            {"role": "assistant", "content": "should not be requested"},
        ],
        handler,
    )
    assert result.reason == "confirm"
    assert len(ollama.requests) == 1
    assert len(plane.calls) == 1
    assert result.detail["arguments"]["operator_confirm"] is True
    assert "operator_confirm" not in result.detail["sent_arguments"]
    assert "HUMAN_CONFIRM_REQUIRED" in text
    assert "cannot set it" in text


def test_freeze_stops_the_loop(tmp_path):
    def handler(_name, _args):
        return {
            "executed": False,
            "verdict": {"decision": "DENY", "code": "FREEZE", "detail": "freeze file present"},
            "result": None,
        }

    result, plane, ollama, text = _run(
        tmp_path,
        [
            _tool_call("shell_read_file", {"path": "README.md"}),
            {"role": "assistant", "content": "should not be requested"},
        ],
        handler,
    )
    assert result.reason == "freeze"
    assert len(plane.calls) == 1
    assert len(ollama.requests) == 1
    assert "not retrying" in text


def test_deny_stops_the_loop(tmp_path):
    def handler(_name, _args):
        return {
            "executed": False,
            "verdict": {"decision": "DENY", "code": "PATH_DENIED", "detail": "outside roots"},
            "result": None,
        }

    result, _plane, ollama, _text = _run(
        tmp_path,
        [
            _tool_call("shell_read_file", {"path": "/etc/passwd"}),
            {"role": "assistant", "content": "nope"},
        ],
        handler,
    )
    assert result.reason == "deny"
    assert len(ollama.requests) == 1


def test_status_report_of_freeze_is_not_a_denial(tmp_path):
    def handler(_name, _args):
        return {
            "executed": True,
            "verdict": {"decision": "ALLOW", "code": "ALLOW"},
            "result": {
                "ok": True,
                "freeze": {
                    "engaged": True,
                    "detail": "FREEZE engaged — only allowed_while_frozen tools will execute",
                },
            },
        }

    result, _plane, ollama, _text = _run(
        tmp_path,
        [
            _tool_call("plane_status", {}),
            {"role": "assistant", "content": "freeze is engaged"},
        ],
        handler,
    )
    assert result.reason == "answered"
    assert len(ollama.requests) == 2
    assert result.answer == "freeze is engaged"


def test_max_steps_is_enforced(tmp_path):
    result, plane, ollama, _text = _run(
        tmp_path,
        [_tool_call("plane_status", {}) for _ in range(5)],
        _ok,
        max_steps=2,
    )
    assert result.reason == "max_steps"
    assert len(ollama.requests) == 2
    assert len(plane.calls) == 2


def test_timeout_stops_before_the_model(tmp_path):
    result, plane, ollama, _text = _run(
        tmp_path,
        [_tool_call("plane_status", {})],
        _ok,
        timeout_s=0,
    )
    assert result.reason == "timeout"
    assert ollama.requests == []
    assert plane.calls == []


def test_consecutive_errors_stop(tmp_path):
    def handler(_name, _args):
        return {
            "executed": True,
            "verdict": {"decision": "ALLOW"},
            "result": {"ok": False, "code": "NOT_FOUND"},
        }

    result, plane, ollama, _text = _run(
        tmp_path,
        [_tool_call("shell_read_file", {"path": "missing"}) for _ in range(4)],
        handler,
        max_consecutive_errors=2,
    )
    assert result.reason == "max_errors"
    assert len(ollama.requests) == 2
    assert len(plane.calls) == 2


def test_successful_tool_resets_consecutive_errors(tmp_path):
    calls = {"n": 0}

    def handler(_name, _args):
        calls["n"] += 1
        if calls["n"] == 2:
            return _ok(_name, _args)
        return {
            "executed": True,
            "verdict": {"decision": "ALLOW"},
            "result": {"ok": False, "code": "NOT_FOUND"},
        }

    result, _plane, ollama, _text = _run(
        tmp_path,
        [
            _tool_call("shell_read_file", {"path": "a"}),
            _tool_call("shell_read_file", {"path": "b"}),
            _tool_call("shell_read_file", {"path": "c"}),
            {"role": "assistant", "content": "done"},
        ],
        handler,
        max_consecutive_errors=2,
    )
    assert result.reason == "answered"
    assert len(ollama.requests) == 4


def test_dry_run_does_not_call_the_model(tmp_path):
    result, plane, ollama, text = _run(
        tmp_path,
        [{"role": "assistant", "content": "should not be asked"}],
        _ok,
        dry_run=True,
    )
    assert result.reason == "dry_run"
    assert ollama.requests == []
    assert plane.calls == []
    assert "dry-run (no model call)" in text
    assert "VERIFIED" in text
    prompt = text.split("system prompt:", 1)[1]
    assert "shell_exec" not in prompt
    assert "plane_call" not in prompt
    assert "shell_read_file" in prompt


def test_rules_file_is_appended_to_the_prompt(tmp_path):
    rules = tmp_path / "AGENTS.md"
    rules.write_text("OPERATOR-PROTOCOL-MARKER facts over narrative\n", encoding="utf-8")
    result, _plane, ollama, _text = _run(
        tmp_path,
        [{"role": "assistant", "content": "ok"}],
        _ok,
        rules=(rules,),
    )
    assert result.reason == "answered"
    system = ollama.requests[0]["messages"][0]["content"]
    assert "OPERATOR-PROTOCOL-MARKER" in system
    assert "Never supply `operator_confirm`" in system


def test_allowlist_uses_only_advertised_names():
    exposed, missing = agent.select_tools(
        [_spec("shell_stat")],
        ["shell.stat", "desktop.status", "shell.exec"],
    )
    assert [tool.name for tool in exposed] == ["shell_stat"]
    assert missing == ["desktop.status", "shell.exec"]


def test_default_allowlist_excludes_high_blast_names():
    names = set(agent.DEFAULT_TOOL_CANDIDATES)
    names |= {name.replace(".", "_") for name in agent.DEFAULT_TOOL_CANDIDATES}
    for banned in (
        "shell.exec",
        "shell_exec",
        "plane.call",
        "plane_call",
        "shell.write_file",
        "browser.x_post",
        "desktop.quit",
        "plane.unfreeze",
    ):
        assert banned not in names


def test_default_candidates_are_real_server_tools():
    text = (ROOT / "mcp_server.py").read_text(encoding="utf-8")
    for name in agent.DEFAULT_TOOL_CANDIDATES:
        assert f"def {name.replace('.', '_')}" in text


def test_launch_uses_stdio_actor_flag():
    command, args = agent.mcp_launch_command(agent.Config())
    assert args[-2:] == ["--actor", "ollama"]
    assert args[0].endswith("mcp_server.py")
    assert command


def test_ollama_is_not_a_builtin_actor(tmp_path, capsys):
    assert "ollama" not in DEFAULT_ROSTER
    assert DEFAULT_ROSTER == ("grok", "claude", "codex")
    with pytest.raises(SystemExit) as exc:
        resolve_stdio_actor(["--actor", "ollama"], {}, receipts_dir=tmp_path)
    assert exc.value.code == 2
    assert "ollama" in capsys.readouterr().err
    (tmp_path / "stdio-actors").write_text("# local harness\nollama\n", encoding="utf-8")
    assert resolve_stdio_actor(["--actor", "ollama"], {}, receipts_dir=tmp_path) == "ollama"


def test_mcp_client_is_not_imported_at_module_level():
    text = (ROOT / "ollama_agent.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("import ") or line.startswith("from "):
            assert "mcp" not in line.split()


def test_chat_body_disables_thinking_and_streaming():
    body = agent.chat_request_body(
        model="qwen3:8b",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "plane_status"}}],
        think=False,
    )
    assert body["think"] is False
    assert body["stream"] is False
    assert body["model"] == "qwen3:8b"
    assert body["tools"][0]["function"]["name"] == "plane_status"


def test_strip_operator_confirm_is_case_insensitive():
    cleaned, found = agent.strip_operator_confirm(
        {"Operator_Confirm": "true", "path": "a", "inner": [{"operator_confirm": False}]}
    )
    assert found is True
    assert cleaned == {"path": "a", "inner": [{}]}


def test_prompt_requires_verified_close_and_freeze_stop():
    text = (ROOT / "docs" / "OLLAMA_AGENT_PROMPT.md").read_text(encoding="utf-8")
    for needle in (
        "VERIFIED",
        "Tested:",
        "Results:",
        "Live-proof:",
        "Gaps:",
        "FREEZE",
        "operator_confirm",
    ):
        assert needle in text


def test_docs_tell_the_operator_to_add_the_actor():
    text = (ROOT / "docs" / "OLLAMA_AGENT.md").read_text(encoding="utf-8")
    assert "ollama pull qwen3:8b" in text
    assert "receipts/stdio-actors" in text
    assert "printf 'ollama\\n'" in text
    assert "ollama_agent.py --dry-run" in text
    assert "Honest ceiling" in text
    assert "not a security boundary" in text.lower() or "not a security boundary" in text


def test_parse_config_defaults():
    cfg = agent.parse_config(["read the status"])
    assert cfg.task == "read the status"
    assert cfg.model == "qwen3:8b"
    assert cfg.host == "http://127.0.0.1:11434"
    assert cfg.max_steps == 20
    assert cfg.timeout_s == 180
    assert cfg.dry_run is False
    assert cfg.think is False
    assert cfg.preflight is True
    assert agent.parse_config(["task", "--no-preflight"]).preflight is False
    widened = agent.parse_config(["task", "--tools", "shell_exec,plane_status", "--max-steps", "2"])
    assert "shell_exec" in widened.tool_candidates
    assert widened.max_steps == 2


def test_harness_closeout_uses_only_dispatched_calls():
    text = agent.harness_closeout(
        [
            {
                "kind": "preflight",
                "classification": "ok",
                "actor": "ollama",
                "freeze_engaged": False,
                "result": {"verdict": {"code": "OK"}, "result": {"ok": True}},
            },
            {
                "kind": "tool",
                "step": 1,
                "name": "shell_read_file",
                "forwarded": True,
                "classification": "ok",
                "result": {"result": {"code": "READ"}},
            },
            {
                "kind": "tool",
                "step": 1,
                "name": "shell_exec",
                "forwarded": False,
                "classification": "spray",
                "result": {"code": "TOOL_NOT_EXPOSED"},
            },
        ],
        reason="answered",
        task="read the file",
        transcript_path=Path("/tmp/run.jsonl"),
    )
    assert "HARNESS VERIFIED" in text
    assert "preflight plane_status" in text
    assert "step 1 shell_read_file" in text
    assert "code=READ" in text
    assert "shell_exec not forwarded code=TOOL_NOT_EXPOSED" in text
    assert "shell_exec was not sent to the plane" in text
    assert "model prose was not re-checked" in text
    assert "actor=ollama" in text


def test_round_trip_prints_harness_closeout(tmp_path):
    result, _plane, _ollama, text = _run(
        tmp_path,
        [
            _tool_call("shell_read_file", {"path": "README.md"}),
            {"role": "assistant", "content": "done"},
        ],
        _ok,
    )
    assert result.reason == "answered"
    assert result.closeout.startswith("HARNESS VERIFIED")
    assert "step 1 shell_read_file" in result.closeout
    assert "code=READ" in result.closeout
    assert "HARNESS VERIFIED" in text
    assert result.closeout in text


def test_dry_run_closeout_records_no_calls(tmp_path):
    result, plane, ollama, text = _run(
        tmp_path,
        [{"role": "assistant", "content": "no"}],
        _ok,
        dry_run=True,
    )
    assert result.reason == "dry_run"
    assert plane.calls == []
    assert ollama.requests == []
    assert "dry-run did not call the model or the plane" in result.closeout
    assert "HARNESS VERIFIED" in text


def test_freeze_closeout_records_the_stop(tmp_path):
    def handler(_name, _args):
        return {
            "executed": False,
            "verdict": {"decision": "DENY", "code": "FREEZE", "detail": "frozen"},
            "result": None,
        }

    result, _plane, _ollama, _text = _run(
        tmp_path,
        [_tool_call("shell_read_file", {"path": "README.md"})],
        handler,
    )
    assert result.reason == "freeze"
    assert "code=FREEZE" in result.closeout
    assert "stopped: freeze" in result.closeout
    assert "model prose was not re-checked" not in result.closeout


def test_exit_codes():
    assert agent.exit_code(agent.RunResult("answered")) == 0
    assert agent.exit_code(agent.RunResult("freeze")) == 2
    assert agent.exit_code(agent.RunResult("deny")) == 3
    assert agent.exit_code(agent.RunResult("confirm")) == 4
    assert agent.exit_code(agent.RunResult("max_steps")) == 6


def test_content_tool_call_is_dispatched_for_an_exact_name(tmp_path):
    result, plane, ollama, text = _run(
        tmp_path,
        [
            {
                "role": "assistant",
                "content": (
                    '<tool_call>\n{"name": "shell_read_file", "arguments": {"path": "README.md"}}\n</tool_call>'
                ),
            },
            {"role": "assistant", "content": "read it"},
        ],
        _ok,
    )
    assert result.reason == "answered"
    assert plane.calls == [("shell_read_file", {"path": "README.md"})]
    assert ollama.requests[1]["messages"][-1]["role"] == "tool"
    sources = [row.get("tool_call_source") for row in result.events if row.get("kind") == "model"]
    assert sources[0] == "content"


def test_qwen_xml_tool_call_is_dispatched(tmp_path):
    content = (
        "<tool_call>\n"
        "<function=shell_read_file>\n"
        "<parameter=path>\nREADME.md\n</parameter>\n"
        "</function>\n"
        "</tool_call>"
    )
    result, plane, _ollama, _text = _run(
        tmp_path,
        [
            {"role": "assistant", "content": content},
            {"role": "assistant", "content": "done"},
        ],
        _ok,
    )
    assert result.reason == "answered"
    assert plane.calls == [("shell_read_file", {"path": "README.md"})]


def test_prose_that_names_a_tool_is_not_a_call(tmp_path):
    result, plane, ollama, _text = _run(
        tmp_path,
        [{"role": "assistant", "content": "I would call plane_status, but this sentence is the answer."}],
        _ok,
    )
    assert result.reason == "answered"
    assert plane.calls == []
    assert len(ollama.requests) == 1


def test_content_unknown_tool_is_not_forwarded(tmp_path):
    result, plane, ollama, _text = _run(
        tmp_path,
        [
            {
                "role": "assistant",
                "content": '<tool_call>{"name": "shell_exec", "arguments": {"argv": ["id"]}}</tool_call>',
            },
            {"role": "assistant", "content": "stopped asking"},
        ],
        _ok,
    )
    assert result.reason == "answered"
    assert plane.calls == []
    blocked = json.loads(
        [m for m in ollama.requests[1]["messages"] if m["role"] == "tool"][0]["content"]
    )
    assert blocked["code"] == "TOOL_NOT_EXPOSED"
    dotted = agent.parse_content_tool_calls(
        '<tool_call>{"name": "shell.read_file", "arguments": {"path": "a"}}</tool_call>'
    )
    assert dotted == [{"name": "shell.read_file", "arguments": {"path": "a"}}]


def test_dotted_content_name_is_a_local_miss(tmp_path):
    result, plane, _ollama, _text = _run(
        tmp_path,
        [
            {
                "role": "assistant",
                "content": '<tool_call>{"name": "shell.read_file", "arguments": {"path": "README.md"}}</tool_call>',
            },
            {"role": "assistant", "content": "ok"},
        ],
        _ok,
    )
    assert result.reason == "answered"
    assert plane.calls == []


def test_preflight_records_actor_before_the_model(tmp_path):
    def handler(name, args):
        if name == "plane_status" and not args:
            return {
                "executed": True,
                "verdict": {"decision": "ALLOW", "code": "OK"},
                "result": {
                    "ok": True,
                    "actors": {"current": "ollama"},
                    "freeze": {"engaged": True, "detail": "FREEZE engaged — only allowed_while_frozen tools will execute"},
                },
            }
        return _ok(name, args)

    result, plane, ollama, text = _run(
        tmp_path,
        [{"role": "assistant", "content": "freeze is engaged"}],
        handler,
        preflight=True,
    )
    assert result.reason == "answered"
    assert plane.calls[0] == ("plane_status", {})
    assert len(ollama.requests) == 1
    assert "preflight plane_status → ok actor=ollama freeze=engaged" in text
    assert any(row.get("kind") == "preflight" and row.get("freeze_engaged") is True for row in result.events)


def test_preflight_deny_stops_before_the_model(tmp_path):
    def handler(_name, _args):
        return {
            "executed": False,
            "verdict": {"decision": "DENY", "code": "FREEZE", "detail": "frozen"},
            "result": None,
        }

    result, plane, ollama, text = _run(
        tmp_path,
        [{"role": "assistant", "content": "should not be asked"}],
        handler,
        preflight=True,
    )
    assert result.reason == "freeze"
    assert plane.calls == [("plane_status", {})]
    assert ollama.requests == []
    assert "not starting the model" in text


def test_preflight_failure_stops_before_the_model(tmp_path):
    def handler(_name, _args):
        return {"ok": False, "code": "MCP_ERROR", "detail": "session dropped"}

    result, _plane, ollama, _text = _run(
        tmp_path,
        [{"role": "assistant", "content": "should not be asked"}],
        handler,
        preflight=True,
    )
    assert result.reason == "preflight"
    assert ollama.requests == []
