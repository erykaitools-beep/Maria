#!/usr/bin/env python3
"""
Benchmark script for Model Registry v2 candidates.

Tests:
1. TRIAGE: qwen3:1.7b vs rule-based heuristic_classify()
2. PLANNER: qwen3:8b vs llama3.1:8b on reasoning tasks

Usage: python scripts/benchmark_models.py
"""

import json
import time
import subprocess
import sys

# ─── Test cases ──────────────────────────────────────────────

# Triage: prompt -> expected TaskType
TRIAGE_CASES = [
    # CODE
    ("Napraw bug w pliku test_teacher.py - assertEqual nie dziala", "code"),
    ("Napisz funkcje ktora parsuje JSONL i zwraca ostatni rekord", "code"),
    ("Zrefaktoruj class SandboxManager - za duzo metod", "code"),
    ("import numpy nie dziala po pip install", "code"),
    # PLAN
    ("Zaplanuj migracje bazy danych z JSONL na SQLite", "plan"),
    ("Jaka powinna byc architektura modulu Vision?", "plan"),
    ("Przeanalizuj czy warto dodac semantic memory zamiast keyword search", "plan"),
    ("Jak powinien wygladac deployment pipeline dla nowych modeli?", "plan"),
    # SUMMARIZE
    ("Podsumuj co Maria nauczyla sie w ostatnim tygodniu", "summarize"),
    ("Skompresuj te notatki do 3 zdaen", "summarize"),
    ("Wyciagnij kluczowe fakty z tego artykulu", "summarize"),
    ("Zrob brief z ostatnich 10 egzaminow", "summarize"),
    # CLASSIFY
    ("Sklasyfikuj ten tekst - czy to nauka czy literatura?", "classify"),
    ("Oznacz tagami ten artykul o fizyce kwantowej", "classify"),
    ("Jaki typ zadania to jest?", "classify"),
    # GENERAL / CHAT
    ("Czesc, jak sie masz?", "general"),
    ("Ile masz lat?", "general"),
    ("Opowiedz mi cos ciekawego o kosmosie", "general"),
    ("Dzieki za pomoc!", "general"),
    # LEARN/EXAM (special - current heuristic maps to GENERAL)
    ("Naucz sie tego artykulu o archeologii", "learn"),
    ("Przygotuj egzamin z ostatniego materialu", "exam"),
]

# Planner: reasoning quality prompts
PLANNER_CASES = [
    {
        "prompt": (
            "Maria ma 109 plikow completed, zero nowych. "
            "Spaced repetition sugeruje 5 plikow do powtorki. "
            "NIM budget wyczerpany (101k/100k). "
            "Jaki powinien byc nastepny krok? Wymien 3 opcje z priorytetami."
        ),
        "check_keywords": ["powtorka", "spaced", "Ollama", "fallback", "priorytet"],
    },
    {
        "prompt": (
            "System ma 32GB RAM. Aktualnie zaladowane: llama3.1:8b (5GB), "
            "qwen2.5:3b (2GB). Potrzebujesz zaladowac qwen3:8b (5.5GB) do planowania. "
            "Czy jest wystarczajaco RAM? Jesli nie, co zwolnic? "
            "Pamietaj: llama3.1:8b to P0 (nie ubijac), qwen2.5:3b to P4."
        ),
        "check_keywords": ["RAM", "32", "zwolni", "P4", "wystarczajaco"],
    },
    {
        "prompt": (
            "Maria uczy sie z plikow tekstowych. Obecna retencja: 83%. "
            "Cel: 90%. Dostepne strategie: 1) wiecej powtore, 2) mniejsze chunki, "
            "3) trudniejsze pytania egzaminacyjne. "
            "Ktora strategia da najlepszy efekt i dlaczego?"
        ),
        "check_keywords": ["retencja", "powtork", "chunk", "strategia"],
    },
]


def ollama_generate(model: str, prompt: str, timeout: int = 60) -> dict:
    """Call ollama API and return response + timing."""
    import urllib.request
    start = time.time()
    try:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 256},
            "think": False,
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        elapsed = time.time() - start
        return {
            "response": data.get("response", "").strip(),
            "stderr": "",
            "elapsed_s": round(elapsed, 2),
            "ok": True,
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "response": "",
            "stderr": str(e)[:100],
            "elapsed_s": round(elapsed, 2),
            "ok": False,
        }


