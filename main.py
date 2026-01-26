# main.py (CORRECTED)
# Enhanced M.A.R.I.A. Main – integracja wszystkich modułów uczenia
# Self-Learning, Web Learning, API Bridge, Query Interface
# VERSION: 1.1 (Fixed bugs + improved + conversation logging)

import json
import threading
import time
import importlib
from datetime import datetime
from maria_core.utils.conversation_logger import log_message  # 👈 LOGOWANIE ROZMÓW
# NOTE: Nie importujemy 'main' z orchestrator - uzywamy lokalnej funkcji main()
from models import ollama_brain
from maria_core.memory_engine import brain_memory_integration
from maria_core.memory_engine.semantic.semantic_graph import SemanticGraph

# ====== GLOBALNE STANY ======
AGENT_RUNNING = False
AGENT_SHOULD_STOP = False
AGENT_THREAD = None

semantic_memory = None
episodic_memory = None
maria_brain = None
brain_loop = None

# MODEL OLLAMA – dopasuj do `ollama list`
BRAIN_MODEL = "llama3.1:8b"

# ====== LEARNING MODULES (opcjonalne) ======
SELF_LEARNING_AVAILABLE = True
WEB_LEARNING_AVAILABLE = True
API_BRIDGE_AVAILABLE = True
QUERY_INTERFACE_AVAILABLE = True

try:
    from maria_core.learning.maria_self_learning import SelfLearningMode
except ImportError:
    SELF_LEARNING_AVAILABLE = False

try:
    from maria_web_learning import WebLearningMode
except ImportError:
    WEB_LEARNING_AVAILABLE = False

try:
    from maria_api_bridge import MariaAPIBridge
except ImportError:
    API_BRIDGE_AVAILABLE = False

try:
    from maria_query_interface import MariaREPL
except ImportError:
    QUERY_INTERFACE_AVAILABLE = False


# ====== POMOC ======
def print_help():
    """Rozszerzona pomoc z realnie dostępnymi komendami"""
    print("\n" + "=" * 70)
    print("M.A.R.I.A. ENHANCED – FULL LEARNING INTERFACE")
    print("=" * 70)

    print("\n📌 PODSTAWOWE KOMENDY:")
    print("  /help        - pokaż tę pomoc")
    print("  /status      - co robi Maria (reasoning + statystyki)")
    print("  /episodes    - ostatnie epizody pracy")
    print("  /nodes       - przykładowe węzły z grafu")
    print("  /save        - zapisz graf do pliku semantic_graph.json")
    print("  /load        - wczytaj graf z pliku semantic_graph.json")
    print("  /exit        - wyjście\n")

    print("🤖 AGENT CONTROL:")
    print("  /start       - uruchom agenta w tle")
    print("  /stop        - zatrzymaj agenta w tle")
    print("  /reload      - przeładuj kod mózgu i pętli (ollama_brain, brain_memory_integration)\n")

    if SELF_LEARNING_AVAILABLE:
        print("🎓 SELF-LEARNING (Ollama local):")
        print("  /learn                 - auto-learning z domyślną ciekawością 60%")
        print("  /learn 0.5             - learning z ciekawością 50%")
        print("  /learn 0.9             - aggressive learning 90%\n")

    if WEB_LEARNING_AVAILABLE:
        print("🌐 WEB LEARNING (Perplexity / Ollama web search):")
        print("  /learn-web             - web learning przez Perplexity (zapytanie o API key)")
        print("  /learn-web ollama      - web learning przez Ollama (bez API key)\n")

    if API_BRIDGE_AVAILABLE:
        print("🤝 API BRIDGE (TY nauczasz):")
        print("  /teach                 - uruchom lokalny API server (Ty odpowiadasz, Maria zapisuje)\n")

    if QUERY_INTERFACE_AVAILABLE:
        print("🔍 QUERY MODE (szybkie pytania do Marii):")
        print("  /ask PYTANIE           - zapytaj Marię o to, co wie")
        print("  /ask Co to jest LLM?   - przykład\n")

    print("📊 KNOWLEDGE MANAGEMENT:")
    print("  /export-learned        - exportuj wyuczone pojęcia do maria_learned_concepts.json")
    print("  /report                - generuj raport o stanie nauki (maria_report.json)")
    print("  /hybrid                - uruchom sekwencję: self-learning → web-learning → report\n")

    print("Każdy inny tekst → PERCEPCJA dla Marii (analiza + zapis do pamięci)\n")
    print("=" * 70 + "\n")


