# brain_memory_integration.py
# M.A.R.I.A. Pipeline V3.1 – Zintegrowana pętla z obsługą błędów, refleksją i celami nauki

from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from models.ollama_brain import OllamaBrain   # ⬅ ważne: bez _v3, bo plik nazywa się ollama_brain.py


class BrainMemoryLoop:
    def __init__(
        self,
        semantic_memory,             # Twój obiekt SemanticGraph
        episodic_memory: List[Dict], # Lista epizodów (np. [] na start)
        maria_brain: Optional[OllamaBrain] = None,  # Opcjonalny mózg
        chunk_size: int = 1500,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.semantic = semantic_memory
        self.episodic = episodic_memory
        self.log_fn = log_fn or print
        self.chunk_size = chunk_size

        # Inicjalizacja mózgu (jeśli nie podano, stwórz nowy)
        if maria_brain is not None:
            self.maria_brain = maria_brain
        else:
            self.maria_brain = OllamaBrain(log_fn=self.log_fn)

        self.log_fn("[BrainMemoryLoop] ✓ System Gotowy (V3.1 Stable)")

    # === TEKST NA CHUNKI ===

    def split_large_text(self, text: str) -> List[str]:
        """Inteligentne dzielenie tekstu po akapitach."""
        if len(text) < self.chunk_size:
            return [text]

        chunks: List[str] = []
        current_chunk = ""

        for para in text.split("\n\n"):
            if len(current_chunk) + len(para) < self.chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

        # === GŁÓWNA PĘTLA PERCEPCJI ===

    def process_perception(self, perception: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Główna pętla przetwarzania.
        Teraz zawiera:
        - analizę LLM z retry (JSON),
        - zapis faktów do grafu,
        - zbieranie celów nauki i nieznanych pojęć,
        - AUTO-WYJAŚNIANIE nieznanych pojęć,
        - epizod + auto-refleksję.

        context: opcjonalny opis kontekstu (np. 'logika formalna', 'kurs programowania')
        """
        self.log_fn(
            f"\n[M.A.R.I.A.] 👁 Odbieram percepcję ({len(perception)} znaków), context={context!r}"
        )

        chunks = self.split_large_text(perception)
        processed_stats = {"facts": 0, "errors": 0}
        final_reasoning = ""

        all_learning_goals: List[str] = []
        all_unknown_terms: List[str] = []

        for i, chunk in enumerate(chunks):
            self.log_fn(f"[Loop] Przetwarzam fragment {i + 1}/{len(chunks)}...")

            # Krok 1: Analiza LLM (z mechanizmem retry)
            analysis = self.maria_brain.analyze_task(chunk)

            facts = analysis.get("memory_facts", [])
            learning_goals = analysis.get("learning_goals", []) or []
            unknown_terms = analysis.get("unknown_terms", []) or []

            # Zbieranie celów i pojęć
            all_learning_goals.extend(learning_goals)
            all_unknown_terms.extend(unknown_terms)

            # Krok 2: Zapis do Grafu (Pamięć Semantyczna)
            for fact in facts:
                try:
                    if not isinstance(fact, (list, tuple)) or len(fact) != 3:
                        # ignorujemy błędne rekordy zamiast crasha
                        self.log_fn(f"[Loop] ⚠ Pomijam niepoprawny fakt: {fact}")
                        processed_stats["errors"] += 1
                        continue

                    subj, rel, obj = fact

                    # API grafu – dopasuj do swojego SemanticGraph
                    if hasattr(self.semantic, "add_triple"):
                        self.semantic.add_triple(str(subj), str(rel), str(obj))
                    else:
                        # Minimalny, bezpieczny fallback
                        if hasattr(self.semantic, "add_node") and hasattr(self.semantic, "add_edge"):
                            s_id = self.semantic.add_node(str(subj))
                            o_id = self.semantic.add_node(str(obj))
                            self.semantic.add_edge(s_id, str(rel), o_id)
                        else:
                            self.log_fn(
                                "[Loop] ⚠ Brak obsługiwanych metod grafu (add_triple / add_node + add_edge)."
                            )
                            processed_stats["errors"] += 1
                            continue

                    processed_stats["facts"] += 1

                except Exception as e:
                    self.log_fn(f"[Loop] ⚠ Błąd zapisu do grafu: {e}")
                    processed_stats["errors"] += 1

            # Krok 3: Rozumowanie (na pierwszym fragmencie – można rozszerzyć)
            if i == 0:
                reasoning_prompt = (
                    f"Na podstawie faktów: {facts}, "
                    f"oraz analizy zadania: {analysis.get('main_task')}, "
                    f"opisz krótko (max 3 zdania), co M.A.R.I.A. powinna zrobić dalej."
                )
                final_reasoning = self.maria_brain.think(reasoning_prompt, temperature=0.2)

        # Usunięcie duplikatów, zachowanie kolejności
        def unique(seq: List[str]) -> List[str]:
            seen = set()
            out = []
            for x in seq:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        all_learning_goals = unique(all_learning_goals)
        all_unknown_terms = unique(all_unknown_terms)

        # Krok 4: AUTO-WYJAŚNIANIE nieznanych pojęć
        learning_explanations = ""
        if all_unknown_terms:
            try:
                explain_prompt = (
                    "Wyjaśnij zwięźle (2–3 zdania każde) następujące pojęcia "
                    "tak, jakbyś tłumaczyła je M.A.R.I.I uczącej się nowych rzeczy:\n"
                    f"{', '.join(all_unknown_terms)}"
                )
                learning_explanations = self.maria_brain.think(
                    explain_prompt, temperature=0.2
                )
            except Exception as e:
                self.log_fn(f"[Auto-Explain] ⚠ Błąd podczas wyjaśniania pojęć: {e}")
                learning_explanations = ""

        # Krok 5: Epizod i Refleksja
        success_status = processed_stats["errors"] == 0
        episode: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "input_snippet": perception[:80],
	    "context": context,
            "stats": processed_stats,
            "success": success_status,
            "learning_goals": all_learning_goals,
            "unknown_terms": all_unknown_terms,
            "had_explanation": bool(learning_explanations),
        }
        self.episodic.append(episode)

        if not success_status:
            self.log_fn(
                "[Auto-Reflection] ⚠ Wykryto problemy w procesie. Zapisuję flagę do pamięci epizodycznej."
            )

        return {
            "status": "completed",
            "reasoning": final_reasoning,
            "stats": processed_stats,
            "learning_goals": all_learning_goals,
            "unknown_terms": all_unknown_terms,
            "learning_explanations": learning_explanations,
            "episode": episode,
        }
