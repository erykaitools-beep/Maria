"""
K12 Self-Analysis: ExternalAnalyzer.

Invokes a stronger AI model to analyze Maria's compressed state
and return structured recommendations.

Backend cascade: NIM API (z-ai/glm5) -> local_planner (qwen3:8b).
NIM is stronger and faster (cloud, 40 RPM).
Local planner is fallback when NIM unavailable or rate-limited.
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
        nim_fn: Optional[Callable[[str], str]] = None,
        backend: str = "local_planner",
    ):
        """
        Args:
            llm_fn: Function for local planner (router.ask_as_role(PLANNER, prompt)).
            nim_fn: Function for NIM API (router._ask_once(prompt)).
                    Stronger model, cloud, 40 RPM limit.
            backend: Which backend to use for local fallback (for reporting).
        """
        self._llm_fn = llm_fn
        self._nim_fn = nim_fn
        self._backend = backend
        self._claude_cli = None

    def set_llm_fn(self, fn: Callable[[str], str]):
        """Set local LLM function (dependency injection from homeostasis wiring)."""
        self._llm_fn = fn

    def set_nim_fn(self, fn: Callable[[str], str]):
        """Set NIM API function for stronger analysis (K12 Phase 2)."""
        self._nim_fn = fn

    def set_claude_cli(self, client):
        """Set Claude CLI client for stronger analysis (K12 Phase 2)."""
        self._claude_cli = client

    def analyze(self, state_summary: Dict[str, Any]) -> AnalysisReport:
        """
        Send compressed state to external AI and parse recommendations.

        Cascade: NIM API -> local planner (fallback).

        Args:
            state_summary: Output from StateCollector.collect_with_prompt()

        Returns:
            AnalysisReport with recommendations (may be empty on failure)
        """
        # Try NIM API first (stronger model, cloud)
        if self._nim_fn is not None:
            try:
                nim_report = self._analyze_with_nim(state_summary)
                if nim_report and not nim_report.error:
                    return nim_report
                logger.info("[K12] NIM returned error, falling back to local")
            except Exception as e:
                logger.info(f"[K12] NIM failed, falling back to local: {e}")

        # Try Claude CLI if available
        if self._claude_cli:
            try:
                claude_report = self._analyze_with_claude(state_summary)
                if claude_report and not claude_report.error:
                    return claude_report
                logger.info("[K12] Claude CLI returned error, falling back to local")
            except Exception as e:
                logger.info(f"[K12] Claude CLI failed, falling back to local: {e}")

        # Fallback: local planner
        return self._analyze_with_local(state_summary)

    def _analyze_with_nim(self, state_summary: Dict[str, Any]) -> Optional[AnalysisReport]:
        """Analyze using NIM API (z-ai/glm5, stronger cloud model)."""
        if self._nim_fn is None:
            return None

        report = AnalysisReport(
            analyzer="nim_api",
            input_summary_hash=state_summary.get("input_hash", ""),
        )

        start_ms = time.time() * 1000

        # Use the same prompt as local, NIM handles it well
        prompt = self._build_prompt(state_summary)

        try:
            raw_response = self._nim_fn(prompt)
            report.raw_response = (raw_response or "")[:4000]

            if not raw_response:
                report.error = "Empty response from NIM API"
                return report

            recommendations = self._parse_response(raw_response)
            report.recommendations = recommendations[:MAX_RECOMMENDATIONS_PER_REPORT]

        except Exception as e:
            report.error = f"NIM analysis failed: {str(e)[:200]}"
            logger.error(f"[K12] NIM error: {e}")

        report.duration_ms = time.time() * 1000 - start_ms
        return report

    def _analyze_with_local(self, state_summary: Dict[str, Any]) -> AnalysisReport:
        """Analyze using local planner model (qwen3:8b)."""
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

    def _analyze_with_claude(self, state_summary: Dict[str, Any]) -> Optional[AnalysisReport]:
        """Analyze using Claude Code CLI (stronger model, K12 Phase 2)."""
        if not self._claude_cli or not self._claude_cli.is_available():
            return None

        report = AnalysisReport(
            analyzer="claude_cli",
            input_summary_hash=state_summary.get("input_hash", ""),
        )

        start_ms = time.time() * 1000
        prompt = self._build_claude_prompt(state_summary)

        try:
            raw_response = self._claude_cli.analyze(prompt)
            if raw_response is None:
                report.error = "Claude CLI returned None (rate limited or unavailable)"
                return report

            report.raw_response = (raw_response or "")[:4000]

            if not raw_response:
                report.error = "Empty response from Claude CLI"
                return report

            recommendations = self._parse_response(raw_response)
            report.recommendations = recommendations[:MAX_RECOMMENDATIONS_PER_REPORT]

        except Exception as e:
            report.error = f"Claude CLI analysis failed: {str(e)[:200]}"
            logger.error(f"[K12] Claude CLI error: {e}")

        report.duration_ms = time.time() * 1000 - start_ms
        return report

    def _build_claude_prompt(self, state_summary: Dict[str, Any]) -> str:
        """Build enhanced prompt for Claude CLI (handles larger context)."""
        analysis_prompt = state_summary.pop("analysis_prompt", "")
        state_json = json.dumps(state_summary, indent=None, default=str, ensure_ascii=False)

        return (
            "You are analyzing M.A.R.I.A., an autonomous AI learning agent "
            "running on a local mini PC with Ollama (llama3.1:8b). "
            "Analyze the operational data below and return actionable recommendations.\n\n"
            "Return JSON with:\n"
            '- "recommendations": [{rec_id, category, topic, description, priority (0-1), '
            'suggested_action (learn/fetch/review/experiment), '
            'file_paths (list of relevant source files), '
            'line_hints (dict of file->line_range)}]\n'
            '- "systemic_issues": [strings]\n'
            '- "summary": one paragraph\n\n'
            f"=== AGENT STATE DATA ===\n{state_json}\n\n"
            f"=== ANALYSIS TASK ===\n{analysis_prompt}\n\n"
            "Be specific. Reference file paths and line numbers where possible."
        )

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
