"""
Approval Queue for Effector Actions (Phase 5).

Manages the HITL flow for effector tool invocations:
1. Maria's planner submits a request (tool_name, tool_args, goal context)
2. Operator gets notified via Telegram
3. Operator approves/rejects via /efapprove or /efreject
4. Next planner cycle picks up approved requests and executes them

Pending requests expire after EXPIRY_SEC (default 5 min).
Persistence: meta_data/approval_queue.jsonl (append-only log).

ADR-026: Effector Safety Envelope.
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default config
EXPIRY_SEC = 300  # 5 minutes
MAX_PENDING = 10  # Maximum concurrent pending requests
MAX_RECENT = 50   # Max stored in memory

_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
DEFAULT_LOG_PATH = _META_DIR / "approval_queue.jsonl"


def _gen_request_id() -> str:
    """Generate a short request ID."""
    return f"ereq-{uuid.uuid4().hex[:12]}"


@dataclass
class ApprovalRequest:
    """A single effector approval request."""
    request_id: str
    plan_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    goal_id: Optional[str]
    goal_description: str
    authority_level: str      # which level triggered this
    created_at: float
    status: str = "pending"   # pending | approved | rejected | expired
    operator_ts: Optional[float] = None
    episode_id: str = ""
    action_params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "ApprovalRequest":
        return cls(
            request_id=data.get("request_id", ""),
            plan_id=data.get("plan_id", ""),
            tool_name=data.get("tool_name", ""),
            tool_args=data.get("tool_args", {}),
            goal_id=data.get("goal_id"),
            goal_description=data.get("goal_description", ""),
            authority_level=data.get("authority_level", ""),
            created_at=data.get("created_at", 0.0),
            status=data.get("status", "pending"),
            operator_ts=data.get("operator_ts"),
            episode_id=data.get("episode_id", ""),
            action_params=data.get("action_params", {}),
        )


class ApprovalQueue:
    """
    Thread-safe queue for effector approval requests.

    Submit -> notify operator -> approve/reject -> pickup.
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        expiry_sec: float = EXPIRY_SEC,
    ):
        self._log_path = log_path or DEFAULT_LOG_PATH
        self._expiry_sec = expiry_sec
        self._lock = threading.Lock()
        self._requests: Dict[str, ApprovalRequest] = {}
        self._recent: List[ApprovalRequest] = []  # bounded history

    def submit(
        self,
        plan_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        goal_id: Optional[str] = None,
        goal_description: str = "",
        authority_level: str = "",
        episode_id: str = "",
        action_params: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """
        Submit a new approval request.

        Returns:
            The created ApprovalRequest
        """
        request = ApprovalRequest(
            request_id=_gen_request_id(),
            plan_id=plan_id,
            tool_name=tool_name,
            tool_args=tool_args,
            goal_id=goal_id,
            goal_description=goal_description,
            authority_level=authority_level,
            created_at=time.time(),
            episode_id=episode_id,
            action_params=action_params or {},
        )

        with self._lock:
            # Enforce max pending limit
            pending_count = sum(
                1 for r in self._requests.values() if r.status == "pending"
            )
            if pending_count >= MAX_PENDING:
                logger.warning(
                    "Approval queue full (%d pending), rejecting new request",
                    pending_count,
                )
                request.status = "rejected"
                self._append_log(request)
                return request

            self._requests[request.request_id] = request
            self._append_log(request)

        logger.info(
            "[ApprovalQueue] Submitted: %s tool=%s goal=%s",
            request.request_id, tool_name, goal_id,
        )
        return request

    def approve(self, request_id_prefix: str) -> Optional[ApprovalRequest]:
        """
        Approve a pending request by ID or prefix.

        Returns:
            The approved request, or None if not found/already processed/expired.
        """
        with self._lock:
            request = self._find_by_prefix(request_id_prefix)
            if not request:
                return None
            if request.status != "pending":
                return None
            # Check expiry
            if self._is_expired(request):
                request.status = "expired"
                self._append_log(request)
                return None

            request.status = "approved"
            request.operator_ts = time.time()
            self._append_log(request)

        logger.info("[ApprovalQueue] Approved: %s", request.request_id)
        return request

    def reject(self, request_id_prefix: str) -> Optional[ApprovalRequest]:
        """
        Reject a pending request by ID or prefix.

        Returns:
            The rejected request, or None if not found/already processed.
        """
        with self._lock:
            request = self._find_by_prefix(request_id_prefix)
            if not request:
                return None
            if request.status != "pending":
                return None

            request.status = "rejected"
            request.operator_ts = time.time()
            self._append_log(request)

        logger.info("[ApprovalQueue] Rejected: %s", request.request_id)
        return request

    def get_pending(self) -> List[ApprovalRequest]:
        """Get all pending (non-expired) requests."""
        with self._lock:
            self._expire_stale_locked()
            return [
                r for r in self._requests.values()
                if r.status == "pending"
            ]

    def get_approved_ready(self) -> Optional[ApprovalRequest]:
        """
        Get the oldest approved request ready for execution.

        Returns a single request (FIFO) and marks it as consumed
        by removing from the pending dict and moving to recent history.
        """
        with self._lock:
            approved = [
                r for r in self._requests.values()
                if r.status == "approved"
            ]
            if not approved:
                return None

            # FIFO: oldest first
            approved.sort(key=lambda r: r.created_at)
            request = approved[0]

            # Move to recent history
            del self._requests[request.request_id]
            self._recent.append(request)
            if len(self._recent) > MAX_RECENT:
                self._recent = self._recent[-MAX_RECENT:]

            return request

    def expire_stale(self) -> int:
        """Expire all stale pending requests. Returns count expired."""
        with self._lock:
            return self._expire_stale_locked()

    def get_by_id(self, request_id_prefix: str) -> Optional[ApprovalRequest]:
        """Find request by ID or prefix (in pending or recent)."""
        with self._lock:
            req = self._find_by_prefix(request_id_prefix)
            if req:
                return req
            # Also check recent history
            for r in reversed(self._recent):
                if r.request_id.startswith(request_id_prefix) or r.request_id == request_id_prefix:
                    return r
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        with self._lock:
            statuses = {}
            for r in self._requests.values():
                statuses[r.status] = statuses.get(r.status, 0) + 1
            return {
                "pending": statuses.get("pending", 0),
                "approved": statuses.get("approved", 0),
                "rejected": statuses.get("rejected", 0),
                "expired": statuses.get("expired", 0),
                "recent_total": len(self._recent),
                "expiry_sec": self._expiry_sec,
            }

    def reject_all_pending(self, reason: str = "authority_downgrade") -> int:
        """
        Reject all pending requests. Used on authority level downgrade.

        Returns count rejected.
        """
        with self._lock:
            count = 0
            for req in list(self._requests.values()):
                if req.status == "pending":
                    req.status = "rejected"
                    req.operator_ts = time.time()
                    self._append_log(req)
                    count += 1
            return count

    # -- Internal helpers --

    def _find_by_prefix(self, prefix: str) -> Optional[ApprovalRequest]:
        """Find request by ID prefix in pending dict."""
        # Exact match first
        if prefix in self._requests:
            return self._requests[prefix]
        # Prefix match
        matches = [
            r for rid, r in self._requests.items()
            if rid.startswith(prefix)
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def _is_expired(self, request: ApprovalRequest) -> bool:
        return (time.time() - request.created_at) > self._expiry_sec

    def _expire_stale_locked(self) -> int:
        """Expire stale pending requests (must hold lock)."""
        count = 0
        for req in list(self._requests.values()):
            if req.status == "pending" and self._is_expired(req):
                req.status = "expired"
                self._append_log(req)
                count += 1
        return count

    def _append_log(self, request: ApprovalRequest) -> None:
        """Append request state to JSONL log."""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(request.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to write approval log: %s", e)
