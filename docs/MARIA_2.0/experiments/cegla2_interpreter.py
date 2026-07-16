#!/usr/bin/env python
"""CEGLA 2 -- deterministyczny INTERPRETER regul-jako-danych (cegla2_rules.py) nad ramka decyzji.

Wykonuje wylacznie prymitywy zamrozonego slownika (cegla2_vocab.md). Zwraca (action_type, escape_marker):
escape_marker = None jesli decyzja w pelni wyznaczona z ramki; nazwa proxy jesli wymagala escape do 1.0.
Zero wywolan kodu 1.0 (poza czytaniem pol ramki). RESEARCH_ONLY.
"""
from typing import Any, Dict, Optional, Tuple
import importlib.util, os
_spec = importlib.util.spec_from_file_location(
    "cegla2_rules", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cegla2_rules.py"))
_rules = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_rules)
ACTION_RULES = _rules.ACTION_RULES
DECIDE_LEARNING_RULES = _rules.DECIDE_LEARNING_RULES
DECIDE_NON_LEARNING_RULES = _rules.DECIDE_NON_LEARNING_RULES
DERIVED = _rules.DERIVED
FEASIBILITY_RULES = _rules.FEASIBILITY_RULES
META_LEARNING_KEYWORDS = _rules.META_LEARNING_KEYWORDS

LEARN_FAMILY = {"learn", "exam", "review", "fetch", "ask_expert"}


# Pola-proxy stanu zewnetrznego -> nazwa escape (vocab 6). k8_action = OUT OF SCOPE (nie escape).
ESCAPE_PROXY_FIELDS = {
    "ext.weak_topic_file_exists": "weak_topic_file",
    "ext.expert_topic_available": "expert_topic",
    "ext.creative_should_reflect": "creative_should_reflect",
    "ext.project_child_material_count": "project_child_material_count",
}