# ====== INICJALIZACJA ======
def init_brain():
    """Tworzy/odświeża instancję mózgu i pętli pamięci."""
    global semantic_memory, episodic_memory, maria_brain, brain_loop

    if semantic_memory is None:
        semantic_memory = SemanticGraph()
    if episodic_memory is None:
        episodic_memory = []

    maria_brain = ollama_brain.OllamaBrain(
        model=BRAIN_MODEL,
        verify_model=True
    )

    brain_loop = brain_memory_integration.BrainMemoryLoop(
        semantic_memory=semantic_memory,
        episodic_memory=episodic_memory,
        maria_brain=maria_brain,
    )


# ====== HELPER: Setup learning agent ======
def _setup_learning_agent(agent_obj):
    """Helper do ustawienia learning agenta"""
    if agent_obj is None:
        return None
    agent_obj.semantic_memory = semantic_memory
    agent_obj.brain = maria_brain
    agent_obj.agent = brain_loop
    return agent_obj


# ====== LEARNING COMMANDS ======
def cmd_learn(args):
    """Uruchom Self-Learning (lokalny, na Ollama)"""
    if not SELF_LEARNING_AVAILABLE:
        print("[System] ❌ maria_self_learning.py not found")
        return

    curiosity = 0.6
    if args:
        try:
            curiosity = float(args[0])
            if not (0.0 <= curiosity <= 1.0):
                print("[System] ⚠ Curiosity must be between 0.0 and 1.0, using 0.6")
                curiosity = 0.6
        except (ValueError, IndexError):
            curiosity = 0.6

    print(f"[Self-Learning] 🎓 Starting (curiosity={curiosity:.0%})")

    try:
        learner = SelfLearningMode(None, curiosity=curiosity)
        _setup_learning_agent(learner)
        learner.run_cycle_with_learning()
        print("[Self-Learning] ✅ Cycle complete")
    except Exception as e:
        print(f"[Self-Learning] ❌ Error: {e}")


def cmd_learn_web(args):
    """Uruchom Web Learning (Perplexity lub Ollama web)"""
    if not WEB_LEARNING_AVAILABLE:
        print("[System] ❌ maria_web_learning.py not found")
        return

    source = "perplexity"
    if args and args[0].lower() == "ollama":
        source = "ollama"

    if source == "perplexity":
        api_key = input("[Web Learning] Enter Perplexity API Key: ").strip()
        log_message("user", "[/learn-web] Entered Perplexity API key (hidden)")  # nie logujemy samego klucza
        if not api_key:
            print("[System] No API key provided, aborting web learning.")
            return
    else:
        api_key = None

    print(f"[Web Learning] 🌐 Starting (source={source})")

    try:
        from maria_web_learning import WebLearningMode

        web_mode = WebLearningMode(None, perplexity_key=api_key, source=source)
        _setup_learning_agent(web_mode)
        web_mode.run_cycle_with_web_learning()
        print("[Web Learning] ✅ Cycle complete")
    except Exception as e:
        print(f"[Web Learning] ❌ Error: {e}")


def cmd_teach():
    """Uruchom API Bridge (TY nauczasz Marię)"""
    if not API_BRIDGE_AVAILABLE:
        print("[System] ❌ maria_api_bridge.py not found")
        return

    try:
        from maria_api_bridge import SimpleAPIServer

        print("[API Bridge] 🤝 Starting API Server (Ty będziesz nauczać Marię)")
        print("[API Bridge] Running on http://localhost:8000")

        server = SimpleAPIServer(port=8000)
        server.run()
    except Exception as e:
        print(f"[API Bridge] ❌ Error: {e}")


