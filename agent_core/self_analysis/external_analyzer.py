"""
K12 Self-Analysis: ExternalAnalyzer.

Invokes a stronger AI model to analyze Maria's compressed state
and return structured recommendations.

MVP backend: local_planner (qwen3:8b via ModelScheduler).
Phase 2: claude_cli (Claude Code CLI via OpenClaw exec).
"""

import json
import logging
import time
from typing import Dict, Any, List, Optional, Callable

from .recommendation_model import (
    AnalysisRecommendation,
    AnalysisReport,
    AnalyzerBackend,
    MAX_RECOMMENDATIONS_PER_REPORT,
    _gen_id,
)

logger = logging.getLogger(__name__)

# System prompt for analysis
_ANALYSIS_SYSTEM_PROMPT = (
    "You are an expert AI systems analyst. You are analyzing the performance logs "
    "of M.A.R.I.A., an autonomous AI learning agent that learns from text files. "
    "Analyze the provided data and return actionable recommendations. "
    "Be specific about topics, not generic advice."
)


class ExternalAnalyzer:
    """Analyze Maria's state using a stronger AI model."""

    def __init__(
        self,
        llm_fn: Optional[Callable[[str], str]] = None,
        backend: str = "local_planner",
    ):
        """
        Args:
            llm_fn: Function that takes prompt string, returns response string.
                     For local_planner: router.ask_as_role(PLANNER, prompt)
                     For claude_cli: subprocess wrapper (Phase 2)
            backend: Which backend to use (for reporting).
        """
        self._llm_fn = llm_fn
        self._backend = backend

    def set_llm_fn(self, fn: Callable[[str], str]):
        """Set LLM function (dependency injection from homeostasis wiring)."""
        self._llm_fn = fn

    def analyze(self, state_summary: Dict[str, Any]) -> AnalysisReport:
        """
        Send compressed state to external AI and parse recommendations.

        Args:
            state_summary: Output from StateCollector.collect_with_prompt()

        Returns:
            AnalysisReport with recommendations (may be empty on failure)
        """
        report = AnalysisReport(
            analyzer=self._backend,
            input_summary_hash=state_summary.get("input_hash", ""),
        )

        if self._llm_fn is None:
            report.error = "No LLM function configured"
            logger.warning("[K12] ExternalAnalyzer: no llm_fn set")
            return report

        start_ms = time.time() * 1000

        # Build prompt
        prompt = self._build_prompt(state_summary)

        try:
            # Call the stronger model
            raw_response = self._llm_fn(prompt)
            report.raw_response = (raw_response or "")[:2000]

            if not raw_response:
                report.error = "Empty response from analyzer"
                return report

            # Parse recommendations from response
            recommendations = self._parse_response(raw_response)
            report.recommendations = recommendations[:MAX_RECOMMENDATIONS_PER_REPORT]

        except Exception as e:
            report.error = f"Analysis failed: {str(e)[:200]}"
            logger.error(f"[K12] Analysis error: {e}")

        report.duration_ms = time.time() * 1000 - start_ms
        return report

    def _build_prompt(self, state_summary: Dict[str, Any]) -> str:
        """Build analysis prompt from state summary."""
        # Extract the analysis prompt (set by StateCollector)
        analysis_prompt = state_summary.pop("analysis_prompt", "")

        # Serialize state data (compact)
        state_json = json.dumps(state_summary, indent=None, default=str, ensure_ascii=False)

        prompt = (
            f"{_ANALYSIS_SYSTEM_PROMPT}\n\n"
            f"=== AGENT STATE DATA ===\n{state_json}\n\n"
            f"=== YOUR TASK ===\n{analysis_prompt}"
        )

        return prompt

    def _parse_response(self, response: str) -> List[AnalysisRecommendation]:
        """Parse AI response into AnalysisRecommendation list."""
        # Try JSON parse (ideal case)
        parsed = self._try_parse_json(response)

        if parsed and "recommendations" in parsed:
            return [
                AnalysisRecommendation.from_dict(r)
                for r in parsed["recommendations"]
                if isinstance(r, dict)
            ]

        # Fallback: try to extract structured data from free text
        return self._parse_freetext(response)

    def _try_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Try to extract JSON from response (handles markdown wrapping)."""
        import re

        text = text.strip()

        # Try markdown code fences
        md_match = re.search(r'```(?:json)?\s*(.+?)\s*```', text, re.DOTALL)
        if md_match:
            try:
                return json.loads(md_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try direct JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try bracket extraction
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None

    def _parse_freetext(self, text: str) -> List[AnalysisRecommendation]:
        """Extract recommendations from free-text response (fallback)."""
        recommendations = []
        lines = text.strip().split("\n")

        current_topic = ""
        current_desc = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Look for numbered items or bullet points
            import re
            match = re.match(r'^[\d]+[.)]\s*(.+)', line)
            if not match:
                match = re.match(r'^[-*]\s*(.+)', line)

            if match:
                content = match.group(1).strip()

                # If we have a previous item, save it
                if current_topic and current_desc:
                    recommendations.append(AnalysisRecommendation(
                        rec_id=_gen_id("rec"),
                        category="knowledge_gap",
                        topic=current_topic[:100],
                        description=current_desc[:300],
                        priority=0.5,
                        suggested_action="learn",
                    ))

                # Parse new item
                # Try to split "topic: description" or "topic - description"
                for sep in [":", " - ", " -- "]:
                    if sep in content:
                        parts = content.split(sep, 1)
                        current_topic = parts[0].strip()
                        current_desc = parts[1].strip()
                        break
                else:
                    current_topic = content[:50]
                    current_desc = content

            elif current_topic:
                # Continuation of description
                current_desc += " " + line

        # Save last item
        if current_topic and current_desc:
            recommendations.append(AnalysisRecommendation(
                rec_id=_gen_id("rec"),
                category="knowledge_gap",
                topic=current_topic[:100],
                description=current_desc[:300],
                priority=0.5,
                suggested_action="learn",
            ))

        return recommendations[:MAX_RECOMMENDATIONS_PER_REPORT]
