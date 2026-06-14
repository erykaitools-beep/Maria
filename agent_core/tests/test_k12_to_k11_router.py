"""Tests for K12 -> K11 router (Most #2 step 1+2, 2026-05-08+09)."""

from agent_core.experiment.experiment_model import (
    ProposalSource,
    ProposalStatus,
)
from agent_core.self_analysis.k12_to_k11_router import (
    AUTO_APPROVE_CONFIDENCE,
    SKIP_DOMINATES_DELTA,
    SKIP_DOMINATES_THRESHOLD_PCT,
    STALE_GOALS_DELTA,
    STALE_GOALS_MIN_DAYS,
    heuristic_skip_dominates,
    heuristic_stale_goals_aging,
    route_recommendation,
)
from agent_core.self_analysis.recommendation_model import AnalysisRecommendation


def _make_rec(
    topic: str = "Akcja 'skip' - dominacja",
    description: str = "Akcja 'skip' stanowi 87% wszystkich akcji",
    suggested_action: str = "experiment",
    category: str = "strategy_change",
) -> AnalysisRecommendation:
    return AnalysisRecommendation(
        rec_id="rec-test123",
        category=category,
        topic=topic,
        description=description,
        priority=0.9,
        suggested_action=suggested_action,
    )


# --- heuristic_skip_dominates ----------------------------------------


def test_skip_dominates_match_summary_pct():
    rec = _make_rec(description="skip stanowi 75% wszystkich akcji")
    match = heuristic_skip_dominates(rec, current_threshold=0.7)
    assert match is not None
    assert match.heuristic_name == "skip_dominates"
    assert match.proposal.parameter_id == "config.EXAM_PASS_THRESHOLD"
    assert match.proposal.current_value == 0.7
    assert match.proposal.proposed_value == round(0.7 - SKIP_DOMINATES_DELTA, 2)
    assert match.proposal.source == ProposalSource.K12_STRATEGIC_CHANGE
    assert match.confidence == 0.65


def test_skip_dominates_match_topic_pct():
    rec = _make_rec(
        topic="skip 89% blokuje proces",
        description="text without percentage",
    )
    match = heuristic_skip_dominates(rec, current_threshold=0.65)
    assert match is not None
    assert match.proposal.proposed_value == 0.6


def test_skip_dominates_below_threshold():
    rec = _make_rec(description="skip stanowi 35% akcji")
    match = heuristic_skip_dominates(rec, current_threshold=0.7)
    assert match is None  # 35 < 50 threshold


def test_skip_dominates_no_skip_word():
    rec = _make_rec(
        topic="learning velocity inconsistent",
        description="agent ma 75% problemow z retention",
    )
    match = heuristic_skip_dominates(rec, current_threshold=0.7)
    assert match is None  # 'skip' not in text


def test_skip_dominates_no_percentage():
    rec = _make_rec(description="agent skipuje materialy")
    match = heuristic_skip_dominates(rec, current_threshold=0.7)
    assert match is None  # no '%' in text


def test_skip_dominates_floor_respected():
    # min_value for EXAM_PASS_THRESHOLD is 0.4
    rec = _make_rec(description="skip stanowi 90% akcji")
    match = heuristic_skip_dominates(rec, current_threshold=0.4)
    assert match is None  # 0.4 - 0.05 = 0.35 < min 0.4


def test_skip_dominates_proposal_metadata():
    rec = _make_rec(description="skip stanowi 88% przy 0% sukcesu")
    match = heuristic_skip_dominates(rec, current_threshold=0.7)
    assert match is not None
    p = match.proposal
    assert "88" in p.hypothesis
    assert "skip" in p.hypothesis.lower()
    assert p.trigger_data["heuristic"] == "skip_dominates"
    assert p.trigger_data["skip_pct_observed"] == 88
    assert p.trigger_data["rec_id"] == rec.rec_id
    assert p.risk_assessment == "medium"


# --- route_recommendation --------------------------------------------


