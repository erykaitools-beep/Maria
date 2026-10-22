"""Opt-in dynamic tools: fake stdio/session, no model/network/process."""
from agent_core.tests.spec_helpers import specced
from agent_core.introspection.query_router import OperationalQueryRouter
from agent_core.introspection.evidence_collector import EvidenceCollector
from agent_core.introspection.response_builder import ResponseBuilder
import json
import signal
import threading

import pytest

from agent_core.llm.codex_chat import CodexChatBackend
from agent_core.tests.test_codex_chat import Process, MESSAGES, item, done


SPEC = {"type": "function", "name": "kritaqo_projects", "description": "Allowed projects",
        "inputSchema": {"type": "object", "properties": {}}}


class Session:
    specs = [SPEC]
    instructions = "Use only selected Kritaqo scope; accepted is not completed."

    def __init__(self):
        self.calls = []
        self.closed = threading.Event()
        self.result = {"success": True, "projects": [{"id": "allowed"}]}

    def call(self, name, arguments):
        assert not self.closed.is_set()
        self.calls.append((name, arguments))
        return self.result

    def close(self):
        self.closed.set()


class Provider:
    def __init__(self, session):
        self.session = session
        self.calls = []

    def for_turn(self, latest, interaction_id):
        self.calls.append((latest, interaction_id))
        return self.session


def call(ident=90, call_id="c1", name="kritaqo_projects", arguments=None,
         thread="t", turn="u", **extra):
    return {"id": ident, "method": "item/tool/call", "params": {
        "threadId": thread, "turnId": turn, "callId": call_id, "tool": name,
        "arguments": {} if arguments is None else arguments, **extra}}


def dynamic(method="item/started", tool="kritaqo_projects", thread="t", turn="u"):
    return {"method": method, "params": {"threadId": thread, "turnId": turn,
        "item": {"id": "c1", "type": "dynamicToolCall", "tool": tool,
                 "arguments": {}, "status": "inProgress"}}}


class ToolProcess(Process):
    def __init__(self, events=(), early=False, **kwargs):
        super().__init__(events=events, **kwargs)
        self.early = early

    def on_message(self, msg):
        if msg.get("method") == "turn/start" and self.early:
            for event in self.events:
                self.stdout.emit(event)
            self.stdout.emit({"id": msg["id"], "result": {"turn": {"id": "u"}}})
            self.stdout.emit(item("Finished", "final_answer"))
            self.stdout.emit(done())
            self.stdout.lines.put(b"")
        else:
            super().on_message(msg)


def backend(tmp_path, proc, provider, **kwargs):
    return CodexChatBackend(config_path=tmp_path / "no-config", tool_provider=provider,
                            popen_factory=proc.spawn, killpg=proc.killpg, **kwargs)


def response(proc, ident):
    return next(m for m in proc.sent if m.get("id") == ident and "method" not in m)


def events(*extra):
    return [*extra, item("Finished", "final_answer"), done()]


def test_opt_in_schema_response_scope_and_builtins(tmp_path):
    s = Session(); provider = Provider(s)
    proc = ToolProcess(events(dynamic(), call(), dynamic("item/completed")))
    api = backend(tmp_path, proc, provider)
    assert api.tool_provider is provider
    with pytest.raises(AttributeError):
        api.tool_provider = None
    assert api.chat(MESSAGES, interaction_id="trusted-id") == "Finished"
    assert provider.calls == [("kolejne", "trusted-id")]
    sent = {m["method"]: m["params"] for m in proc.sent if "method" in m}
    assert sent["initialize"]["capabilities"] == {"experimentalApi": True}
    assert sent["thread/start"]["dynamicTools"] == [SPEC]
    assert s.instructions in sent["thread/start"]["developerInstructions"]
    assert "No execution tools are available" not in sent["thread/start"]["developerInstructions"]
    assert sent["thread/start"]["sandbox"] == "read-only"
    assert sent["thread/start"]["approvalPolicy"] == "never"
    assert response(proc, 90)["result"] == {"contentItems": [{"type": "inputText", "text": json.dumps(s.result, ensure_ascii=False)}], "success": True}
    assert s.calls == [("kritaqo_projects", {})] and s.closed.is_set()
    argv = proc.args[0]
    overrides = dict(arg.split("=", 1) for i, arg in enumerate(argv) if i and argv[i-1] == "-c")
    assert overrides["features.code_mode_host"] == "true"
    for name in ["shell_tool", "unified_exec", "code_mode", "hooks", "multi_agent_v2"]:
        assert overrides["features." + name] == "false"


