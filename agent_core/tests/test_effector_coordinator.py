"""Tests for EffectorCoordinator — preflight, prewarm, retry, self-diagnose."""

from unittest.mock import MagicMock, patch

import pytest

from agent_core.effector.coordinator import (
    EffectorCoordinator,
    EffectorTask,
    TaskStatus,
    AGENT_TOOLS,
    NODE_TOOLS,
)
from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.effector.openclaw_client import OpenClawClient
from agent_core.telegram.notifier import TelegramNotifier
from agent_core.tests.spec_helpers import specced


def _make_client(results):
    """Mock openclaw_client whose invoke_tool returns a queue of results."""
    client = specced(OpenClawClient)
    queue = list(results)

    def _invoke(tool_name, args):
        if queue:
            return queue.pop(0)
        return {"ok": False, "error": "no more results"}

    client.invoke_tool = MagicMock(side_effect=_invoke)
    return client


class _Env:
    """Bundle of patched helpers in coordinator; exposes mocks on the object."""

    def __init__(self, *, gateway=True, ollama=True, model_loaded=False):
        self._patches = [
            patch("agent_core.effector.coordinator.openclaw_gateway_alive",
                  return_value=gateway),
            patch("agent_core.effector.coordinator.ollama_alive",
                  return_value=ollama),
            patch("agent_core.effector.coordinator.model_loaded",
                  return_value=model_loaded),
            patch("agent_core.effector.coordinator.warm_ollama_model",
                  return_value=True),
        ]
        self.gateway = None
        self.ollama = None
        self.model_loaded = None
        self.warm = None

    def __enter__(self):
        self.gateway = self._patches[0].start()
        self.ollama = self._patches[1].start()
        self.model_loaded = self._patches[2].start()
        self.warm = self._patches[3].start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def _patch_env(**kwargs):
    return _Env(**kwargs)


class TestPreflight:
    def test_gateway_down_skips_retries(self):
        client = _make_client([])
        coord = EffectorCoordinator(openclaw_client=client)
        with _patch_env(gateway=False):
            task = EffectorTask(tool_name="web_search", tool_args={"q": "x"})
            outcome = coord.execute_task(task)

        assert outcome.status == TaskStatus.PREFLIGHT_FAILED
        assert len(outcome.attempts) == 1
        assert outcome.attempts[0].stage == "preflight"
        assert "gateway" in outcome.attempts[0].error
        client.invoke_tool.assert_not_called()

    def test_ollama_down_skips_retries(self):
        client = _make_client([])
        coord = EffectorCoordinator(openclaw_client=client)
        with _patch_env(gateway=True, ollama=False):
            outcome = coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={}),
            )

        assert outcome.status == TaskStatus.PREFLIGHT_FAILED
        client.invoke_tool.assert_not_called()


class TestPrewarm:
    def test_agent_tool_warms_model(self):
        client = _make_client([{"ok": True, "result": {"data": "..."}}])
        coord = EffectorCoordinator(openclaw_client=client)
        with _patch_env() as env:
            outcome = coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={}),
            )

        assert outcome.ok
        env.warm.assert_called()

    def test_node_tool_does_not_warm(self):
        client = _make_client([{"ok": True, "result": {"data": "..."}}])
        coord = EffectorCoordinator(openclaw_client=client)
        with _patch_env() as env:
            outcome = coord.execute_task(
                EffectorTask(tool_name="exec", tool_args={"command": "ls"}),
            )

        assert outcome.ok
        env.warm.assert_not_called()


class TestRetry:
    def test_first_attempt_success_no_retry(self):
        client = _make_client([{"ok": True, "result": {"data": "x"}}])
        coord = EffectorCoordinator(openclaw_client=client)
        with _patch_env():
            outcome = coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={}),
            )

        assert outcome.ok
        assert len(outcome.attempts) == 1
        assert client.invoke_tool.call_count == 1

    def test_second_attempt_succeeds(self):
        client = _make_client([
            {"ok": False, "error": "timeout"},
            {"ok": True, "result": {"data": "x"}},
        ])
        # Use zero-backoff so tests don't sleep
        coord = EffectorCoordinator(
            openclaw_client=client,
            backoff_seq=[0, 0, 0],
        )
        with _patch_env():
            outcome = coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={}),
            )

        assert outcome.ok
        assert len(outcome.attempts) == 2
        assert outcome.attempts[0].ok is False
        assert outcome.attempts[1].ok is True

    def test_top_level_aborted_status_counts_as_fail(self):
        """Openclaw-style aborted reply (top-level status) must trigger retry."""
        client = _make_client([
            {"ok": False, "status": "aborted", "result": "..."},
            {"ok": True, "result": {"data": "weather sunny"}},
        ])
        coord = EffectorCoordinator(
            openclaw_client=client, backoff_seq=[0, 0, 0],
        )
        with _patch_env():
            outcome = coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={}),
            )

        assert outcome.ok
        assert len(outcome.attempts) == 2
        assert outcome.attempts[0].error == "aborted_by_openclaw"

    def test_all_attempts_fail_reaches_diagnose(self):
        client = _make_client([
            {"ok": False, "error": "timeout"},
            {"ok": False, "error": "timeout"},
            {"ok": False, "status": "aborted", "result": "..."},
        ])
        bulletin = specced(BulletinStore)
        notifier = specced(TelegramNotifier)
        coord = EffectorCoordinator(
            openclaw_client=client,
            bulletin_store=bulletin,
            telegram_notifier=notifier,
            backoff_seq=[0, 0, 0],
        )
        with _patch_env():
            outcome = coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={"q": "x"}),
            )

        assert outcome.status == TaskStatus.FAILED
        assert len(outcome.attempts) == 3
        # Last attempt captured the aborted-status normalization
        assert outcome.attempts[-1].error == "aborted_by_openclaw"
        # Bulletin + Telegram notified
        bulletin.post.assert_called_once()
        assert notifier.notify_effector_incident.called \
            or notifier.notify_effector_result.called

    def test_exception_counts_as_failed_attempt(self):
        client = specced(OpenClawClient)
        client.invoke_tool.side_effect = RuntimeError("boom")
        coord = EffectorCoordinator(
            openclaw_client=client, backoff_seq=[0, 0, 0],
        )
        with _patch_env():
            outcome = coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={}),
            )

        assert outcome.status == TaskStatus.FAILED
        assert all("exception" in a.error for a in outcome.attempts)


