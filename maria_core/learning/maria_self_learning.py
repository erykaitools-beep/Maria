# maria_self_learning.py
# Automatyczne uczenie się – Maria samodzielnie wyjaśnia nieznane zagadnienia
# WERSJA DLA: SemanticGraph + BrainMemoryLoop + main.py v1.1

import re
import json
from typing import Dict, Any, List, Optional, Set
from datetime import datetime

from models.ollama_brain import OllamaBrain


class MariaSelfLearner:
    """
    Self-Learning Mode dla Marii

    Proces:
    1. Maria czyta tekst (percepcję / opis)
    2. Ekstrahuje pojęcia/zagadnienia
    3. Sprawdza, co już zna w grafie
    4. Dla nieznanych pojęć pyta lokalny model (Ollama)
    5. Zapisuje wyjaśnienia jako węzły + relacje w SemanticGraph
    """

    def __init__(
        self,
        semantic_memory,
        maria_brain: OllamaBrain,
        log_fn=None,
        curiosity_threshold: float = 0.6,  # 0-1, jak ciekawy jest agent
    ):
        """
        :param semantic_memory: SemanticGraph
        :param maria_brain: OllamaBrain
        :param log_fn: Funkcja do logowania
        :param curiosity_threshold: Próg ciekawości (wyżej = więcej pytań)
        """
        self.semantic = semantic_memory
        self.brain = maria_brain
        self.log_fn = log_fn or print
        self.curiosity = curiosity_threshold

        # Statystyki uczenia się
        self.learned_concepts: Dict[str, Dict[str, Any]] = {}  # {concept: {...}}
        self.unknown_concepts: Set[str] = set()                # Pojęcia, których nie udało się wyjaśnić

        self.log_fn(
            f"[MariaSelfLearner] ✓ Initialized (curiosity={self.curiosity:.0%})"
        )

    # ========== EKSTRAKCJA POJĘĆ ==========

    def extract_concepts(self, text: str) -> List[str]:
        """
        Ekstrahuj główne pojęcia z tekstu.

        Szuka:
        - słów z DUŻYCH LITER (np. JSON, AGI)
        - fraz typu "jest X", "to X", "oznacza X"
        - tytułów sekcji przed dwukropkiem

        :return: Lista pojęć (lowercase, unikalne)
        """
        concepts: List[str] = []

        # 1. Słowa z DUŻYCH LITER
        uppercase_words = re.findall(r"\b[A-Z][A-Z_]+\b", text)
        concepts.extend(uppercase_words)

        # 2. Frazy definicyjne: "jest X", "to X", "oznacza X"
        definition_phrases = re.findall(
            r"(?:jest|to|oznacza)\s+([a-ząćęłńóśźżA-Z0-9\s\-]+?)(?:\.|,|;|$)",
            text,
            re.IGNORECASE,
        )
        concepts.extend([p.strip() for p in definition_phrases if len(p.strip()) > 3])

        # 3. Słowa przed dwukropkami (tytuły)
        titled_concepts = re.findall(
            r"([A-Za-ząćęłńóśźż0-9\s\-]+):\s*(?:\n|$)", text, re.IGNORECASE
        )
        concepts.extend([c.strip() for c in titled_concepts if len(c.strip()) > 3])

        # Normalizacja + deduplikacja
        concepts = [
            c.lower().strip()
            for c in concepts
            if len(c.strip()) > 2
        ]
        concepts = list(sorted(set(concepts)))

        self.log_fn(
            f"[MariaSelfLearner] [EXTRACT] Extracted concepts: {', '.join(concepts[:10]) or 'none'}"
        )
        return concepts

    # ========== SPRAWDZANIE WIEDZY ==========

    def check_knowledge(self, concept: str) -> bool:
        """
        Czy Maria już zna to pojęcie?

        True jeśli:
        - concept jest w learned_concepts
        - istnieje node w grafie o podobnej etykiecie
        """
        concept_lower = concept.lower()

        if concept_lower in self.learned_concepts:
            return True

        for node_id, node_data in self.semantic.nodes.items():
            label = str(node_data.get("label", "")).lower()
            if concept_lower == label or concept_lower in label or label in concept_lower:
                return True

        return False

    # ========== UCZENIE POJĘCIA ==========

    def learn_concept(self, concept: str, temperature: float = 0.2) -> Dict[str, Any]:
        """
        Maria samodzielnie uczy się pojedynczego pojęcia.

        1. Sprawdza, czy już je zna
        2. Jeśli nie – pyta Ollamę o krótkie wyjaśnienie
        3. Zapisuje jako node typu 'concept' + relację z kontenerem 'Knowledge Base'
        """
        self.log_fn(f"\n[MariaSelfLearner] [THINK] Learning concept: '{concept}'")

        if self.check_knowledge(concept):
            self.log_fn(f"[MariaSelfLearner] [OK] Already knows: {concept}")
            return {
                "concept": concept,
                "status": "already_known",
                "definition": "Already in memory",
                "learned": False,
            }

        prompt = f"""
Wyjaśnij w maksymalnie 2 zdaniach, co to jest: "{concept}".

Odpowiedź:
"""

        self.log_fn("[MariaSelfLearner] [BRAIN] Asking local model (Ollama)...")
        definition = self.brain.think(prompt, temperature=temperature).strip()

        if not definition:
            self.log_fn(f"[MariaSelfLearner] [WARN] Empty definition for: {concept}")
            self.unknown_concepts.add(concept)
            return {
                "concept": concept,
                "status": "empty",
                "definition": "",
                "learned": False,
            }

        if "nie znam" in definition.lower():
            self.log_fn(f"[MariaSelfLearner] [WARN] Model doesn't know: {concept}")
            self.unknown_concepts.add(concept)
            return {
                "concept": concept,
                "status": "unknown",
                "definition": definition,
                "learned": False,
            }

        # Zapisz lokalnie
        now_iso = datetime.now().isoformat()
        self.learned_concepts[concept.lower()] = {
            "definition": definition,
            "timestamp": now_iso,
            "source": "self_learning",
        }

        # Zapisz w grafie semantycznym
        try:
            concept_node_id = self.semantic.add_node(
                label=concept,
                node_type="concept",
                attributes={
                    "definition": definition,
                    "learned_at": now_iso,
                },
                confidence=0.8,
                source="self_learning",
            )

            knowledge_node_id = self.semantic.add_node(
                label="Knowledge Base",
                node_type="container",
                attributes={},
                confidence=0.9,
                source="self_learning",
            )

            self.semantic.add_edge(
                from_id=knowledge_node_id,
                relation="contains",
                to_id=concept_node_id,
                weight=1.0,
                confidence=0.8,
                source="self_learning",
            )

            self.log_fn(f"[MariaSelfLearner] [OK] Learned: {concept}")
            self.log_fn(
                f"[MariaSelfLearner] [DEF] Definition: {definition[:100]}..."
            )

            return {
                "concept": concept,
                "status": "learned",
                "definition": definition,
                "learned": True,
                "node_id": concept_node_id,
            }

        except Exception as e:
            self.log_fn(f"[MariaSelfLearner] [WARN] Failed to add to graph: {e}")
            return {
                "concept": concept,
                "status": "error",
                "definition": definition,
                "learned": False,
                "error": str(e),
            }

    # ========== AUTO-LEARNING Z TEKSTU ==========

    def auto_learn_from_perception(
        self,
        text: str,
        max_concepts: int = 5,
        curiosity_override: bool = False,
    ) -> Dict[str, Any]:
        """
        Automatyczne uczenie się z jednego tekstu (percepcji).
        """
        self.log_fn(
            f"\n[MariaSelfLearner] [LEARN] Auto-learning from text ({len(text)} chars)"
        )

        concepts = self.extract_concepts(text)
        unknown = [c for c in concepts if not self.check_knowledge(c)]

        self.log_fn(f"[MariaSelfLearner] [EXTRACT] Extracted: {len(concepts)}")
        self.log_fn(f"[MariaSelfLearner] [UNKNOWN] Unknown: {len(unknown)}")

        if curiosity_override:
            to_learn = unknown[:max_concepts]
        else:
            import random

            to_learn = []
            for c in unknown:
                if random.random() < self.curiosity:
                    to_learn.append(c)
                if len(to_learn) >= max_concepts:
                    break

        self.log_fn(
            f"[MariaSelfLearner] [TARGET] Learning {len(to_learn)} concepts "
            f"(curiosity={self.curiosity:.0%})"
        )

        results = [self.learn_concept(c) for c in to_learn]
        learned_count = len([r for r in results if r.get("learned")])

        return {
            "timestamp": datetime.now().isoformat(),
            "total_concepts_extracted": len(concepts),
            "unknown_concepts": len(unknown),
            "attempted_to_learn": len(to_learn),
            "successfully_learned": learned_count,
            "results": results,
            "learned_concepts_total": len(self.learned_concepts),
        }

    # ========== RAPORTY ==========

    def get_learning_report(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.now().isoformat(),
            "learned_concepts": len(self.learned_concepts),
            "unknown_concepts": len(self.unknown_concepts),
            "known_nodes_in_graph": len(self.semantic.nodes),
            "concepts": self.learned_concepts,
            "unknowns": list(self.unknown_concepts),
        }

    def export_learning(self, filepath: str):
        data = {
            "timestamp": datetime.now().isoformat(),
            "learned_concepts": self.learned_concepts,
            "unknown_concepts": list(self.unknown_concepts),
            "total_learned": len(self.learned_concepts),
            "graph_snapshot": {
                "nodes": len(self.semantic.nodes),
                "edges": len(self.semantic.edges),
            },
        }
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.log_fn(f"[MariaSelfLearner] [SAVE] Learning exported: {filepath}")
        except Exception as e:
            self.log_fn(f"[MariaSelfLearner] [WARN] Export failed: {e}")