def test_route_only_for_experiment_suggested_action():
    rec_review = _make_rec(
        description="skip stanowi 75% akcji",
        suggested_action="review",
    )
    match = route_recommendation(rec_review, current_exam_pass_threshold=0.7)
    assert match is None  # not experiment-suggested

    rec_exp = _make_rec(
        description="skip stanowi 75% akcji",
        suggested_action="experiment",
    )
    match = route_recommendation(rec_exp, current_exam_pass_threshold=0.7)
    assert match is not None


def test_route_no_match_no_proposal():
    rec = _make_rec(
        topic="abstract problem",
        description="rebuild decision procedure",
        suggested_action="experiment",
    )
    match = route_recommendation(rec, current_exam_pass_threshold=0.7)
    assert match is None


def test_route_returns_match_with_proposal():
    rec = _make_rec(description="skip stanowi 80% akcji")
    match = route_recommendation(rec, current_exam_pass_threshold=0.75)
    assert match is not None
    assert match.proposal.status == ProposalStatus.DRAFT
    # Confidence below auto-approve threshold means caller routes to operator
    assert match.confidence < AUTO_APPROVE_CONFIDENCE
    assert match.confidence == 0.65


# --- heuristic_stale_goals_aging --------------------------------------


def test_stale_goals_aging_match_basic():
    rec = _make_rec(
        topic="stale learning goals",
        description="Cele eksperymentalne lezace odlogiem 21 dni",
    )
    match = heuristic_stale_goals_aging(rec, current_aging_factor=0.1)
    assert match is not None
    assert match.heuristic_name == "stale_goals_aging"
    assert match.proposal.parameter_id == "goal_selector.AGING_FACTOR_PER_HOUR"
    assert match.proposal.current_value == 0.1
    assert match.proposal.proposed_value == round(0.1 + STALE_GOALS_DELTA, 2)
    assert match.proposal.source == ProposalSource.K12_STRATEGIC_CHANGE
    assert match.confidence == 0.65
    assert match.proposal.trigger_data["stale_days_observed"] == 21


def test_stale_goals_aging_polish_diacritics():
    rec = _make_rec(
        topic="stale learning goals",
        description="Cel meta-learn lezy odlogiem 68 dni bez progresu",
    )
    match = heuristic_stale_goals_aging(rec, current_aging_factor=0.2)
    assert match is not None
    assert match.proposal.proposed_value == 0.22
    assert match.proposal.trigger_data["stale_days_observed"] == 68


def test_stale_goals_aging_below_min_days():
    rec = _make_rec(description="zalegle cele od 7 dni")
    match = heuristic_stale_goals_aging(rec, current_aging_factor=0.1)
    assert match is None  # 7 < 14 min_days


def test_stale_goals_aging_no_stale_word():
    rec = _make_rec(
        topic="learn velocity",
        description="agent stracil velocity 30 dni temu",  # no stale-language
    )
    match = heuristic_stale_goals_aging(rec, current_aging_factor=0.1)
    assert match is None


def test_stale_goals_aging_no_day_count():
    rec = _make_rec(description="cele lezace odlogiem od dluzszego czasu")
    match = heuristic_stale_goals_aging(rec, current_aging_factor=0.1)
    assert match is None


def test_stale_goals_aging_ceiling_respected():
    # max_value for AGING_FACTOR_PER_HOUR is 0.5
    rec = _make_rec(description="cele odlogiem 100 dni")
    match = heuristic_stale_goals_aging(rec, current_aging_factor=0.5)
    assert match is None  # 0.5 + 0.02 = 0.52 > max 0.5


def test_stale_goals_aging_proposal_metadata():
    rec = _make_rec(description="goal-meta-learn odlogiem 68 dni")
    match = heuristic_stale_goals_aging(rec, current_aging_factor=0.1)
    assert match is not None
    p = match.proposal
    assert "68" in p.hypothesis
    assert p.trigger_data["heuristic"] == "stale_goals_aging"
    assert p.trigger_data["stale_days_observed"] == 68
    assert p.trigger_data["rec_id"] == rec.rec_id
    assert p.risk_assessment == "medium"


# --- route_recommendation precedence (h1 > h2) ------------------------


