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
    """Create SharedContext with brain, brain_loop, memory, and identity."""
    semantic_memory = SemanticGraph()
    episodic_memory = []

    # Create identity store for consciousness
    identity_store = None
    consciousness = None
    try:
        from agent_core.consciousness import IdentityStore, ConsciousnessCore

        identity_store = IdentityStore(data_dir="meta_data")
        print(f"[INIT] Identity loaded: session {identity_store.get_session_count()}")
    except Exception as e:
        print(f"[INIT] Identity store disabled: {e}")

    brain = ollama_brain.OllamaBrain(
        model=BRAIN_MODEL,
        verify_model=True,
        identity_store=identity_store,
    )

    # Attach conversation memory for persistence
    conversation_memory = None
    try:
        from agent_core.consciousness.conversation_memory import ConversationMemory
        session_id = identity_store.get_session_count() if identity_store else 0
        conversation_memory = ConversationMemory(session_id=session_id)
        brain.set_conversation_memory(conversation_memory)
        print(f"[INIT] Conversation memory: active (session {session_id})")
    except Exception as e:
        print(f"[INIT] Conversation memory disabled: {e}")

    # Wrap with LLM Router if NIM API available
    router = _create_router(brain)
    active_brain = router if router else brain

    brain_loop = brain_memory_integration.BrainMemoryLoop(
        semantic_memory=semantic_memory,
        episodic_memory=episodic_memory,
        maria_brain=active_brain,
    )

    # Initialize consciousness (after brain + memory ready)
    if identity_store:
        try:
            from agent_core.consciousness import ConsciousnessCore

            consciousness = ConsciousnessCore(
                semantic_memory=semantic_memory,
                identity_store=identity_store,
            )
            consciousness.initialize()
            print(f"[INIT] Consciousness: session {identity_store.get_session_count()}")
        except Exception as e:
            print(f"[INIT] Consciousness disabled: {e}")

    return SharedContext(
        brain=active_brain,
        brain_loop=brain_loop,
        semantic_memory=semantic_memory,
        episodic_memory=episodic_memory,
        brain_model=BRAIN_MODEL,
        identity_store=identity_store,
        consciousness=consciousness,
        conversation_memory=conversation_memory,
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

    def make_consciousness():
        from agent_core.modules.consciousness_module import ConsciousnessModule
        return ConsciousnessModule()

    def make_awareness():
        from agent_core.modules.awareness_module import AwarenessModule
        return AwarenessModule()

    def make_teacher():
        from agent_core.modules.teacher_module import TeacherModule
        return TeacherModule()

    def make_planner():
        from agent_core.modules.planner_module import PlannerModule
        return PlannerModule()

    def make_experiment():
        from agent_core.modules.experiment_module import ExperimentModule
        return ExperimentModule()

    registry.try_register(make_homeostasis, "homeostasis")
    registry.try_register(make_introspection, "introspection")
    registry.try_register(make_learning, "learning")
    registry.try_register(make_knowledge, "knowledge")
    registry.try_register(make_query, "query")
    registry.try_register(make_nim, "nim")
    registry.try_register(make_consciousness, "consciousness")
    registry.try_register(make_awareness, "awareness")
    registry.try_register(make_teacher, "teacher")
    registry.try_register(make_planner, "planner")
    registry.try_register(make_experiment, "experiment")

    def make_self_analysis():
        from agent_core.modules.self_analysis_module import SelfAnalysisModule
        return SelfAnalysisModule()

    def make_critique():
        from agent_core.modules.critique_module import CritiqueModule
        return CritiqueModule()

    def make_vision():
        from agent_core.modules.vision_module import VisionModule
        return VisionModule()

    registry.try_register(make_self_analysis, "self_analysis")
    registry.try_register(make_critique, "critique")
    registry.try_register(make_vision, "vision")

    def make_v3():
        from agent_core.modules.v3_module import V3Module
        return V3Module()

    registry.try_register(make_v3, "v3")

    def make_code():
        from agent_core.modules.code_module import CodeModule
        return CodeModule()

    registry.try_register(make_code, "code")


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


# ====== SESSION SUMMARY ======

def _generate_session_summary(ctx) -> str:
    """Generate session summary from conversation history using LLM."""
    try:
        brain = ctx.brain
        # Get conversation history (skip system prompt)
        history = getattr(brain, "history", [])
        if len(history) <= 1:
            return "Krotka sesja bez rozmowy"

        # Extract last user/assistant messages (max 10 pairs)
        messages = []
        for msg in history[1:]:  # Skip system prompt
            role = msg.get("role", "")
            content = msg.get("content", "")[:200]
            if role in ("user", "assistant"):
                messages.append(f"{role}: {content}")

        if not messages:
            return "Sesja bez rozmowy"

        # Keep last 20 messages max for context
        recent = messages[-20:]
        conversation_snippet = "\n".join(recent)

        prompt = (
            "Przeczytaj te fragmenty rozmowy i napisz JEDNO krotkie zdanie (max 15 slow) "
            "podsumowujace o czym rozmawialismy. "
            "Nie uzywaj cudzyslow. Pisz w 1 osobie l. mn. (np. 'Pracowalismy nad...'). "
            "Nie dodawaj nic wiecej.\n\n"
            f"{conversation_snippet}"
        )

        summary = brain._ask_once(prompt, temperature=0.1)
        # Clean up - take first line, strip quotes
        summary = summary.strip().split("\n")[0].strip('"\'')
        # Limit length
        if len(summary) > 100:
            summary = summary[:97] + "..."
        return summary or "Sesja REPL"
    except Exception as e:
        return "Sesja REPL"


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

    # 5. Greeting (consciousness-aware or fallback)
    if ctx.consciousness:
        try:
            intro = ctx.consciousness.get_startup_greeting(ctx.brain)
        except Exception:
            intro = ctx.brain.think(
                "Przywitaj sie z Erykiem. "
                "Powiedz kim jestes (M.A.R.I.A.) i ze jestes gotowa do pracy.",
                temperature=0.3,
            )
    else:
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

        # Record conversation experience
        if ctx.consciousness:
            ctx.consciousness.record_experience("conversation_turn")

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

        # ===== CONVERSATION-DRIVEN LEARNING =====
        # Detect learning intent before brain processes (zero LLM)
        try:
            from agent_core.perception.conversation_learning import process_user_message
            cdl_result = process_user_message(user_input, ctx, channel="repl")
            if cdl_result:
                topic = cdl_result["topic"]
                action = cdl_result["action"]
                print(f"[Maria] Rozumiem - {action}: '{topic}'. Dodam do celow nauki.")
        except Exception:
            pass  # CDL is optional, never block chat

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

        # Record experience for personality evolution
        if ctx.consciousness:
            stats = ctx.last_result.get("stats", {})
            ctx.consciousness.record_experience("perception_processed", {
                "facts_count": stats.get("facts", 0),
            })
            if ctx.last_result.get("unknown_terms"):
                ctx.consciousness.record_experience("unknown_terms_found", {
                    "count": len(ctx.last_result["unknown_terms"]),
                })

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
            if ctx.consciousness:
                ctx.consciousness.record_experience("followup_asked")

        print("\n" + "-" * 70)

    # 7. Cleanup - condense conversation and save consciousness
    summary = "REPL session"

    # Condense conversation into structured summary
    if ctx.conversation_memory and ctx.conversation_memory.get_session_turn_count() > 0:
        try:
            # Use raw brain for condensation (not router, to avoid NIM cost for this)
            condense_brain = getattr(ctx.brain, 'ollama', ctx.brain)
            condensed = ctx.conversation_memory.condense_session(condense_brain)
            if condensed:
                ctx.conversation_memory.save_summary(condensed)
                summary = condensed.get("summary", summary)
                print(f"[System] Conversation condensed: {summary}")
        except Exception as e:
            print(f"[System] Condensation failed: {e}")

    # Generate session summary as fallback if no condensation happened
    if summary == "REPL session":
        try:
            summary = _generate_session_summary(ctx)
        except Exception:
            pass

    if ctx.consciousness:
        try:
            ctx.consciousness.checkpoint(summary=summary)
            print(f"[System] Consciousness checkpoint: {summary}")
        except Exception:
            try:
                ctx.consciousness.checkpoint(summary="REPL session")
            except Exception:
                pass
    registry.cleanup_all()


if __name__ == "__main__":
    main()
