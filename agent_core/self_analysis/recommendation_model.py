"""
K12 Self-Analysis: data models for analysis recommendations and reports.

Follows the pattern of experiment_model.py (K11) - frozen dataclasses
with JSON serialization.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Any, List, Optional
import time
import uuid


class RecommendationCategory(Enum):
    """What kind of recommendation."""
    KNOWLEDGE_GAP = "knowledge_gap"       # Topic with low confidence
    RETENTION_PROBLEM = "retention_problem"  # Failing exams on known topic
    STRATEGY_CHANGE = "strategy_change"    # Suggest parameter tuning
    NEW_TOPIC = "new_topic"               # Completely new area to explore


class SuggestedAction(Enum):
    """What Maria should do about the recommendation."""
    LEARN = "learn"     # Create learning goal
    FETCH = "fetch"     # Fetch materials then learn
    REVIEW = "review"   # Review/consolidate existing knowledge
    EXPERIMENT = "experiment"  # K11 parameter experiment


class AnalyzerBackend(Enum):
    """Which AI backend performed the analysis."""
    LOCAL_PLANNER = "local_planner"   # qwen3:8b via ModelScheduler
    CLAUDE_CLI = "claude_cli"         # Claude Code CLI (Phase 2)
    CHATGPT_CLI = "chatgpt_cli"      # ChatGPT/Codex (Phase 3)
    MANUAL = "manual"                 # Operator pasted results


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class AnalysisRecommendation:
    """Single recommendation from external analysis."""
    rec_id: str
    category: str          # RecommendationCategory value
    topic: str
    description: str
    priority: float        # 0.0-1.0
    suggested_action: str  # SuggestedAction value
    evidence: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    file_paths: list = field(default_factory=list)        # files related to recommendation
    line_hints: Dict[str, str] = field(default_factory=dict)  # {"file.py": "120-135"}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AnalysisRecommendation":
        return cls(
            rec_id=d.get("rec_id", _gen_id("rec")),
            category=d.get("category", "knowledge_gap"),
            topic=d.get("topic", "unknown"),
            description=d.get("description", ""),
            priority=float(d.get("priority", 0.5)),
            suggested_action=d.get("suggested_action", "learn"),
            evidence=d.get("evidence", {}),
            metadata=d.get("metadata", {}),
            file_paths=d.get("file_paths", []),
            line_hints=d.get("line_hints", {}),
        )


@dataclass
class AnalysisReport:
    """Complete self-analysis report."""
    report_id: str = field(default_factory=lambda: _gen_id("sa"))
    timestamp: float = field(default_factory=time.time)
    analyzer: str = "local_planner"  # AnalyzerBackend value
    model: Optional[str] = None       # Concrete model name used by analyzer
    input_summary_hash: str = ""
    recommendations: List[AnalysisRecommendation] = field(default_factory=list)
    goals_created: List[str] = field(default_factory=list)
    beliefs_updated: int = 0
    duration_ms: float = 0.0
    raw_response: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["recommendations"] = [r.to_dict() for r in self.recommendations]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AnalysisReport":
        recs = [
            AnalysisRecommendation.from_dict(r)
            for r in d.get("recommendations", [])
        ]
        return cls(
            report_id=d.get("report_id", _gen_id("sa")),
            timestamp=d.get("timestamp", time.time()),
            analyzer=d.get("analyzer", "local_planner"),
            model=d.get("model"),
            input_summary_hash=d.get("input_summary_hash", ""),
            recommendations=recs,
            goals_created=d.get("goals_created", []),
            beliefs_updated=d.get("beliefs_updated", 0),
            duration_ms=d.get("duration_ms", 0),
            raw_response=d.get("raw_response", ""),
            error=d.get("error"),
        )


# Limits
MAX_RECOMMENDATIONS_PER_REPORT = 5
MAX_PROPOSED_GOALS_FROM_ANALYSIS = 3

# Max length of one composed recommendation line. Five of these sit comfortably
# inside Telegram's message limit; long enough that a real finding + its number
# ("exam success rate is low (0.19)") survives intact.
REC_LINE_MAX = 240


def _markdown_safe(text: str) -> str:
    """Neutralise Telegram-Markdown metacharacters in operator-facing prose.

    Recommendation text is prose and snake_case identifiers from an LLM, never
    intended markdown. Telegram reads _ * ` [ as formatting: a topic like
    'system_stability' (32% of live recommendations carry '_') italicises, or,
    when the underscores balance across the message, is silently eaten with no
    API error -- so the bot's markdown->plain fallback never fires. Underscore
    becomes a space (keeps snake_case readable); the rest are dropped. This is
    what the docstring's "markdown-clean" promise always claimed but never did.
    """
    text = text.replace("_", " ")
    for ch in ("*", "`", "[", "]"):
        text = text.replace(ch, "")
    return text


def _truncate(text: str, limit: int) -> str:
    """Trim to `limit` chars on a word boundary, marking the cut with '...'."""
    text = text.strip()
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[: limit - 3].rstrip()
    # Prefer breaking at the last space so a word is not sliced mid-token.
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space].rstrip()
    return cut + "..."


def format_report_for_telegram(report: "AnalysisReport") -> tuple:
    """Build a clean (summary, recommendations) pair for the K12 Telegram card.

    The notifier used to receive ``report.raw_response[:300]`` (raw JSON / model
    prose) as the summary and ``str(recommendation)`` dataclass reprs as the
    items -- operator-facing junk seen in Telegram on 2026-06-15. This returns a
    one-line provenance + count, and one line per recommendation, both already
    markdown-clean (the parser strips markers).

    Each line is "topic -> action: description". The description is the finding
    and its number -- "exam success rate is low (0.19)". Dropping it (as this
    did before 2026-07-16) left the operator with "Exam Success Rate -> review":
    a label with no idea of what was wrong or how bad. The "topic -> action" head
    stays as the scannable prefix; the reason rides behind it.
    """
    recs = []
    for r in report.recommendations:
        if isinstance(r, str):
            line = r.strip()
        else:
            topic = (getattr(r, "topic", "") or "").strip()
            action = (getattr(r, "suggested_action", "") or "").strip()
            description = (getattr(r, "description", "") or "").strip()
            head = f"{topic} -> {action}" if (topic and action) else (topic or action)
            if head and description:
                # Trim only the reason, never the head -- the label must stay whole.
                budget = REC_LINE_MAX - len(head) - 2  # ": "
                line = f"{head}: {_truncate(description, budget)}"
            else:
                line = _truncate(head or description, REC_LINE_MAX)
        if line:
            recs.append(_markdown_safe(line))
    provenance = report.model or report.analyzer or "?"
    summary = _markdown_safe(f"{provenance}: {len(recs)} rekomendacji")
    return summary, recs
