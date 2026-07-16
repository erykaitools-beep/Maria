"""Decision Tap -- obserwowalnosc plannera K5 (CEGLA 2, krok 0 wg BLUEPRINT 7.4.D).

USPIONY: ten modul NIE jest nigdzie importowany. Wpiecie w run_cycle = dotkniecie produkcji ->
review + restart przez operatora (patrz WIRING na dole). Do tego czasu zero efektu na demona.

Cel: zrzucic PELNA ramke wejsciowa decyzji ("czemu planner wybral X" -- dzis nieodtwarzalne z
decision_traces). Ramka niesie te same DANE co konsumuje cegla2_interpreter/differential, ale w innym
KSZTALCIE -- replay adapter (WIRING krok 5) MUSI zrobic pivot, inaczej naiwny replay po cichu zle
dekoduje galezie (shadow-of-self tego NIE zlapie -- interp i oracle czytaja ten sam brakujacy klucz):
  - candidates[list]                    -> per-goal frame['goal'] (iteruj kandydatow)
  - kandydat.backed_off_learn           -> hidden.backed_off[action]
  - kandydat.project_child_material_count -> ext.project_child_material_count
  - snapshot_digest.has_*/present       -> snapshot.files_by_status.* / is_null(snapshot)
ZAKRES: tylko exit_path="goal_loop" (taktyczny lancuch transpilowany w cegle 2). creative/effector
pre-goal to INNE decyzje -> metryke etykietuj "goal_loop-conditioned escape-hatch" (bias konserwatywny:
pomija sciezki escape=0 -> zawyza escape, nie da falszywego PASS). K8 deliberation poza zakresem (7.4.C)
-> ramki z hidden.deliberation_present=True traktuj jako escape 'k8_out_of_scope', nie dekoduj R6.

DYSCYPLINA (7.4.G):
- PEEK bez skutkow ubocznych: tap NIGDY nie wola akcesora mutujacego (zwlaszcza deliberator.get_next_action
  -- flipuje step->ACTIVE). Caller podaje juz-policzone wartosci; tap tylko serializuje.
- Stan ukryty per-decyzja (nie koncowy snapshot): _action_failures/backed_off, stuck_cooldowns, K7
  rate-limiter history, off_window budget, last_*_ts -- w chwili T.
- 3 wartosci escape-surface (7.4.J): world_model gaps -> weak_topic/expert_topic, project_child_material.
- knowledge_snapshot: hash + TYLKO czytane pola (nie 370KB/cykl -> lekcja watchdog-lease 92b1501).
- Budzet rozmiaru + pomiar latencji; zapis append-only JSONL.
- JOIN z etykieta 1.0 (DecisionTrace) po episode_id.
"""
from __future__ import annotations
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)

_DEFAULT_PATH = "meta_data/decision_frames.jsonl"
_SIZE_BUDGET_BYTES = 200 * 1024 * 1024   # twardy cap pliku; powyzej -> tap milczy (nie rosnie w nieskonczonosc)
_FRAME_BYTES_WARN = 16 * 1024            # ostrzezenie gdy pojedyncza ramka > 16KB