def run_triage_benchmark():
    """Benchmark qwen3:1.7b as triage classifier vs rule-based."""
    print("=" * 70)
    print("BENCHMARK 1: TRIAGE - qwen3:1.7b vs rule-based")
    print("=" * 70)

    # Import rule-based classifier
    sys.path.insert(0, ".")
    from agent_core.llm.routing_rules import heuristic_classify

    triage_prompt_template = (
        "Classify this task into exactly ONE category. "
        "Categories: code, plan, summarize, classify, general, learn, exam\n"
        "Respond with ONLY the category name, nothing else.\n\n"
        "Task: {task}"
    )

    results = {"rule_based": {"correct": 0, "total": 0, "time_ms": 0},
               "qwen3_1.7b": {"correct": 0, "total": 0, "time_ms": 0}}

    print(f"\n{'Prompt':<55} {'Expected':<10} {'Rules':<10} {'qwen3:1.7b':<12} {'Time'}")
    print("-" * 100)

    for prompt, expected in TRIAGE_CASES:
        # Rule-based
        start = time.time()
        rule_result = heuristic_classify(prompt).value
        rule_time = (time.time() - start) * 1000

        results["rule_based"]["total"] += 1
        results["rule_based"]["time_ms"] += rule_time
        rule_correct = rule_result == expected
        if rule_correct:
            results["rule_based"]["correct"] += 1

        # qwen3:1.7b (think=False via API)
        llm_prompt = triage_prompt_template.format(task=prompt)
        llm = ollama_generate("qwen3:1.7b", llm_prompt, timeout=60)
        llm_result = llm["response"].strip().lower().split()[0] if llm["response"] else "error"
        # Clean up common LLM formatting
        llm_result = llm_result.strip(".*:\"'`")
        llm_time = llm["elapsed_s"] * 1000

        results["qwen3_1.7b"]["total"] += 1
        results["qwen3_1.7b"]["time_ms"] += llm_time
        llm_correct = llm_result == expected
        if llm_correct:
            results["qwen3_1.7b"]["correct"] += 1

        r_mark = "OK" if rule_correct else "MISS"
        l_mark = "OK" if llm_correct else "MISS"

        print(f"{prompt[:53]:<55} {expected:<10} {rule_result:<5}{r_mark:<5} {llm_result:<7}{l_mark:<5} {llm['elapsed_s']:.1f}s")

    print("\n--- SUMMARY ---")
    for name, r in results.items():
        acc = r["correct"] / r["total"] * 100 if r["total"] else 0
        avg_ms = r["time_ms"] / r["total"] if r["total"] else 0
        print(f"{name:<15} accuracy={acc:.0f}% ({r['correct']}/{r['total']})  avg={avg_ms:.1f}ms")


def run_planner_benchmark():
    """Benchmark qwen3:8b vs llama3.1:8b on reasoning tasks."""
    print("\n" + "=" * 70)
    print("BENCHMARK 2: PLANNER - qwen3:8b vs llama3.1:8b")
    print("=" * 70)

    models = ["llama3.1:8b", "qwen3:8b"]

    for i, case in enumerate(PLANNER_CASES, 1):
        print(f"\n--- Case {i} ---")
        print(f"Prompt: {case['prompt'][:80]}...")
        print()

        for model in models:
            print(f"  [{model}]")
            result = ollama_generate(model, case["prompt"], timeout=300)

            if result["ok"]:
                response = result["response"]
                # Check for keywords
                found = [kw for kw in case["check_keywords"]
                         if kw.lower() in response.lower()]
                missing = [kw for kw in case["check_keywords"]
                           if kw.lower() not in response.lower()]

                print(f"    Time: {result['elapsed_s']}s")
                print(f"    Keywords found: {len(found)}/{len(case['check_keywords'])} {found}")
                if missing:
                    print(f"    Missing: {missing}")
                # Show first 300 chars of response
                print(f"    Response: {response[:300]}...")
            else:
                print(f"    ERROR: {result['stderr'][:100]}")
            print()


if __name__ == "__main__":
    print("M.A.R.I.A. Model Benchmark v1")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    run_triage_benchmark()
    run_planner_benchmark()

    print("\n" + "=" * 70)
    print("BENCHMARK COMPLETE")
    print("=" * 70)
