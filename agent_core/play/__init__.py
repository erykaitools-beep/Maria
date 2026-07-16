"""Play - Maria's ungraded self-time ("pokoj dla siebie").

A deliberately non-instrumental room: when Maria has nothing assigned to do
and is awake, she takes a "walk through her own head" (spacer po wlasnej
glowie) -- picks a couple of things she already knows, writes a short free
musing or question connecting them, FOR ITS OWN SAKE. No exam, no score, no
goal, no promotion gate.

Why this exists (2026-06-19): the diagnosis found Maria's idle time was
either dead no_goals or a closed creative loop that detected its own boredom,
proposed "be more diverse", posted it to a bulletin nobody read, and forgot it
(journal later_outcome = 0/1931). Play is the structural opposite:
  - feed-forward: she RE-READS her own recent musings and can continue a
    thread -- the loop the creative journal never closed.
  - ungraded: nothing here is measured, promoted, or examined.

K7: classified FREE (internal, writes only to its own journal, no effector).
Wired into the planner as ActionType.PLAY, gated by PLAY_ENABLED (default OFF).
"""

from agent_core.play.play_module import PlayModule, PlayJournal

__all__ = ["PlayModule", "PlayJournal"]