def cmd_ask(question: str):
    """Zapytaj Marię (szybki tryb, bez REPL-a)"""
    if not maria_brain:
        print("[System] ❌ Maria's brain not initialized")
        return

    if not question:
        print("[System] Brak pytania. Użyj: /ask Co to jest LLM?")
        return

    try:
        log_message("user", f"/ask {question}")
        prompt = f"Na podstawie tego co wiesz, odpowiedz na pytanie: {question}"
        answer = maria_brain.think(prompt, temperature=0.2)
        print(f"\nMaria: {answer}\n")
        log_message("maria", f"[Answer] {answer}")
    except Exception as e:
        print(f"[Query] ❌ Error: {e}")


def cmd_export_learned():
    """Exportuj pojęcia wyuczone przez różne tryby learningu."""
    try:
        learned_concepts = {}

        for node_id, node_data in semantic_memory.nodes.items():
            # Próbuj znaleźć source
            source = node_data.get("source", "unknown")
            if source not in ["self_learning", "perplexity", "ollama_web", "api"]:
                continue

            attrs = node_data.get("attributes", {}) or {}
            label = node_data.get("label", node_id)

            # Spróbuj znaleźć definition z attrs lub node_data
            definition = attrs.get("definition", node_data.get("definition", ""))

            learned_concepts[label] = {
                "definition": definition,
                "source": source,
                "confidence": node_data.get("confidence", 0.0),
                "learned_at": attrs.get("learned_at", ""),
            }

        export_data = {
            "timestamp": datetime.now().isoformat(),
            "total_learned": len(learned_concepts),
            "nodes": len(semantic_memory.nodes),
            "edges": len(semantic_memory.edges),
            "concepts": learned_concepts,
        }

        with open("maria_learned_concepts.json", "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        print(f"[Export] ✅ Exported {len(learned_concepts)} concepts to maria_learned_concepts.json")
    except Exception as e:
        print(f"[Export] ❌ Error: {e}")


def cmd_report():
    """Pokaż i zapisz pełny raport z nauki."""
    try:
        stats = {
            "nodes": len(semantic_memory.nodes),
            "edges": len(semantic_memory.edges),
            "episodes": len(episodic_memory),
            "successful_episodes": len([e for e in episodic_memory if e.get("success")]),
            "timestamp": datetime.now().isoformat(),
        }

        prompt = f"""
        Napisz krótki raport (3-5 zdań) o postępach w nauce.

        Statystyki:
        - Węzłów w grafie: {stats['nodes']}
        - Krawędzi: {stats['edges']}
        - Epizodów: {stats['episodes']}
        - Pomyślnych: {stats['successful_episodes']}

        Jakie są główne obszary nauki? Co nauczyłaś się najciekawszego?
        """

        report = maria_brain.think(prompt, temperature=0.3)

        print("\n" + "=" * 70)
        print("📊 MARIA'S LEARNING REPORT")
        print("=" * 70)
        print(f"Timestamp: {stats['timestamp']}")
        print(f"Nodes: {stats['nodes']} | Edges: {stats['edges']} | Episodes: {stats['episodes']}")
        success_rate = f"{stats['successful_episodes']}/{stats['episodes']}" if stats['episodes'] > 0 else "0/0"
        print(f"Success Rate: {success_rate}")
        print("=" * 70)
        print(report)
        print("=" * 70 + "\n")

        with open("maria_report.json", "w", encoding="utf-8") as f:
            json.dump(
                {"stats": stats, "report": report},
                f,
                indent=2,
                ensure_ascii=False,
            )

        print("[Report] ✅ Saved to maria_report.json")
        log_message("maria", f"[Report] {report}")

    except Exception as e:
        print(f"[Report] ❌ Error: {e}")


def cmd_hybrid():
    """Uruchom sekwencję: self-learning → web-learning → report."""
    print("[Hybrid] 🚀 Starting all learning sources...\n")

    # 1. Self-Learning
    if SELF_LEARNING_AVAILABLE:
        print("[1/3] Self-Learning...")
        cmd_learn(["0.7"])
        time.sleep(2)

    # 2. Web Learning (opcjonalnie Perplexity)
    if WEB_LEARNING_AVAILABLE:
        print("\n[2/3] Web Learning...")
        api_key = input("[Web Learning] Perplexity API Key (optional, Enter to skip): ").strip()
        if api_key:
            try:
                from maria_web_learning import WebLearningMode

                web_mode = WebLearningMode(None, perplexity_key=api_key, source="perplexity")
                _setup_learning_agent(web_mode)
                web_mode.run_cycle_with_web_learning()
            except Exception as e:
                print(f"[Web Learning] ❌ Error: {e}")
        else:
            print("[Web Learning] Skipped (no API key)")
        time.sleep(2)

    # 3. Raport
    print("\n[3/3] Generating report...")
    cmd_report()

    print("[Hybrid] ✅ All sources processed!")


# ====== AGENT WORKER ======
def agent_worker(loop):
    """Worker agenta w tle – rotuje zadania 'serwisowe'."""
    global AGENT_RUNNING, AGENT_SHOULD_STOP

    AGENT_RUNNING = True    # nie loguję, bo to raczej stan systemu, nie dialog
    AGENT_SHOULD_STOP = False

    tasks = [
        "Analizuj strukturę grafu i szukaj luk w wiedzy",
        "Wygeneruj nowe pytania wyjaśniające dla operatora",
        "Porównaj ostatnie epizody - co się poprawiło?",
        "Zaplanuj dalszą strategię nauki",
        "Szukaj wzorów w powiązaniach między pojęciami",
    ]

    task_idx = 0
    print("[Agent] ▶ Start pracy w tle...")

    while not AGENT_SHOULD_STOP:
        try:
            task = tasks[task_idx % len(tasks)]
            loop.process_perception(task)
            task_idx += 1
            time.sleep(10)
        except Exception as e:
            print(f"[Agent] ⚠ Error: {e}")

    AGENT_RUNNING = False
    print("[Agent] ⛔ Praca zatrzymana.")


# ====== GENERATE FOLLOWUP ======
def generate_followup_question(last_result: dict) -> str:
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
            "(maks 1-2 zdania), które pomoże Ci lepiej zrozumieć jego intencje. "
            f"Dane:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
            "Jeśli pytanie nie jest potrzebne, odpowiedz: NONE"
        )
        answer = maria_brain.think(prompt, temperature=0.2)
        return answer.strip()
    except Exception:
        return "NONE"


