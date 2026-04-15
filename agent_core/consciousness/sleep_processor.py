"""
SleepProcessor - Memory consolidation during SLEEP mode.

When Maria enters SLEEP mode, this processor runs through 4 phases:
- NREM1: Gather stats about knowledge and beliefs (observation)
- NREM2: Strengthen high-confidence beliefs, re-index semantic vectors
- NREM3: Decay old beliefs, prune weak ones, mark stale knowledge (FORGETTING)
- REM: Generate dreams from beliefs (creative connections)
- Archival: Compress old JSONL logs to /mnt/storage

Works on REAL data: BeliefStore, knowledge_index, SemanticMemory.
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
        # Legacy compat: accept semantic_memory but ignore internals
        semantic_memory=None,
    ):
        self._belief_store = belief_store
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
        """NREM2 - Boost confidence of well-evidenced beliefs."""
        boosted = 0

        if self._belief_store:
            beliefs = self._belief_store.get_current()
            for belief in beliefs:
                # Beliefs with evidence from multiple sources get a small boost
                evidence = getattr(belief, 'evidence', []) or []
                if len(evidence) >= 2 and belief.confidence < 0.95:
                    new_conf = min(0.95, belief.confidence + 0.02)
                    self._belief_store.revise(belief.belief_id, new_conf)
                    boosted += 1

        result = {
            "phase": "nrem2",
            "beliefs_boosted": boosted,
        }
        logger.debug(f"NREM2: boosted {boosted} beliefs")
        return result

    # -- NREM3: Forgetting (decay, prune, cleanup) --

    def _phase_nrem3(self) -> Dict[str, Any]:
        """NREM3 - Compact and prune weak beliefs. THIS IS FORGETTING."""
        before = 0
        pruned = 0

        if self._belief_store:
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
            "beliefs_before": before if self._belief_store else 0,
            "beliefs_pruned": pruned,
        }
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
            return {
                "type": dream_type,
                "content": content,
                "beliefs": [a.belief_id],
                "timestamp": time.time(),
            }
        else:
            template = random.choice(CONNECTION_TEMPLATES)
            dream_type = "connection"

        content = template.format(a=label_a, b=label_b)
        return {
            "type": dream_type,
            "content": content,
            "beliefs": [a.belief_id, b.belief_id],
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
