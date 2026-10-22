"""The tape must not call a successful fallback a failure (2026-08-11).

`ask_as_role()` has a two-stage local path: the scheduler's model (qwen3:8b
for the planner) and, if that overruns its role budget, a direct Ollama call
on `self.ollama.model` (llama3.1:8b). The second stage recorded
`success=False` unconditionally, so an answer that actually came back and
was actually used still landed on the tape as a loss.

Cost of the lie, measured over 7 days of live tape: 120 planner entries
carried `scheduler_inference_fail`, and 53 of them held a 290-2000 char
answer. Reading the tape at face value put the local path's failure rate at
73% when the truth was 41% -- and that rate is the number the NIM cutover
decision (the API KEY itself expires 2026-08-18, with no top-up path) rests
on.

These tests pin the fix. Removing `success=bool(text)` from router.py must
turn the first one red.
"""



import pytest

from agent_core.llm.router import LLMRouter
from agent_core.tests.spec_helpers import specced
from models.ollama_brain import OllamaBrain
from agent_core.llm.model_scheduler import ModelScheduler, EnsureResult
from agent_core.llm.local_compute import LocalComputeCoordinator


class _Role:
    """Stand-in for ModelRole: ask_as_role() only reads `.value`."""

    value = "planner"


def _router(fallback_text: str, recorded: list):
    """Router wired so the scheduler stage raises and the fallback answers.

    `_record_tape` is a real function with the production signature, not a
    MagicMock: a mock would swallow a wrong kwarg and keep the test green
    while the bug walked past it.
    """
    r = LLMRouter.__new__(LLMRouter)
    r.nim = None
    r._nim_calls = 0
    r._nim_fallbacks = 0
    r._ollama_calls = 0
    r.ollama = specced(OllamaBrain, model="llama3.1:8b")
    r.ollama.model = "llama3.1:8b"
    r._is_nim_primary_role = lambda role_name: False
    r._bounded_ask_once = lambda prompt, temperature, role_name: fallback_text

    scheduler = specced(ModelScheduler)
    ready = EnsureResult(success=True)
    ready.success = True
    ready.ollama_tag = "qwen3:8b"
    ready.role = _Role()
    scheduler.ensure_ready.return_value = ready
    # The scheduler stage blows up -> except branch -> local fallback.
    scheduler.record_request.side_effect = AssertionError("unreachable")
    r._model_scheduler = scheduler

    def _tape(role, model, prompt, response, start_time,
              success=True, route_reason=""):
        recorded.append({
            "role": role, "model": model, "response": response,
            "success": success, "route_reason": route_reason,
        })

    r._record_tape = _tape
    return r


@pytest.fixture
def force_scheduler_failure(monkeypatch):
    """Make the scheduler-stage call raise, as a role-budget overrun does."""
    def _boom(fn, timeout_sec=None, label=""):
        raise TimeoutError(
            f"LLM call '{label}' exceeded {timeout_sec:.0f}s deadline"
        )

    monkeypatch.setattr(
        "agent_core.llm.execution_budget.call_with_timeout", _boom
    )


def test_answering_fallback_is_recorded_as_success(force_scheduler_failure):
    recorded: list = []
    r = _router("{\"plan\": [], \"idle_strategy\": \"wait\"}", recorded)

    text = r.ask_as_role(_Role(), "zaplanuj nastepne 30 minut")

    assert text  # the caller really got an answer
    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["success"] is True, (
        "a fallback that answered must not be taped as a failure -- this is "
        "the 2026-08-11 regression that inflated the local failure rate"
    )
    # The scheduler's error is not lost: it still rides in route_reason.
    assert "scheduler_inference_fail" in entry["route_reason"]
    assert "qwen3:8b" in entry["route_reason"]
    # The model field names who DID the work, not who was asked.
    assert entry["model"] == "llama3.1:8b"


def test_empty_fallback_is_still_recorded_as_failure(force_scheduler_failure):
    recorded: list = []
    r = _router("", recorded)

    text = r.ask_as_role(_Role(), "zaplanuj nastepne 30 minut")

    assert text == ""
    assert recorded[0]["success"] is False, (
        "an empty fallback IS a failure -- the planner falls back to rules"
    )


# ---------------------------------------------------------------------------
# think=False on the scheduler stage (2026-08-11)
# ---------------------------------------------------------------------------
# qwen3:8b is a reasoning model and the planner wants JSON, so its thinking
# tokens are pure cost. Measured on the production planner prompt with the
# daemon live: thinking median 415s (0/3 inside the 180s budget, 0/3 even
# inside a 230s ceiling) against 114s with think=False (3/3 inside budget,
# 3/3 parsing). Raising the budget could not have fixed it; this flag did.


def test_scheduler_stage_disables_thinking(monkeypatch):
    """`think=False` must reach chat() as a TOP-LEVEL argument.

    Passed inside `options` the Ollama server ignores it silently, which
    would look identical in code review and change nothing at runtime -- so
    the assertion checks where it landed, not merely that it was passed.
    """
    seen: dict = {}

    class _Client:
        def chat(self, **kwargs):
            seen.update(kwargs)
            return {"message": {"content": "{\"plan\": []}"}}

    class _Lease:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        "agent_core.llm.router.get_ollama_client", lambda: _Client()
    )
    coordinator = specced(LocalComputeCoordinator)
    coordinator.lease.return_value = _Lease()
    monkeypatch.setattr(
        "agent_core.llm.router.get_local_compute_coordinator", lambda: coordinator
    )
    monkeypatch.setattr(
        "agent_core.llm.execution_budget.call_with_timeout",
        lambda fn, timeout_sec=None, label="": fn(),
    )

    recorded: list = []
    r = _router("unused-fallback", recorded)
    r._model_scheduler.record_request.side_effect = None

    text = r.ask_as_role(_Role(), "zaplanuj nastepne 30 minut")

    assert text == "{\"plan\": []}"
    assert seen.get("think") is False, (
        "the reasoning model must be told to stop thinking: without this the "
        "planner prompt measured 415s against a 180s budget"
    )
    assert "think" not in seen.get("options", {}), (
        "think inside options is silently ignored by the server"
    )


def test_learning_fallback_disables_thinking(monkeypatch):
    """The learning fallback carries the same flag, and nothing pinned it.

    Found 2026-08-15 by mutation: commenting out `think=False` in
    `_ask_once`'s local branch left the whole suite green, even though the
    router docstring records 208s -> 64s for that one flag and the learning
    fallback becomes the primary learning path once the NIM key expires
    (2026-08-18). The scheduler stage had a test; this one did not.
    """
    seen: dict = {}

    def _ask_once(prompt, **kwargs):
        seen.update(kwargs)
        return "{\"summary\": \"ok\"}"

    r = LLMRouter.__new__(LLMRouter)
    r.nim = None
    r.budget = None
    r._nim_calls = 0
    r._nim_fallbacks = 0
    r._ollama_calls = 0
    r._model_scheduler = None
    r._record_tape = lambda *a, **kw: None
    r.ollama = specced(OllamaBrain, model="llama3.1:8b")
    r.ollama.model = "llama3.1:8b"
    r.ollama._ask_once = _ask_once

    monkeypatch.setattr(
        "agent_core.llm.router.call_with_timeout",
        lambda fn, timeout_sec=None, label="": fn(),
    )

    text = r._ask_once("streszcz ten fragment")

    assert text
    assert seen.get("think") is False, (
        "the local learning model must be told to stop thinking: qwen3 with "
        "thinking on returned nothing usable at all (0/30)"
    )
