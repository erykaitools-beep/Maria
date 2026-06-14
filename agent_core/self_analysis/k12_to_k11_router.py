"""K12 strategic-change recommendations → K11 ExperimentRunner Proposals.

Most #2 step 1 (2026-05-08): rule-based heuristics convert K12 bulletin
recommendations into K11 parameter-change Proposals. K11's existing
ProposalEngine handles cooldown / limits / experiment lifecycle / ADOPT
gate; this module is just the translation layer.

Why heuristics, not LLM:
  - K12 produces recommendations whose `topic` and `description` describe
    Maria's broken self-behavior in natural language (e.g. "Akcja 'skip'
    stanowi 87% wszystkich akcji"). K11 needs concrete (parameter_id,
    proposed_value) tuples. Bridging the gap with a hand-crafted regex
    pattern stays auditable and predictable.
  - LLM-assisted bridging stays as a future option (Most #2 step 3+).

Confidence:
  - Each heuristic returns its own confidence score (0..1). Caller can
    decide auto-approve vs DRAFT-pending-operator-review threshold.
  - Default contract: confidence >= 0.75 → auto-approve; else DRAFT.

Coverage today (2 heuristics):
  - skip_dominates → config.EXAM_PASS_THRESHOLD (lower by 0.05)
  - stale_goals_aging → goal_selector.AGING_FACTOR_PER_HOUR (raise by 0.02)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from agent_core.experiment.experiment_model import (
    Proposal,
    ProposalSource,
    create_proposal,
)
from agent_core.experiment.parameter_registry import (
    get_parameter,
    validate_value,
)
from agent_core.self_analysis.recommendation_model import AnalysisRecommendation

logger = logging.getLogger(__name__)


# Confidence threshold above which proposals are auto-approved by caller.
AUTO_APPROVE_CONFIDENCE = 0.75

# Skip-dominates: trigger when 'skip' percentage in summary >= this.
SKIP_DOMINATES_THRESHOLD_PCT = 50

# Skip-dominates: how much to lower EXAM_PASS_THRESHOLD per Proposal.
SKIP_DOMINATES_DELTA = 0.05

# Stale-goals: minimum days mentioned in rec before triggering.
STALE_GOALS_MIN_DAYS = 14

# Stale-goals: how much to raise AGING_FACTOR_PER_HOUR per Proposal.
STALE_GOALS_DELTA = 0.02


@dataclass(frozen=True)
class HeuristicMatch:
    """Result of a heuristic — what to propose + how confident we are."""
    proposal: Proposal
    confidence: float
    heuristic_name: str


def heuristic_skip_dominates(
    rec: AnalysisRecommendation,
    current_threshold: float,
) -> Optional[HeuristicMatch]:
    """Detect 'skip dominates X%' pattern and propose lower EXAM_PASS_THRESHOLD.

    Hypothesis: when Maria is skipping >50% of new material with 0% success
    on attempts, the bottleneck is often that EXAM_PASS_THRESHOLD is set
    too high — agent gives up rather than risking another failed exam.
    Lowering the threshold by one notch (0.05) encourages "try, don't skip".

    Args:
        rec: K12 recommendation (likely with topic/summary mentioning 'skip').
        current_threshold: Current EXAM_PASS_THRESHOLD value (read from
            config so we generate a valid proposed_value).

    Returns:
        HeuristicMatch if pattern matches and a valid proposal can be built,
        None otherwise (caller falls through to next heuristic).
    """
    text = f"{rec.topic} {rec.description}".lower()
    if "skip" not in text:
        return None

    # Find first percentage in text (e.g. "75%", "stanowi 89%")
    match = re.search(r"(\d{1,3})\s*%", text)
    if match is None:
        return None

    try:
        pct = int(match.group(1))
    except ValueError:
        return None

    if pct < SKIP_DOMINATES_THRESHOLD_PCT:
        return None

    spec = get_parameter("config.EXAM_PASS_THRESHOLD")
    if spec is None:
        logger.warning(
            "[K12->K11] config.EXAM_PASS_THRESHOLD not in registry; skip"
        )
        return None

    proposed = round(current_threshold - SKIP_DOMINATES_DELTA, 2)
    if proposed < spec.min_value:
        # Already at floor; nothing more to propose along this heuristic.
        logger.info(
            f"[K12->K11] skip_dominates would breach floor "
            f"({proposed} < {spec.min_value}); skip"
        )
        return None

    if not validate_value("config.EXAM_PASS_THRESHOLD", proposed):
        return None

    if proposed == current_threshold:
        return None

    proposal = create_proposal(
        source=ProposalSource.K12_STRATEGIC_CHANGE,
        parameter_id="config.EXAM_PASS_THRESHOLD",
        current_value=current_threshold,
        proposed_value=proposed,
        hypothesis=(
            f"Akcja 'skip' stanowi {pct}% obserwowanych akcji. "
            f"Hipoteza: prog zaliczenia exam jest za wysoki, agent unika "
            f"prob zamiast ryzykowac kolejna porazke. Obnizenie progu o "
            f"{SKIP_DOMINATES_DELTA} powinno przesunac wybor 'skip' -> 'learn'."
        ),
        rationale=(
            f"K12 rec {rec.rec_id}: {rec.topic[:80]}. "
            f"Pattern: skip-dominates >= {SKIP_DOMINATES_THRESHOLD_PCT}%."
        ),
        expected_outcome=(
            "Spadek skip-rate o >=20% w oknie 7 dni; brak degradacji "
            "retention_rate >3% (cross-metric guard)."
        ),
        risk_assessment=spec.risk_level.value,
        trigger_data={
            "heuristic": "skip_dominates",
            "rec_id": rec.rec_id,
            "skip_pct_observed": pct,
            "summary": rec.description[:200] if rec.description else "",
        },
    )

    return HeuristicMatch(
        proposal=proposal,
        confidence=0.65,  # rule-based pattern match, no LLM verification
        heuristic_name="skip_dominates",
    )


def heuristic_stale_goals_aging(
    rec: AnalysisRecommendation,
    current_aging_factor: float,
) -> Optional[HeuristicMatch]:
    """Detect 'stale goals N days' pattern, raise AGING_FACTOR_PER_HOUR.

    Hypothesis: when goals languish for many days untouched, the priority
    boost per hour for pending goals is too small to push them above
    fresher work in the goal selector. Bumping AGING_FACTOR_PER_HOUR by
    one notch (0.02) makes older goals rise faster, encouraging the
    planner to act on them.

    Args:
        rec: K12 recommendation (likely with topic/description mentioning
            'stale', 'odlogiem', 'nieaktywny' + a day count like '68 dni').
        current_aging_factor: Current AGING_FACTOR_PER_HOUR value.

    Returns:
        HeuristicMatch if pattern matches and a valid proposal can be
        built, None otherwise.
    """
    text = f"{rec.topic} {rec.description}".lower()

    stale_words = (
        "stale", "odlogiem", "odłogiem",
        "nieaktywn", "nieaktualn", "zaleg", "lezy", "leży",
    )
    if not any(w in text for w in stale_words):
        return None

    day_match = re.search(r"(\d{1,3})\s*dni", text)
    if day_match is None:
        return None

    try:
        days = int(day_match.group(1))
    except ValueError:
        return None

    if days < STALE_GOALS_MIN_DAYS:
        return None

    spec = get_parameter("goal_selector.AGING_FACTOR_PER_HOUR")
    if spec is None:
        logger.warning(
            "[K12->K11] goal_selector.AGING_FACTOR_PER_HOUR not in registry; skip"
        )
        return None

    proposed = round(current_aging_factor + STALE_GOALS_DELTA, 2)
    if proposed > spec.max_value:
        logger.info(
            f"[K12->K11] stale_goals_aging would breach ceiling "
            f"({proposed} > {spec.max_value}); skip"
        )
        return None

    if not validate_value("goal_selector.AGING_FACTOR_PER_HOUR", proposed):
        return None

    if proposed == current_aging_factor:
        return None

    proposal = create_proposal(
        source=ProposalSource.K12_STRATEGIC_CHANGE,
        parameter_id="goal_selector.AGING_FACTOR_PER_HOUR",
        current_value=current_aging_factor,
        proposed_value=proposed,
        hypothesis=(
            f"Cele lezace odlogiem {days} dni. Hipoteza: czynnik aging "
            f"jest za niski, by stare cele przebily nowsze prace w "
            f"priority. Podniesienie czynnika o {STALE_GOALS_DELTA} "
            f"powinno przesunac wybor planera na zalegle cele."
        ),
        rationale=(
            f"K12 rec {rec.rec_id}: {rec.topic[:80]}. "
            f"Pattern: stale-goals-aging >= {STALE_GOALS_MIN_DAYS} days."
        ),
        expected_outcome=(
            "Spadek liczby celow pending >14d o >=30% w oknie 7 dni; "
            "brak degradacji learning_velocity (cross-metric guard)."
        ),
        risk_assessment=spec.risk_level.value,
        trigger_data={
            "heuristic": "stale_goals_aging",
            "rec_id": rec.rec_id,
            "stale_days_observed": days,
            "summary": rec.description[:200] if rec.description else "",
        },
    )

    return HeuristicMatch(
        proposal=proposal,
        confidence=0.65,
        heuristic_name="stale_goals_aging",
    )


def route_recommendation(
    rec: AnalysisRecommendation,
    current_exam_pass_threshold: Optional[float] = None,
    current_aging_factor: Optional[float] = None,
) -> Optional[HeuristicMatch]:
    """Try each heuristic in priority order; return first match.

    Args:
        rec: K12 strategic-change recommendation.
        current_exam_pass_threshold: Live value of EXAM_PASS_THRESHOLD.
            If None, the function imports it from config at call time.
        current_aging_factor: Live value of AGING_FACTOR_PER_HOUR.
            If None, the function imports it from goal_selector at call time.

    Returns:
        HeuristicMatch if any heuristic matched, None if no rule applies
        (recommendation stays as bulletin entry only — operator-visible
        but not auto-converted to experiment).
    """
    if rec.suggested_action != "experiment":
        return None

    if current_exam_pass_threshold is None:
        try:
            from maria_core.sys.config import EXAM_PASS_THRESHOLD
            current_exam_pass_threshold = float(EXAM_PASS_THRESHOLD)
        except Exception as e:
            logger.warning(f"[K12->K11] cannot read EXAM_PASS_THRESHOLD: {e}")
            return None

    match = heuristic_skip_dominates(rec, current_exam_pass_threshold)
    if match is not None:
        return match

    if current_aging_factor is None:
        try:
            from agent_core.planner.goal_selector import AGING_FACTOR_PER_HOUR
            current_aging_factor = float(AGING_FACTOR_PER_HOUR)
        except Exception as e:
            logger.warning(f"[K12->K11] cannot read AGING_FACTOR_PER_HOUR: {e}")
            return None

    match = heuristic_stale_goals_aging(rec, current_aging_factor)
    if match is not None:
        return match

    return None
