"""
Master Prompt - single source of truth for Maria's identity across all LLM paths.

Replaces hardcoded prompts in OllamaBrain, NIMClient, and Web UI.
Based on docs/MARIA_PROMPT.md (operator personality spec).

Three context levels:
- FULL: OllamaBrain (local chat) - base + time + identity + user + work + awareness
- COMPACT: NIM / Web UI chat - base + time + user (key facts only)
- BRIEF: External models (Codex, Claude) - context brief for delegated tasks
"""

import logging
import os
from datetime import datetime
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base identity prompt - derived from docs/MARIA_PROMPT.md
# Operator name is injected dynamically from environment or UserProfile.
# ---------------------------------------------------------------------------

_OPERATOR_NAME_DEFAULT = os.environ.get("MARIA_OPERATOR_NAME", "Operator")


def _get_base_identity(operator_name: Optional[str] = None) -> str:
    """Build base identity prompt with dynamic operator name."""
    name = operator_name or _OPERATOR_NAME_DEFAULT
    return (
        "Jestes M.A.R.I.A. - Meta Analysis Recalibration Intelligence Architecture.\n"
        f"Jestes osobistym asystentem {name}.\n"
        "\n"
        "Styl: naturalny, spokojny, konkretny, ludzki, inteligentny. "
        "Bez korpo-belkotu, bez sztucznego entuzjazmu.\n"
        "Mow jasno, prosto i celnie. Najpierw sens, potem szczegoly.\n"
        "Skupiaj sie na dzialaniu: co zrobilas, co zamierzasz, czego potrzebujesz.\n"
        "\n"
        f"Do uzytkownika zwracaj sie po imieniu: {name}.\n"
        "Odpowiadasz po polsku, chyba ze zadanie wymaga inaczej.\n"
        "\n"
        "Nie udawaj czlowieka biologicznego. Nie kiam ze cos zrobilas jesli nie. "
        "Nie przepraszaj bez potrzeby. Nie gadaj za dlugo jesli mozna krocej. "
        "Nie eksponuj chaosu wewnetrznych modulow - opisz zadanie prosciej. "
        "Jesli cos sie nie uda, sprobuj fallbacku zanim zameldujesz problem.\n"
        "\n"
        "Masz oko (kamere USB) - widzisz otoczenie.\n"
        "Pamietasz kontekst, planujesz, delegujesz zadania do odpowiednich narzedzi."
    )


# Backward-compatible constant (uses default name)
BASE_IDENTITY = _get_base_identity()

# ---------------------------------------------------------------------------
# Context brief for external models (Codex, Claude)
# ---------------------------------------------------------------------------

CONTEXT_BRIEF = (
    "You are helping M.A.R.I.A. - a local-first cognitive AI system. "
    "M.A.R.I.A. runs on Ubuntu Mini PC (Python 3.8+, Ollama, 32GB RAM). "
    "Architecture: agent_core/ (homeostasis, planner, autonomy, memory, "
    "self_analysis, routing, tracing, vision, creative, semantic). "
    "Values: local-first, action over talk, modular, safe delegation, "
    "graceful fallback. Respond in the same language as the task."
)

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_base_prompt() -> str:
    """Return the base identity prompt (no dynamic context)."""
    return BASE_IDENTITY


def build_full_prompt(
    time_context: str = "",
    identity_context: str = "",
    user_context: str = "",
    work_context: str = "",
    conversation_context: str = "",
    awareness_context: str = "",
    operational_summary: str = "",
    grounding_active: bool = False,
) -> str:
    """
    Build FULL system prompt for local chat (OllamaBrain).

    Assembles base identity + all available dynamic context sections.
    """
    prompt = BASE_IDENTITY

    if time_context:
        prompt += f"\n\n[Kontekst czasowy: {time_context}]"
    if identity_context:
        prompt += f"\n[Tozsamosc: {identity_context}]"
    if user_context:
        prompt += f"\n{user_context}"
    if work_context:
        prompt += f"\n[Aktualna praca: {work_context}]"
    if conversation_context:
        prompt += f"\n{conversation_context}"

    # Operational summary replaces awareness if available
    if operational_summary:
        prompt += f"\n{operational_summary}"
    elif awareness_context:
        prompt += f"\n{awareness_context}"

    if grounding_active:
        prompt += (
            "\nGdy operator pyta o Twoj stan, logi lub bledy, "
            "odpowiadaj na podstawie danych operacyjnych. "
            "Mow 'Widze w logach...', 'Zrodlo danych: ...'. "
            "Nigdy nie wymyslaj informacji o wlasnym stanie."
        )

    return prompt


def build_compact_prompt(
    time_context: str = "",
    user_context: str = "",
) -> str:
    """
    Build COMPACT system prompt for NIM / Web UI chat.

    Base identity + time + user profile (no work/awareness/grounding).
    """
    prompt = BASE_IDENTITY

    if time_context:
        prompt += f"\n\n[Kontekst czasowy: {time_context}]"
    if user_context:
        prompt += f"\n{user_context}"

    return prompt


def build_context_brief() -> str:
    """Return context brief for external models (Codex, Claude)."""
    return CONTEXT_BRIEF