def test_route_skip_dominates_takes_precedence_over_stale():
    """A rec mentioning BOTH skip% and stale days routes to h1 (skip)."""
    rec = _make_rec(
        topic="zalegle akcje",
        description="skip stanowi 80% akcji a cele lezace odlogiem 30 dni",
    )
    match = route_recommendation(
        rec,
        current_exam_pass_threshold=0.7,
        current_aging_factor=0.1,
    )
    assert match is not None
    assert match.heuristic_name == "skip_dominates"


def test_route_stale_when_no_skip_match():
    rec = _make_rec(
        topic="stale learning goals",
        description="Cele eksperymentalne lezace odlogiem 21 dni",
    )
    match = route_recommendation(
        rec,
        current_exam_pass_threshold=0.7,
        current_aging_factor=0.1,
    )
    assert match is not None
    assert match.heuristic_name == "stale_goals_aging"


# --- regression: real K12 rec text from production ---------------------


def test_route_real_k12_rec_skip_87pct():
    """Regression: actual K12 rec from sa-5d880f82e70c (2026-05-09 07:28 UTC).

    This rec was the case where h1 should have fired but a wrong import
    silently failed in production for 4 days.
    """
    rec = AnalysisRecommendation(
        rec_id="rec-b52c14aae61f",
        category="strategy_change",
        topic="akcja 'skip'",
        description=(
            "Akcja 'skip' stanowi 87% wszystkich akcji (174 z 200) i ma "
            "0% sukcesu. Agresywne pomijanie blokuje naplyw nowych "
            "danych, powodujac stagnacje (learning_velocity = 0)."
        ),
        priority=1.0,
        suggested_action="experiment",
    )
    match = route_recommendation(rec)  # uses live config
    assert match is not None
    assert match.heuristic_name == "skip_dominates"
    assert match.proposal.trigger_data["skip_pct_observed"] == 87


def test_route_real_k12_rec_stale_meta_learn():
    """Regression: actual K12 rec from sa-9a73b09db12f (2026-05-08)."""
    rec = AnalysisRecommendation(
        rec_id="rec-60ceb595384e",
        category="strategy_change",
        topic="stale learning goals",
        description=(
            "Cel meta-learn lezy odlogiem 68 dni, a eksperymenty z akcja "
            "'learn' od 21 dni. Nalezy wznowic eksperymenty, by "
            "odblokowac zatrzymana learning_velocity."
        ),
        priority=0.75,
        suggested_action="experiment",
    )
    match = route_recommendation(rec)  # uses live config
    assert match is not None
    assert match.heuristic_name == "stale_goals_aging"
    # First day-count in text: '68 dni'
    assert match.proposal.trigger_data["stale_days_observed"] == 68


def test_route_uses_live_aging_factor_when_none_passed():
    """Fallback import path for AGING_FACTOR_PER_HOUR works."""
    from agent_core.planner.goal_selector import AGING_FACTOR_PER_HOUR as live

    rec = _make_rec(
        topic="stale goals",
        description="cele lezace odlogiem 30 dni bez ruchu",
    )
    match = route_recommendation(rec, current_exam_pass_threshold=0.7)
    assert match is not None, (
        "Fallback import path for AGING_FACTOR_PER_HOUR is broken."
    )
    assert match.proposal.parameter_id == "goal_selector.AGING_FACTOR_PER_HOUR"
    assert match.proposal.current_value == float(live)


def test_route_uses_live_threshold_when_none_passed():
    """When threshold not passed, function must import live value from config.

    Regression: a wrong import path (`from config import ...` vs
    `from maria_core.sys.config import ...`) silently failed in production
    for 4 days while unit tests passed by always injecting the threshold.
    This test forces the fallback path so an import-path break is caught.
    """
    from maria_core.sys.config import EXAM_PASS_THRESHOLD as live_threshold

    rec = _make_rec(description="skip stanowi 70% akcji")
    match = route_recommendation(rec, current_exam_pass_threshold=None)
    assert match is not None, (
        "Fallback import path is broken — router cannot read live threshold."
    )
    assert match.proposal.parameter_id == "config.EXAM_PASS_THRESHOLD"
    assert match.proposal.current_value == float(live_threshold)
    assert match.proposal.proposed_value == round(
        float(live_threshold) - SKIP_DOMINATES_DELTA, 2
    )
