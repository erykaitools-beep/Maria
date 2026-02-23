# main.py
# M.A.R.I.A. ENHANCED - REPL Interface
# VERSION: 2.0 (Registry-based architecture)

import json
from maria_core.utils.conversation_logger import log_message
from models import ollama_brain
from maria_core.memory_engine import brain_memory_integration
from maria_core.memory_engine.semantic.semantic_graph import SemanticGraph

from agent_core.registry import SharedContext, ModuleRegistry, CommandDispatcher

# MODEL OLLAMA - dopasuj do `ollama list`
BRAIN_MODEL = "llama3.1:8b"


# ====== INICJALIZACJA ======

def _create_router(brain):
    """Create LLM Router wrapping brain. Returns None if NIM unavailable."""
    try:
        from maria_core.sys.config import (
            NVIDIA_NIM_API_KEY, NVIDIA_NIM_BASE_URL, NVIDIA_NIM_MODEL,
            NIM_DAILY_TOKEN_LIMIT, NIM_MONTHLY_TOKEN_LIMIT,
        )
        if not NVIDIA_NIM_API_KEY:
            print("[INIT] LLM Router: NIM API key not set, using Ollama only")
            return None

        from agent_core.llm import NIMClient, TokenBudget, LLMRouter

        nim = NIMClient(
            api_key=NVIDIA_NIM_API_KEY,
            model=NVIDIA_NIM_MODEL,
            base_url=NVIDIA_NIM_BASE_URL,
        )
        budget = TokenBudget(
            daily_limit=NIM_DAILY_TOKEN_LIMIT,
            monthly_limit=NIM_MONTHLY_TOKEN_LIMIT,
        )
        router = LLMRouter(
            ollama_brain=brain,
            nim_client=nim,
            token_budget=budget,
        )
        print(f"[INIT] LLM Router: hybrid (NIM: {NVIDIA_NIM_MODEL} + Ollama)")
        return router
    except Exception as e:
        print(f"[INIT] LLM Router disabled: {e}")
        return None


def init_brain():
    """Create SharedContext with brain, brain_loop, and memory."""
    semantic_memory = SemanticGraph()
    episodic_memory = []

    brain = ollama_brain.OllamaBrain(
        model=BRAIN_MODEL,
        verify_model=True,
    )

    # Wrap with LLM Router if NIM API available
    router = _create_router(brain)
    active_brain = router if router else brain

    brain_loop = brain_memory_integration.BrainMemoryLoop(
        semantic_memory=semantic_memory,
        episodic_memory=episodic_memory,
        maria_brain=active_brain,
    )

    return SharedContext(
        brain=active_brain,
        brain_loop=brain_loop,
        semantic_memory=semantic_memory,
        episodic_memory=episodic_memory,
        brain_model=BRAIN_MODEL,
    )


# ====== REJESTRACJA MODULOW ======

def register_modules(registry):
    """Register all available modules. Failed imports are gracefully skipped."""
    # Core module is always required
    from agent_core.modules.core_module import CoreModule
    registry.register(CoreModule())

    # Optional modules - graceful degradation if dependencies missing
    def make_homeostasis():
        from agent_core.modules.homeostasis_module import HomeostasisModule
        return HomeostasisModule()

    def make_introspection():
        from agent_core.modules.introspection_module import IntrospectionModule
        return IntrospectionModule()

    def make_learning():
        from agent_core.modules.learning_module import LearningModule
        return LearningModule()

    def make_knowledge():
        from agent_core.modules.knowledge_module import KnowledgeModule
        return KnowledgeModule()

    def make_query():
        from agent_core.modules.query_module import QueryModule
        return QueryModule()

    def make_nim():
        from agent_core.modules.nim_module import NIMModule
        return NIMModule()

    registry.try_register(make_homeostasis, "homeostasis")
    registry.try_register(make_introspection, "introspection")
    registry.try_register(make_learning, "learning")
    registry.try_register(make_knowledge, "knowledge")
    registry.try_register(make_query, "query")
    registry.try_register(make_nim, "nim")


# ====== POMOC ======

def print_help(dispatcher):
    """Print help from all registered modules."""
    print("\n" + "=" * 70)
    print("M.A.R.I.A. ENHANCED - FULL LEARNING INTERFACE")
    print("=" * 70)

    # Merge duplicate categories (builtins + module help)
    merged = {}
    for category, lines in dispatcher.get_all_help():
        if category not in merged:
            merged[category] = []
        merged[category].extend(lines)

    for category, lines in merged.items():
        print(f"\n{category}:")
        for line in lines:
            print(line)

    print("\nKazdy inny tekst -> PERCEPCJA dla Marii (analiza + zapis do pamieci)\n")
    print("=" * 70 + "\n")


# ====== FOLLOWUP ======

