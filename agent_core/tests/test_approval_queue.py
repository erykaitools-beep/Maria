"""
Tests for Phase 5: Approval Queue + Telegram HITL.

Tests:
- ApprovalRequest creation and serialization
- ApprovalQueue submit/approve/reject/expire flows
- Prefix matching for operator convenience
- Queue full rejection
- FIFO ordering for approved requests
- Thread safety
- JSONL persistence
- PlanStatus.AWAITING_APPROVAL
- Planner effector escalation handling
- Telegram notification methods
"""

import json
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.tests.spec_helpers import specced
from agent_core.telegram.bot import TelegramBot

from agent_core.autonomy.approval_queue import (
    ApprovalRequest,
    ApprovalQueue,
    EXPIRY_SEC,
    MAX_PENDING,
)
from agent_core.planner.planner_model import PlanStatus


# ---- ApprovalRequest ----

class TestApprovalRequest:

    def test_creation(self):
        req = ApprovalRequest(
            request_id="ereq-abc123",
            plan_id="plan-1",
            tool_name="exec",
            tool_args={"command": "ls -la"},
            goal_id="goal-1",
            goal_description="Test goal",
            authority_level="confirm",
            created_at=1000.0,
        )
        assert req.status == "pending"
        assert req.request_id == "ereq-abc123"
        assert req.tool_name == "exec"

    def test_serialization_roundtrip(self):
        req = ApprovalRequest(
            request_id="ereq-abc123",
            plan_id="plan-1",
            tool_name="web_fetch",
            tool_args={"url": "https://example.com"},
            goal_id=None,
            goal_description="Fetch data",
            authority_level="bounded",
            created_at=12345.0,
            episode_id="ep-xyz",
        )
        data = req.to_dict()
        restored = ApprovalRequest.from_dict(data)
        assert restored.request_id == req.request_id
        assert restored.tool_args == req.tool_args
        assert restored.episode_id == "ep-xyz"

    def test_from_dict_defaults(self):
        req = ApprovalRequest.from_dict({})
        assert req.request_id == ""
        assert req.status == "pending"


# ---- ApprovalQueue basic operations ----

