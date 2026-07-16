#!/usr/bin/env python
"""CEGLA 2 -- TEST ROZNICOWY (7.4.D krok 2): interpreter(reguly) vs PRAWDZIWY kod 1.0.

Dla kazdej syntezowanej ramki:
  - INTERP: cegla2_interpreter.decide(frame) -> (action, escape)
  - ORACLE 1.0: prawdziwy PlannerCore._create_plan_for_goal(goal, ctx) ze wstrzyknietym stanem ramki
    (K8/_deliberation = None -> poza zakresem; is_learning_window + gettery stanu zewnetrznego
    monkeypatchowane na wartosci z ramki, reszta = ORYGINALNY kod 1.0).
Metryki: SHADOW-OF-SELF (zgodnosc interp vs oracle -- ma byc 1.0), ESCAPE-HATCH (udzial decyzji przez
galaz-escape), per-klasa. RESEARCH_ONLY, read-only, zero dotykania produkcji.
"""
import os, sys, tempfile, itertools, importlib.util
from types import SimpleNamespace
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
interp_mod = _load("cegla2_interpreter")
rules_mod = _load("cegla2_rules")

from agent_core.planner.planner_model import ActionType
from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
import agent_core.environment.environment_model as envmod
from agent_core.planner.planner_core import PlannerCore

# ---- budowa Goala z ramki ----
_GT = {"learning": GoalType.LEARNING, "meta": GoalType.META, "user": GoalType.USER,
       "maintenance": GoalType.MAINTENANCE}

def make_goal(g):
    return Goal(
        id="g-test", type=_GT[g["type"]], description=g.get("description", "cel testowy"),
        priority=g.get("priority", 1.0), status=GoalStatus.ACTIVE, progress=g.get("progress", 0.0),
        parent_goal_id=None, created_by="system", created_at=g.get("created_at", 0.0),
        updated_at=g.get("created_at", 0.0), deadline=g.get("deadline"),
        metadata=dict(g.get("metadata", {})))

# ---- ORACLE: prawdziwy PlannerCore ze wstrzyknietym stanem ramki ----
class StubStore:
    def _mark_dirty(self, gid): pass
    def save(self): pass

def build_oracle():
    tmpd = tempfile.mkdtemp()
    pc = PlannerCore(state_path=os.path.join(tmpd, "s.json"),
                     decisions_path=os.path.join(tmpd, "d.jsonl"))
    pc._deliberation = None                    # K8 poza zakresem (7.4.C)
    pc._goal_store = StubStore()
    return pc

def oracle_action(pc, frame):
    f = frame
    goal = make_goal(f["goal"])
    ctx = {"knowledge_snapshot": f.get("snapshot"), "evaluation_metrics": f.get("metrics", {})}
    ext = f.get("ext", {}); hidden = f.get("hidden", {})
    # wstrzykniecie stanu zewnetrznego jako wartosci z ramki (reszta = oryginalny kod 1.0)
    pc._is_action_rate_limited = lambda a: bool((hidden.get("k7_limited") or {}).get(a, False))
    pc.is_action_backed_off = lambda a, gid=None: bool((hidden.get("backed_off") or {}).get(a, False))
    pc._find_weak_topic_file = lambda snap: ("wf" if ext.get("weak_topic_file_exists") else None)
    pc._pick_expert_topic = lambda: ("t" if ext.get("expert_topic_available") else None)
    pc._creative_module = SimpleNamespace(should_reflect=lambda: bool(ext.get("creative_should_reflect")))
    pc._project_child_material_count = lambda g: int(ext.get("project_child_material_count", 0) or 0)
    pc._spend_fetch_attempt = lambda g: None
    pc._post_need_material_if_missing = lambda: None
    pc._off_window_budget_remaining = lambda: (1 if f.get("off_window_exec_allowed") else 0)
    pc._heavy_action_mode_ok = lambda: True
    # is_learning_window: monkeypatch modulu (czytany wewnatrz _decide_learning_action i _enforce_...)
    envmod.is_learning_window = lambda: bool(f.get("is_learning_window"))
    plan = pc._create_plan_for_goal(goal, ctx)
    return plan.action_type.value