@pytest.mark.parametrize("kwargs", [{}, {"interaction_id": ""}, {"interaction_id": " "},
    {"interaction_id": 42}, {"force_json": True, "interaction_id": "trusted"}])
def test_missing_trusted_interaction_or_structured_calls_keep_tools_off(tmp_path, kwargs):
    s = Session(); provider = Provider(s); proc = ToolProcess([item('{"ok":true}'), done()])
    assert backend(tmp_path, proc, provider).chat(MESSAGES, **kwargs) == '{"ok":true}'
    assert provider.calls == [] and s.calls == []
    start = next(m["params"] for m in proc.sent if m.get("method") == "thread/start")
    assert "dynamicTools" not in start and "No execution tools are available" in start["developerInstructions"]
    argv = proc.args[0]
    overrides = dict(arg.split("=", 1) for i, arg in enumerate(argv) if i and argv[i-1] == "-c")
    assert overrides["features.code_mode_host"] == "false"


def test_provider_can_decline_tools(tmp_path):
    provider = Provider(None); proc = ToolProcess([item("Text only"), done()])
    assert backend(tmp_path, proc, provider).chat(MESSAGES, interaction_id="trusted") == "Text only"
    assert provider.calls == [("kolejne", "trusted")]
    assert "dynamicTools" not in next(m["params"] for m in proc.sent if m.get("method") == "thread/start")
    assert "features.code_mode_host=false" in proc.args[0]


@pytest.mark.parametrize("tool_request", [call(thread="other"), call(turn="other"), call(name="shell"),
    call(arguments="{}"), call(arguments=[]), call(name=["kritaqo_projects"]),
    call(namespace="shell"), call(call_id=""), call(call_id=None)])
def test_invalid_or_unscoped_requests_never_dispatch(tmp_path, tool_request):
    s = Session(); proc = ToolProcess(events(tool_request))
    assert backend(tmp_path, proc, Provider(s)).chat(MESSAGES, interaction_id="trusted") == "Finished"
    assert s.calls == [] and response(proc, 90)["result"]["success"] is False


def test_duplicate_call_id_immutable_input_and_result(tmp_path):
    s = Session(); proc = ToolProcess(events(
        call(arguments={"b": 2, "a": 1}), call(91, arguments={"a": 1, "b": 2}),
        call(92, arguments={"a": "changed"}), call(93, name="not_allowed")))
    backend(tmp_path, proc, Provider(s)).chat(MESSAGES, interaction_id="trusted")
    assert len(s.calls) == 1
    assert response(proc, 90)["result"] == response(proc, 91)["result"]
    assert response(proc, 92)["result"]["success"] is False
    assert response(proc, 93)["result"]["success"] is False


def test_eight_unique_dispatch_limit(tmp_path):
    s = Session(); proc = ToolProcess(events(*[call(90+i, "c"+str(i)) for i in range(9)]))
    backend(tmp_path, proc, Provider(s)).chat(MESSAGES, interaction_id="trusted")
    assert len(s.calls) == 8 and response(proc, 98)["result"]["success"] is False


@pytest.mark.parametrize("event", [dynamic(tool="shell"), dynamic(thread="other"), dynamic(turn="other"),
    {"method": "item/started", "params": {"threadId": "t", "turnId": "u", "item": {"type": "commandExecution"}}},
    {"method": "hook/started", "params": {}}])
def test_dynamic_notifications_dont_allow_other_operations(tmp_path, event):
    s = Session(); proc = ToolProcess(events(event))
    with pytest.raises(RuntimeError, match="unexpectedly"):
        backend(tmp_path, proc, Provider(s)).chat(MESSAGES, interaction_id="trusted")
    assert s.calls == [] and s.closed.is_set()


def test_requests_before_turn_response_wait_for_confirmed_scope(tmp_path):
    s = Session(); proc = ToolProcess([dynamic(), call()], early=True)
    assert backend(tmp_path, proc, Provider(s)).chat(MESSAGES, interaction_id="trusted") == "Finished"
    assert len(s.calls) == 1


