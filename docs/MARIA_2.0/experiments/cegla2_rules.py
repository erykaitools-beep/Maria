#!/usr/bin/env python
"""CEGLA 2 -- taktyczny lancuch Plannera K5 jako REGULY-JAKO-DANE (transpilacja).

Wg BLUEPRINT 7.4 + zamrozonego slownika prymitywow cegla2_vocab.md. Reguly sa DANYMI (deklaratywna,
uporzadkowana lista first-match nad prymitywami slownika) -- NIE kodem imperatywnym. Interpreter
(cegla2_interpreter.py) je wykonuje nad ramka decyzji. Escape = galaz, ktorej action_type nie da sie
wyznaczyc z ramki bez wywolania zywego podsystemu 1.0 (oznaczone "escape": <proxy>).

Zrodlo prawdy 1.0 (transpilowane 1:1, numery linii = planner_core.py @2026-07-09):
- _create_plan_for_goal (1979-2285): forced -> fetch_valve -> learn_backoff -> maintenance ->
  saturation -> [K8 poza zakresem] -> fallback(_decide_learning_action / fetch_handoff->LEARN)
- _decide_learning_action (2440-2509): P0-P7
- _decide_non_learning_action (2511-2544): kaskada creative>self_analyze>critique>evaluate>validate

Stale zamrozone (goal_selector.py): AGING 0.1, MAX_AGING 4.0, retention 0.8, weak-belief 0.3.
"""

# --- Reguly wyprowadzenia action_type dla POJEDYNCZEGO celu (first-match, kolejnosc = 1.0) ---
# Format reguly: {"id", "when": <expr>, "then": <action|"@subrule"|"@window">, ["escape": proxy]}
# <expr> = zagniezdzone listy prefiksowe nad prymitywami slownika (patrz interpreter._eval).

ACTION_RULES = [
    # R1 forced (planner_core.py:1986)
    {"id": "R1_forced",
     "when": ["truthy", ["field", "goal.metadata.forced_action_type"]],
     "then": ["action_from_field", "goal.metadata.forced_action_type"]},

    # R2 B2 fetch-valve (2013): needs_fetch AND not fetch_handoff AND not k7(fetch)
    #   sub: project_parent + material>0 -> disarm (przechodzi dalej) else window_guard(FETCH)
    {"id": "R2_fetch_valve",
     "when": ["and",
              ["truthy", ["field", "goal.metadata.needs_fetch"]],
              ["not", ["derived", "is_fetch_handoff"]],
              ["not", ["k7_limited", "fetch"]]],
     "when_inner_skip": ["and",
                         ["truthy", ["field", "goal.metadata.project_parent"]],
                         ["gt", ["field", "ext.project_child_material_count"], 0]],
     "then": ["window_guard", "fetch"],
     "fall_through_if": "noop"},   # 1.0: fetch zablokowany oknem NIE zwraca, needs_fetch zostaje uzbrojony

    # R3 learn-backoff (2047): backed_off(learn,goal) AND type==learning -> NOOP
    {"id": "R3_learn_backoff",
     "when": ["and",
              ["backed_off", "learn"],
              ["eq", ["field", "goal.type"], "learning"]],
     "then": "noop"},

    # R4 maintenance (2061): type==maintenance -> map[theme_tag] default MAINTENANCE
    {"id": "R4_maintenance",
     "when": ["eq", ["field", "goal.type"], "maintenance"],
     "then": ["map", ["field", "goal.metadata.theme_tag"], {
         "learn_failures": "learn", "passive_drift": "learn",
         "retention_low": "review", "skip_overuse": "evaluate",
         "stale_goals": "evaluate", "validate_failures": "evaluate",
         "exam_failures": "review"}, "maintenance"]},

    # R5 saturation META (2097): is_saturation_meta AND not k7(fetch) -> window_guard(FETCH)
    {"id": "R5_saturation_meta",
     "when": ["and", ["derived", "is_saturation_meta"], ["not", ["k7_limited", "fetch"]]],
     "then": ["window_guard", "fetch"]},

    # R6 K8 Deliberation (2125): POZA ZAKRESEM (7.4.C). Gdy deliberation obecne -> ext.k8_action.
    {"id": "R6_k8",
     "when": ["truthy", ["field", "hidden.deliberation_present"]],
     "then": ["field", "ext.k8_action"],
     "escape": "k8_out_of_scope"},

    # R7 fallback (2210): fetch_handoff -> LEARN, else _decide_learning_action; potem window_guard
    {"id": "R7_fetch_handoff",
     "when": ["derived", "is_fetch_handoff"],
     "then": ["window_guard", "learn"]},
    {"id": "R7_fallback",
     "when": True,
     "then": ["window_guard", "@decide_learning"]},
]

