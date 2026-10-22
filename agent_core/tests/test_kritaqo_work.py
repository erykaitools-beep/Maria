"""Generic work fixtures. Temporary files and injected bridge only; no models."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from agent_core.llm.kritaqo_work_service import WorkService, WorkError
from agent_core.llm.kritaqo_work import WorkToolsProvider


class Bridge:
    def __init__(self):
        self.calls, self.jobs = [], {}
        self.before_submit = None
        self.fail_submit = self.offline = self.wrong_job = False
        self.catalog = [
            {"key": "local:local-project", "hostNodeId": "mini", "projectId": "local-project", "peerId": None,
             "name": "X3-5z", "computerName": "MiniPC", "workspaceRevision": None, "executionAllowed": True, "available": True},
            {"key": "peer:roblox", "hostNodeId": "msi", "projectId": "roblox", "peerId": "peer", "name": "Roblox",
             "computerName": "MSI", "workspaceRevision": 1, "executionAllowed": True, "readOnlyAllowed": True, "available": True},
        ]

    def __call__(self, request):
        self.calls.append(copy.deepcopy(request))
        action = request["action"]
        if self.offline: raise OSError("fake connection failure; never expose native text")
        if action == "catalog": return {"ok": True, "projects": copy.deepcopy(self.catalog), "partial": False}
        if action == "submit":
            if self.before_submit: self.before_submit(request)
            if self.fail_submit: raise TimeoutError("fake unknown send")
            job = {"id": "job-" + str(len(self.jobs)), "requestId": request["requestId"], "projectId": request["projectId"],
                   "status": "queued", "execution": True, "executionMode": "workspace-write", "steps": []}
            self.jobs[job["id"]] = job
            return {"ok": True, "job": copy.deepcopy(job)}
        if action in {"status", "view"}:
            jobs = [j for j in self.jobs.values() if j["projectId"] == request["projectId"]]
            job = self.jobs.get(request.get("jobId"))
            if self.wrong_job and job: job = dict(job, requestId="another-request")
            return {"ok": True, "project": {"id": request["projectId"]}, "jobs": copy.deepcopy(jobs), "job": copy.deepcopy(job)}
        if action == "artifacts": return {"ok": True, "artifacts": [{"path": "reports/result.txt", "referencedByJobId": request["jobId"], "verified": False}]}
        if action == "artifact": return {"ok": True, "content": "VGVzdA==", "mime": "text/plain", "size": 4}
        if action == "cancel": return {"ok": True}
        raise AssertionError("Unexpected fake bridge action")

    def submissions(self): return [c for c in self.calls if c["action"] == "submit"]


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); state = root / "private"; state.mkdir(mode=0o700)
        self.config = {"state_dir": str(state), "data_dir": str(root / "data"), "bridge_path": str(root / "bridge.py"),
                       "peer_id": "peer", "host_node_id": "msi", "project_id": "roblox", "workspace_revision": 1,
                       "project_name": "Roblox", "computer_name": "MSI"}
        self.bridge = Bridge(); self.clock = 1000
        self.service = WorkService(self.config, bridge=self.bridge, clock=lambda: self.clock)
        self.addCleanup(self.service.close)
        self.provider = WorkToolsProvider(None, self.service)

    def select(self, name="Roblox"):
        project = next(p for p in self.service.projects()["projects"] if p["name"] == name)
        self.service.select_project(project["key"])
        return self.service.selected()

    def session(self, text, n=1):
        interaction = "%032x" % n
        context = self.provider.prepare_turn(text, interaction, "socket1")
        return self.provider.for_turn(text, interaction, tool_context=context)

    def submit(self, n=1):
        target, epoch = self.select()
        return self.service.submit("%032x" % n, "Przygotuj raport w projekcie Roblox na MSI", target, epoch)

    def finish(self, task):
        self.bridge.jobs[task["jobId"]].update(status="completed", steps=[{"role": "master", "status": "completed",
                                                                        "result": {"text": "Utworzono raport; test telefonu pozostaje ręczny."}}])

    def test_catalog_cache_identity_and_no_initial_model_or_submit(self):
        first = self.service.projects(); self.service.projects()
        self.assertEqual(len(self.bridge.calls), 1)
        self.assertNotEqual(first["projects"][0]["key"], first["projects"][1]["key"])
        self.assertEqual(self.service.tasks()["tasks"], [])
        self.assertEqual(self.bridge.submissions(), [])
        self.clock += 31; self.service.projects(); self.assertEqual(len(self.bridge.calls), 2)

    def test_selection_persists_and_unknown_selection_keeps_old(self):
        target, _ = self.select()
        with self.assertRaises(ValueError): self.service.select_project("not-a-project")
        restored = WorkService(self.config, bridge=self.bridge, clock=lambda: self.clock)
        self.assertEqual(restored.selected()[0], target)
        self.assertEqual((Path(self.config["state_dir"]) / "work/state.json").stat().st_mode & 0o777, 0o600)

    def test_durable_original_request_before_send_and_same_turn_never_resubmits(self):
        target, epoch = self.select(); text = "Przygotuj raport. Zachowaj ORYGINALNY tekst!"
        def inspect(request):
            state = json.loads((Path(self.config["state_dir"]) / "work/state.json").read_text())
            self.assertEqual(state["tasks"][-1]["status"], "unknown")
            self.assertEqual(state["tasks"][-1]["prompt"], text)
            self.assertEqual(request["text"], text)
            self.assertEqual(request["expectedHostNodeId"], "msi")
        self.bridge.before_submit = inspect
        a = self.service.submit("a" * 32, text, target, epoch)
        b = self.service.submit("a" * 32, text, target, epoch)
        self.assertEqual(a["jobId"], b["jobId"]); self.assertEqual(len(self.bridge.submissions()), 1)
        with self.assertRaises(WorkError): self.service.submit("a" * 32, text + "changed", target, epoch)

    def test_unknown_send_survives_reload_no_replay_or_new_project_job(self):
        self.bridge.fail_submit = True
        a = self.submit()
        self.assertEqual(a["status"], "unknown")
        restored = WorkService(self.config, bridge=self.bridge, clock=lambda: self.clock)
        target, epoch = restored.selected()
        again = restored.submit("%032x" % 1, "Przygotuj raport w projekcie Roblox na MSI", target, epoch)
        self.assertEqual(again["status"], "unknown")
        with self.assertRaises(WorkError): restored.submit("b" * 32, "Przygotuj nowy raport", target, epoch)
        restored.observer_step()
        self.assertEqual(len(self.bridge.submissions()), 1)

    def test_two_hosts_work_independently_without_revision_for_local_managed(self):
        remote = self.submit()
        target, epoch = self.select("X3-5z")
        local = self.service.submit("c" * 32, "Przygotuj raport X3-5z", target, epoch)
        self.assertNotEqual(remote["projectKey"], local["projectKey"])
        request = self.bridge.submissions()[-1]
        self.assertIsNone(request["peerId"])
        self.assertNotIn("workspaceRevision", request)
        self.assertEqual(request["expectedHostNodeId"], "mini")

    def test_permission_and_revision_change_refuse_before_send(self):
        for field, value in (("workspaceRevision", 2), ("executionAllowed", False), ("hostNodeId", "repaired-host")):
            with self.subTest(field=field):
                self.bridge.catalog[1].update(workspaceRevision=1, executionAllowed=True, hostNodeId="msi")
                target, epoch = self.select()
                self.bridge.catalog[1][field] = value
                with self.assertRaises(WorkError): self.service.submit("d" * 32, "Przygotuj test", target, epoch)
                self.assertEqual(self.bridge.submissions(), [])

    def test_known_observer_persists_result_one_event_and_never_submits(self):
        task = self.submit(); self.finish(task); count = len(self.bridge.submissions())
        self.service.observer_step()
        updated = self.service.tasks()["tasks"][0]
        self.assertEqual(updated["status"], "completed")
        self.assertIn("test telefonu", updated["resultText"])
        self.assertEqual(updated["verificationState"], "not-established")
        event = updated["completionEventId"]; self.assertTrue(event)
        self.service.refresh(task["key"])
        self.assertEqual(self.service.tasks()["tasks"][0]["completionEventId"], event)
        restored = WorkService(self.config, bridge=self.bridge, clock=lambda: self.clock)
        self.assertEqual(restored.tasks()["tasks"][0]["completionEventId"], event)
        self.assertEqual(len(self.bridge.submissions()), count)

    def test_offline_keeps_last_known_status_but_never_current_and_bad_correlation(self):
        task = self.submit(); self.bridge.offline = True; self.service.refresh(task["key"])
        card = self.service.tasks()["tasks"][0]
        self.assertEqual(card["status"], "queued"); self.assertFalse(card["available"]); self.assertTrue(card["stale"])
        self.bridge.offline = False; self.bridge.wrong_job = True; self.service.refresh(task["key"])
        self.assertFalse(self.service.tasks()["tasks"][0]["available"])

    def test_legacy_baseline_has_no_completion_storm_and_result_read_is_compatible(self):
        self.service.close()
        state = Path(self.config["state_dir"])
        (state / "work/state.json").unlink()
        legacy_job = {"id": "old-job", "requestId": "old-request", "projectId": "roblox", "status": "completed", "steps": [{"role": "master", "status": "completed", "result": {"text": "Historical report"}}]}
        self.bridge.jobs["old-job"] = legacy_job
        (state / "receipts.json").write_text(json.dumps({"receipts": {"old-interaction": {"state": "completed", "jobId": "old-job", "createdAt": 20,
                 "payload": {"projectId": "roblox", "requestId": "old-request", "text": "Old request"}}}}))
        service = WorkService(self.config, bridge=self.bridge, clock=lambda: self.clock)
        service.observer_step()
        card = service.tasks()["tasks"][0]
        self.assertTrue(card["historical"]); self.assertIsNone(card["completionEventId"])
        self.assertEqual(card["resultText"], "Historical report")
        self.assertEqual(self.bridge.submissions(), [])

    def test_artifacts_are_exact_job_listed_safe_relative_paths_only(self):
        task = self.submit(); self.finish(task); self.service.refresh(task["key"])
        with self.assertRaises(WorkError): self.service.artifact(task["key"], "../private")
        with self.assertRaises(WorkError): self.service.artifact(task["key"], "not-listed.txt")
        result = self.service.artifact(task["key"], "reports/result.txt")
        self.assertEqual(result["content"], "VGVzdA==")
        last = self.bridge.calls[-1]
        self.assertEqual((last["jobId"], last["expectedHostNodeId"]), (task["jobId"], "msi"))

    def test_explicit_generic_target_and_original_text_tool_arguments_closed(self):
        text = "Przygotuj raport w projekcie X3-5z na MiniPC"
        session = self.session(text)
        self.assertIn("kritaqo_work_submit", [s["name"] for s in session.specs])
        self.assertFalse(session.call("kritaqo_work_submit", {"projectId": "roblox"})["success"])
        result = session.call("kritaqo_work_submit", {})
        self.assertTrue(result["success"])
        self.assertEqual(self.bridge.submissions()[0]["text"], text)
        self.assertEqual(self.bridge.submissions()[0]["expectedHostNodeId"], "mini")

    def test_asr_glued_unknown_target_and_explicit_other_never_inherit_selected(self):
        self.select()
        for n, text in enumerate(("Przygotuj w projekcie Robloxną MSI test", "Przygotuj w projekcie Minecraft test", "Przygotuj test w innym projekcie", "Przygotuj test nie w projekcie Roblox"), 100):
            with self.subTest(text=text):
                session = self.session(text, n)
                self.assertNotIn("kritaqo_work_submit", [s["name"] for s in session.specs])
                self.assertTrue(session.call("kritaqo_work_result", {})["chooseProject"])
                self.assertIn("choose", session.instructions)
        self.assertEqual(self.bridge.submissions(), [])

    def test_same_named_projects_need_host_and_selection_change_revokes_frozen_turn(self):
        self.bridge.catalog.append(dict(self.bridge.catalog[1], hostNodeId="another", peerId="peer2", computerName="Laptop2"))
        session = self.session("Przygotuj raport w projekcie Roblox")
        self.assertNotIn("kritaqo_work_submit", [s["name"] for s in session.specs])
        valid = self.session("Przygotuj raport w projekcie Roblox na MSI", 2)
        self.assertIn("kritaqo_work_submit", [s["name"] for s in valid.specs])
        self.select("X3-5z")
        self.assertFalse(valid.call("kritaqo_work_submit", {})["success"])
        self.assertEqual(self.bridge.submissions(), [])

    def test_result_request_cannot_submit_and_clear_or_cancel_invalidates_session(self):
        self.select()
        result = self.session("Jaki jest wynik zadania Roblox na MSI?")
        self.assertNotIn("kritaqo_work_submit", [s["name"] for s in result.specs])
        result.close(); self.assertFalse(result.call("kritaqo_work_result", {})["success"])
        current = self.session("Przygotuj test Roblox na MSI", 3)
        self.provider.clear_context("socket1")
        self.assertFalse(current.call("kritaqo_work_submit", {})["success"])
        self.assertEqual(self.bridge.submissions(), [])

    def test_remaining_work_uses_persisted_selection_after_ack_and_new_sid(self):
        self.select()
        self.assertIsNone(self.provider.prepare_turn("Dziękuję", "e" * 32, "socket1"))
        self.assertIsNone(self.provider.prepare_turn("Ciękuję", "f" * 32, "socket1"))
        service = WorkService(self.config, bridge=self.bridge)
        provider = WorkToolsProvider(None, service)
        text = "Co jeszcze zostało do zrobienia?"
        context = provider.prepare_turn(text, "a" * 32, "new-socket")
        session = provider.for_turn(text, "a" * 32, tool_context=context)
        self.assertEqual(context.target["projectId"], "roblox")
        self.assertNotIn("kritaqo_work_submit", [s["name"] for s in session.specs])
        self.assertTrue(session.call("kritaqo_work_result", {})["success"])
        self.assertEqual(self.bridge.submissions(), [])

    def test_real_project_title_exact_distinctive_token_and_unknown_host(self):
        self.bridge.catalog[0]["name"] = "Projekt testowy X3-5z"
        session = self.session("Sprawdź stan X3-5z na mini PC")
        self.assertEqual(session.context.target["projectId"], "local-project")
        self.assertNotIn("kritaqo_work_submit", [s["name"] for s in session.specs])
        result = session.call("kritaqo_work_result", {})
        self.assertTrue(result["available"])
        self.assertEqual(result["reason"], "no_generic_work_receipt_not_no_project_jobs")
        self.assertIn("sharedState", result)
        bad = self.session("Przygotuj test w projekcie Roblox na NIEZNANYM", 2)
        self.assertNotIn("kritaqo_work_submit", [s["name"] for s in bad.specs])

    def test_completed_snapshot_and_artifact_failure_do_not_claim_live_or_available(self):
        task = self.submit(); self.finish(task); self.service.refresh(task["key"])
        self.clock += 300
        card = self.service.tasks()["tasks"][0]
        self.assertTrue(card["snapshot"]); self.assertFalse(card["stale"])
        self.assertEqual(card["lastSeenAt"], 1000)
        original = self.service._bridge
        self.service._bridge = lambda request: {"ok": False} if request["action"] == "artifacts" else original(request)
        self.service.refresh(task["key"])
        card = self.service.tasks()["tasks"][0]
        self.assertFalse(card["artifacts"][0]["available"])
        self.assertEqual(card["artifactReason"], "artifact_listing_unavailable")
        with self.assertRaises(WorkError): self.service.artifact(task["key"], "reports/result.txt")

    def test_refresh_network_does_not_block_cached_tasks_and_round_robin(self):
        task = self.submit()
        started, release = threading.Event(), threading.Event()
        original = self.service._bridge
        def slow(request):
            if request["action"] == "status":
                started.set(); release.wait(2)
            return original(request)
        self.service._bridge = slow
        thread = threading.Thread(target=lambda: self.service.refresh(task["key"]))
        thread.start(); self.assertTrue(started.wait(1))
        read = threading.Event()
        reader = threading.Thread(target=lambda: (self.service.tasks(), read.set()))
        reader.start()
        try: self.assertTrue(read.wait(.5), "cached UI reads must not wait for offline bridge")
        finally: release.set(); thread.join(2); reader.join(2)
        self.service._bridge = original
        template = self.service._state["tasks"][0]
        for i in range(12):
            extra = copy.deepcopy(template); extra["key"] = "extra_%s" % i
            self.service._state["tasks"].append(extra)
        seen = []
        self.service.refresh = lambda key, cancelled=None: seen.append(key)
        self.service.observer_step(); self.service.observer_step()
        self.assertEqual(len(set(seen)), 13)

    def test_artifact_mime_hash_and_metadata(self):
        task = self.submit(); self.finish(task); self.service.refresh(task["key"])
        result = self.service.artifact(task["key"], "reports/result.txt")
        self.assertEqual(result["mime"], "text/plain")
        self.assertEqual(result["observedAt"], 1000)
        self.assertEqual(len(result["sha256"]), 64)
        original = self.service._bridge
        self.service._bridge = lambda request: {"ok": True, "content": "VGVzdA==", "sha256": "0" * 64} if request["action"] == "artifact" else original(request)
        with self.assertRaisesRegex(WorkError, "artifact_hash_mismatch"):
            self.service.artifact(task["key"], "reports/result.txt")

    def test_portfolio_broad_requests_keep_existing_provider_and_no_generic_mutation(self):
        class Legacy:
            def prepare_turn(self, text, interaction_id, conversation_id): return marker
            def for_turn(self, text, interaction_id, tool_context=None):
                self_context.append(tool_context); return "legacy-session"
            def accepts_context(self, text, interaction_id, context): return context is marker
        marker, self_context = object(), []
        provider = WorkToolsProvider(Legacy(), self.service)
        text = "Sprawdź stan wszystkich projektów"
        context = provider.prepare_turn(text, "a" * 32, "socket")
        self.assertIs(context, marker)
        self.assertEqual(provider.for_turn(text, "a" * 32, tool_context=context), "legacy-session")
        self.assertEqual(self_context, [marker])
        self.assertEqual(self.bridge.calls, [])

    def test_inflected_other_project_never_inherits_selected_target(self):
        self.select("X3-5z")
        for n, text in enumerate(("Przygotuj test Robloxa", "Przygotuj test w Robloxie", "Przygotuj test Robloxną MSI"), 200):
            with self.subTest(text=text):
                session = self.session(text, n)
                self.assertIsNone(session.context.target)
                self.assertNotIn("kritaqo_work_submit", [s["name"] for s in session.specs])
                self.assertFalse(session.call("kritaqo_work_submit", {})["success"])
        self.assertEqual(self.bridge.submissions(), [])
        self.assertEqual(self.service.selected()[0]["projectId"], "local-project")

    def test_duration_and_deadline_are_not_unknown_computer_selectors(self):
        self.select("X3-5z")
        for n, text in enumerate(("Przygotuj raport na jutro", "Przygotuj raport na 10 minut"), 250):
            with self.subTest(text=text):
                session = self.session(text, n)
                self.assertEqual(session.context.target["projectId"], "local-project")
                self.assertIn("kritaqo_work_submit", [s["name"] for s in session.specs])
        for n, text in enumerate(("Przygotuj raport na komputerze NIEZNANYM", "Przygotuj test Roblox na NIEZNANYM"), 260):
            with self.subTest(text=text):
                session = self.session(text, n)
                self.assertIsNone(session.context.target)
                self.assertNotIn("kritaqo_work_submit", [s["name"] for s in session.specs])

    def test_late_older_observation_cannot_erase_completion_or_result(self):
        task = self.submit()
        started, release = threading.Event(), threading.Event()
        original = self.service._bridge
        calls = []
        def racing(request):
            if request["action"] == "status":
                calls.append(request)
                if len(calls) == 1:
                    old = original(request)
                    old["job"]["status"] = "running"
                    started.set(); release.wait(2)
                    return old
            return original(request)
        self.service._bridge = racing
        first = threading.Thread(target=lambda: self.service.refresh(task["key"]))
        first.start(); self.assertTrue(started.wait(1))
        try:
            self.finish(task)
            self.service.refresh(task["key"])
            completed = self.service.tasks()["tasks"][0]
            self.assertEqual(completed["status"], "completed")
            self.assertTrue(completed["completionEventId"])
        finally:
            release.set(); first.join(2)
        after = self.service.tasks()["tasks"][0]
        self.assertEqual(after["status"], "completed")
        self.assertEqual(after["resultText"], completed["resultText"])
        self.assertEqual(after["completionEventId"], completed["completionEventId"])
        restored = WorkService(self.config, bridge=self.bridge)
        self.assertEqual(restored.tasks()["tasks"][0]["status"], "completed")

    def test_actual_phone_project_reference_reads_seeded_result_without_submit(self):
        task = self.submit(); self.finish(task)
        before = len(self.bridge.submissions())
        text = "odczytaj ostatni wynik tego projektu i podaj jeden następny krok, nie uruchamiaj nowej pracy"
        session = self.session(text, 400)
        self.assertIsNotNone(session.context.target, "anaphoric project reference must keep the selected target")
        self.assertEqual(session.context.target["projectId"], "roblox")
        self.assertEqual(session.context.action, "read")
        self.assertEqual({s["name"] for s in session.specs}, {"kritaqo_work_projects", "kritaqo_work_result"})
        result = session.call("kritaqo_work_result", {})
        self.assertTrue(result["success"])
        self.assertEqual(result["jobId"], task["jobId"])
        self.assertEqual(result["status"], "completed")
        self.assertIn("test telefonu", result["resultText"])
        self.assertEqual(len(self.bridge.submissions()), before)

    def test_anaphoric_conjunctions_preserve_selection_but_not_explicit_names(self):
        self.select()
        for n, text in enumerate(("Odczytaj wynik tego projektu oraz podaj następny krok", "Odczytaj wynik wybranego projektu a potem podaj ograniczenia", "Odczytaj wynik obecnego projektu i podaj datę", "Odczytaj wynik tego projektu oraz następnie powiedz datę", "Odczytaj wynik tego projektu"), 410):
            with self.subTest(text=text):
                session = self.session(text, n)
                self.assertEqual(session.context.target["projectId"], "roblox")
                self.assertEqual(session.context.action, "read")
        for n, text in enumerate(("Przygotuj test w projekcie Minecraft", "Przygotuj test tego projektu Minecraft", "Przygotuj test w innym projekcie", 'Przygotuj test tego projektu "i"', "Przygotuj test tego projektu o nazwie i", "Przygotuj test tego projektu i w projekcie Minecraft", "Przygotuj test tego projektu i Minecraft", "Przygotuj test tego projektu i projektu X3-5z", "Przygotuj test Robloxa", "Przygotuj test Roblox na NIEZNANYM"), 420):
            with self.subTest(text=text):
                session = self.session(text, n)
                self.assertIsNone(session.context.target)
                self.assertNotIn("kritaqo_work_submit", [s["name"] for s in session.specs])
                self.assertEqual(self.service.selected()[0]["projectId"], "roblox")
        self.assertEqual(self.bridge.submissions(), [])


if __name__ == "__main__": unittest.main()
