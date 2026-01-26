"""
M.A.R.I.A. Agent Core - Homeostasis-based AI Agent Architecture

This package implements the full homeostasis system as specified in homeostasis_spec.md.
All modules follow the specification exactly - no MVP shortcuts.

Subpackages:
- homeostasis: Core homeostasis loop, sensors, constraints, mode regulation
- memory: Memory management with JSONL as source of truth
- llm: LLM interface and latency monitoring
- metacontrol: Meta-controller for higher-level reasoning
- executor: Module signal dispatch and communication
- ui: Telemetry API and operator controls
- tests: Full test coverage for all requirements

Version: 0.1.0
Status: Implementation in progress
Spec: homeostasis_spec.md (1852 lines)
"""

__version__ = "0.1.0"
__author__ = "MARIA Project"
