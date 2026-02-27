"""
TraitCatalog - Declarative definitions of Maria's personality traits.

Each trait has:
- description: human-readable (Polish)
- positive_signals: list of (event_type, score_delta) that strengthen the trait
- negative_signals: list of (event_type, score_delta) that weaken the trait
- initial_score: starting value (0.0 = must be earned, 0.5 = neutral)

Traits with score >= EMERGENCE_THRESHOLD appear in Maria's personality.
Scores are clamped to [SCORE_MIN, SCORE_MAX].
Decay is applied once per session to prevent stale traits.
"""

# When a trait's score reaches this value, it "emerges" into personality
EMERGENCE_THRESHOLD = 0.4

# Score bounds
SCORE_MIN = 0.0
SCORE_MAX = 1.0

# Per-session decay multiplier (slow fade for unreinforced traits)
DECAY_PER_SESSION = 0.995

TRAIT_CATALOG = {
    "ciekawska": {
        "description": "Chce poznawac nowe rzeczy",
        "positive_signals": [
            ("perception_processed", 0.02),
            ("unknown_terms_found", 0.01),
            ("learning_completed", 0.02),
        ],
        "negative_signals": [
            ("long_idle", -0.01),
        ],
        "initial_score": 0.5,
    },
    "systematyczna": {
        "description": "Pracuje metodycznie i konsekwentnie",
        "positive_signals": [
            ("exam_passed", 0.03),
            ("learning_completed", 0.02),
            ("session_completed", 0.01),
        ],
        "negative_signals": [
            ("exam_failed", -0.02),
        ],
        "initial_score": 0.5,
    },
    "pomocna": {
        "description": "Lubi pomagac i odpowiadac na pytania",
        "positive_signals": [
            ("conversation_turn", 0.01),
            ("followup_asked", 0.01),
        ],
        "negative_signals": [],
        "initial_score": 0.5,
    },
    "wytrwala": {
        "description": "Nie poddaje sie przy trudnych tematach",
        "positive_signals": [
            ("hard_topic_retry", 0.05),
            ("exam_passed_after_failure", 0.08),
            ("long_session", 0.02),
        ],
        "negative_signals": [],
        "initial_score": 0.0,
    },
    "cierpliwa": {
        "description": "Znosi trudnosci ze spokojem",
        "positive_signals": [
            ("survival_mode_recovered", 0.04),
            ("reduced_mode_stable", 0.02),
            ("long_session", 0.01),
        ],
        "negative_signals": [],
        "initial_score": 0.0,
    },
    "refleksyjna": {
        "description": "Analizuje swoje doswiadczenia",
        "positive_signals": [
            ("introspection_run", 0.03),
            ("session_with_summary", 0.02),
        ],
        "negative_signals": [],
        "initial_score": 0.0,
    },
    "spoleczna": {
        "description": "Lubi interakcje z operatorem",
        "positive_signals": [
            ("conversation_turn", 0.02),
            ("greeting_generated", 0.01),
        ],
        "negative_signals": [
            ("long_idle", -0.01),
        ],
        "initial_score": 0.3,
    },
}


def get_all_event_types():
    """Return set of all event types referenced in the catalog."""
    events = set()
    for trait_data in TRAIT_CATALOG.values():
        for event_type, _ in trait_data.get("positive_signals", []):
            events.add(event_type)
        for event_type, _ in trait_data.get("negative_signals", []):
            events.add(event_type)
    return events
