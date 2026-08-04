"""Guards the single-source NIM model fallback (config.DEFAULT_NIM_MODEL).

The live NIM model id used to be hardcoded as a stale string in several places
(config, model_registry, external_analyzer, self_model_facade, nim_client) --
each pointing at a now-dead model whenever .env's NVIDIA_NIM_MODEL was unset
(nemotron-70b decommissioned 404; nemotron-super-49b-v1.5 degraded server-side).
They are now all sourced from maria_core.sys.config.DEFAULT_NIM_MODEL.

These tests pin DEFAULT_NIM_MODEL to the live model (so a switch is a one-line
change here + .env) and assert every fallback site resolves to that one constant,
so future drift onto a dead model fails loudly instead of lurking as a footgun.

2026-07-27: dracarys became the third model retired under us (HTTP 410 Gone,
223 failed calls before anyone noticed). Treat this constant as perishable --
and note that NIM's /v1/models catalogue is NOT a list of working models: half
the heavyweight names there answer 404 with no deployment behind them, so
verify any replacement with a real request before pinning it.
"""

import inspect

from maria_core.sys.config import DEFAULT_NIM_MODEL


def test_default_nim_model_pinned_to_live():
    # Tripwire: when the live NIM model changes, update THIS constant (and
    # .env NVIDIA_NIM_MODEL) -- not a scattered string.
    # 2026-07-27: dracarys hit end-of-life (410 Gone). Successor picked by
    # measurement on Maria's own analyze_task path, not by parameter count.
    assert DEFAULT_NIM_MODEL == "nvidia/nemotron-3-ultra-550b-a55b"


# Named corpses, not a banned family. The original guard was
# `"nemotron" not in DEFAULT_NIM_MODEL`, written in June when two nemotron
# models died within days of each other. That was a heuristic standing in for
# "these specific ids are dead", and it expired: nemotron-3 is a later
# generation and was verified live on 2026-07-27 (5/5 screening answers, 3/3
# real content through analyze_task). A family-wide ban would now block a
# measured-working model, so list the actual dead ids instead.
RETIRED_MODELS = {
    "abacusai/dracarys-llama-3.1-70b-instruct",   # 410 Gone, 2026-07-27
    "nvidia/llama-3.1-70b-nemotron-instruct",     # 404, 2026-06-08
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",   # degraded server-side
    "moonshotai/kimi-k2.6",                       # listed but 404, no deployment
}


def test_default_not_a_retired_model():
    assert DEFAULT_NIM_MODEL not in RETIRED_MODELS


def test_config_nim_model_falls_back_to_constant():
    # config.NVIDIA_NIM_MODEL must use DEFAULT_NIM_MODEL as its env fallback
    # (not a literal model string). Source-level check is robust to the actual
    # environment / .env without reloading the widely-imported config module.
    from maria_core.sys import config

    src = "".join(inspect.getsource(config).split())  # strip all whitespace
    assert 'NVIDIA_NIM_MODEL=os.environ.get("NVIDIA_NIM_MODEL",DEFAULT_NIM_MODEL)' in src


def test_model_registry_external_uses_constant():
    from agent_core.llm.model_registry import ModelRole, get_model

    spec = get_model(ModelRole.EXTERNAL)
    assert spec is not None
    assert spec.model_id == DEFAULT_NIM_MODEL


def test_nim_client_default_model_is_constant():
    from agent_core.llm.nim_client import NIMClient

    default = inspect.signature(NIMClient.__init__).parameters["model"].default
    assert default == DEFAULT_NIM_MODEL


def test_external_analyzer_nim_fallback_is_constant(monkeypatch):
    # Exercise the real fallback path: with NVIDIA_NIM_MODEL unset, the NIM
    # report's model field resolves to DEFAULT_NIM_MODEL.
    from agent_core.self_analysis.external_analyzer import ExternalAnalyzer

    monkeypatch.delenv("NVIDIA_NIM_MODEL", raising=False)
    analyzer = ExternalAnalyzer(nim_fn=lambda prompt: "")
    monkeypatch.setattr(analyzer, "_build_prompt", lambda summary: "noop")

    report = analyzer._analyze_with_nim({"input_hash": "abc"})
    assert report is not None
    assert report.model == DEFAULT_NIM_MODEL