def test_foreign_final_and_completion_cannot_finish_current_turn(tmp_path):
    wrong = done(); wrong["params"]["turn"]["id"] = "foreign"
    wrong_item = item("Wrong answer", "final_answer"); wrong_item["params"]["turnId"] = "foreign"
    s = Session(); proc = ToolProcess(events(wrong_item, wrong, call()))
    assert backend(tmp_path, proc, Provider(s)).chat(MESSAGES, interaction_id="trusted") == "Finished"
    assert len(s.calls) == 1


def test_tool_exception_is_private_and_cached_without_repeat(tmp_path):
    class Failing(Session):
        def call(self, name, arguments):
            self.calls.append((name, arguments)); raise TimeoutError("SECRET diagnostic token")
    s = Failing(); proc = ToolProcess(events(call(), call(91)))
    assert backend(tmp_path, proc, Provider(s)).chat(MESSAGES, interaction_id="trusted") == "Finished"
    assert len(s.calls) == 1 and response(proc, 90)["result"] == response(proc, 91)["result"]
    assert response(proc, 90)["result"]["success"] is False and "SECRET" not in json.dumps(proc.sent)


def test_timeout_closes_session_before_cleanup_and_drops_late_dispatch(tmp_path):
    class Blocking(Session):
        def __init__(self):
            super().__init__(); self.entered = threading.Event(); self.exited = threading.Event()
        def call(self, name, arguments):
            self.calls.append((name, arguments)); self.entered.set()
            assert self.closed.wait(2), "close must interrupt a blocked tool"
            self.exited.set(); return {"success": True}
    s = Blocking(); proc = ToolProcess(events(call(), call(91, "second")))
    original_kill = proc.killpg
    def killpg(pid, sig):
        assert s.closed.is_set()
        original_kill(pid, sig)
    api = CodexChatBackend(config_path=tmp_path/'none', tool_provider=Provider(s),
                           popen_factory=proc.spawn, killpg=killpg, timeout_s=0.05)
    with pytest.raises(TimeoutError):
        api.chat(MESSAGES, interaction_id="trusted")
    assert s.entered.is_set() and s.exited.is_set() and len(s.calls) == 1
    assert not any(m.get("id") in (90, 91) and "method" not in m for m in proc.sent)
    assert signal.SIGKILL in proc.signals
    assert not any(t.name == "maria-codex-chat" for t in threading.enumerate())


def test_invalid_specs_and_spawn_error_close_session(tmp_path):
    s = Session(); s.specs = [{**SPEC, "type": "namespace"}]; proc = ToolProcess()
    with pytest.raises(RuntimeError, match="session"):
        backend(tmp_path, proc, Provider(s)).chat(MESSAGES, interaction_id="trusted")
    assert s.closed.is_set() and proc.args is None
    s = Session()
    def fail(*args, **kwargs):
        raise OSError("SECRET")
    api = CodexChatBackend(config_path=tmp_path/'none', tool_provider=Provider(s), popen_factory=fail)
    with pytest.raises(RuntimeError, match="Cannot start"):
        api.chat(MESSAGES, interaction_id="trusted")
    assert s.closed.is_set()


class ContextProvider(Provider):
    def __init__(self, session):
        super().__init__(session)
        self.context = object()
        self.prepared = []

    def prepare_turn(self, text, interaction_id, conversation_id):
        self.prepared.append((text, interaction_id, conversation_id))
        return self.context

    def accepts_prompt(self, text):
        return False  # This follow-up has no explicit project keyword.

    def accepts_context(self, text, interaction_id, context):
        return text == "Dodaj plakat" and interaction_id == "trusted" and context is self.context

    def for_turn(self, text, interaction_id, *, tool_context=None):
        assert self.accepts_context(text, interaction_id, tool_context)
        self.calls.append((text, interaction_id, tool_context))
        return self.session


