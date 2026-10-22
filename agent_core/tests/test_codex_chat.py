"""Offline protocol tests: no Codex process, login, inference, or network."""

import json
from pathlib import Path
import queue
import signal
import threading

import pytest

from agent_core.llm.codex_chat import CodexChatBackend


class Output:
    def __init__(self):
        self.lines = queue.Queue()

    def emit(self, message):
        self.lines.put((json.dumps(message) + "\n").encode())

    def readline(self, limit):
        return self.lines.get()

    def close(self):
        self.lines.put(b"")


class Input:
    def __init__(self, owner):
        self.owner = owner

    def write(self, data):
        message = json.loads(data)
        self.owner.sent.append(message)
        self.owner.on_message(message)

    def flush(self):
        pass

    def close(self):
        pass


class Process:
    pid = 987654

    def __init__(self, events=(), stall=False, rpc_error=False):
        self.stdout = Output()
        self.stdin = Input(self)
        self.sent = []
        self.events = events
        self.stall = stall
        self.rpc_error = rpc_error
        self.signals = []
        self.waited = False
        self.args = None

    def spawn(self, argv, **kwargs):
        self.args = (argv, kwargs)
        return self

    def on_message(self, msg):
        method = msg.get("method")
        if method == "initialize":
            if not self.stall:
                self.stdout.emit({"id": msg["id"], "result": {}})
        elif method == "thread/start":
            if self.rpc_error:
                self.stdout.emit({"id": msg["id"], "error": {
                    "code": -1, "message": "SECRET in upstream diagnostic"}})
            else:
                self.stdout.emit({"id": msg["id"], "result": {"thread": {"id": "t"}}})
        elif method == "turn/start":
            self.stdout.emit({"id": msg["id"], "result": {"turn": {"id": "u"}}})
            for event in self.events:
                self.stdout.emit(event)
            self.stdout.lines.put(b"")

    def killpg(self, pid, sig):
        assert pid == self.pid
        self.signals.append(sig)
        self.stdout.close()

    def wait(self, timeout):
        self.waited = True
        return -15


def item(text, phase=None, ident="a", thread="t"):
    return {"method": "item/completed", "params": {"threadId": thread,
        "turnId": "u", "item": {"id": ident, "type": "agentMessage",
                                  "text": text, "phase": phase}}}


def done(status="completed", items=None):
    return {"method": "turn/completed", "params": {"threadId": "t", "turn": {
        "id": "u", "status": status, "items": items or []}}}


def backend(tmp_path, proc, **kwargs):
    return CodexChatBackend(config_path=tmp_path / "config.toml",
                            popen_factory=proc.spawn, killpg=proc.killpg, **kwargs)


MESSAGES = [{"role": "system", "content": "Polski kontekst Marii"},
            {"role": "user", "content": "pierwsze"},
            {"role": "assistant", "content": "poprzednia odpowiedz"},
            {"role": "user", "content": "kolejne"}]


def test_final_only_context_ephemeral_tools_and_cleanup(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[mcp_servers.example]\ncommand="DO_NOT_RUN"\n'
        '[mcp_servers.second_server]\nurl="https://invalid.test"\n')
    proc = Process([item("progress", "commentary"),
                    item("ignore other thread", "final_answer", thread="other"),
                    item("odpowiedz", "final_answer", ident="b"), done()])
    api = backend(tmp_path, proc)
    assert api.chat(MESSAGES, model="cannot override", sandbox="danger-full-access") == "odpowiedz"
    requests = {m["method"]: m for m in proc.sent if "method" in m}
    start = requests["thread/start"]["params"]
    assert start["ephemeral"] is True
    assert start["sandbox"] == "read-only" and start["approvalPolicy"] == "never"
    assert start["model"] == "gpt-6.1-sol"
    assert MESSAGES[0]["content"] in start["developerInstructions"]
    assert "No execution tools are available" in start["developerInstructions"]
    assert "background reasoning is currently paused" in start["developerInstructions"]
    turn = requests["turn/start"]["params"]
    assert turn["effort"] == "low"
    transcript = json.loads(turn["input"][0]["text"].split("\n", 1)[1])
    assert transcript == MESSAGES[1:]
    argv, options = proc.args
    overrides = dict(arg.split("=", 1) for i, arg in enumerate(argv) if i and argv[i-1] == "-c")
    assert overrides['mcp_servers.example.enabled'] == "false"
    assert overrides['mcp_servers.second_server.enabled'] == "false"
    for key in ("features.shell_tool", "features.hooks", "features.apps",
                "features.plugins", "features.multi_agent", "features.computer_use",
                "features.view_image"):
        assert overrides[key] == "false"
    assert overrides["web_search"] == '"disabled"'
    assert options["start_new_session"] is True
    assert "env" not in options and "shell" not in options
    assert options["cwd"].startswith("/tmp/maria-codex-chat-")
    assert not Path(options["cwd"]).exists()
    assert proc.waited and proc.signals == [signal.SIGTERM, signal.SIGKILL]