# --- _decide_learning_action P0-P7 (first-match) ---
DECIDE_LEARNING_RULES = [
    # P0: poza oknem -> _decide_non_learning_action
    {"id": "P0_off_window",
     "when": ["not", ["field", "is_learning_window"]],
     "then": "@decide_non_learning"},
    # snapshot None -> LEARN (2464)
    {"id": "P0b_no_snapshot",
     "when": ["is_null", ["field", "snapshot"]],
     "then": "learn"},
    # P1: learning -> LEARN
    {"id": "P1_learning",
     "when": ["nonempty", ["field", "snapshot.files_by_status.learning"]],
     "then": "learn"},
    # P2: learned -> EXAM (albo REVIEW gdy k7(exam))
    {"id": "P2_learned",
     "when": ["nonempty", ["field", "snapshot.files_by_status.learned"]],
     "then": ["if", ["not", ["k7_limited", "exam"]], "exam", "review"]},
    # P2.5: weak beliefs -> REVIEW (ESCAPE: _find_weak_topic_file uzywa world_model + k7(review))
    {"id": "P2_5_weak",
     "when": ["truthy", ["field", "ext.weak_topic_file_exists"]],
     "then": "review",
     "escape": "weak_topic_file"},
    # P3: new files -> LEARN
    {"id": "P3_new",
     "when": ["truthy", ["field", "snapshot.new_files_available"]],
     "then": "learn"},
    # P4: retention < 0.8 -> REVIEW
    {"id": "P4_retention",
     "when": ["lt", ["field", "metrics.retention_rate"], 0.8],
     "then": "review"},
    # P5: completed AND not k7(fetch) -> FETCH
    {"id": "P5_completed",
     "when": ["and", ["nonempty", ["field", "snapshot.files_by_status.completed"]],
              ["not", ["k7_limited", "fetch"]]],
     "then": "fetch"},
    # P6: not k7(ask_expert) AND expert_topic -> ASK_EXPERT (ESCAPE: _pick_expert_topic)
    {"id": "P6_ask_expert",
     "when": ["and", ["not", ["k7_limited", "ask_expert"]],
              ["truthy", ["field", "ext.expert_topic_available"]]],
     "then": "ask_expert",
     "escape": "expert_topic"},
    # P7: NOOP (post NEED_MATERIAL = side effect, nie determinuje akcji)
    {"id": "P7_noop", "when": True, "then": "noop"},
]

# --- _decide_non_learning_action kaskada (first-match) ---
# creative gated dodatkowo przez ext.creative_should_reflect (ESCAPE: should_reflect)
DECIDE_NON_LEARNING_RULES = [
    {"id": "NL_creative",
     "when": ["and", ["not", ["k7_limited", "creative"]],
              ["truthy", ["field", "ext.creative_should_reflect"]]],
     "then": "creative",
     "escape": "creative_should_reflect"},
    {"id": "NL_self_analyze",
     "when": ["not", ["k7_limited", "self_analyze"]], "then": "self_analyze"},
    {"id": "NL_critique",
     "when": ["not", ["k7_limited", "critique"]], "then": "critique"},
    {"id": "NL_evaluate",
     "when": ["not", ["k7_limited", "evaluate"]], "then": "evaluate"},
    {"id": "NL_validate",
     "when": ["not", ["k7_limited", "validate"]], "then": "validate"},
    {"id": "NL_noop", "when": True, "then": "noop"},
]