class Interp:
    def __init__(self, frame: Dict[str, Any]):
        self.f = frame
        self.escape: Optional[str] = None  # ostatni escape uzyty na sciezce decyzji
        self.proxies_read = set()          # audyt: ktore escape-proxy REALNIE odczytano (short-circuit)

    # --- dostep do pola ramki (kropkowana sciezka; slowniki + zagniezdzenia) ---
    def _field(self, path: str) -> Any:
        if path in ESCAPE_PROXY_FIELDS:
            self.proxies_read.add(ESCAPE_PROXY_FIELDS[path])
        cur: Any = self.f
        for part in path.split("."):
            if cur is None:
                return None
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                cur = getattr(cur, part, None)
        return cur

    # --- ewaluacja wyrazenia prefiksowego ---
    def _eval(self, e: Any) -> Any:
        if e is True or e is False or e is None:
            return e
        if isinstance(e, (int, float, str)):
            return e
        op = e[0]
        if op == "field":
            return self._field(e[1])
        if op == "@":                       # odwolanie do DERIVED
            return self._eval(DERIVED[e[1]])
        if op == "derived":
            return self._eval(DERIVED[e[1]])
        if op == "truthy":
            return bool(self._eval(e[1]))
        if op == "is_null":
            return self._eval(e[1]) is None
        if op == "nonempty":
            v = self._eval(e[1]); return bool(v)
        if op == "not":
            return not self._eval(e[1])
        if op == "and":
            return all(self._eval(x) for x in e[1:])
        if op == "or":
            return any(self._eval(x) for x in e[1:])
        if op in ("eq", "ne", "lt", "le", "gt", "ge"):
            a, b = self._eval(e[1]), self._eval(e[2])
            if op == "eq": return a == b
            if op == "ne": return a != b
            # porownania num: None traktuj bezpiecznie
            if a is None or b is None:
                return False
            if op == "lt": return a < b
            if op == "le": return a <= b
            if op == "gt": return a > b
            if op == "ge": return a >= b
        if op in ("mul", "add", "sub", "div", "min", "max"):
            vals = [self._eval(x) for x in e[1:]]
            if op == "mul": r = 1.0
            elif op == "add": r = 0.0
            else: r = None
            if op == "mul":
                for v in vals: r *= float(v)
                return r
            if op == "add":
                for v in vals: r += float(v)
                return r
            if op == "sub": return float(vals[0]) - float(vals[1])
            if op == "div": return float(vals[0]) / float(vals[1])
            if op == "min": return min(float(v) for v in vals)
            if op == "max": return max(float(v) for v in vals)
        if op == "in_set":
            return self._eval(e[1]) in set(e[2])
        if op == "substr_any":
            s = (self._eval(e[1]) or "")
            kws = META_LEARNING_KEYWORDS if e[2] == "META_LEARNING_KEYWORDS" else e[2]
            sl = str(s).lower()
            return any(k in sl for k in kws)
        if op == "k7_limited":                # bramka K7 z ramki (hidden.k7_limited[action])
            lim = (self._field("hidden.k7_limited") or {})
            return bool(lim.get(e[1], False))
        if op == "backed_off":                # is_action_backed_off z ramki (hidden.backed_off[action])
            bo = (self._field("hidden.backed_off") or {})
            return bool(bo.get(e[1], False))
        if op == "map":
            key = self._eval(e[1]); table = e[2]; default = e[3]
            return table.get(key, default)
        if op == "if":
            return self._eval(e[2]) if self._eval(e[1]) else self._eval(e[3])
        raise ValueError(f"nieznany operator: {op}")

    # --- rozwiazanie "then" na action_type (obsluga @subrule, window_guard, action_from_field, map, if) ---
    def _resolve_then(self, then: Any, escape: Optional[str]) -> str:
        if escape:
            self.escape = escape
        if isinstance(then, str):
            if then == "@decide_learning":
                return self._run_rules(DECIDE_LEARNING_RULES)
            if then == "@decide_non_learning":
                return self._run_rules(DECIDE_NON_LEARNING_RULES)
            return then                        # literal action
        op = then[0]
        if op == "action_from_field":
            v = self._field(then[1])
            return str(v).lower() if v else "noop"
        if op == "window_guard":
            inner = self._resolve_then(then[1], None)
            return self._window_guard(inner)
        if op == "map":
            return self._eval(then)
        if op == "if":
            return self._eval(then)
        if op == "field":                      # np. ext.k8_action
            v = self._eval(then)
            return str(v).lower() if v else "noop"
        raise ValueError(f"nieznany then: {then}")

    def _window_guard(self, action: str) -> str:
        if action not in LEARN_FAMILY:
            return action
        if self._field("is_learning_window"):
            return action
        if self._field("off_window_exec_allowed"):
            return action
        return "noop"

    def _run_rules(self, rules) -> str:
        for r in rules:
            when = r["when"]
            if when is True or self._eval(when):
                # obsluga wewnetrznego skip (disarm -> przechodzi dalej, np. R2 project-child)
                if r.get("when_inner_skip") is not None and self._eval(r["when_inner_skip"]):
                    continue
                action = self._resolve_then(r["then"], r.get("escape"))
                # fall-through: gdy window_guard zdemotowal do noop, 1.0 NIE zwraca -> przelec dalej
                if r.get("fall_through_if") is not None and action == r["fall_through_if"]:
                    continue
                return action
        return "noop"

    def decide(self):
        self.escape = None
        self.proxies_read = set()
        action = self._run_rules(ACTION_RULES)
        return action, sorted(self.proxies_read)

    def is_feasible(self) -> bool:
        for r in FEASIBILITY_RULES:
            if r["when"] is True or self._eval(r["when"]):
                res = self._eval(r["then"]) if not isinstance(r["then"], bool) else r["then"]
                if r.get("then_is") == "infeasible_if_true":
                    return not bool(res)
                return bool(res)
        return True

    def effective_priority(self) -> float:
        return float(self._eval(DERIVED["effective_priority_base"]))


def decide(frame: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    return Interp(frame).decide()