@pytest.mark.parametrize("status", ["failed", "interrupted", "inProgress"])
def test_failure_never_returns_partial_answer(tmp_path, status):
    proc = Process([item("partial", "final_answer"), done(status)])
    with pytest.raises(RuntimeError, match="did not complete"):
        backend(tmp_path, proc).chat(MESSAGES)
    assert proc.waited


def test_rpc_error_is_explicit_and_does_not_echo_upstream_secrets(tmp_path):
    proc = Process(rpc_error=True)
    with pytest.raises(RuntimeError, match="RPC failed") as error:
        backend(tmp_path, proc).chat(MESSAGES)
    assert "SECRET" not in str(error.value)


def test_server_requests_are_denied_never_executed(tmp_path):
    proc = Process([
        {"id": 90, "method": "item/commandExecution/requestApproval", "params": {}},
        {"id": 91, "method": "item/fileChange/requestApproval", "params": {}},
        {"id": 92, "method": "item/tool/call", "params": {"tool": "run"}},
        item("safe", "final_answer"), done()])
    assert backend(tmp_path, proc).chat(MESSAGES) == "safe"
    responses = {m["id"]: m for m in proc.sent if "method" not in m and "id" in m}
    assert responses[90]["result"] == {"decision": "decline"}
    assert responses[91]["result"] == {"decision": "decline"}
    assert responses[92]["error"]["code"] == -32601


def test_timeout_terminates_process_group_and_reader(tmp_path):
    proc = Process(stall=True)
    with pytest.raises(TimeoutError):
        backend(tmp_path, proc, timeout_s=0.02).chat(MESSAGES)
    assert proc.waited and signal.SIGKILL in proc.signals
    assert not any(t.name == "maria-codex-chat" for t in threading.enumerate())


@pytest.mark.parametrize("events", [[item("only progress", "commentary"), done()],
                                   [item("incomplete", "final_answer")]])
def test_missing_final_or_completion_is_error(tmp_path, events):
    with pytest.raises(RuntimeError):
        backend(tmp_path, Process(events)).chat(MESSAGES)


@pytest.mark.parametrize("text,valid", [('{"ok":true}', True), ('[]', False),
                                      ('```json\n{}\n```', False)])
def test_force_json_validates_result(tmp_path, text, valid):
    proc = Process([item(text), done()])
    if valid:
        assert backend(tmp_path, proc).chat(MESSAGES, force_json=True) == text
    else:
        with pytest.raises(RuntimeError, match="JSON"):
            backend(tmp_path, proc).chat(MESSAGES, force_json=True)


def test_malformed_config_fails_before_spawn(tmp_path):
    (tmp_path / "config.toml").write_text('[mcp_servers broken')
    proc = Process()
    with pytest.raises(RuntimeError, match="configuration"):
        backend(tmp_path, proc).chat(MESSAGES)
    assert proc.args is None


def test_no_history_retained_between_calls(tmp_path):
    processes = []
    def spawn(argv, **kwargs):
        proc = Process([item("ok"), done()])
        processes.append(proc)
        return proc.spawn(argv, **kwargs)
    api = CodexChatBackend(config_path=tmp_path / "none", popen_factory=spawn,
                          killpg=lambda pid, sig: None)
    api.chat(MESSAGES)
    api.chat([{"role": "user", "content": "fresh"}])
    turn = next(m for m in processes[1].sent if m.get("method") == "turn/start")
    assert "pierwsze" not in turn["params"]["input"][0]["text"]
    assert len(processes) == 2


@pytest.mark.parametrize("event", [
    {"method": "item/started", "params": {"threadId": "t", "item": {
        "type": "commandExecution", "command": "DO_NOT_RUN"}}},
    {"method": "item/started", "params": {"threadId": "t", "item": {
        "type": "mcpToolCall"}}},
    {"method": "hook/started", "params": {}},
    done(items=[{"type": "fileChange"}]),
])
def test_unexpected_tool_or_hook_fails_closed(tmp_path, event):
    proc = Process([event, item("do not return", "final_answer"), done()])
    with pytest.raises(RuntimeError, match="unexpectedly"):
        backend(tmp_path, proc).chat(MESSAGES)
    assert proc.waited and signal.SIGKILL in proc.signals


def test_unaddressable_mcp_identifier_fails_before_spawn(tmp_path):
    (tmp_path / "config.toml").write_text('[mcp_servers."quoted.server"]\ncommand="none"')
    proc = Process()
    with pytest.raises(RuntimeError, match="MCP identifier"):
        backend(tmp_path, proc).chat(MESSAGES)
    assert proc.args is None
