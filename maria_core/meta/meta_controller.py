# maria_core/meta/meta_controller.py
import json
import time
import os
from datetime import datetime
from pathlib import Path
import requests

from maria_core.meta.meta_config import (
    META_STATE_FILE,
    REWARDS_LOG,
    DECISIONS_LOG,
    TRAUMA_LOG,
    EMERGENCY_STOP_FILE,
    Mode,
    Goal,
    REWARD_CHUNK_LEARNED,
    PENALTY_CRASH,
    PENALTY_LOOP_DETECTED,
    PENALTY_MEMORY_ERROR,
    PENALTY_THRESHOLD_RECOVERY,
    REWARD_THRESHOLD_EXIT_RECOVERY,
    MOTIVATION_THRESHOLD_SLEEP,
    CRASH_STREAK_FOR_TRAUMA,
)

# Definicja LOGS_DIR (jeśli nie ma w config)
LOGS_DIR = Path(__file__).parent.parent.parent / "data" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class MetaController:
    """
    Warstwa meta-sterowania dla całego systemu Maria.
    Trzyma:
      - aktualny tryb (learning/testing/recovery/sleep/demo)
      - aktualny główny cel
      - sumę nagród / kar
      - uptime
      - serię crashy / traumy
    """

    def __init__(self) -> None:
        self.state_file = META_STATE_FILE
        self._ensure_log_files()
        self.state = self._load_state()

    # ================== PROPERTY ==================
    
    @property
    def current_mode(self) -> Mode:
        """Wygodny dostęp do aktualnego trybu."""
        return self.state["current_mode"]
    
    @property
    def current_goal(self) -> Goal:
        """Wygodny dostęp do aktualnego celu."""
        return self.state["current_goal"]

    # ================== INIT / PLIK STANU ==================

    def _ensure_log_files(self) -> None:
        """Tworzy puste pliki logów, jeśli nie istnieją."""
        for path in (REWARDS_LOG, DECISIONS_LOG, TRAUMA_LOG):
            if not path.exists():
                path.write_text("", encoding="utf-8")

    def _load_state(self) -> dict:
        default = {
            "version": "1.5",
            "system_start_time": time.time(),
            "current_session_start": time.time(),
            "total_uptime_hours": 0.0,
            "total_reward": 0.0,
            "total_penalty": 0.0,
            "current_mode": Mode.LEARNING,
            "current_goal": Goal.EXPAND_VOCABULARY,
            "crash_streak": 0,
            "trauma_events": [],
            "last_decision": None,
            "last_decision_reason": "init",
        }

        if self.state_file.exists():
            try:
                raw = json.loads(self.state_file.read_text(encoding="utf-8"))
                # Konwersja string -> Enum dla zgodności wstecz
                if "current_mode" in raw:
                    raw["current_mode"] = Mode(raw["current_mode"])
                if "current_goal" in raw:
                    raw["current_goal"] = Goal(raw["current_goal"])
                default.update(raw)
            except Exception:
                # jak plik popsuty → lecimy na default
                pass

        return default

    def _save(self) -> None:
        """Zapisuje stan + aktualizuje uptime."""
        session_hours = (time.time() - self.state["current_session_start"]) / 3600.0
        self.state["total_uptime_hours"] += max(0.0, session_hours)
        self.state["current_session_start"] = time.time()

        # Enumy zapisujemy jako stringi
        to_save = self.state.copy()
        to_save["current_mode"] = self.state["current_mode"].value
        to_save["current_goal"] = self.state["current_goal"].value

        self.state_file.write_text(
            json.dumps(to_save, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ================== NAGRODY / KARY ==================

    def reward(self, value: float, reason: str = "") -> None:
        self.state["total_reward"] += float(value)
        self._log_reward(value, reason)
        self._save()

    def penalty(self, value: float, reason: str = "") -> None:
        self.state["total_penalty"] += float(value)
        self._log_reward(-value, reason)
        self._check_emergency()
        self._save()

    def get_motivation_score(self) -> float:
        """
        Prosty "nastrój" systemu:
          nagrody - 1.5 * kary - (uptime * decay)
        """
        base = self.state["total_reward"] - (self.state["total_penalty"] * 1.5)

        if self.state["total_uptime_hours"] < 24:
            decay = 0.02
        elif self.state["total_uptime_hours"] < 168:
            decay = 0.05
        else:
            decay = 0.08

        decayed = base - (self.state["total_uptime_hours"] * decay)
        return round(max(-20.0, decayed), 2)

    # ================== TRYBY / CELE ==================

    def set_mode(self, mode: str | Mode, reason: str = "manual") -> None:
        mode_enum = Mode(mode)
        self.state["current_mode"] = mode_enum
        self.state["last_decision_reason"] = f"mode → {mode_enum.value} ({reason})"
        self._log_decision("set_mode", mode_enum.value, reason)
        self._save()

    def set_goal(self, goal: str | Goal, reason: str = "manual") -> None:
        goal_enum = Goal(goal)
        self.state["current_goal"] = goal_enum
        self.state["last_decision_reason"] = f"goal → {goal_enum.value} ({reason})"
        self._log_decision("set_goal", goal_enum.value, reason)
        self._save()

    def should_sleep(self) -> bool:
        """Czy system powinien wejść w tryb 'sleep'."""
        return self.get_motivation_score() <= MOTIVATION_THRESHOLD_SLEEP or (
            2 <= datetime.now().hour <= 5
            and self.state["current_mode"] != Mode.RECOVERY
        )

    def is_learning_allowed(self) -> bool:
        """Czy wolno teraz uczyć (learning / testing)."""
        return self.state["current_mode"] in {Mode.LEARNING, Mode.TESTING}

    # ================== ZDARZENIA KRYTYCZNE ==================

    def register_crash(self) -> None:
        """Rejestruje crash systemu / agenta."""
        self.state["crash_streak"] += 1
        self.penalty(PENALTY_CRASH, "system crash")

        if self.state["crash_streak"] >= CRASH_STREAK_FOR_TRAUMA:
            self._add_trauma("crash_streak", self.state["crash_streak"])

    def register_memory_error(self) -> None:
        """Specjalna kara za MemoryError – możesz wywołać w except MemoryError."""
        self.penalty(PENALTY_MEMORY_ERROR, "MemoryError detected")

    def register_loop(self) -> None:
        self.penalty(PENALTY_LOOP_DETECTED, "loop detected")

    def _add_trauma(self, type_: str, count: int) -> None:
        event = {
            "type": type_,
            "count": count,
            "timestamp": time.time(),
            "recovered": False,
        }
        self.state["trauma_events"].append(event)
        # log do osobnego pliku
        self._append_jsonl(TRAUMA_LOG, event)
        self.set_mode(Mode.RECOVERY, "trauma detected")

    # ================== EMERGENCY / KILL-SWITCH ==================

    def _check_emergency(self) -> None:
        """Sprawdza EMERGENCY_STOP + bardzo niską motywację."""
        if EMERGENCY_STOP_FILE.exists():
            print("\n[EMERGENCY] STOP FILE DETECTED – SHUTTING DOWN NOW!")
            os._exit(0)

        if self.get_motivation_score() < -15:
            self.set_mode(Mode.RECOVERY, "motivation critical")

    # ================== LOGOWANIE ==================

    def _append_jsonl(self, path, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _log_reward(self, value: float, reason: str) -> None:
        event = {
            "ts": time.time(),
            "value": float(value),
            "reason": reason,
        }
        self._append_jsonl(REWARDS_LOG, event)

    def _log_decision(self, action: str, target: str, reason: str) -> None:
        event = {
            "ts": time.time(),
            "action": action,
            "target": target,
            "reason": reason,
        }
        self._append_jsonl(DECISIONS_LOG, event)

    # ================== API DLA DAEMONA ==================

    def log_decision(self, decision: str, reason: str = "") -> None:
        """Prosty wrapper jeśli chcesz logować własne decyzje tekstowo."""
        self.state["last_decision"] = decision
        self.state["last_decision_reason"] = reason
        self._log_decision("custom", decision, reason)
        self._save()

    def get_status_summary(self) -> str:
        m = self.get_motivation_score()
        if m > 10:
            emoji = "Znakomita"
        elif m > 0:
            emoji = "Dobra"
        elif m > -8:
            emoji = "Słaba"
        else:
            emoji = "Krytyczna"

        return (
            f"[META] Tryb: {self.state['current_mode'].value} | "
            f"Cel: {self.state['current_goal'].value} | "
            f"Motywacja: {m} ({emoji}) | "
            f"Uptime: {self.state['total_uptime_hours']:.1f}h"
        )

    # ================== NOWE METODY ==================
    
    def raport_do_taty(self, title: str, content: str) -> None:
        """
        Wysyła raport administratorowi.
        MVP: zapisuje do logu + wyświetla w konsoli.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        raport = {
            "timestamp": timestamp,
            "title": title,
            "content": content,
            "motivation": self.get_motivation_score(),
            "mode": self.state["current_mode"].value,
            "goal": self.state["current_goal"].value,
            "uptime_hours": round(self.state["total_uptime_hours"], 2),
        }
        
        # 1. Zapisz do pliku logów
        REPORTS_LOG = LOGS_DIR / "reports.jsonl"
        try:
            self._append_jsonl(REPORTS_LOG, raport)
        except Exception as e:
            print(f"[RAPORT] [WARN] Nie udalo sie zapisac do pliku: {e}")

        # 2. Wyswietl w konsoli
        print(f"\n{'='*60}")
        print(f"[RAPORT DO TATY] {title}")
        print(f"{content}")
        print(f"Motywacja: {raport['motivation']} | Uptime: {raport['uptime_hours']}h")
        print(f"{'='*60}\n")

    def update_goal(self, goal_description: str, reason: str = "morning_reflection") -> None:
        """
        Aktualizuje cel jako wolny tekst (nie enum).
        Uzywane przez poranna refleksje LLM.
        """
        self.state["current_goal_description"] = goal_description
        self.state["last_decision_reason"] = f"goal updated: {goal_description[:50]}"
        self._log_decision("update_goal", goal_description, reason)
        self._save()
        print(f"[META] [GOAL] Nowy cel: {goal_description}")


# Singleton do użycia wszędzie
meta = MetaController()
