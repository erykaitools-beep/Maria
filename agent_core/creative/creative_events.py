"""Event names and payload contracts for Creative Module telemetry."""


# Event names for PerceptionAdapter / event logging
TENSION_DETECTED = "creative.tension_detected"
INSIGHT_FORMED = "creative.insight_formed"
META_GOAL_PROPOSED = "creative.meta_goal_proposed"
REFRAME_GENERATED = "creative.reframe_generated"
EXPLORATION_PROPOSED = "creative.exploration_program_proposed"
GOAL_REJECTED_DUPLICATE = "creative.goal_rejected_duplicate"
GOAL_SUPPRESSED_LOOP = "creative.goal_suppressed_loop"  # D3
MEMORY_RETRIEVED = "creative.memory_retrieved"
JOURNAL_ENTRY_WRITTEN = "creative.journal_entry_written"
PERSONALITY_SIGNAL_EMITTED = "creative.personality_signal_emitted"
PERSONALITY_SIGNAL = PERSONALITY_SIGNAL_EMITTED  # alias for facade
GOAL_PROMOTED = "creative.goal_promoted_to_goalstore"
REFLECTION_SESSION_COMPLETE = "creative.reflection_session_complete"
