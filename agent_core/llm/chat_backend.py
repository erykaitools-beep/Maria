"""Select the interactive transport without changing Maria's memory pipeline."""
import os
import shutil


def chat_backend_config():
    provider = os.environ.get("MARIA_CHAT_BACKEND", "ollama").strip().lower()
    if provider not in {"ollama", "codex"}:
        raise ValueError("MARIA_CHAT_BACKEND must be ollama or codex")
    model = (os.environ.get("MARIA_CODEX_MODEL", "gpt-6.1-sol") if provider == "codex"
             else os.environ.get("MARIA_CHAT_MODEL", "llama3.1:8b"))
    # Configured != authenticated or proven healthy. A real turn proves that.
    configured = bool(shutil.which(os.environ.get("CODEX_BIN", "codex"))) if provider == "codex" else True
    return {"provider": provider, "model": model, "configured": configured}


def create_chat_backend(timeout_s=90):
    config = chat_backend_config()
    if config["provider"] == "ollama":
        return None
    from agent_core.llm.codex_chat import CodexChatBackend
    from agent_core.llm.kritaqo_tools import create_kritaqo_tools_provider
    from agent_core.llm.kritaqo_work_service import get_work_service
    from agent_core.llm.kritaqo_work import WorkToolsProvider
    legacy = create_kritaqo_tools_provider()
    work = get_work_service()
    return CodexChatBackend(model=config["model"], timeout_s=timeout_s,
                            codex_bin=os.environ.get("CODEX_BIN") or None,
                            tool_provider=WorkToolsProvider(legacy, work) if work is not None else legacy)


def prepare_interactive_tools(backend, prompt, interaction_id, conversation_id):
    """Freeze provider-owned context once at the authenticated UI boundary."""
    if not isinstance(interaction_id, str) or not interaction_id.strip():
        return None
    provider = getattr(backend, "tool_provider", None)
    prepare = getattr(provider, "prepare_turn", None)
    return prepare(prompt, interaction_id, conversation_id) if callable(prepare) else None


def interactive_tools_match(backend, prompt, interaction_id, tool_context=None):
    """Route only a trusted interactive request to the installed tool provider."""
    if not isinstance(interaction_id, str) or not interaction_id.strip():
        return False
    provider = getattr(backend, "tool_provider", None)
    if tool_context is not None:
        accepts = getattr(provider, "accepts_context", None)
        return callable(accepts) and accepts(prompt, interaction_id, tool_context) is True
    return provider is not None and provider.accepts_prompt(prompt) is True
