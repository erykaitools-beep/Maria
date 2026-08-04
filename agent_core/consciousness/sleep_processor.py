"""
SleepProcessor - Memory consolidation during SLEEP mode.

When Maria enters SLEEP mode, this processor runs through 5 phases:
- NREM1: Gather stats about knowledge and beliefs (observation)
- NREM2: Corroboration boost for beliefs with NO exam record, toward a
         level set by source count (rewritten 2026-08-01; see constants)
- NREM3: Compact the belief file, prune over-cap beliefs (FORGETTING)
- Archival: Compress old JSONL logs to /mnt/storage
- REM: Generate dreams from beliefs (creative connections)

Semantic vectors are NOT touched here (stale docstring fixed 2026-06-10):
indexing happens in agent_core/semantic/indexer.py at startup, semantic
dedup in the planner's post-EVALUATE maintain() path.

Works on REAL data: BeliefStore, knowledge_index.
Pure logic, no LLM calls. Runs once when SLEEP mode is entered.
"""

import json
import time
import random
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Storage archival (lazy import)
_log_archiver = None

DEFAULT_DREAM_LOG = Path("meta_data/dream_log.jsonl")
KNOWLEDGE_INDEX_PATH = Path("memory/knowledge_index.jsonl")

# Thresholds
BELIEF_STALE_DAYS = 30          # Observations older than this get extra decay
BELIEF_PRUNE_FLOOR = 0.05       # Below this confidence = candidate for removal
KNOWLEDGE_STALE_DAYS = 60       # Knowledge not reviewed in this many days
MAX_DREAMS_PER_CYCLE = 3

# --- Corroboration boost (rewritten 2026-08-01) ------------------------------
#
# The previous rule gave every belief with two or more evidence entries a flat
# +0.02 on EVERY sleep cycle, capped at 0.95. Corroboration is a one-time
# property of the evidence -- a belief either has two sources or it does not --
# but it was being paid out again every night, so given enough nights every
# qualifying belief reached the cap regardless of whether it was true.
#
# Measured before this change: 43.4% of 2000 beliefs sat at exactly 0.95, the
# literal value of the old min() cap. Replaying the exam ratchet alone over the
# true exam history produces a median of 0.600, so the gap up to 0.95 was this
# function's doing, not the exams'. 156 beliefs that had never passed a single
# exam held a median confidence of 0.95: they did not need to be right, only to
# survive two dozen nights.
#
# Two rules now:
#   1. The boost targets a LEVEL derived from how many sources corroborate the
#      belief, and stops on arrival. It cannot accumulate with time.
#   2. It applies only to beliefs with NO direct exam evidence. Corroboration is
#      weak indirect evidence; where direct evidence exists the exam record
#      governs, and a source count must never lift a belief that keeps failing.
CORROBORATION_CEILING = 0.85    # never as high as the old 0.95 cap
CORROBORATION_BASE = 0.70       # target with the minimum two sources
CORROBORATION_PER_SOURCE = 0.03
CORROBORATION_STEP = 0.02       # per-cycle approach rate toward the target

def _has_exam_evidence(evidence) -> bool:
    """True if this belief carries direct evidence from an exam.

    Matches on the evidence source field, which BeliefStore writes as the
    first element of each (source, ref, score) triple.
    """
    for ev in evidence or []:
        if not isinstance(ev, (list, tuple)) or not ev:
            continue
        if str(ev[0]).lower() == "exam":
            return True
    return False


# Dream templates (Polish)
CONNECTION_TEMPLATES = [
    "Snilo mi sie, ze {a} laczy sie z {b} - moze sa ze soba powiazane?",
    "Przysnilo mi sie, ze {a} i {b} maja cos wspolnego. Ciekawe...",
    "We snie zobaczyalam polaczenie miedzy {a} a {b}. Warto zbadac.",
    "Snilo mi sie o {a}. Nagle pojawialo sie {b} - dziwne, ale intrygujace.",
]

HYPOTHESIS_TEMPLATES = [
    "A co jesli {a} wplywa na {b}? We snie to mialo sens.",
    "Moze {a} i {b} to dwa aspekty tego samego? Tak mi sie snilo.",
    "Sen podpowiedzial mi: zbadaj zwiazek miedzy {a} a {b}.",
]

EXPLORATION_TEMPLATES = [
    "Snilo mi sie o {a}. Chcialabym wiedziec o tym wiecej.",
    "We snie gleboko myslalam o {a}. Moze warto do tego wrocic.",
]


def _curiosity_topics(*beliefs) -> List[str]:
    """Fetchable concept labels from beliefs -> the TopicSuggester DREAM strategy.

    Only TOPIC-type entities qualify: they are tag-derived clean labels
    ("mechanika", "dedukcja"). CONCEPT/FILE/OBSERVATION entities are frequently
    sentence- or file-id-shaped ("Dla liczb nieparzystych: c_{n+1}=...",
    "web_rss_x.txt") which Wikipedia opensearch returns nothing for, so they are
    dropped at the source. (2026-06-20, review MF1)
    """
    try:
        from agent_core.world_model.belief_model import EntityType
        topic_type = EntityType.TOPIC
    except Exception:
        return []
    out = []
    for b in beliefs:
        if getattr(b, "entity_type", None) == topic_type and getattr(b, "entity", ""):
            out.append(b.entity)
    return out