class TestApprovalQueue:

    def test_submit(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(
            plan_id="plan-1",
            tool_name="exec",
            tool_args={"command": "df -h"},
            goal_description="Check disk",
        )
        assert req.status == "pending"
        assert req.request_id.startswith("ereq-")
        assert req.tool_name == "exec"

    def test_approve(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        approved = q.approve(req.request_id)
        assert approved is not None
        assert approved.status == "approved"
        assert approved.operator_ts is not None

    def test_reject(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        rejected = q.reject(req.request_id)
        assert rejected is not None
        assert rejected.status == "rejected"

    def test_approve_not_found(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        result = q.approve("nonexistent")
        assert result is None

    def test_reject_not_found(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        result = q.reject("nonexistent")
        assert result is None

    def test_approve_already_approved(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        q.approve(req.request_id)
        # Second approve returns None
        result = q.approve(req.request_id)
        assert result is None

    def test_approve_already_rejected(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        q.reject(req.request_id)
        result = q.approve(req.request_id)
        assert result is None

    def test_prefix_matching(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        # Use first 8 chars as prefix
        prefix = req.request_id[:8]
        approved = q.approve(prefix)
        assert approved is not None
        assert approved.request_id == req.request_id

    def test_ambiguous_prefix_returns_none(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        # Submit two requests - both start with "ereq-"
        q.submit(plan_id="p1", tool_name="exec", tool_args={})
        q.submit(plan_id="p2", tool_name="read", tool_args={})
        # "ereq-" is ambiguous prefix
        result = q.approve("ereq-")
        assert result is None


# ---- Expiry ----

class TestApprovalQueueExpiry:

    def test_expire_stale(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl", expiry_sec=0.01)
        q.submit(plan_id="p1", tool_name="exec", tool_args={})
        time.sleep(0.02)
        count = q.expire_stale()
        assert count == 1

    def test_approve_expired_returns_none(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl", expiry_sec=0.01)
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        time.sleep(0.02)
        result = q.approve(req.request_id)
        assert result is None

    def test_get_pending_excludes_expired(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl", expiry_sec=0.01)
        q.submit(plan_id="p1", tool_name="exec", tool_args={})
        time.sleep(0.02)
        pending = q.get_pending()
        assert len(pending) == 0

    def test_non_expired_still_pending(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl", expiry_sec=300)
        q.submit(plan_id="p1", tool_name="exec", tool_args={})
        pending = q.get_pending()
        assert len(pending) == 1


# ---- Approved ready (pickup) ----

class TestApprovalQueuePickup:

    def test_get_approved_ready(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={"command": "ls"})
        q.approve(req.request_id)
        ready = q.get_approved_ready()
        assert ready is not None
        assert ready.request_id == req.request_id
        assert ready.tool_args == {"command": "ls"}

    def test_get_approved_ready_fifo(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req1 = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        req2 = q.submit(plan_id="p2", tool_name="read", tool_args={})
        q.approve(req1.request_id)
        q.approve(req2.request_id)
        # First pickup should be req1
        ready = q.get_approved_ready()
        assert ready.request_id == req1.request_id
        # Second should be req2
        ready = q.get_approved_ready()
        assert ready.request_id == req2.request_id

    def test_get_approved_ready_none_when_empty(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        ready = q.get_approved_ready()
        assert ready is None

    def test_consumed_not_available_again(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        q.approve(req.request_id)
        q.get_approved_ready()  # consume
        ready = q.get_approved_ready()
        assert ready is None


# ---- Queue limits ----

class TestApprovalQueueLimits:

    def test_max_pending(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        for i in range(MAX_PENDING):
            req = q.submit(plan_id=f"p{i}", tool_name="exec", tool_args={})
            assert req.status == "pending"

        # MAX_PENDING+1 should be rejected
        req = q.submit(plan_id="overflow", tool_name="exec", tool_args={})
        assert req.status == "rejected"

    def test_reject_all_pending(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        q.submit(plan_id="p1", tool_name="exec", tool_args={})
        q.submit(plan_id="p2", tool_name="read", tool_args={})
        count = q.reject_all_pending("test_downgrade")
        assert count == 2
        assert len(q.get_pending()) == 0


# ---- Persistence ----

class TestApprovalQueuePersistence:

    def test_jsonl_written_on_submit(self, tmp_path):
        path = tmp_path / "q.jsonl"
        q = ApprovalQueue(log_path=path)
        q.submit(plan_id="p1", tool_name="exec", tool_args={"command": "ls"})
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["tool_name"] == "exec"
        assert data["status"] == "pending"

    def test_jsonl_written_on_approve(self, tmp_path):
        path = tmp_path / "q.jsonl"
        q = ApprovalQueue(log_path=path)
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        q.approve(req.request_id)
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2  # submit + approve
        data = json.loads(lines[1])
        assert data["status"] == "approved"


# ---- Thread safety ----

class TestApprovalQueueThreadSafety:

    def test_concurrent_submit(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        results = []

        def submit(idx):
            req = q.submit(plan_id=f"p{idx}", tool_name="exec", tool_args={})
            results.append(req)

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        # All should have unique IDs
        ids = {r.request_id for r in results}
        assert len(ids) == 5


# ---- Stats ----

class TestApprovalQueueStats:

    def test_stats(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        q.submit(plan_id="p1", tool_name="exec", tool_args={})
        req2 = q.submit(plan_id="p2", tool_name="read", tool_args={})
        q.approve(req2.request_id)
        stats = q.get_stats()
        assert stats["pending"] == 1
        assert stats["approved"] == 1
        assert stats["expiry_sec"] == EXPIRY_SEC


# ---- get_by_id ----

class TestApprovalQueueGetById:

    def test_get_pending(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        found = q.get_by_id(req.request_id)
        assert found is not None
        assert found.request_id == req.request_id

    def test_get_from_recent(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = q.submit(plan_id="p1", tool_name="exec", tool_args={})
        q.approve(req.request_id)
        q.get_approved_ready()  # moves to recent
        found = q.get_by_id(req.request_id)
        assert found is not None

    def test_not_found(self, tmp_path):
        q = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        assert q.get_by_id("nonexistent") is None


# ---- PlanStatus ----

class TestPlanStatusAwaiting:

    def test_awaiting_approval_exists(self):
        assert PlanStatus.AWAITING_APPROVAL.value == "awaiting_approval"

    def test_all_statuses(self):
        values = {s.value for s in PlanStatus}
        assert "awaiting_approval" in values
        assert "pending" in values
        assert "completed" in values


# ---- TelegramNotifier effector methods ----

class TestTelegramNotifierEffector:

    def test_notify_effector_request(self):
        from agent_core.telegram.notifier import TelegramNotifier
        bot = specced(TelegramBot, configured=True)
        bot.send_message.return_value = True
        notifier = TelegramNotifier(bot=bot)

        ok = notifier.notify_effector_request(
            tool_name="exec",
            tool_args={"command": "df -h"},
            goal_description="Check disk space",
            authority_level="confirm",
            request_id="ereq-abc123def456",
        )
        assert ok
        call_text = bot.send_message.call_args[0][0]
        assert "exec" in call_text
        assert "df -h" in call_text
        assert "/efapprove" in call_text
        assert "/efreject" in call_text

    def test_notify_effector_request_no_request_id(self):
        from agent_core.telegram.notifier import TelegramNotifier
        bot = specced(TelegramBot)
        bot.send_message.return_value = True
        notifier = TelegramNotifier(bot=bot)

        ok = notifier.notify_effector_request(
            tool_name="web_fetch",
            tool_args={"url": "https://example.com"},
        )
        assert ok
        call_text = bot.send_message.call_args[0][0]
        assert "web_fetch" in call_text
        assert "/efapprove" not in call_text

    def test_notify_effector_result_success(self):
        from agent_core.telegram.notifier import TelegramNotifier
        bot = specced(TelegramBot)
        bot.send_message.return_value = True
        notifier = TelegramNotifier(bot=bot)

        ok = notifier.notify_effector_result(
            tool_name="exec",
            success=True,
            summary="file list output",
        )
        assert ok
        call_text = bot.send_message.call_args[0][0]
        assert "OK" in call_text
        assert "exec" in call_text

    def test_notify_effector_result_failure(self):
        from agent_core.telegram.notifier import TelegramNotifier
        bot = specced(TelegramBot)
        bot.send_message.return_value = True
        notifier = TelegramNotifier(bot=bot)

        ok = notifier.notify_effector_result(
            tool_name="exec",
            success=False,
            summary="permission denied",
        )
        assert ok
        call_text = bot.send_message.call_args[0][0]
        assert "BLAD" in call_text