def test_context_identity_flows_from_prepare_through_brain_to_exact_session(tmp_path):
    from agent_core.llm.chat_backend import prepare_interactive_tools, interactive_tools_match
    from agent_core.tests.test_codex_brain_integration import make_brain
    from unittest.mock import Mock, create_autospec

    s = Session(); provider = ContextProvider(s)
    proc = ToolProcess(events(call()))
    api = backend(tmp_path, proc, provider)
    context = prepare_interactive_tools(api, "Dodaj plakat", "trusted", "authenticated-socket")
    assert context is provider.context
    assert provider.prepared == [("Dodaj plakat", "trusted", "authenticated-socket")]
    assert interactive_tools_match(api, "Dodaj plakat", "trusted", tool_context=context)
    brain = make_brain(api)
    brain._query_router = Mock(spec=OperationalQueryRouter, side_effect=AssertionError("must bypass grounding"))
    brain._query_router.classify.side_effect = AssertionError("must bypass grounding")
    brain._request_context_provider = create_autospec(lambda prompt: None, side_effect=AssertionError("must bypass snapshot"))
    brain._evidence_collector = specced(EvidenceCollector); brain._response_builder = specced(ResponseBuilder)
    assert brain.think("Dodaj plakat", interaction_id="trusted", tool_context=context) == "Finished"
    assert provider.calls == [("Dodaj plakat", "trusted", context)]
    assert s.calls == [("kritaqo_projects", {})]
    brain._query_router.classify.assert_not_called()
    brain._request_context_provider.assert_not_called()


@pytest.mark.parametrize("kwargs", [
    {"interaction_id": "trusted", "tool_context": object()},
    {"interaction_id": "wrong", "tool_context": "valid"},
    {"tool_context": "valid"},
    {"interaction_id": "", "tool_context": "valid"},
    {"interaction_id": "trusted", "tool_context": "valid", "force_json": True},
])
def test_untrusted_or_noninteractive_context_never_opens_session(tmp_path, kwargs):
    from agent_core.llm.chat_backend import interactive_tools_match
    s = Session(); provider = ContextProvider(s)
    if kwargs.get("tool_context") == "valid":
        kwargs = {**kwargs, "tool_context": provider.context}
    proc = ToolProcess(events=[item("{}", "final_answer"), done()])
    api = backend(tmp_path, proc, provider)
    if not kwargs.get("force_json"):
        assert not interactive_tools_match(api, "Dodaj plakat", kwargs.get("interaction_id"),
                                           tool_context=kwargs["tool_context"])
    api.chat([{"role": "user", "content": "Dodaj plakat"}], **kwargs)
    assert provider.calls == []
    assert not any(m.get("params", {}).get("dynamicTools") for m in proc.sent)


def test_context_helper_legacy_and_oneshot_ollama_isolation():
    from types import SimpleNamespace
    from unittest.mock import Mock, create_autospec
    from agent_core.llm.chat_backend import prepare_interactive_tools, interactive_tools_match
    from agent_core.tests.test_codex_brain_integration import make_brain

    legacy = SimpleNamespace(tool_provider=SimpleNamespace(accepts_prompt=lambda text: True))
    assert prepare_interactive_tools(legacy, "Roblox", "trusted", "socket") is None
    assert interactive_tools_match(legacy, "Roblox", "trusted")
    assert not interactive_tools_match(legacy, "Roblox", "trusted", tool_context=object())
    api = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None); api.chat.return_value = "OK"
    brain = make_brain(api)
    context = object()
    brain._ask_once("Dodaj plakat", interaction_id="trusted", tool_context=context)
    assert "tool_context" not in api.chat.call_args.kwargs
    assert "interaction_id" not in api.chat.call_args.kwargs
    brain._chat([{"role": "user", "content": "Dodaj plakat"}], force_json=True,
                interaction_id="trusted", tool_context=context)
    assert "tool_context" not in api.chat.call_args.kwargs
    brain._chat([{"role": "user", "content": "Dodaj plakat"}], tool_context=context)
    assert "tool_context" not in api.chat.call_args.kwargs
    brain._chat_backend = None
    brain._client.chat.return_value = {"message": {"content": "OK"}}
    brain._chat([{"role": "user", "content": "Dodaj plakat"}],
                interaction_id="trusted", tool_context=context)
    assert "tool_context" not in brain._client.chat.call_args.kwargs["options"]
    assert "interaction_id" not in brain._client.chat.call_args.kwargs["options"]
