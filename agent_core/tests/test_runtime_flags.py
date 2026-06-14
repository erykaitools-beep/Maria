"""Tests for agent_core.runtime_flags."""

import threading

from agent_core import runtime_flags


class TestRestartFlag:

    def setup_method(self):
        runtime_flags.clear_restart_request()

    def teardown_method(self):
        runtime_flags.clear_restart_request()

    def test_default_false(self):
        assert runtime_flags.restart_requested() is False

    def test_request_sets_flag(self):
        runtime_flags.request_restart()
        assert runtime_flags.restart_requested() is True

    def test_clear_resets_flag(self):
        runtime_flags.request_restart()
        runtime_flags.clear_restart_request()
        assert runtime_flags.restart_requested() is False

    def test_idempotent_request(self):
        runtime_flags.request_restart()
        runtime_flags.request_restart()
        assert runtime_flags.restart_requested() is True

    def test_thread_safety_smoke(self):
        # Hammer the flag from many threads — must not deadlock or raise.
        def worker():
            for _ in range(50):
                runtime_flags.request_restart()
                runtime_flags.restart_requested()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive()
        assert runtime_flags.restart_requested() is True