def _snapshot_digest(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Hash + TYLKO pola realnie czytane przez lancuch decyzji (nie caly ~370KB indeks)."""
    if snapshot is None:
        return {"present": False}
    fbs = snapshot.get("files_by_status", {}) or {}
    return {
        "present": True,
        # tylko OBECNOSC statusow czytanych przez _decide_learning_action (P1/P2/P5)
        "has_learning": bool(fbs.get("learning")),
        "has_learned": bool(fbs.get("learned")),
        "has_completed": bool(fbs.get("completed")),
        "new_files_available": bool(snapshot.get("new_files_available")),
        # hash pelnego snapshotu -> wykrycie zmiany bez zrzutu tresci
        "digest": hash(json.dumps(fbs, sort_keys=True, default=str)) & 0xFFFFFFFF,
    }


def build_frame(
    *,
    episode_id: str,
    tick_count: int,
    now: float,
    mode: str,
    health_score: float,
    exit_path: str,                       # "goal_loop" | "creative_pre" | "fs_write_pre" | "heldout_pre" | "effector"
    ranked_goals: List[Dict[str, Any]],   # [{id,type,priority,created_at,progress,deadline,metadata}] -- juz po mutacjach + strategic
    snapshot: Optional[Dict[str, Any]],
    metrics: Dict[str, Any],
    is_learning_window: bool,
    off_window_exec_allowed: bool,
    hidden: Dict[str, Any],               # {k7_limited:{action:bool}, backed_off:{action:bool},
                                          #  stuck_cooldowns:{goal:until}, consecutive_noop:int,
                                          #  off_window_used:int, last_ts:{name:ts}, deliberation_present:bool}
    ext: Dict[str, Any],                  # {weak_topic_file_exists, expert_topic_available,
                                          #  creative_should_reflect, project_child_material_count, k8_action}
    strategic: Optional[Dict[str, Any]],  # surowy stan StrategicPlan (blocked_goals, active, cursor) BEZ get_next_action
) -> Dict[str, Any]:
    """Zbuduj ramke w schemacie interpretera (goal(pojedynczy chosen NIE tu -- tu KANDYDACI) + kontekst).

    Uwaga: pojedyncza ramka niesie CALY ranked_goals (pivot jest po stronie replayu). Dla per-goal
    decyzji replay iteruje kandydatow. Etykieta ground-truth (goal_id+action wybrany przez 1.0) =
    z DecisionTrace po episode_id, NIE dublujemy jej tutaj.
    """
    return {
        "episode_id": episode_id,
        "tick_count": tick_count,
        "now": now,
        "mode": mode,
        "health_score": health_score,
        "exit_path": exit_path,
        "candidates": ranked_goals,
        "snapshot_digest": _snapshot_digest(snapshot),
        "metrics": {"retention_rate": (metrics or {}).get("retention_rate", 1.0)},
        "is_learning_window": bool(is_learning_window),
        "off_window_exec_allowed": bool(off_window_exec_allowed),
        "hidden": hidden,
        "ext": ext,
        "strategic": strategic,
    }


class DecisionTap:
    """Side-effect-free zrzut ramek decyzji do JSONL. Guarded flaga + budzet rozmiaru + pomiar latencji."""

    def __init__(self, out_path: str = _DEFAULT_PATH, enabled: Optional[bool] = None):
        self.path = out_path
        # domyslnie czyta flage srodowiskowa; wpiecie moze podac jawnie
        if enabled is None:
            enabled = os.environ.get("DECISION_TAP_ENABLED", "false").strip().lower() in (
                "1", "true", "yes", "on")
        self.enabled = enabled
        # jednorazowe flagi logowania -- tydzien zbierania to one-shot, wiec zepsuty tap
        # (0 ramek / cichy blad) MUSI zostawic slad w journalu, inaczej = "cichy planner"
        self._over_budget_logged = False
        self._first_write_logged = False
        self._first_error_logged = False
        self._oversize_logged = False
        self.last_write_ms: float = 0.0
        if self.enabled:
            _logger.info("decision_tap: ENABLED -> collecting decision frames to %s", self.path)

    def write(self, frame: Dict[str, Any]) -> None:
        """Serializuj i dopisz ramke. Twardy cap rozmiaru pliku; pomiar latencji do budzetu ticku."""
        if not self.enabled:
            return
        t0 = time.time()
        try:
            if os.path.exists(self.path) and os.path.getsize(self.path) > _SIZE_BUDGET_BYTES:
                if not self._over_budget_logged:
                    self._over_budget_logged = True
                    _logger.warning("decision_tap: %s exceeded %d MB budget -- tap now SILENT "
                                    "(collection stopped growing)", self.path,
                                    _SIZE_BUDGET_BYTES // (1024 * 1024))
                return
            line = json.dumps(frame, ensure_ascii=False, default=str)
            if len(line) > _FRAME_BYTES_WARN and not self._oversize_logged:
                self._oversize_logged = True
                _logger.warning("decision_tap: frame > %d KB (%d bytes) -- possible snapshot leak "
                                "(patrz lekcja watchdog-lease 92b1501)", _FRAME_BYTES_WARN // 1024, len(line))
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            if not self._first_write_logged:
                self._first_write_logged = True
                _logger.info("decision_tap: ARMED -- first frame written (episode_id=%s, exit_path=%s)",
                             frame.get("episode_id", ""), frame.get("exit_path", ""))
        except Exception as exc:
            # tap NIGDY nie wywraca ticku planera -- ale pierwszy blad zostawia slad
            if not self._first_error_logged:
                self._first_error_logged = True
                _logger.warning("decision_tap: write failed (%s: %s) -- tap continues, "
                                "collection may be incomplete", type(exc).__name__, exc)
        finally:
            self.last_write_ms = (time.time() - t0) * 1000.0


# =====================================================================================
# WIRING (do review operatora -- to jest dotkniecie produkcji, restart robi operator):
#
# 1. W PlannerCore.__init__:  self._decision_tap = DecisionTap()
#
# 2. W run_cycle, TUZ przed `for candidate in ranked_goals` (planner_core.py:838), PO wszystkich
#    mutacjach GoalStore (STEP 2.3/2.35/2.4) -- zbuduj `hidden`/`ext` z JUZ-policzonych wartosci
#    (NIE wolaj get_next_action; deliberation_present = self._deliberation is not None). Dla 3 wartosci
#    escape-surface: weak = self._find_weak_topic_file(snapshot) is not None; expert =
#    self._pick_expert_topic() is not None (UWAGA: sprawdz czy pick nie ma skutkow ubocznych -- jesli ma,
#    dodaj peek); child = self._project_child_material_count(goal). Zrzuc:
#       self._decision_tap.write(build_frame(episode_id=<ep>, ..., exit_path="goal_loop", ...))
#
# 3. Pre-goal intercepty (creative/fs_write/heldout, :797-817) + approved-effector (:3883): albo
#    przenies tap przed :753 i loguj exit_path, albo dodaj lekki write() przy kazdym z tych return
#    (exit_path="creative_pre" itd.) -- inaczej ich decyzje (goal_id=None) wypadaja z mianownika (7.4.G).
#
# 4. Flaga .env: DECISION_TAP_ENABLED=true (domyslnie OFF). Zmiana flagi = restart demona.
#
# 5. Po ~tygodniu zbierania: cegla2_differential.py replayuje na `meta_data/decision_frames.jsonl`
#    (JOIN etykiety po episode_id z decision_traces) -> real-distribution escape-hatch + per-klasa recall.
# =====================================================================================