# ---- SYNTEZA RAMEK (kombinatoryczne pokrycie galezi) ----
def synth_frames():
    frames = []
    idx = 0
    def add(fr):
        nonlocal idx
        fr.setdefault("goal", {}); fr["goal"].setdefault("priority", 1.0); fr["goal"].setdefault("created_at", 0.0)
        fr["_id"] = idx; idx += 1; frames.append(fr)

    actions = ["learn", "exam", "review", "fetch"]
    bools = [False, True]
    fbs_variants = [None, {}, {"learning": ["a"]}, {"learned": ["a"]}, {"completed": ["a"]}]

    # 1) forced_action_type
    for a in actions + ["creative", "noop"]:
        add({"goal": {"type": "learning", "metadata": {"forced_action_type": a}}})
    # 2) maintenance themes
    for theme in ["learn_failures", "passive_drift", "retention_low", "skip_overuse", "stale_goals",
                  "validate_failures", "exam_failures", "unknown_theme", ""]:
        add({"goal": {"type": "maintenance", "metadata": {"theme_tag": theme}}})
    # 3) fetch-valve: needs_fetch x fetch_handoff x k7(fetch) x project x material x window
    for nf, handoff_src, k7f, proj, mat, win in itertools.product(
            bools, [None, "fetch_handoff"], bools, bools, [0, 1], bools):
        md = {"needs_fetch": nf}
        if handoff_src: md["source"] = handoff_src; md["file_ids"] = ["f"]
        if proj: md["project_parent"] = "p"
        add({"goal": {"type": "learning", "metadata": md},
             "hidden": {"k7_limited": {"fetch": k7f}},
             "ext": {"project_child_material_count": mat},
             "is_learning_window": win, "off_window_exec_allowed": False,
             "snapshot": {"files_by_status": {}}, "metrics": {}})
    # 4) learn-backoff
    for bo, typ in itertools.product(bools, ["learning", "meta"]):
        add({"goal": {"type": typ, "metadata": {}}, "hidden": {"backed_off": {"learn": bo}},
             "is_learning_window": True, "snapshot": {"files_by_status": {}}, "metrics": {}})
    # 5) saturation meta
    for desc, newf, learningf, win in itertools.product(
            ["nauka nowego", "cel bez slow kluczy"], bools, bools, bools):
        add({"goal": {"type": "meta", "description": desc, "metadata": {}},
             "snapshot": {"files_by_status": ({"learning": ["a"]} if learningf else {}),
                          "new_files_available": newf},
             "hidden": {"k7_limited": {"fetch": False}},
             "is_learning_window": win, "off_window_exec_allowed": win, "metrics": {}})
    # 6) _decide_learning P0-P7 (pelne pokrycie)
    for fbs, newf, ret, win, k7exam, k7fetch, k7ask, weak, expert in itertools.product(
            fbs_variants, bools, [0.5, 0.9], bools, bools, bools, bools, bools, bools):
        add({"goal": {"type": "learning", "metadata": {}},
             "snapshot": (None if fbs is None else
                          {"files_by_status": fbs, "new_files_available": newf}),
             "metrics": {"retention_rate": ret},
             "hidden": {"k7_limited": {"exam": k7exam, "fetch": k7fetch, "ask_expert": k7ask}},
             "ext": {"weak_topic_file_exists": weak, "expert_topic_available": expert},
             "is_learning_window": win, "off_window_exec_allowed": win})
    # 7) _decide_non_learning kaskada (poza oknem)
    for kc, ks, kcr, ke, kv, reflect in itertools.product(bools, bools, bools, bools, bools, bools):
        add({"goal": {"type": "learning", "metadata": {}},
             "snapshot": {"files_by_status": {}}, "metrics": {"retention_rate": 0.9},
             "hidden": {"k7_limited": {"creative": kc, "self_analyze": ks, "critique": kcr,
                                       "evaluate": ke, "validate": kv}},
             "ext": {"creative_should_reflect": reflect},
             "is_learning_window": False, "off_window_exec_allowed": False})
    return frames