class SelfLearningMode:
    """
    Cienka warstwa integracji z main.py
    - w main.py tworzysz: SelfLearningMode(None, curiosity)
    - potem _setup_learning_agent(...) wstrzykuje:
        .semantic_memory
        .brain
        .agent (BrainMemoryLoop)
    """

    def __init__(self, agent=None, curiosity: float = 0.6):
        self.agent = agent  # w praktyce BrainMemoryLoop, ale może być None przy starcie
        self.curiosity = curiosity

        self.semantic_memory = None   # wstrzykiwane przez main.py
        self.brain: Optional[OllamaBrain] = None
        self.log_fn = print

        self.learner: Optional[MariaSelfLearner] = None

    def _ensure_bound(self):
        """
        Upewnij się, że mamy semantic_memory + brain + learner.
        Wywoływane na początku run_cycle_with_learning().
        """
        # main.py ustawia te atrybuty:
        # agent_obj.semantic_memory = semantic_memory
        # agent_obj.brain = maria_brain
        # agent_obj.agent = brain_loop

        if self.semantic_memory is None and hasattr(self, "semantic_memory"):
            # atrybut już podpięty przez main
            pass

        if self.brain is None and hasattr(self, "brain"):
            # atrybut już podpięty przez main
            pass

        # jeśli dalej brakuje – spróbuj z self.agent (BrainMemoryLoop)
        if self.semantic_memory is None and self.agent is not None:
            if hasattr(self.agent, "semantic"):
                self.semantic_memory = self.agent.semantic

        if self.brain is None and self.agent is not None:
            if hasattr(self.agent, "maria_brain"):
                self.brain = self.agent.maria_brain

        if self.agent is not None and hasattr(self.agent, "log_fn"):
            self.log_fn = self.agent.log_fn

        if self.semantic_memory is None or self.brain is None:
            raise RuntimeError(
                "SelfLearningMode not properly bound – missing semantic_memory or brain."
            )

        if self.learner is None:
            self.learner = MariaSelfLearner(
                semantic_memory=self.semantic_memory,
                maria_brain=self.brain,
                log_fn=self.log_fn,
                curiosity_threshold=self.curiosity,
            )

    def run_cycle_with_learning(self):
        """
        Jeden prosty cykl auto-nauki:
        - pyta operatora o tekst do nauki
        - robi auto_learn_from_perception(...)
        """
        self._ensure_bound()

        text = input(
            "[Self-Learning] Podaj tekst/percepcję, z której mam się uczyć:\n> "
        ).strip()
        if not text:
            self.log_fn("[Self-Learning] Brak tekstu – przerwane.")
            return

        report = self.learner.auto_learn_from_perception(
            text,
            max_concepts=5,
            curiosity_override=False,
        )

        self.log_fn(
            f"[Self-Learning] [OK] Learned {report['successfully_learned']} "
            f"/ {report['attempted_to_learn']} concepts "
            f"(extracted={report['total_concepts_extracted']})"
        )

    def show_learning_progress(self):
        """Prosty podgląd postępów."""
        if not self.learner:
            print("[Self-Learning] Brak learner'a – nic jeszcze się nie uczyłam.")
            return

        report = self.learner.get_learning_report()

        print("\n" + "=" * 70)
        print("[PROGRESS] MARIA'S LEARNING PROGRESS")
        print("=" * 70)
        print(f"Concepts Learned (in this session): {report['learned_concepts']}")
        print(f"Concepts in Graph (nodes): {report['known_nodes_in_graph']}")
        print(f"Unknown concepts: {report['unknown_concepts']}")
        print("\nRecently Learned:")
        for concept, data in list(report["concepts"].items())[-5:]:
            ts = data["timestamp"][:10]
            print(f"  • {concept}: {data['definition'][:60]}... ({ts})")
        print("=" * 70 + "\n")

    def export_learning(self, filepath: str):
        if not self.learner:
            print("[Self-Learning] Nic do eksportu.")
            return
        self.learner.export_learning(filepath)
        self.log_fn(f"[Self-Learning] [OK] Learning exported to {filepath}")