class TestBulletinContent:
    def test_incident_entry_has_attempts_and_context(self):
        client = _make_client([
            {"ok": False, "error": "e1"},
            {"ok": False, "error": "e2"},
            {"ok": False, "error": "e3"},
        ])
        bulletin = specced(BulletinStore)
        coord = EffectorCoordinator(
            openclaw_client=client, bulletin_store=bulletin,
            backoff_seq=[0, 0, 0],
        )
        with _patch_env():
            coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={"q": "x"}),
            )

        bulletin.post.assert_called_once()
        entry = bulletin.post.call_args[0][0]
        assert entry.reason_code == "effector_persistent_fail"
        assert entry.metadata["attempts"] and len(entry.metadata["attempts"]) == 3
        assert "system_context" in entry.metadata
        assert entry.metadata["tool_args"] == {"q": "x"}

    def test_incident_entry_lands_in_real_store(self, tmp_path):
        """Audyt 2026-06-12: add_entry bylo fantomem certyfikowanym mockiem
        (metoda nigdy nie istniala na BulletinStore) -- ten test mowi do
        PRAWDZIWEGO store i pilnuje, ze incydent faktycznie laduje na desce."""
        from agent_core.bulletin.bulletin_store import BulletinStore
        from agent_core.bulletin.bulletin_model import EntryType

        client = _make_client([
            {"ok": False, "error": "e1"},
            {"ok": False, "error": "e2"},
            {"ok": False, "error": "e3"},
        ])
        store = BulletinStore(path=tmp_path / "bulletin.jsonl")
        coord = EffectorCoordinator(
            openclaw_client=client, bulletin_store=store,
            backoff_seq=[0, 0, 0],
        )
        with _patch_env():
            coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={"q": "x"}),
            )

        entries = store.get_by_type(EntryType.IMPROVEMENT)
        assert len(entries) == 1
        assert entries[0].reason_code == "effector_persistent_fail"
        assert entries[0].metadata["tool_args"] == {"q": "x"}


class TestLateBinding:
    """Coordinator can receive bulletin/notifier after construction.

    Regression: homeostasis_module constructs the coordinator before
    BulletinStore and TelegramBridge exist. Without setters, the first
    incident entry was lost and the operator saw only a generic fail.
    """

    def test_set_bulletin_store_after_init(self):
        client = _make_client([
            {"ok": False, "error": "timeout"},
            {"ok": False, "error": "timeout"},
            {"ok": False, "status": "aborted", "result": "..."},
        ])
        coord = EffectorCoordinator(
            openclaw_client=client, backoff_seq=[0, 0, 0],
        )
        # Wire bulletin *after* construction
        bulletin = specced(BulletinStore)
        coord.set_bulletin_store(bulletin)

        with _patch_env():
            coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={}),
            )

        bulletin.post.assert_called_once()

    def test_set_telegram_notifier_after_init(self):
        client = _make_client([
            {"ok": False, "error": "x"},
            {"ok": False, "error": "x"},
            {"ok": False, "error": "x"},
        ])
        coord = EffectorCoordinator(
            openclaw_client=client, backoff_seq=[0, 0, 0],
        )
        notifier = specced(TelegramNotifier)
        coord.set_telegram_notifier(notifier)

        with _patch_env():
            coord.execute_task(
                EffectorTask(tool_name="web_search", tool_args={}),
            )

        assert notifier.notify_effector_incident.called \
            or notifier.notify_effector_result.called


class TestTaskHelpers:
    def test_agent_tool_flag(self):
        t1 = EffectorTask(tool_name="web_search", tool_args={})
        t2 = EffectorTask(tool_name="exec", tool_args={})
        assert t1.is_agent_tool is True
        assert t2.is_agent_tool is False

    def test_tool_sets_are_disjoint(self):
        assert not (AGENT_TOOLS & NODE_TOOLS)