def main():
    # GENUINE escape = wymaga zywego podsystemu, NIE frameowalne z innych pol (vocab 6).
    # creative_should_reflect = cooldown czasowy -> frameowalny z (now, last_creative_ts) -> NIE escape.
    GENUINE = {"weak_topic_file", "expert_topic", "project_child_material_count"}
    FLIP = {"ext.weak_topic_file_exists": [False, True],
            "ext.expert_topic_available": [False, True],
            "ext.project_child_material_count": [0, 1]}

    def escape_determined(fr, base_action):
        """True jesli przelaczenie ktoregokolwiek GENUINE proxy zmienia akcje (proxy DETERMINUJE)."""
        ext = fr.get("ext", {})
        for path, (v0, v1) in FLIP.items():
            key = path.split(".", 1)[1]
            if key not in ext:
                continue
            cur = ext.get(key)
            other = v1 if cur in (v0, False, 0, None) else v0
            fr2 = dict(fr); fr2["ext"] = dict(ext); fr2["ext"][key] = other
            a2, _ = interp_mod.decide(fr2)
            if a2 != base_action:
                return True
        return False

    pc = build_oracle()
    frames = synth_frames()
    print(f"== syntezowanych ramek: {len(frames)} ==")
    agree = 0; disagree = []; escapes = Counter(); by_class = Counter()
    interp_err = oracle_err = 0
    esc_consult_genuine = 0; esc_determined = 0
    for fr in frames:
        try:
            a_i, esc = interp_mod.decide(fr)
        except Exception as e:
            interp_err += 1; disagree.append(("INTERP_ERR", fr["_id"], repr(e)[:120])); continue
        try:
            a_o = oracle_action(pc, fr)
        except Exception as e:
            oracle_err += 1; disagree.append(("ORACLE_ERR", fr["_id"], repr(e)[:120])); continue
        by_class[a_o] += 1
        for p in esc: escapes[p] += 1
        genuine_read = [p for p in esc if p in GENUINE]
        if genuine_read:
            esc_consult_genuine += 1
            if escape_determined(fr, a_i):
                esc_determined += 1
        if a_i == a_o:
            agree += 1
        else:
            disagree.append((a_i, a_o, {k: fr[k] for k in ("goal", "hidden", "ext", "is_learning_window",
                                        "off_window_exec_allowed", "snapshot", "metrics") if k in fr}))
    n = len(frames)
    print(f"\n== SHADOW-OF-SELF (interp vs prawdziwy 1.0) ==")
    print(f"  zgodnosc: {agree}/{n} = {100*agree/n:.2f}%   (cel: 100% -- sanity transpilacji)")
    print(f"  interp_err={interp_err}  oracle_err={oracle_err}  niezgodnych={n-agree-interp_err-oracle_err}")
    print(f"\n== ESCAPE-HATCH (na syntezowanym pokryciu galezi -- NIE rozklad zywy) ==")
    print(f"  GENUINE escape (zapytanie do zywego podsystemu, vocab 6):")
    print(f"    - KONSULTOWANE (proxy odczytane na sciezce): {esc_consult_genuine}/{n} = {100*esc_consult_genuine/n:.1f}%")
    print(f"    - DETERMINUJACE (flip proxy zmienia akcje):   {esc_determined}/{n} = {100*esc_determined/n:.1f}%")
    print(f"  odczyty proxy (wszystkie, w tym frameowalne):")
    for k, v in escapes.most_common():
        genuine = " [GENUINE]" if k in {"weak_topic_file","expert_topic","project_child_material_count"} else " [frameowalny]"
        print(f"    {k:28} {v}{genuine}")
    print(f"\n== rozklad akcji (oracle) ==")
    for k, v in by_class.most_common():
        print(f"    {k:14} {v}")
    if disagree:
        print(f"\n== NIEZGODNOSCI/bledy (do {min(20,len(disagree))}) ==")
        for d in disagree[:20]:
            print(f"    interp={d[0]} oracle={d[1]}  {str(d[2])[:220]}")

if __name__ == "__main__":
    main()