# ====== EXPLAIN STATUS ======
def explain_status(last_result: dict):
    """Maria wyjaśnia, co robi i jaki ma stan wiedzy."""
    if not last_result:
        print("[Status] Brak danych – jeszcze nic nie przetworzyliśmy.\n")
        return

    try:
        stats = {
            "nodes": len(semantic_memory.nodes),
            "edges": len(semantic_memory.edges),
            "episodes": len(episodic_memory),
            "learning_goals": len(last_result.get("learning_goals", [])),
            "unknown_terms": len(last_result.get("unknown_terms", [])),
        }

        prompt = (
            "Opisz w 3-4 zdaniach co aktualnie robisz, "
            "jak wygląda Twój proces (percepcja→analiza→pamięć), "
            "i co planujesz dalej.\n\n"
            f"Stats: {json.dumps(stats, ensure_ascii=False)}"
        )

        text = maria_brain.think(prompt, temperature=0.2)
        print("\n[Status]")
        print(text)
        print()
        log_message("maria", f"[Status] {text}")
    except Exception as e:
        print(f"[Status] ❌ Error: {e}")


# ====== GŁÓWNA FUNKCJA ======
def main():
    global AGENT_THREAD, AGENT_RUNNING, AGENT_SHOULD_STOP

    init_brain()

    print("\n" + "=" * 70)
    print("🤖 M.A.R.I.A. – ENHANCED LOCAL BRAIN INTERFACE v1.1")
    print("=" * 70)
    print("With Self-Learning, Web Learning, API Bridge, Query Interface")
    print(f"Model: {BRAIN_MODEL} | Nodes: {len(semantic_memory.nodes)}")
    print("=" * 70 + "\n")

    intro = maria_brain.think(
        "Przywitaj się z Erykiem. "
        "Powiedz kim jesteś (M.A.R.I.A. z pełnym systemem uczenia) "
        "i zadaj jedno pytanie o priorytecie nauki.",
        temperature=0.3,
    )
    print("Maria:", intro, "\n")
    log_message("maria", intro)

    last_result: dict = {}

    while True:
        try:
            user_input = input("Ty >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[System] Zamykam interfejs.")
            break

        if not user_input:
            continue

        # logujemy CAŁY input użytkownika (w tym komendy)
        log_message("user", user_input)

        # ===== KOMENDY =====
        if user_input.startswith("/"):
            parts = user_input.split()
            command = parts[0].lower()
            args = parts[1:] if len(parts) > 1 else []

            if command == "/help":
                print_help()

            elif command == "/exit":
                print("[System] Do zobaczenia, Operatorze.")
                break

            elif command == "/status":
                explain_status(last_result)

            elif command == "/episodes":
                if not episodic_memory:
                    print("[Episodes] Brak epizodów.\n")
                else:
                    print("\n[Episodes] Ostatnie epizody:")
                    for ep in episodic_memory[-5:]:
                        print(f"- {ep.get('timestamp', '?')} | success={ep.get('success')}")
                    print()

            elif command == "/nodes":
                if not semantic_memory.nodes:
                    print("[Graph] Brak węzłów.\n")
                else:
                    print("\n[Graph] Przykładowe węzły:")
                    for i, (nid, node) in enumerate(semantic_memory.nodes.items()):
                        if i >= 10:
                            break
                        print(f"- {nid}: {node['label']} (type={node['type']})")
                    print()

            elif command == "/save":
                try:
                    semantic_memory.save_to_json("semantic_graph.json")
                    print("[Graph] ✅ Zapisano do semantic_graph.json\n")
                except Exception as e:
                    print(f"[Graph] ❌ Error: {e}\n")

            elif command == "/load":
                try:
                    semantic_memory.load_from_json("semantic_graph.json")
                    print("[Graph] ✅ Wczytano z semantic_graph.json\n")
                except Exception as e:
                    print(f"[Graph] ❌ Error: {e}\n")

            elif command == "/start":
                if AGENT_RUNNING:
                    print("[System] Agent już pracuje.\n")
                else:
                    AGENT_THREAD = threading.Thread(
                        target=agent_worker,
                        args=(brain_loop,),
                        daemon=True,
                    )
                    AGENT_THREAD.start()
                    print("[System] ✅ Agent uruchomiony w tle.\n")

            elif command == "/stop":
                if not AGENT_RUNNING:
                    print("[System] Agent już zatrzymany.\n")
                else:
                    AGENT_SHOULD_STOP = True
                    print("[System] Zatrzymuję agenta...\n")

            elif command == "/reload":
                if AGENT_RUNNING:
                    print("[System] Najpierw zatrzymaj agenta komendą /stop.\n")
                else:
                    try:
                        importlib.reload(ollama_brain)
                        importlib.reload(brain_memory_integration)
                        init_brain()
                        print("[System] ✅ Przeładowano kod mózgu i pętli.\n")
                    except Exception as e:
                        print(f"[System] ❌ Error: {e}\n")

            elif command == "/learn":
                cmd_learn(args)

            elif command == "/learn-web":
                cmd_learn_web(args)

            elif command == "/teach":
                cmd_teach()

            elif command == "/ask":
                question = user_input[5:].strip()
                cmd_ask(question)

            elif command == "/export-learned":
                cmd_export_learned()

            elif command == "/report":
                cmd_report()

            elif command == "/hybrid":
                cmd_hybrid()

            else:
                print("[System] Nieznana komenda. /help dla listy.\n")

            continue

        # ===== NORMALNY TEKST → PERCEPCJA =====
        last_result = brain_loop.process_perception(user_input)

        print("\nMaria [Reasoning]:")
        reasoning = last_result.get("reasoning", "")
        print(reasoning[:500] if reasoning else "N/A")
        if reasoning:
            log_message("maria", f"[Reasoning] {reasoning}")

        if last_result.get("learning_goals"):
            print("\n[Goals]")
            for g in last_result["learning_goals"][:3]:
                print(f"- {g}")

        if last_result.get("unknown_terms"):
            print("\n[Unknown Terms]")
            for t in last_result["unknown_terms"][:5]:
                print(f"- {t}")

        followup = generate_followup_question(last_result)
        if followup and followup.upper() != "NONE":
            print("\nMaria [Pytanie]:")
            print(followup)
            log_message("maria", f"[Pytanie] {followup}")

        print("\n" + "-" * 70)


if __name__ == "__main__":
    main()
