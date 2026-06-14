"""Guards the single-source NIM model fallback (config.DEFAULT_NIM_MODEL).

The live NIM model id used to be hardcoded as a stale string in several places
(config, model_registry, external_analyzer, self_model_facade, nim_client) --
each pointing at a now-dead model whenever .env's NVIDIA_NIM_MODEL was unset
(nemotron-70b decommissioned 404; nemotron-super-49b-v1.5 degraded server-side).
They are now all sourced from maria_core.sys.config.DEFAULT_NIM_MODEL.

These tests pin DEFAULT_NIM_MODEL to the live model (so a switch is a one-line
change here + .env) and assert every fallback site resolves to that one constant,
so future drift onto a dead model fails loudly instead of lurking as a footgun.
"""

import inspect

from maria_core.sys.config import DEFAULT_NIM_MODEL


def test_default_nim_model_pinned_to_live():
    # Tripwire: when the live NIM model changes, update THIS constant (and
    # .env NVIDIA_NIM_MODEL) -- not a scattered string. dracarys-llama-3.1-70b
    # is live as of 2026-06-08.
    assert DEFAULT_NIM_MODEL == "abacusai/dracarys-llama-3.1-70b-instruct"


def test_default_not_a_dead_nemotron():
    # The whole reason this constant exists: the nemotron-* shelf went dead.
    # Guard against accidentally re-pinning the default onto that family.
    assert "nemotron" not in DEFAULT_NIM_MODEL


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
