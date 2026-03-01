"""
Sandbox / Production Boundary - Warstwa 0.5, Kontrakt K2

Kazda operacja nauki idzie przez sandbox.
Promote() to JEDYNY most do produkcji.

Kontrakt: docs/CONTRACTS.md - Kontrakt 2: Sandbox / Production Boundary
ADR-010: Sandbox-first learning
"""

from agent_core.sandbox.protocol import SandboxStatus, SandboxSession, PromoteResult
from agent_core.sandbox.manager import SandboxManager

__all__ = ["SandboxStatus", "SandboxSession", "PromoteResult", "SandboxManager"]