def _get_archiver():
    """Lazy-init LogArchiver (only if /mnt/storage is mounted)."""
    global _log_archiver
    if _log_archiver is not None:
        return _log_archiver
    archive_path = Path("/mnt/storage/data/logs")
    if archive_path.parent.exists():
        from agent_core.storage import LogArchiver
        _log_archiver = LogArchiver()
        return _log_archiver
    return None


class SleepProcessor:
    """
    Processes a full sleep cycle on Maria's real memory systems.

    Usage:
        processor = SleepProcessor(
            belief_store=ctx.world_model.store,
            knowledge_index_path=Path("memory/knowledge_index.jsonl"),
            session_id=42,
        )
        report = processor.process_sleep_cycle()
    """

    def __init__(
        self,
        belief_store=None,
        knowledge_index_path: Optional[Path] = None,
        session_id: int = 0,
        dream_log_path: Optional[Path] = None,
        mutate_beliefs: bool = True,
        # Legacy compat: accept semantic_memory but ignore internals
        semantic_memory=None,
    ):
        self._belief_store = belief_store
        # When False, the belief-MUTATING phases (NREM2 boost, NREM3 prune) are
        # skipped while the READ-only phases (NREM1 stats, REM dreams) still run.
        # Lets dreams fire on a throttled sleep without re-saturating confidence.
        self._mutate_beliefs = mutate_beliefs
        self._ki_path = Path(knowledge_index_path or KNOWLEDGE_INDEX_PATH)
        self.session_id = session_id
        self._dream_log_path = Path(dream_log_path or DEFAULT_DREAM_LOG)

    def process_sleep_cycle(self) -> Dict[str, Any]:
        """Run full sleep cycle through all phases."""
        start = time.time()

        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session": self.session_id,
            "phases": {},
            "phases_completed": 0,
            "dreams": [],
            "duration_ms": 0,
        }

        phases = [
            ("nrem1", self._phase_nrem1),
            ("nrem2", self._phase_nrem2),
            ("nrem3", self._phase_nrem3),
            ("archival", self._phase_archival),
            ("rem", self._phase_rem),
        ]

        for name, fn in phases:
            try:
                result = fn()
                report["phases"][name] = result
                report["phases_completed"] += 1
                if name == "rem":
                    report["dreams"] = result.get("dreams", [])
            except Exception as e:
                logger.warning(f"Sleep {name} failed: {e}")
                report["phases"][name] = {"error": str(e)}

        report["duration_ms"] = round((time.time() - start) * 1000, 1)

        logger.info(
            f"Sleep cycle complete: {report['phases_completed']} phases, "
            f"{len(report['dreams'])} dreams, {report['duration_ms']}ms"
        )

        return report

    # -- NREM1: Observation (stats gathering) --

    def _phase_nrem1(self) -> Dict[str, Any]:
        """NREM1 - Gather stats about beliefs and knowledge."""
        result = {"phase": "nrem1"}

        # Belief stats
        if self._belief_store:
            beliefs = self._belief_store.get_current()
            confs = [b.confidence for b in beliefs]
            result["beliefs_total"] = len(beliefs)
            result["beliefs_avg_confidence"] = round(
                sum(confs) / max(len(confs), 1), 3
            )
            result["beliefs_weak"] = sum(1 for c in confs if c < 0.3)
            result["beliefs_strong"] = sum(1 for c in confs if c >= 0.7)

            # By type
            from collections import Counter
            types = Counter(b.belief_type for b in beliefs)
            result["beliefs_by_type"] = dict(types)
        else:
            result["beliefs_total"] = 0
            result["beliefs_skipped"] = "no belief_store"

        # Knowledge stats
        ki = self._load_knowledge_index()
        result["knowledge_total"] = len(ki)
        from collections import Counter
        statuses = Counter(f.get("status", "?") for f in ki.values())
        result["knowledge_by_status"] = dict(statuses)

        logger.debug(
            f"NREM1: {result.get('beliefs_total', 0)} beliefs, "
            f"{result.get('knowledge_total', 0)} knowledge files"
        )
        return result

    # -- NREM2: Strengthen (reinforce good memories) --

    def _phase_nrem2(self) -> Dict[str, Any]:
        """NREM2 - Boost confidence of well-evidenced beliefs (mutating phase)."""
        boosted = 0

        skipped_examined = 0
        if self._belief_store and self._mutate_beliefs:
            beliefs = self._belief_store.get_current()
            for belief in beliefs:
                evidence = getattr(belief, 'evidence', []) or []
                if len(evidence) < 2:
                    continue
                # Direct evidence wins. A belief that has sat exams is scored by
                # those exams; corroboration must not lift one that keeps failing.
                if _has_exam_evidence(evidence):
                    skipped_examined += 1
                    continue
                # Corroboration sets a level, it does not pay out per cycle.
                target = min(
                    CORROBORATION_CEILING,
                    CORROBORATION_BASE + CORROBORATION_PER_SOURCE * (len(evidence) - 2),
                )
                if belief.confidence >= target:
                    continue
                new_conf = min(target, belief.confidence + CORROBORATION_STEP)
                self._belief_store.revise(belief.belief_id, new_conf)
                boosted += 1

        result = {
            "phase": "nrem2",
            "beliefs_boosted": boosted,
            # Recorded rather than silent: this is the population that used to
            # be lifted to 0.95 without regard to its exam record.
            "beliefs_left_to_exams": skipped_examined,
        }
        if not self._mutate_beliefs:
            result["skipped"] = "throttled"
        logger.debug(f"NREM2: boosted {boosted} beliefs")
        return result

    # -- NREM3: Forgetting (decay, prune, cleanup) --

    def _phase_nrem3(self) -> Dict[str, Any]:
        """NREM3 - Compact and prune weak beliefs (mutating phase). FORGETTING."""
        before = 0
        pruned = 0

        if self._belief_store and self._mutate_beliefs:
            try:
                before = len(self._belief_store.get_current())
                self._belief_store.compact()
                self._belief_store._enforce_cap()
                after = len(self._belief_store.get_current())
                pruned = max(0, before - after)
            except Exception as e:
                logger.warning(f"NREM3 belief compact failed: {e}")

        result = {
            "phase": "nrem3",
            "beliefs_before": before,
            "beliefs_pruned": pruned,
        }
        if not self._mutate_beliefs:
            result["skipped"] = "throttled"
        logger.debug(f"NREM3: pruned {pruned}")
        return result

    # -- Archival: Log compression --

    def _phase_archival(self) -> Dict[str, Any]:
        """Compress old JSONL logs to /mnt/storage."""
        archiver = _get_archiver()
        if archiver is None:
            return {"phase": "archival", "skipped": True, "reason": "no storage"}

        result = archiver.run_archival()
        archived = result.get("total_archived", 0)
        kept = result.get("total_kept", 0)
        logger.info(f"Archival: {archived} archived, {kept} kept")
        return {
            "phase": "archival",
            "total_archived": archived,
            "total_kept": kept,
        }

    # -- REM: Dreams (creative connections from beliefs) --

    def _phase_rem(self) -> Dict[str, Any]:
        """REM - Generate dreams from beliefs (creative connections)."""
        dreams = []

        if self._belief_store:
            beliefs = self._belief_store.get_current()
            # Filter: only beliefs with meaningful content
            dreamable = [
                b for b in beliefs
                if b.confidence >= 0.2 and len(b.content) > 10
            ]

            attempts = 0
            while len(dreams) < MAX_DREAMS_PER_CYCLE and attempts < MAX_DREAMS_PER_CYCLE * 3:
                attempts += 1
                dream = self._generate_dream(dreamable)
                if dream:
                    dreams.append(dream)

        # Save dreams
        if dreams:
            self._save_dreams(dreams)

        result = {
            "phase": "rem",
            "dreams_generated": len(dreams),
            "dreams": dreams,
        }
        logger.debug(f"REM: generated {len(dreams)} dreams")
        return result

    def _generate_dream(self, beliefs: list) -> Optional[Dict[str, Any]]:
        """Generate a single dream from two random beliefs."""
        if len(beliefs) < 2:
            return None

        a, b = random.sample(beliefs, 2)
        label_a = a.content[:50].strip()
        label_b = b.content[:50].strip()

        # Choose dream type
        if random.random() < 0.3:
            template = random.choice(HYPOTHESIS_TEMPLATES)
            dream_type = "hypothesis"
        elif random.random() < 0.5:
            template = random.choice(EXPLORATION_TEMPLATES)
            dream_type = "exploration"
            content = template.format(a=label_a)
            # 2026-06-20: surface the (clean, TOPIC-type) concept she dreamed about
            # so the fetcher can chase curiosity (TopicSuggester DREAM strategy).
            topics = _curiosity_topics(a)
            return {
                "type": dream_type,
                "content": content,
                "beliefs": [a.belief_id],
                "topics": topics,
                "to_explore": bool(topics),
                "timestamp": time.time(),
            }
        else:
            template = random.choice(CONNECTION_TEMPLATES)
            dream_type = "connection"

        content = template.format(a=label_a, b=label_b)
        topics = _curiosity_topics(a, b)
        return {
            "type": dream_type,
            "content": content,
            "beliefs": [a.belief_id, b.belief_id],
            "topics": topics,
            "to_explore": bool(topics),
            "timestamp": time.time(),
        }

    def _save_dreams(self, dreams: List[Dict]) -> None:
        """Append dreams to dream_log.jsonl."""
        try:
            self._dream_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._dream_log_path, "a", encoding="utf-8") as f:
                for dream in dreams:
                    f.write(json.dumps(dream, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to save dreams: {e}")

    # -- Helpers --

    def _load_knowledge_index(self) -> Dict[str, dict]:
        """Load knowledge_index.jsonl (MERGE by id)."""
        result = {}
        if not self._ki_path.exists():
            return result
        try:
            with open(self._ki_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line.strip())
                        result[r.get("id", "")] = r
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass
        return result