def generate_followup_question(ctx, last_result):
    """Maria generuje jedno pytanie zwrotne do operatora."""
    if not last_result:
        return "NONE"

    try:
        compact = {
            "learning_goals": last_result.get("learning_goals", [])[:3],
            "unknown_terms": last_result.get("unknown_terms", [])[:3],
        }
        prompt = (
            "Na podstawie danych, zaproponuj JEDNO pytanie do operatora "
            "(maks 1-2 zdania), ktore pomoze Ci lepiej zrozumiec jego intencje. "
            f"Dane:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
            "Jesli pytanie nie jest potrzebne, odpowiedz: NONE"
        )
        answer = ctx.brain.think(prompt, temperature=0.2)
        return answer.strip()
    except Exception:
        return "NONE"


# ====== GLOWNA FUNKCJA ======

def main():
    # 1. Initialize brain and shared context
    ctx = init_brain()

    # 2. Register and initialize modules
    registry = ModuleRegistry()
    register_modules(registry)
    registry.init_all(ctx)

    # 3. Build command dispatcher
    dispatcher = CommandDispatcher(registry)
    dispatcher.add_builtin("/help", lambda args: print_help(dispatcher))
    dispatcher.set_builtin_help([
        ("[INFO] PODSTAWOWE", [
            "  /help        - pokaz te pomoc",
            "  /exit        - wyjscie",
        ]),
    ])

    # 4. Banner
    print("\n" + "=" * 70)
    print("M.A.R.I.A. - ENHANCED LOCAL BRAIN INTERFACE v2.0")
    print("=" * 70)
    print("Registry-based architecture | Plug-in module system")
    print(f"Model: {BRAIN_MODEL} | Nodes: {len(ctx.semantic_memory.nodes)}")

    # Show module status
    status = registry.get_status()
    active = [n for n, s in status.items() if s == "active"]
    failed = {n: s for n, s in status.items() if s != "active"}
    print(f"Modules: {', '.join(active)}")
    if failed:
        for name, state in failed.items():
            print(f"  [{name}] {state}")

    print("=" * 70 + "\n")

    # 5. Greeting
    intro = ctx.brain.think(
        "Przywitaj sie z Erykiem. "
        "Powiedz kim jestes (M.A.R.I.A. z pelnym systemem uczenia) "
        "i zadaj jedno pytanie o priorytecie nauki.",
        temperature=0.3,
    )
    print("Maria:", intro, "\n")
    log_message("maria", intro)

    # 6. REPL loop
    while True:
        try:
            user_input = input("Ty >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[System] Zamykam interfejs.")
            break

        if not user_input:
            continue

        log_message("user", user_input)

        # ===== COMMANDS =====
        if user_input.startswith("/"):
            parts = user_input.split()
            command = parts[0].lower()
            args = parts[1:] if len(parts) > 1 else []

            if command == "/exit":
                print("[System] Do zobaczenia, Operatorze.")
                break

            if not dispatcher.dispatch(command, args):
                print("[System] Nieznana komenda. /help dla listy.\n")

            continue

        # ===== PERCEPTION =====
        # Check homeostasis mode before processing
        core = ctx.homeostasis_core
        if core:
            mode_val = core.state.mode.value
            if mode_val == "survival":
                print("[Homeostasis] [WARN] SURVIVAL mode - percepcja wstrzymana")
                print("  System w trybie awaryjnym. Uzyj /homeostasis status")
                continue
            elif mode_val == "sleep":
                print("[Homeostasis] [SLEEP] SLEEP mode - budze system...")
                core.time_sensor.record_interaction()
            elif mode_val == "reduced":
                print("[Homeostasis] [REDUCED] REDUCED mode - ograniczona wydajnosc")

        ctx.last_result = ctx.brain_loop.process_perception(user_input)

        # Record successful inference for homeostasis
        if ctx.homeostasis_core:
            ctx.homeostasis_core.time_sensor.record_interaction()

        # Display results
        print("\nMaria [Reasoning]:")
        reasoning = ctx.last_result.get("reasoning", "")
        print(reasoning[:500] if reasoning else "N/A")
        if reasoning:
            log_message("maria", f"[Reasoning] {reasoning}")

        if ctx.last_result.get("learning_goals"):
            print("\n[Goals]")
            for g in ctx.last_result["learning_goals"][:3]:
                print(f"- {g}")

        if ctx.last_result.get("unknown_terms"):
            print("\n[Unknown Terms]")
            for t in ctx.last_result["unknown_terms"][:5]:
                print(f"- {t}")

        followup = generate_followup_question(ctx, ctx.last_result)
        if followup and followup.upper() != "NONE":
            print("\nMaria [Pytanie]:")
            print(followup)
            log_message("maria", f"[Pytanie] {followup}")

        print("\n" + "-" * 70)

    # 7. Cleanup
    registry.cleanup_all()


if __name__ == "__main__":
    main()
