"""Offline transport contract; no live Kritaqo/auth/model requests."""
import copy
import dataclasses
import gc
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location("tools_subject", Path(__file__).resolve().parents[1] / "llm/kritaqo_tools.py")
k = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(k)


class FakeServer:
    def __init__(self):
        self.calls = []
        self.logout_ok = True
        self.send_timeout = self.pair_timeout = False
        self.before_send = self.before_view = None
        self.hub = {"protocol": "kritaqo-project-hub-v1", "peers": [{"id": "peer1", "nodeId": "host1", "work": True}]}
        self.view = {"protocol": "kritaqo-project-hub-v1", "nodeId": "host1", "project": {"id": "project1"},
                     "jobs": [], "messages": [], "execution": {"allowed": True, "workspaceRevision": 4}, "busy": False,
                     "preferences": {"master": {"providerId": "openai-codex", "model": "test-model"}},
                     "providers": [{"id": "openai-codex", "authenticated": True, "models": [{"id": "test-model"}],
                                    "capabilities": {"existingWorkspace": True, "execution": True}}]}

    def client(self, record):
        server = self

        class Client:
            cookie = None

            def request(self, method, route, payload=None, capture_cookie=False):
                server.calls.append((method, route, copy.deepcopy(payload)))
                if route == "/api/control":
                    return {"application": "kritaqo", "pid": 44, "version": "0.8.18-alpha.2", "ticket": "a" * 64}
                if route == "/api/desktop-pair":
                    if server.pair_timeout:
                        raise k.ToolError("remote_unavailable")
                    self.cookie = "FAKE_NEVER_RETURN"
                    return {"paired": True}
                if route == "/api/logout":
                    return {"loggedOut": server.logout_ok}
                if route == "/api/hub":
                    return copy.deepcopy(server.hub)
                if route == "/api/hub/remote":
                    action = payload["action"]
                    if action == "view":
                        if server.before_view:
                            server.before_view()
                        return copy.deepcopy(server.view)
                    if action == "send":
                        if server.before_send:
                            server.before_send(payload)
                        if server.send_timeout:
                            raise k.ToolError("remote_unavailable")
                        job_id = "job%d" % (len(server.view["jobs"]) + 1)
                        server.view["jobs"].append({"id": job_id, "requestId": payload["payload"]["requestId"], "status": "running", "steps": []})
                        return {"protocol": "kritaqo-project-hub-v1", "nodeId": "host1", "jobId": job_id}
                    if action == "cancel":
                        return {"protocol": "kritaqo-project-hub-v1", "nodeId": "host1", "jobId": payload["payload"]["jobId"]}
                raise AssertionError((method, route))
        return Client()

    def mutations(self, action="send"):
        return [c[2] for c in self.calls if c[1] == "/api/hub/remote" and c[2]["action"] == action]


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = dict(data_dir=str(root), bridge_path=str(root / "bridge.py"), state_dir=str(root / "state"),
                           peer_id="peer1", host_node_id="host1", project_id="project1", workspace_revision=4,
                           project_name="Roblox", computer_name="MSI")
        self.server = FakeServer()
        self.provider = self.new_provider()

    def new_provider(self):
        return k.KritaqoToolsProvider(self.config, client_factory=self.server.client,
                                      record_reader=lambda _: {"pid": 44, "version": "0.8.18-alpha.2", "port": 8766, "token": "b" * 64})

    def session(self, text="Zleć w Roblox: sprawdź strukturę bez zmian", n=1, provider=None):
        return (provider or self.provider).for_turn(text, "%032x" % n)

    def call(self, action, session=None):
        return (session or self.session()).call("kritaqo_roblox_" + action, {})

    def state(self):
        return json.loads((Path(self.config["state_dir"]) / "receipts.json").read_text())

    def test_tools_scope_and_no_model_payload(self):
        for text in ("Jaka pogoda?", "Jakie projekty Kritaqo?"):
            self.assertIsNone(self.provider.for_turn(text, "a" * 32))
        for text in ("Czy masz dostęp do Roblox?", "Roblox", "Sprawdź czy masz dostęp do Roblox", "Zleć w Roblox:"):
            self.assertNotIn("kritaqo_roblox_submit", [x["name"] for x in self.session(text).specs])
        s = self.session("Maria, sprawdź strukturę Roblox")
        self.assertIn("kritaqo_roblox_submit", [x["name"] for x in s.specs])
        self.assertTrue(all(x["type"] == "function" and x["inputSchema"]["additionalProperties"] is False for x in s.specs))
        self.assertFalse(s.call("kritaqo_roblox_submit", {"text": "changed"})["success"])
        self.assertEqual(self.server.calls, [])

    def test_status_pinned_without_mutation_or_history_leak(self):
        self.server.view["messages"] = [{"jobId": "unrelated", "text": "SECRET_OTHER_CONVERSATION", "role": "assistant"}]
        result = self.call("status")
        self.assertTrue(result["success"] and result["ready"] and result["pinnedRevisionMatches"])
        self.assertEqual(result["executionMode"], "workspace-write")
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertFalse(self.server.mutations())
        self.assertEqual(self.server.calls[-1][1], "/api/logout")
        self.assertTrue(all(c[2]["device"] == "peer1" and c[2]["payload"]["projectId"] == "project1" for c in self.server.calls if c[1] == "/api/hub/remote"))

    def test_shared_checks_result_without_receipt_and_fresh_status(self):
        from agent_core.tests.test_kritaqo_shared_state import recorded_state
        raw = recorded_state()
        self.server.view["project"]["sharedState"] = raw
        result = self.call("result")
        self.assertEqual(result["state"], "not_recorded")
        self.assertEqual(result["sharedState"]["hostNodeId"], "host1")
        self.assertEqual(result["sharedState"]["projectId"], "project1")
        self.assertEqual(result["sharedState"]["checks"][0]["currency"], "current")
        raw["revision"] = 4
        raw["checks"][0].update(currency="unknown", currencyReason="workspace_unavailable")
        status = self.call("status")
        self.assertEqual(status["sharedState"]["revision"], 4)
        self.assertEqual(status["sharedState"]["checks"][0]["currency"], "unknown")
        del self.server.view["project"]["sharedState"]
        self.assertEqual(self.call("result")["sharedState"]["state"], "unavailable")
        self.assertFalse(self.server.mutations())

    def test_completed_receipt_result_carries_fresh_shared_check_not_old_report_gap(self):
        from agent_core.tests.test_kritaqo_shared_state import recorded_state
        submitted = self.call("submit")
        self.assertTrue(submitted["success"])
        job = self.server.view["jobs"][0]
        job.update(status="completed", steps=[{"role": "master", "status": "completed", "result": {"text": "Older report: independent CSV check remains."}}])
        self.server.view["project"]["sharedState"] = recorded_state()
        output = self.call("result")
        self.assertEqual(output["jobId"], job["id"])
        self.assertEqual(output["state"], "completed")
        self.assertIn("Older report", output["untrustedResult"])
        self.assertEqual(output["sharedState"]["checks"][0]["nextSteps"][0]["status"], "done")
        self.assertIn("Prefer current recorded passed checks", self.session().instructions)

    def test_receipt_before_send_retry_restart_immutable(self):
        def inspect(payload):
            r = next(iter(self.state()["receipts"].values()))
            self.assertEqual(r["payload"], payload["payload"])
            self.assertEqual(r["state"], "unknown")
            self.assertEqual(os.stat(Path(self.config["state_dir"]) / "receipts.json").st_mode & 0o777, 0o600)
        self.server.before_send = inspect
        result = self.call("submit")
        self.assertEqual(result["state"], "accepted")
        p = self.server.mutations()[0]["payload"]
        self.assertEqual(p["text"], self.session().text)
        self.assertEqual((p["workspaceRevision"], p["execution"], p["mode"]), (4, True, "chat"))
        self.assertEqual(self.call("submit")["state"], "running")
        self.assertTrue(self.call("submit", self.session(provider=self.new_provider()))["reused"])
        self.assertEqual(self.call("submit", self.session("Zleć w Roblox: inne rzeczy"))["reason"], "interaction_conflict")
        self.assertEqual(len(self.server.mutations()), 1)

    def test_unknown_missing_job_blocks_new_no_retry(self):
        self.server.send_timeout = True
        self.assertFalse(self.call("submit")["success"])
        self.assertTrue(self.call("submit")["reused"])
        self.assertEqual(self.call("submit", self.session(n=2))["reason"], "previous_outcome_unknown_or_pending")
        self.assertEqual(len(self.server.mutations()), 1)
        self.assertEqual(self.call("result")["state"], "unknown")
        self.assertEqual(self.call("submit", self.session(n=3, provider=self.new_provider()))["reason"], "previous_outcome_unknown_or_pending")

    def test_unknown_reconciled_request_and_result_exact_job(self):
        self.server.send_timeout = True
        self.call("submit")
        request = self.server.mutations()[0]["payload"]["requestId"]
        self.server.view["jobs"] = [{"id": "job1", "requestId": request, "status": "completed", "steps": []}]
        self.server.view["messages"] = [{"role": "assistant", "jobId": "other", "text": "NO_LEAK"},
                                        {"role": "assistant", "jobId": "job1", "text": "Właściwy wynik"}]
        result = self.call("result", self.session("Wynik Roblox", n=3))
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["untrustedResult"], "Właściwy wynik")
        self.server.send_timeout = False
        self.assertEqual(self.call("submit", self.session(n=2))["state"], "accepted")
        self.assertEqual(len(self.server.mutations()), 2)

    def test_target_revision_provider_drift_no_send(self):
        cases = [lambda: self.server.hub["peers"][0].update(nodeId="other"),
                 lambda: self.server.view.update(nodeId="other"),
                 lambda: self.server.view["project"].update(id="other"),
                 lambda: self.server.view["execution"].update(workspaceRevision=5),
                 lambda: self.server.view["execution"].update(allowed=False),
                 lambda: self.server.view["providers"][0]["capabilities"].update(existingWorkspace=False),
                 lambda: self.server.view["providers"][0]["capabilities"].update(execution=False),
                 lambda: self.server.view["providers"][0].update(authenticated=False),
                 lambda: self.server.view["providers"][0].update(models=[]),
                 lambda: self.server.view.update(storageError="storage unavailable"),
                 lambda: self.server.hub["peers"][0].update(work=False)]
        for change in cases:
            with self.subTest(change=change):
                self.server = FakeServer()
                self.provider = self.new_provider()
                change()
                self.assertFalse(self.call("submit")["success"])
                self.assertFalse(self.server.mutations())
                self.assertEqual(self.server.calls[-1][1], "/api/logout")

    def test_cancel_recorded_job_no_cleanup_claim(self):
        self.call("submit")
        self.assertEqual(self.call("cancel")["reason"], "invalid_arguments")
        result = self.call("cancel", self.session("Anuluj zadanie Roblox", n=2))
        self.assertEqual(result["state"], "cancel_requested")
        self.assertEqual(result["processCleanup"], "unknown")
        self.assertEqual(self.server.mutations("cancel")[0]["payload"], {"projectId": "project1", "jobId": "job1"})
        self.server.view["jobs"][0]["status"] = "cancelled"
        self.assertEqual(self.call("submit", self.session(n=3))["reason"], "previous_outcome_unknown_or_pending")

    def test_close_before_or_during_preflight_no_send(self):
        s = self.session()
        s.close()
        self.assertEqual(self.call("submit", s)["reason"], "cancelled")
        self.assertEqual(self.server.calls, [])
        s = self.session()
        self.server.before_view = s.close
        self.assertEqual(self.call("submit", s)["reason"], "cancelled")
        self.assertFalse(self.server.mutations())
        self.assertEqual(self.server.calls[-1][1], "/api/logout")

    def test_logout_latch_survives_provider_restart(self):
        self.server.logout_ok = False
        self.assertEqual(self.call("status")["reason"], "cleanup_uncertain")
        count = len(self.server.calls)
        self.assertEqual(self.call("status", self.session(provider=self.new_provider()))["reason"], "cleanup_uncertain")
        self.assertEqual(len(self.server.calls), count)

    def test_unknown_pair_latch_survives_restart(self):
        self.server.pair_timeout = True
        self.assertFalse(self.call("status")["success"])
        count = len(self.server.calls)
        self.assertEqual(self.call("status", self.session(provider=self.new_provider()))["reason"], "cleanup_uncertain")
        self.assertEqual(len(self.server.calls), count)

    def test_malformed_and_mismatched_job_no_result(self):
        self.call("submit")
        self.server.view["jobs"][0]["requestId"] = "otherrequest"
        self.assertFalse(self.call("result")["success"])
        self.server.view["jobs"] = [{}] * 101
        self.assertFalse(self.call("status")["success"])

    def test_config_validation_and_absent_factory(self):
        with self.assertRaises(k.ToolError):
            k.KritaqoToolsProvider(dict(self.config, peer_id="../peer"))
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(k.create_kritaqo_tools_provider())
        with patch.dict(os.environ, {"MARIA_KRITAQO_TOOLS_CONFIG": "/not-present"}):
            with self.assertRaisesRegex(ValueError, "kritaqo_tools_config_invalid"):
                k.create_kritaqo_tools_provider()

    def test_corrupt_receipt_and_world_readable_state_fail_closed(self):
        self.call("submit")
        path = Path(self.config["state_dir"]) / "receipts.json"
        state = self.state()
        next(iter(state["receipts"].values()))["payload"]["projectId"] = "other"
        path.write_text(json.dumps(state))
        before = len(self.server.calls)
        self.assertEqual(self.call("status")["reason"], "state_invalid")
        self.assertEqual(len(self.server.calls), before)
        path.chmod(0o644)
        self.assertEqual(self.call("status")["reason"], "state_invalid")

    def test_cross_provider_lock_no_auth_while_busy(self):
        other = self.new_provider()
        with self.provider._state():
            result = self.call("submit", self.session(provider=other))
            self.assertEqual(result["reason"], "busy")
        self.assertFalse(self.server.calls)

    def test_http_client_bounds_cookie_capture_and_fixed_transport(self):
        calls = []
        responses = []

        class Response:
            status = 200

            def __init__(self, raw, cookie=False):
                self.raw = io.BytesIO(raw)
                self.cookie = cookie

            def getheaders(self):
                return [("Set-Cookie", "kritaqo_session=" + "a" * 64 + "; HttpOnly")] if self.cookie else []

            def getheader(self, name, default):
                return "application/json"

            def read1(self, size):
                return self.raw.read(size)

        class Connection:
            sock = None

            def __init__(self, host, port, timeout):
                calls.append((host, port, timeout))

            def request(self, method, route, body, headers):
                calls.append((method, route, headers))

            def getresponse(self):
                return responses.pop(0)

            def close(self):
                calls.append("closed")

        client = k._Client({"port": 8766, "token": "b" * 64})
        with patch.object(k.http.client, "HTTPConnection", Connection):
            responses.append(Response(b'{"application":"kritaqo"}'))
            self.assertEqual(client.request("POST", "/api/control", {"action": "status"})["application"], "kritaqo")
            self.assertEqual(calls[0], ("127.0.0.1", 8766, 10))
            self.assertEqual(calls[1][2]["Origin"], "http://127.0.0.1:8766")
            self.assertIn("X-Kritaqo-Control", calls[1][2])
            responses.append(Response(b'not json', cookie=True))
            with self.assertRaises(k.ToolError):
                client.request("POST", "/api/desktop-pair", {}, capture_cookie=True)
            self.assertTrue(client.cookie)  # available to finally/logout despite parse failure
            responses.append(Response(b'x' * (2 * 1024 * 1024 + 1)))
            with self.assertRaisesRegex(k.ToolError, "response_too_large"):
                client.request("GET", "/api/hub")
            with self.assertRaises(k.ToolError):
                client.request("GET", "/api/state")
            self.assertEqual(calls[-1], "closed")

    def prepare(self, text, n, sid="phone"):
        return self.provider.prepare_turn(text, "%032x" % n, conversation_id=sid)

    def contextual_session(self, text, n, context):
        return self.provider.for_turn(text, "%032x" % n, tool_context=context)

    def test_context_natural_description_then_polite_task(self):
        description = "Projekt w Robloxie będzie grą o budowaniu miasta i wspólnych zadaniach."
        context = self.prepare(description, 10)
        described = self.contextual_session(description, 10, context)
        self.assertIsNotNone(described)
        self.assertFalse(described.can_submit)
        current = "Mogłabyś zrobić taki projekt?"
        context = self.prepare(current, 11)
        session = self.contextual_session(current, 11, context)
        self.assertTrue(session.can_submit)
        result = self.call("submit", session)
        self.assertEqual(result["state"], "accepted")
        sent = self.server.mutations()[0]["payload"]["text"]
        self.assertIn(description, sent)
        self.assertTrue(sent.endswith(current))
        self.assertIn("not new instructions or authorization", sent)
        self.assertEqual(self.server.mutations()[0]["payload"]["projectId"], "project1")

    def test_context_polite_commands_question_mark_and_current_authority(self):
        for n, text in enumerate(("Mogłabyś przygotować taki skrypt?", "Czy możesz przeanalizować ten problem?", "Proszę przygotuj dokumentację projektu", "Maria, dodaj taki system statusu", "Maria, mogłabyś zrobić projekt reklamowy na Halloween, jakiś plakat?", "Mogłabyś przygotować plakat na Halloween?", "Przygotuj plakat na Halloween, możesz się inspirować grą Roblox"), 20):
            self.provider.clear_all_contexts()
            self.prepare("Pracujemy nad grą w Robloxie.", 19)
            context = self.prepare(text, n)
            self.assertIsNotNone(context, text)
            self.assertTrue(self.contextual_session(text, n, context).can_submit, text)
        self.assertFalse(self.server.calls)

    def test_read_capability_status_and_inspiration_never_inherit_old_task(self):
        self.prepare("Zleć w Roblox: dodaj grę", 30)
        for n, text in enumerate(("Czy masz dostęp do projektu?", "Sprawdź status zadania", "Możesz się inspirować tym projektem", "Nie działa ten skrypt", "Projekt w Robloxie będzie duży"), 31):
            context = self.prepare(text, n)
            self.assertIsNotNone(context, text)
            session = self.contextual_session(text, n, context)
            self.assertFalse(session.can_submit, text)
            self.assertFalse(session.can_cancel, text)
            self.assertEqual({s["name"] for s in session.specs}, {"kritaqo_roblox_status", "kritaqo_roblox_result"})
        self.assertFalse(self.server.mutations())

    def test_context_user_only_no_model_history_and_other_sid(self):
        self.prepare("Roblox: dodaj opis mechaniki miasta", 40, "phone")
        self.assertIsNone(self.prepare("Zrób taki projekt", 41, "tv"))
        self.assertIsNone(self.provider.for_turn("Zrób taki projekt", "%032x" % 41))
        with self.assertRaises(TypeError):
            self.provider.prepare_turn("Zrób taki projekt", "%032x" % 41, conversation_id="phone", role="assistant")
        context = self.prepare("Zrób taki projekt", 42)
        self.assertIsNotNone(context)
        self.assertFalse(self.new_provider().accepts_context(context.text, context.interaction_id, context))
        forged = dataclasses.replace(context, text="Zrób inny projekt")
        self.assertFalse(self.provider.accepts_context(forged.text, forged.interaction_id, forged))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            context.text = "changed"

    def test_context_clears_unrelated_and_explicit_other_targets(self):
        for n, text in enumerate(("Jaka jutro pogoda?", "Sprawdź co to za pogoda", "Zrób to na obiad", "Zmieńmy temat", "Zrób to w projekcie Minecraft", "Przygotuj projekt Asystent", "Sprawdź projekt InnyFolder", 'Sprawdź projekt "sekretny"', "Sprawdź projekt o nazwie sekret", "Zrób taki projekt na MiniPC", "Zrób to na innym laptopie"), 50):
            self.provider.clear_all_contexts()
            context = self.prepare("Roblox: gra o mieście", 49)
            self.assertIsNone(self.prepare(text, n), text)
            self.assertFalse(self.provider.accepts_context(context.text, context.interaction_id, context))
            self.assertIsNone(self.prepare("Przygotuj taki skrypt", 80))
        self.assertFalse(self.server.calls)
        self.assertFalse(self.provider.accepts_prompt("Zrób w Roblox coś w projekcie Minecraft"))

    def test_asr_alias_only_after_explicit_scope(self):
        self.assertIsNone(self.prepare("Sprawdź roboksz", 90))
        self.prepare("Roblox: gra", 91)
        context = self.prepare("Sprawdź roboksz i jego skrypt", 92)
        self.assertIsNotNone(context)
        self.assertTrue(self.contextual_session(context.text, 92, context).can_submit)
        self.assertFalse(self.provider.accepts_prompt("Sprawdź roboksz"))

    def test_context_ttl_clear_and_revocation_before_send(self):
        with patch.object(k.time, "monotonic", return_value=100):
            context = self.prepare("Sprawdź Roblox", 100)
        with patch.object(k.time, "monotonic", return_value=699):
            self.assertTrue(self.provider.accepts_context(context.text, context.interaction_id, context))
        with patch.object(k.time, "monotonic", return_value=700):
            self.assertFalse(self.provider.accepts_context(context.text, context.interaction_id, context))
        context = self.prepare("Sprawdź Roblox", 101)
        session = self.contextual_session(context.text, 101, context)
        self.server.before_view = lambda: self.provider.clear_context("phone")
        self.assertEqual(self.call("submit", session)["reason"], "context_expired")
        self.assertFalse(self.server.mutations())
        self.assertIsNone(self.contextual_session(context.text, 101, context))
        context = self.prepare("Roblox", 102)
        self.provider.clear_all_contexts()
        self.assertFalse(self.provider.accepts_context(context.text, context.interaction_id, context))

    def test_context_bounds_sessions_messages_and_payload(self):
        for n in range(129):
            self.prepare("Roblox: gra", 200 + n, "sid%d" % n)
        self.assertEqual(len(self.provider._contexts), 128)
        self.assertNotIn("sid0", self.provider._contexts)
        for n in range(20):
            self.prepare("Roblox: skrypt " + str(n) + " x" * 500, 400 + n)
        users = self.provider._contexts["phone"]["users"]
        self.assertLessEqual(len(users), 6)
        self.assertLessEqual(sum(map(len, users)), 6000)
        current = "Przygotuj taki skrypt " + "x" * 11000
        context = self.prepare(current, 500)
        session = self.contextual_session(current, 500, context)
        self.assertLessEqual(len(session.payload_text), 12000)
        self.assertTrue(session.payload_text.endswith(current))

    def test_context_retry_payload_immutable_and_conflict_not_resent(self):
        self.prepare("Roblox: gra o mieście", 600)
        text = "Mogłabyś przygotować taki projekt?"
        context = self.prepare(text, 601)
        session = self.contextual_session(text, 601, context)
        self.assertEqual(self.call("submit", session)["state"], "accepted")
        original_payload = self.server.mutations()[0]["payload"]["text"]
        self.prepare("Co z tym projektem?", 602)
        self.assertIs(self.prepare(text, 601), context)
        retry = self.contextual_session(text, 601, context)
        self.assertEqual(retry.payload_text, original_payload)
        self.assertTrue(self.call("submit", retry)["reused"])
        self.assertFalse(self.provider.accepts_context(text + " inaczej", context.interaction_id, context))
        self.assertIsNone(self.prepare(text + " inaczej", 601))
        self.provider.clear_context("phone")
        self.prepare("Roblox: zupełnie inny kontekst", 603)
        altered = self.prepare(text, 601)
        result = self.call("submit", self.contextual_session(text, 601, altered))
        self.assertEqual(result["reason"], "interaction_conflict")
        self.assertEqual(len(self.server.mutations()), 1)

    def test_retry_context_survives_handler_release_and_clear_releases_registry(self):
        self.prepare("Roblox: pierwotna gra o mieście", 700)
        current = "Przygotuj taki projekt"
        context = self.prepare(current, 701)
        original = self.contextual_session(current, 701, context).payload_text
        del context
        gc.collect()
        self.prepare("Jak idzie ten projekt?", 702)
        retried = self.prepare(current, 701)
        self.assertEqual(self.contextual_session(current, 701, retried).payload_text, original)
        del retried
        self.provider.clear_all_contexts()
        gc.collect()
        self.assertEqual(len(self.provider._issued_contexts), 0)

    def test_observed_thanks_notify_then_poster_result_is_fresh_read(self):
        text = "Mogłabyś przygotować pakiet Halloween w projekcie Roblox na MSI?"
        context = self.prepare(text, 800)
        session = self.contextual_session(text, 800, context)
        self.assertEqual(self.call("submit", session)["state"], "accepted")
        self.server.view["jobs"][0].update(status="completed", steps=[{
            "role": "master", "status": "completed", "result": {"text": "Raport: przygotowano trzy SVG i ZIP; brak przeglądu wizualnego."}}])
        ack = "dziękuję. Powiadom mnie jak będzie gotowe"
        ack_context = self.prepare(ack, 801)
        self.assertIsNotNone(ack_context)
        ack_session = self.contextual_session(ack, 801, ack_context)
        self.assertFalse(ack_session.can_submit or ack_session.can_cancel)
        query = "jak wygląda plakat zrobiłaś, skończony czy jak możesz mieć potwierdzić"
        result_context = self.prepare(query, 802)
        result_session = self.contextual_session(query, 802, result_context)
        self.assertFalse(result_session.can_submit or result_session.can_cancel)
        result = self.call("result", result_session)
        self.assertEqual(result["state"], "completed")
        self.assertIn("trzy SVG", result["untrustedResult"])
        self.assertEqual(len(self.server.mutations()), 1)
        self.assertFalse(self.server.mutations("cancel"))
        self.assertNotIn(ack, self.provider._contexts["phone"]["users"])
        self.assertIn("świeżego wywołania result", result_session.instructions)
        self.assertIn("raportem tekstowym", result_session.instructions)
        self.assertIn("Nie ma automatycznych powiadomień", ack_session.instructions)

    def test_completion_followups_are_read_tools_not_new_jobs(self):
        self.prepare("Zleć w Roblox: przygotuj plakat", 810)
        for n, text in enumerate(("Sprawdź czy już skończył i co przygotował", "Pokaż wynik", "Opisz gotowy plakat", "Opisz plakat", "Czy możesz opisać gotowy plakat?", "Czy możesz sprawdzić czy już skończył?", "Czy już skończyłaś?", "Co przygotował?", "Potwierdź czy jest gotowy", "Pokaż plakat", "Jak wygląda plakat?"), 811):
            with self.subTest(text=text):
                context = self.prepare(text, n)
                self.assertIsNotNone(context)
                session = self.contextual_session(text, n, context)
                self.assertFalse(session.can_submit or session.can_cancel)
                self.assertEqual({s["name"] for s in session.specs}, {"kritaqo_roblox_status", "kritaqo_roblox_result"})
        self.assertFalse(self.server.calls)

    def test_result_support_preserves_new_edit_tasks(self):
        self.prepare("Roblox: przygotowujemy plakat", 830)
        for n, text in enumerate(("Przygotuj nowy plakat", "Popraw kolory gotowego plakatu", "Dodaj logo do plakatu", "Zmień gotowy plakat", "Opisz koncepcję nowego plakatu", "Sprawdź strukturę projektu Roblox"), 831):
            with self.subTest(text=text):
                context = self.prepare(text, n)
                self.assertIsNotNone(context)
                self.assertTrue(self.contextual_session(text, n, context).can_submit)
        self.assertFalse(self.server.mutations())

    def test_neutral_ack_is_bounded_scoped_and_never_revives_old_task(self):
        self.assertIsNone(self.prepare("Dziękuję. Powiadom mnie jak będzie gotowe", 850))
        self.prepare("Zleć w Roblox: dodaj grę", 851)
        for n, ack in enumerate(("Dziękuję", "Dziękuję bardzo", "Dzięki za pomoc", "OK", "Powiadom mnie jak będzie gotowe", "Dziękuję. Powiadom mnie, jak będzie gotowe", "Dobrze, daj znać gdy będzie skończone"), 852):
            context = self.prepare(ack, n)
            self.assertIsNotNone(context, ack)
            session = self.contextual_session(ack, n, context)
            self.assertFalse(session.can_submit or session.can_cancel)
        self.assertEqual(self.provider._contexts["phone"]["users"], ["Zleć w Roblox: dodaj grę"])
        self.assertFalse(self.server.calls)
        self.assertIsNone(self.prepare("Dziękuję za pomoc. Jaka pogoda?", 860))
        self.assertIsNone(self.prepare("Pokaż wynik", 861))
        with patch.object(k.time, "monotonic", return_value=10):
            self.prepare("Roblox: plakat", 862)
        with patch.object(k.time, "monotonic", return_value=610):
            self.assertIsNone(self.prepare("Dziękuję", 863))

    def test_explicit_camera_artifact_requests_decline_and_clear_scope(self):
        for n, query in enumerate(("Jak wygląda plakat przed kamerą?", "Co widzisz w kamerze i jak wygląda plakat?", "Opisz plakat w kamerze", "Pokaż kamerę w Roblox"), 880):
            with self.subTest(query=query):
                previous = self.prepare("Roblox: zrób plakat", 879)
                self.assertFalse(self.provider.accepts_prompt(query))
                self.assertIsNone(self.prepare(query, n))
                self.assertFalse(self.provider.accepts_context(previous.text, previous.interaction_id, previous))
        for n, query in enumerate(("Opisz gotowy plakat bez kamery", "Opisz plakat bez korzystania z kamery", "Jak wygląda projekt kamery w Roblox?"), 891):
            self.prepare("Roblox: plakat", 890)
            context = self.prepare(query, n)
            self.assertIsNotNone(context, query)
            session = self.contextual_session(query, n, context)
            self.assertFalse(session.can_submit or session.can_cancel, query)

    def test_observed_ciekuje_sequence_fetches_changed_result_without_submission(self):
        fixture_interaction = "%032x" % 900
        request_id = "maria_" + hashlib.sha256((self.provider._target + ":" + fixture_interaction).encode()).hexdigest()
        with self.provider._state() as state:
            state["receipts"][fixture_interaction] = {
                "payload": {"projectId": "project1", "text": "Przygotuj pakiet Halloween w Roblox", "requestId": request_id,
                            "mode": "chat", "execution": True, "workspaceRevision": 4},
                "state": "completed", "jobId": "poster-job", "createdAt": 1, "cancelRequested": False}
            self.provider._save(state)
        step = {"role": "master", "status": "completed", "result": {"text": "Wynik A: trzy SVG, brak oględzin."}}
        self.server.view["jobs"] = [{"id": "poster-job", "requestId": request_id, "status": "completed", "steps": [step]}]
        first = "jeszcze raz, jaki jest wynik zadania Halloween w roblox na ms"
        first_context = self.prepare(first, 901)
        first_session = self.contextual_session(first, 901, first_context)
        self.assertFalse(first_session.can_submit or first_session.can_cancel)
        result_a = self.call("result", first_session)
        self.assertEqual(result_a["untrustedResult"], "Wynik A: trzy SVG, brak oględzin.")
        history_before_ack = list(self.provider._contexts["phone"]["users"])
        ack = "Ciękuję"
        ack_context = self.prepare(ack, 902)
        self.assertIsNotNone(ack_context)
        self.assertEqual(ack_context.text, ack)  # preserve the actual ASR transcript
        ack_session = self.contextual_session(ack, 902, ack_context)
        self.assertFalse(ack_session.can_submit or ack_session.can_cancel)
        self.assertEqual(self.provider._contexts["phone"]["users"], history_before_ack)
        step["result"]["text"] = "Wynik B: sprawdzić eksport SVG przed publikacją."
        followup = "to czy należy jeszcze zrobić na plakacie, żeby było skończony"
        context = self.prepare(followup, 903)
        self.assertIsNotNone(context)
        session = self.contextual_session(followup, 903, context)
        self.assertFalse(session.can_submit or session.can_cancel)
        result_b = self.call("result", session)
        self.assertEqual(result_b["untrustedResult"], "Wynik B: sprawdzić eksport SVG przed publikacją.")
        self.assertNotIn("Wynik A", result_b["untrustedResult"])
        self.assertEqual(result_a["jobId"], result_b["jobId"])
        views = [call for call in self.server.calls if call[1] == "/api/hub/remote" and call[2]["action"] == "view"]
        self.assertEqual(len(views), 2)
        self.assertFalse(self.server.mutations())
        self.assertFalse(self.server.mutations("cancel"))
        self.assertEqual(len(self.state()["receipts"]), 1)

    def test_ciekuje_alias_requires_live_scope_and_whole_utterance(self):
        self.assertIsNone(self.prepare("Ciękuję", 910))
        self.prepare("Roblox: plakat", 911, "phone")
        self.assertIsNone(self.prepare("Ciękuję", 912, "other-sid"))
        self.assertIsNotNone(self.prepare("Ciękuję", 913, "phone"))
        mixed = "Ciękuję. Dodaj logo"
        self.assertFalse(k._neutral_acknowledgment(mixed))
        mixed_context = self.prepare(mixed, 914)
        mixed_session = self.contextual_session(mixed, 914, mixed_context)
        self.assertFalse(mixed_session.can_submit or mixed_session.can_cancel)
        self.provider.clear_context("phone")
        self.assertIsNone(self.prepare("Ciękuję", 915))
        for n, text in enumerate(("Siękuję", "Ciękujęxyz", "Ciękuję. Jaka jutro pogoda?", "Ciękuję. Pokaż plakat przed kamerą"), 920):
            with self.subTest(text=text):
                self.provider.clear_all_contexts()
                context = self.prepare("Roblox: plakat", n + 1000)
                self.assertIsNone(self.prepare(text, n))
                self.assertFalse(self.provider.accepts_context(context.text, context.interaction_id, context))
        with patch.object(k.time, "monotonic", return_value=100):
            self.prepare("Roblox: plakat", 930)
        with patch.object(k.time, "monotonic", return_value=700):
            self.assertIsNone(self.prepare("Ciękuję", 931))
        self.assertFalse(self.server.calls)

    def seed_completed_result(self, text="Wynik A"):
        interaction = "%032x" % 1200
        request_id = "maria_" + hashlib.sha256((self.provider._target + ":" + interaction).encode()).hexdigest()
        with self.provider._state() as state:
            state["receipts"][interaction] = {
                "payload": {"projectId": "project1", "text": "Przygotuj Halloween w Roblox", "requestId": request_id,
                            "mode": "chat", "execution": True, "workspaceRevision": 4},
                "state": "completed", "jobId": "done-job", "createdAt": 1, "cancelRequested": False}
            self.provider._save(state)
        step = {"role": "master", "status": "completed", "result": {"text": text}}
        self.server.view["jobs"] = [{"id": "done-job", "requestId": request_id, "status": "completed", "steps": [step]}]
        return step

    def test_exact_jingue_remaining_sequence_recovers_fresh_read_only(self):
        for ack in ("Jingue", "Dziękuję", None):
            with self.subTest(ack=ack):
                self.provider.clear_all_contexts()
                step = self.seed_completed_result("Wynik A")
                base = 1210 + (0 if ack == "Jingue" else 10 if ack else 20)
                first = "jaki jest wynik zadania Halloween w Roblox na MSI"
                context = self.prepare(first, base)
                self.assertEqual(self.call("result", self.contextual_session(first, base, context))["untrustedResult"], "Wynik A")
                original_users = list(self.provider._contexts["phone"]["users"])
                if ack:
                    ack_context = self.prepare(ack, base + 1)
                    if ack == "Jingue":
                        self.assertIsNone(ack_context)
                        self.assertFalse(self.provider.accepts_context(first, context.interaction_id, context))
                        self.assertEqual(self.provider._contexts["phone"]["users"], original_users)
                    else:
                        self.assertIsNotNone(ack_context)
                step["result"]["text"] = "Wynik B: pozostał eksport SVG."
                final = "co jeszcze zostało do zrobienia"
                recovered = self.prepare(final, base + 2)
                self.assertIsNotNone(recovered)
                self.assertEqual(recovered.read_only, ack == "Jingue")
                session = self.contextual_session(final, base + 2, recovered)
                self.assertFalse(session.can_submit or session.can_cancel)
                self.assertIn("co jeszcze zostało do zrobienia", session.instructions)
                if ack == "Jingue":
                    self.assertIn("WYŁĄCZNIE DO ODCZYTU", session.instructions)
                    self.assertIn("jawną nazwą Roblox", session.instructions)
                result = self.call("result", session)
                self.assertEqual(result["untrustedResult"], "Wynik B: pozostał eksport SVG.")
        self.assertFalse(self.server.mutations())
        self.assertFalse(self.server.mutations("cancel"))

    def test_remaining_work_semantics_do_not_execute_new_or_mixed_task(self):
        queries = ("co jeszcze zostało do zrobienia", "Co pozostało do dokończenia?", "Czy coś jeszcze zostało?",
                   "Co jeszcze trzeba zrobić?", "Czego brakuje do ukończenia?", "No, co jeszcze pozostało do ukończenia?",
                   "Sprawdź co jeszcze zostało do zrobienia")
        for n, query in enumerate(queries, 1250):
            self.prepare("Roblox: plakat", n + 1000)
            self.prepare("Jingue", n + 2000)
            context = self.prepare(query, n)
            self.assertIsNotNone(context, query)
            self.assertTrue(context.read_only)
            self.assertFalse(self.contextual_session(query, n, context).can_submit)
        for n, command in enumerate(("Zrób to, co pozostało", "Sprawdź co zostało i dodaj logo", "Pokaż wynik i popraw plakat"), 1270):
            self.provider.clear_all_contexts()
            self.prepare("Roblox: plakat", n + 1000)
            self.prepare("Jingue", n + 2000)
            self.assertFalse(k._result_read(command), command)
            self.assertIsNone(self.prepare(command, n), command)
        self.assertFalse(self.server.calls)

    def test_suspended_tokens_sessions_and_old_explicit_retry_stay_revoked(self):
        task = "Dodaj logo w Roblox"
        context = self.prepare(task, 1300)
        session = self.contextual_session(task, 1300, context)
        self.assertTrue(session.can_submit)
        self.assertIsNone(self.prepare("Jingue", 1301))
        self.assertEqual(self.call("submit", session)["reason"], "context_expired")
        self.assertIsNone(self.provider.for_turn(task, "%032x" % 1300))
        self.assertIsNone(self.prepare(task, 1300))
        read = self.prepare("Pokaż wynik", 1302)
        self.assertTrue(read.read_only)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            read.read_only = False
        read_session = self.contextual_session(read.text, 1302, read)
        read_session.specs.append({"name": "kritaqo_roblox_submit"})  # callguard independent of mutable specs
        self.assertEqual(self.call("submit", read_session)["reason"], "read_only_context")
        read_session.specs.append({"name": "kritaqo_roblox_cancel"})
        self.assertEqual(self.call("cancel", read_session)["reason"], "read_only_context")
        self.assertIsNone(self.prepare("Dodaj logo", 1303))
        fresh = self.prepare("Dodaj logo w Roblox", 1304)
        self.assertTrue(self.contextual_session(fresh.text, 1304, fresh).can_submit)
        self.assertIsNone(self.provider.for_turn(task, "%032x" % 1300))
        self.assertEqual(self.call("submit", session)["reason"], "context_expired")
        self.assertFalse(self.server.calls)

    def test_noise_and_dormant_ack_never_extend_ttl_or_rearm(self):
        with patch.object(k.time, "monotonic", return_value=100):
            self.prepare("Roblox: plakat", 1320)
        with patch.object(k.time, "monotonic", return_value=600):
            self.assertIsNone(self.prepare("Jingue", 1321))
            self.assertEqual(self.provider._contexts["phone"]["at"], 100)
            self.assertTrue(self.provider._contexts["phone"]["dormant"])
        with patch.object(k.time, "monotonic", return_value=650):
            self.assertIsNone(self.prepare("Dziękuję", 1322))
            self.assertIsNone(self.prepare("Mhm hmm", 1323))
            self.assertEqual(self.provider._contexts["phone"]["at"], 100)
        with patch.object(k.time, "monotonic", return_value=700):
            self.assertIsNone(self.prepare("Co jeszcze zostało?", 1324))
            self.assertNotIn("phone", self.provider._contexts)
        self.assertFalse(self.server.calls)

    def test_noise_limits_topics_questions_other_sid_and_clear(self):
        self.assertIsNone(self.prepare("Jingue", 1340))
        self.prepare("Roblox: plakat", 1341)
        self.assertIsNone(self.prepare("Jingue", 1342, "other"))
        self.assertIsNone(self.prepare("Pokaż wynik", 1343, "other"))
        for n, text in enumerate(("Jingue aaa bbb ccc", "J" * 33, "Jingue?", "Co?", "Dodaj", "Anuluj", "pogoda",
                                  "Jak wygląda plakat przed kamerą?", "Projekt Minecraft", "Zmieńmy temat"), 1350):
            self.provider.clear_all_contexts()
            self.prepare("Roblox: plakat", n + 1000)
            self.assertIsNone(self.prepare(text, n), text)
            self.assertNotIn("phone", self.provider._contexts, text)
        self.prepare("Roblox: plakat", 1370)
        self.prepare("Jingue", 1371)
        self.provider.clear_context("phone")
        self.assertIsNone(self.prepare("Pokaż wynik", 1372))
        self.prepare("Roblox: plakat", 1373)
        self.prepare("Jingue", 1374)
        self.provider.clear_all_contexts()
        self.assertIsNone(self.prepare("Co jeszcze zostało?", 1375))
        self.assertFalse(self.server.calls)

    def test_suspended_identity_survives_gc_and_reactivation(self):
        text = "Dodaj logo w Roblox"
        context = self.prepare(text, 1380)
        del context
        gc.collect()
        self.prepare("Jingue", 1381)
        self.prepare("Sprawdź projekt Roblox", 1382)
        self.assertIsNone(self.provider.for_turn(text, "%032x" % 1380))
        self.assertIsNone(self.prepare(text, 1380))

    def test_tool_telemetry_logs_fresh_result_after_logout_without_content(self):
        events = []

        def capture(message, encoded):
            event = json.loads(encoded)
            if event["event"] == "finished":
                self.assertEqual(self.server.calls[-1][1], "/api/logout")
            events.append(event)

        with patch.object(k._LOGGER, "info", side_effect=capture):
            empty = self.call("result", self.session("Pokaż wynik Roblox USER_SECRET", n=1400))
            self.assertEqual(empty["state"], "not_recorded")
            self.seed_completed_result("RESULT_SECRET: grafika nieobejrzana")
            self.call("result", self.session("Pokaż wynik Roblox USER_SECRET", n=1401))
        self.assertEqual([e["event"] for e in events], ["start", "finished", "start", "finished"])
        self.assertFalse(events[1]["has_result"])
        self.assertTrue(events[3]["has_result"])
        self.assertTrue(events[3]["success"])
        self.assertEqual(events[3]["state"], "completed")
        self.assertEqual(events[3]["jobId"], "done-job")
        self.assertEqual(events[3]["sessionCleanup"], "confirmed")
        self.assertEqual(events[3]["action"], "result")
        self.assertTrue(all(e["elapsed_ms"] >= 0 for e in events))
        encoded = json.dumps(events)
        for secret in ("USER_SECRET", "RESULT_SECRET", "FAKE_NEVER_RETURN", "project1", self.config["data_dir"], "b" * 64):
            self.assertNotIn(secret, encoded)

    def test_tool_telemetry_failure_unknown_and_logger_failure_does_not_change_outcome(self):
        self.server.logout_ok = False
        with self.assertLogs(k._LOGGER, level="INFO") as captured:
            result = self.call("result", self.session("Pokaż wynik Roblox", n=1410))
        self.assertEqual(result["reason"], "cleanup_uncertain")
        finished = json.loads(captured.records[-1].getMessage().split("[KRITAQO_TOOL] ", 1)[1])
        self.assertEqual((finished["success"], finished["state"], finished["sessionCleanup"], finished["has_result"]),
                         (False, "unknown", "unknown", False))
        self.assertNotIn("reason", finished)
        self.provider = self.new_provider()
        self.server.calls.clear()
        with patch.object(k._LOGGER, "info", side_effect=RuntimeError("LOGGER_SECRET")):
            blocked = self.call("result")
        self.assertEqual(blocked["reason"], "cleanup_uncertain")
        self.assertFalse(self.server.calls)

    def test_tool_telemetry_raw_failure_redacted_and_success_not_changed_by_logger(self):
        def broken_view():
            raise RuntimeError("RAW_ERROR_SECRET")
        self.server.before_view = broken_view
        with self.assertLogs(k._LOGGER, level="INFO") as captured:
            self.assertFalse(self.call("result")["success"])
        self.assertNotIn("RAW_ERROR_SECRET", "\n".join(captured.output))
        self.server.before_view = None
        with patch.object(k._LOGGER, "info", side_effect=RuntimeError("LOGGER_SECRET")):
            result = self.call("result")
        self.assertTrue(result["success"])
        self.assertEqual(result["state"], "not_recorded")

    def test_exact_cold_project_asr_three_turns_fetch_fresh_read_only(self):
        step = self.seed_completed_result("Wynik A: trzy SVG")
        first = "jaki jest wynik zadania halloween w roblok się na MSI"
        self.assertFalse(self.provider.accepts_prompt(first))
        self.assertIsNone(self.provider.for_turn(first, "%032x" % 1500))
        context = self.prepare(first, 1500)
        self.assertIsNotNone(context)
        self.assertTrue(context.read_only)
        self.assertEqual(context.text, first)
        session = self.contextual_session(first, 1500, context)
        self.assertEqual(session.payload_text, first)
        self.assertIn("Kontrolowany wariant ASR", session.instructions)
        self.assertFalse(session.can_submit or session.can_cancel)
        a = self.call("result", session)
        self.assertEqual(a["untrustedResult"], "Wynik A: trzy SVG")
        at = self.provider._contexts["phone"]["at"]
        self.assertIsNone(self.prepare("JinKu", 1501))
        self.assertEqual(self.provider._contexts["phone"]["at"], at)
        self.assertFalse(self.provider.accepts_context(first, context.interaction_id, context))
        step["result"]["text"] = "Wynik B: potrzebny eksport SVG"
        final = "co jeszcze zostało do zrobienia"
        recovered = self.prepare(final, 1502)
        self.assertTrue(recovered.read_only)
        final_session = self.contextual_session(final, 1502, recovered)
        self.assertFalse(final_session.can_submit or final_session.can_cancel)
        b = self.call("result", final_session)
        self.assertEqual(b["untrustedResult"], "Wynik B: potrzebny eksport SVG")
        self.assertEqual(a["jobId"], b["jobId"])
        self.assertFalse(self.server.mutations())
        self.assertFalse(self.server.mutations("cancel"))
        self.assertEqual(len([c for c in self.server.calls if c[1] == "/api/hub/remote" and c[2]["action"] == "view"]), 2)

    def test_project_asr_gate_boundaries_targets_camera_negation_and_mixed_actions(self):
        bad = ("Jaki jest wynik w roblok się", "Jaki jest wynik w roblok się na MiniPC",
               "Jaki jest wynik w roblok się na MSI2", "Jaki jest wynik w roblok się na MSI-Pro",
               "Jaki jest wynik w xroblok się na MSI", "Jaki jest wynik w roblok siew na MSI",
               "Jaki jest wynik w roblok sięx na MSI", "Jaki jest wynik w robloksie na MSI",
               "Jaki jest wynik w roblok się na MSI w projekcie Minecraft",
               'Jaki jest wynik w roblok się na MSI w projekcie "Obcy"',
               "Jaki jest wynik w roblok się na MSI w projekcie Obcy",
               "Jak wygląda plakat przed kamerą w roblok się na MSI",
               "Jaki jest wynik nie w roblok się na MSI", "Pokaż wynik roblok się nie na MSI",
               "Pokaż wynik zamiast roblok się na MSI", "Pokaż wynik roblok się bez MSI",
               "Pokaż wynik roblok się na MSI, lecz bez MSI",
               "Dodaj logo w roblok się na MSI", "Jaki jest wynik w roblok się na MSI i dodaj logo",
               "Jaki jest wynik w roblok się na MSI i uruchom grę",
               "Jaki jest wynik w roblok się na MSI i anuluj zadanie",
               "Jaki jest wynik w roblok się na MSI i przerwij zadanie",
               "Zatrzymaj zadanie roblok się na MSI")
        for n, text in enumerate(bad, 1510):
            with self.subTest(text=text):
                self.provider.clear_all_contexts()
                self.assertFalse(self.provider._qualified_project_read_alias(text))
                self.assertFalse(self.provider.accepts_prompt(text))
                self.assertIsNone(self.prepare(text, n))
                self.assertIsNone(self.provider.for_turn(text, "%032x" % n))
        self.assertFalse(self.server.calls)

    def test_project_asr_selector_normalization_is_guard_only(self):
        queries = ('Pokaż wynik projektu "Roblok się" na MSI',
                   "Jaki jest wynik projektu Roblok Się na MSI?",
                   "Jaki jest wynik projektu o nazwie roblok się na MSI?",
                   "Pokaż wynik roblok się na MSI bez zmian")
        for n, text in enumerate(queries, 1540):
            self.provider.clear_all_contexts()
            context = self.prepare(text, n)
            self.assertIsNotNone(context, text)
            self.assertTrue(context.read_only)
            self.assertEqual(context.text, text)
            self.assertEqual(self.contextual_session(text, n, context).payload_text, text)
            self.assertFalse(self.provider.accepts_prompt(text))
            self.assertIsNone(self.provider.for_turn(text, "%032x" % n))
        self.assertTrue(self.provider._other_target('Pokaż wynik projektu "Nieznany" na MSI'))
        config = dict(self.config, computer_name="Studio", state_dir=str(Path(self.tmp.name) / "studio-state"))
        other = k.KritaqoToolsProvider(config, client_factory=self.server.client, record_reader=lambda _: {})
        self.assertFalse(other._qualified_project_read_alias("Pokaż wynik roblok się na MSI"))
        self.assertTrue(other._qualified_project_read_alias("Pokaż wynik roblok się na Studio"))

    def test_project_asr_demotes_active_and_never_reactivates_write(self):
        old_text = "Dodaj logo w Roblox"
        old = self.prepare(old_text, 1550)
        old_session = self.contextual_session(old_text, 1550, old)
        alias = "Pokaż wynik roblok się na MSI"
        read = self.prepare(alias, 1551)
        self.assertTrue(read.read_only)
        self.assertFalse(self.provider.accepts_context(old_text, old.interaction_id, old))
        self.assertIsNone(self.provider.for_turn(old_text, "%032x" % 1550))
        self.assertEqual(self.call("submit", old_session)["reason"], "context_expired")
        self.assertIsNone(self.prepare("Dodaj logo", 1552))
        fresh = self.prepare("Dodaj logo w Roblox", 1553)
        self.assertFalse(fresh.read_only)
        self.assertTrue(self.contextual_session(fresh.text, 1553, fresh).can_submit)
        alias2 = self.prepare(alias, 1554)
        self.assertTrue(alias2.read_only)
        self.assertIsNone(self.prepare("Pokaż wynik roblok się na MSI i uruchom grę", 1555))
        self.assertFalse(self.provider.accepts_context(alias2.text, alias2.interaction_id, alias2))
        self.assertFalse(self.server.calls)

    def test_project_asr_demotes_already_held_legacy_session_but_fresh_id_works(self):
        old_text = "Dodaj logo w Roblox"
        self.prepare(old_text, 1570)
        held_legacy = self.provider.for_turn(old_text, "%032x" % 1570)
        self.assertTrue(held_legacy.can_submit)
        self.assertIsNone(held_legacy._tool_context)
        recovered = self.prepare("Pokaż wynik roblok się na MSI", 1571)
        self.assertTrue(recovered.read_only)
        result = self.call("submit", held_legacy)
        self.assertEqual(result["reason"], "context_expired")
        self.assertFalse(self.server.calls)
        fresh = self.provider.for_turn("Dodaj inne logo w Roblox", "%032x" % 1572)
        self.assertTrue(fresh.can_submit)
        self.assertEqual(self.call("submit", fresh)["state"], "accepted")
        self.assertEqual(len(self.server.mutations()), 1)
        self.assertEqual(self.server.mutations()[0]["payload"]["text"], "Dodaj inne logo w Roblox")

    def test_project_asr_scope_ttl_sid_clear_and_canonical_controls(self):
        text = "Jaki jest wynik roblok się na MSI"
        with patch.object(k.time, "monotonic", return_value=100):
            context = self.prepare(text, 1560)
        with patch.object(k.time, "monotonic", return_value=650):
            self.assertIsNone(self.prepare("Pokaż wynik", 1561, "other"))
            self.assertIsNone(self.prepare("JinKu", 1562))
            self.assertEqual(self.provider._contexts["phone"]["at"], 100)
        with patch.object(k.time, "monotonic", return_value=700):
            self.assertIsNone(self.prepare("Co jeszcze zostało?", 1563))
            self.assertFalse(self.provider.accepts_context(text, context.interaction_id, context))
        context = self.prepare(text, 1564)
        self.assertIs(self.prepare(text, 1564), context)
        self.provider.clear_context("phone")
        self.assertIsNone(self.prepare("Pokaż wynik", 1565))
        canonical = "Przygotuj plakat w Roblox na MSI"
        self.assertTrue(self.provider.accepts_prompt(canonical))
        session = self.provider.for_turn(canonical, "%032x" % 1566)
        self.assertTrue(session.can_submit)
        self.assertFalse(self.server.calls)


if __name__ == "__main__":
    unittest.main()