# --- Wyrazenia pomocnicze (derived, DAG bez rekurencji) ---
# effective_priority = priority * (1 + min(aging,4.0)) * deadline_mult(if cutover)
DERIVED = {
    "aging": ["min", ["mul", ["div", ["sub", ["field", "now"], ["field", "goal.created_at"]], 3600.0],
                      0.1], 4.0],
    "effective_priority_base": ["mul", ["field", "goal.priority"], ["add", 1.0, ["@", "aging"]]],
    # is_fetch_handoff: type==learning AND metadata.source=="fetch_handoff" AND (file_ids OR fetched_file_ids)
    "is_fetch_handoff": ["and",
                         ["eq", ["field", "goal.type"], "learning"],
                         ["eq", ["field", "goal.metadata.source"], "fetch_handoff"],
                         ["or", ["truthy", ["field", "goal.metadata.file_ids"]],
                          ["truthy", ["field", "goal.metadata.fetched_file_ids"]]]],
    # is_saturation_meta: type==meta AND substr_any(desc, KEYWORDS) AND snapshot AND
    #   not new_files AND not learning-in-progress
    "is_saturation_meta": ["and",
                           ["eq", ["field", "goal.type"], "meta"],
                           ["substr_any", ["field", "goal.description"], "META_LEARNING_KEYWORDS"],
                           ["not", ["is_null", ["field", "snapshot"]]],
                           ["not", ["truthy", ["field", "snapshot.new_files_available"]]],
                           ["not", ["nonempty", ["field", "snapshot.files_by_status.learning"]]]],
}

# --- Feasibility (dla rankingu; goal_selector._check_feasibility) ---
FEASIBILITY_RULES = [
    {"id": "F_maintenance",
     "when": ["eq", ["field", "goal.type"], "maintenance"],
     "then": ["ge", ["field", "goal.progress"], 1.0], "then_is": "infeasible_if_true"},
    {"id": "F_meta",
     "when": ["eq", ["field", "goal.type"], "meta"],
     "then": ["or", ["not", ["substr_any", ["field", "goal.description"], "META_LEARNING_KEYWORDS"]],
              ["field", "is_learning_window"], ["field", "off_window_allowed"]]},
    {"id": "F_user", "when": ["eq", ["field", "goal.type"], "user"], "then": True},
    {"id": "F_learning_conv",
     "when": ["and", ["eq", ["field", "goal.type"], "learning"],
              ["eq", ["field", "goal.metadata.source"], "conversation"]],
     "then": True},
    {"id": "F_learning",
     "when": ["eq", ["field", "goal.type"], "learning"],
     "then": ["and",
              ["or", ["field", "is_learning_window"], ["field", "off_window_allowed"]],
              ["or", ["is_null", ["field", "snapshot"]],
               ["truthy", ["field", "snapshot.new_files_available"]],
               ["nonempty", ["field", "snapshot.files_by_status.learning"]]]]},
    {"id": "F_default", "when": True, "then": True},
]

# Zbior slow-kluczy (goal_selector.META_LEARNING_KEYWORDS) -- import zywy, nie kopia.
from agent_core.planner.goal_selector import META_LEARNING_KEYWORDS  # noqa: E402

# Zestaw escape-proxy (do audytu 7.4.A/7.4.E)
ESCAPE_PROXIES = {
    "weak_topic_file", "expert_topic", "creative_should_reflect", "project_child_material_count",
}
OUT_OF_SCOPE = {"k8_out_of_scope"}
