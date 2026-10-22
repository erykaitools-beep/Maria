"""Offline stdlib contracts: fake HTTP only, no models or runtime data."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("portfolio_subject", Path(__file__).resolve().parents[1] / "llm/kritaqo_portfolio_client.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def provider():
    return {"id": "fixture", "authenticated": True, "models": [{"id": "fake"}],
            "capabilities": {"existingWorkspace": True, "readOnlyExecution": True, "execution": True}}


def view(project):
    return {"project": {"id": project, "name": project}, "messages": [], "jobs": [], "busy": False,
            "execution": {"allowed": True, "readOnlyAllowed": True, "readOnlySupported": True, "workspaceRevision": 1},
            "preferences": {"master": {"providerId": "fixture", "model": "fake"}}, "providers": [provider()]}


class FakeServer:
    def __init__(self):
        self.calls = []
        self.hub = {"protocol": "kritaqo-project-hub-v1", "local": {"id": "local", "name": "Mini", "projects": [{"id": "local-project", "name": "Local"}]},
                    "peers": [{"id": "peer", "nodeId": "remote", "name": "Laptop", "work": True, "status": "online", "lastSeen": 1,
                               "projects": [{"id": "remote-project", "name": "Remote"}]}]}
        self.local = {"projects": [{"id": "local-project", "name": "Local", "workspace": {"revision": 1}}],
                      "messages": [], "jobs": [], "busy": False, "preferences": {"master": {"providerId": "fixture", "model": "fake"}}, "providers": [provider()]}
        self.views = {"remote-project": view("remote-project")}
        self.fail_view = self.fail_send = self.fail_logout = False
        self.before = None
        self.bad_node = self.bad_project = False
        self.auth_calls = 0
        self.files = {}

    def factory(self, record):
        server = self
        class Client:
            cookie = None
            def request(self, method, route, payload=None, capture_cookie=False):
                payload = payload or {}
                server.calls.append((method, route, copy.deepcopy(payload)))
                if server.before:
                    server.before(method, route, payload)
                if route == "/api/control":
                    result = {"application": "kritaqo", "pid": 17, "version": "test"}
                    if payload["action"] == "desktop-ticket":
                        result["ticket"] = "a" * 64
                    return result
                if route == "/api/desktop-pair":
                    server.auth_calls += 1
                    self.cookie = "fixture-cookie"
                    return {"paired": True}
                if route == "/api/logout":
                    return {"loggedOut": not server.fail_logout}
                if route == "/api/hub/refresh":
                    return copy.deepcopy(server.hub)
                if route == "/api/state":
                    return copy.deepcopy(server.local)
                if method == "GET" and route.startswith("/api/projects/") and route.endswith("/files"):
                    project_id = route.split("/")[3]
                    project = next(x for x in server.local["projects"] if x["id"] == project_id)
                    if "workspace" in project:
                        raise p.PortfolioError("request_rejected")
                    result = server.files.get(project_id, {"files": [], "limit": 100})
                    if isinstance(result, Exception):
                        raise result
                    return copy.deepcopy(result)
                if route == "/api/hub/remote":
                    project = payload["payload"]["projectId"]
                    if payload["action"] == "view":
                        if server.fail_view:
                            raise p.PortfolioError("transport_unavailable")
                        result = copy.deepcopy(server.views[project])
                        if server.bad_project:
                            result["project"]["id"] = "other"
                    else:
                        if server.fail_send:
                            raise TimeoutError("SECRET exception content")
                        result = server.send(payload["payload"], server.views[project]["jobs"])
                    return {"protocol": "kritaqo-project-hub-v1", "nodeId": "wrong" if server.bad_node else "remote", **result}
                if route == "/api/jobs":
                    return {"job": server.send(payload, server.local["jobs"], raw=True), "reused": False}
                raise AssertionError("unexpected route")
        return Client()

    def send(self, payload, jobs, raw=False):
        assert payload["text"] == p._PROMPT
        assert not payload["execution"] or payload["executionMode"] == "read-only"
        job = {"id": "job-" + str(len(jobs)), "requestId": payload["requestId"], "projectId": payload["projectId"],
               "status": "running", "executionMode": payload.get("executionMode"), "steps": [], "createdAt": 42}
        jobs.append(job)
        return copy.deepcopy(job) if raw else {"jobId": job["id"], "requestId": job["requestId"], "projectId": job["projectId"], "executionMode": job["executionMode"]}

    def sends(self):
        return [c for c in self.calls if c[1] == "/api/jobs" or c[1] == "/api/hub/remote" and c[2]["action"] == "send"]


class PortfolioTests(unittest.TestCase):
    def test_shared_checks_fresh_host_identity_status_and_absent_compatibility(self):
        from agent_core.tests.test_kritaqo_shared_state import recorded_state
        self.server.local["projects"][0]["sharedState"] = recorded_state()
        self.server.views["remote-project"]["project"]["sharedState"] = recorded_state()
        reviewed = self.client.review()
        self.assertTrue(reviewed["success"])
        local, remote = reviewed["projects"]
        self.assertEqual((local["sharedState"]["hostNodeId"], remote["sharedState"]["hostNodeId"]), ("local", "remote"))
        self.assertEqual(local["sharedState"]["checks"][0]["currency"], "current")
        state = self.server.local["projects"][0]["sharedState"]
        state["revision"] = 4
        state["checks"][0].update(currency="stale", currencyReason="artifact_changed")
        del self.server.views["remote-project"]["project"]["sharedState"]
        current = self.client.status()
        self.assertEqual(current["projects"][0]["sharedState"]["revision"], 4)
        self.assertEqual(current["projects"][0]["sharedState"]["checks"][0]["currency"], "stale")
        self.assertEqual(current["projects"][1]["sharedState"]["state"], "unavailable")
        self.assertEqual(self.server.sends(), [])

    def test_offline_peer_does_not_promote_cached_checks(self):
        from agent_core.tests.test_kritaqo_shared_state import recorded_state
        peer = self.server.hub["peers"][0]
        peer.update(status="offline")
        peer["projects"][0]["sharedState"] = recorded_state()
        output = self.client.review()["projects"][1]
        self.assertEqual(output["sharedState"]["state"], "unavailable")
        self.assertEqual(output["sharedState"]["checks"], [])

    def test_shared_checks_keep_explicit_analysis_prompt_and_receipt_payload_unchanged(self):
        from agent_core.tests.test_kritaqo_shared_state import recorded_state
        self.server.local["projects"][0]["sharedState"] = recorded_state()
        original_prompt = p._PROMPT
        output = self.client.analyze("newanalysis" * 3)
        self.assertTrue(output["success"])
        self.assertEqual(output["projects"][0]["sharedState"]["checks"][0]["outcome"], "passed")
        self.assertEqual(len(self.server.sends()), 2)
        for job in self.state()["batches"][-1]["jobs"]:
            self.assertEqual(job["payload"]["text"], original_prompt)
            self.assertNotIn("sharedState", job["payload"])
            self.assertNotIn("csv-statistics", json.dumps(job["payload"]))

    def test_total_output_drops_whole_shared_checks_with_explicit_omissions(self):
        from agent_core.tests.test_kritaqo_shared_state import recorded_state
        from agent_core.llm.kritaqo_shared_state import project_shared_state
        projects = []
        for n in range(64):
            raw = recorded_state()
            raw["checks"][0]["limitations"] = "ą" * 4000
            raw["checks"][0]["source"]["method"] = "ó" * 2000
            raw["checks"] = [dict(copy.deepcopy(raw["checks"][0]), id="check" + str(i)) for i in range(3)]
            projects.append({"messages": [], "latestJobs": [], "sharedState": project_shared_state(raw, "host", "p" + str(n), 16000)})
        report = {"projects": projects, "coverage": {}}
        p.PortfolioClient._bound_output(report)
        self.assertLessEqual(len(json.dumps(report, ensure_ascii=False).encode()), 220000)
        self.assertGreater(sum(project["sharedState"]["omittedChecks"] for project in projects), 0)
        for project in projects:
            shared = project["sharedState"]
            self.assertEqual(len(shared["checks"]) + shared["omittedChecks"], 3)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state_dir = root / "private"
        self.state_dir.mkdir(mode=0o700)
        self.config = {"data_dir": str(root / "data"), "bridge_path": str(root / "bridge.py"), "state_dir": str(self.state_dir), "project_id": "ignored"}
        self.server = FakeServer()
        self.client = self.make()

    def make(self, **kwargs):
        return p.PortfolioClient(self.config, client_factory=self.server.factory,
                                 record_reader=lambda _: {"pid": 17, "version": "test", "port": 1, "token": "never-output"}, **kwargs)

    def state(self):
        return json.loads((self.state_dir / "portfolio/receipts.json").read_text())

    def managed_project(self):
        self.server.local["projects"][0].pop("workspace", None)
        self.server.files["local-project"] = {"files": [
            {"path": "projekt_testowy_x3_5z/plik%d.txt" % n, "size": 10 + n, "modifiedAt": 1234.5, "downloadable": True}
            for n in range(4)], "limit": 100}

    def test_managed_actual_listing_shape_plans_readonly_without_revision(self):
        self.managed_project()
        out = self.client.analyze("managed" * 4)
        self.assertTrue(out["success"], out)
        metadata = out["projects"][0]["managedFiles"]
        self.assertEqual(metadata["state"], "available")
        self.assertEqual(metadata["listedFiles"], 4)
        self.assertFalse(metadata["contentRead"])
        self.assertFalse(metadata["completeListing"])
        self.assertFalse(out["projects"][0]["filesInspected"])
        local_send = self.server.sends()[0][2]
        self.assertTrue(local_send["execution"])
        self.assertEqual(local_send["executionMode"], "read-only")
        self.assertNotIn("workspaceRevision", local_send)
        self.assertNotIn("cwd", local_send)
        self.assertEqual(out["analysis"]["jobs"][0]["fileAssessment"], "managed-read-only")
        metadata_calls = [c for c in self.server.calls if c[1] == "/api/projects/local-project/files"]
        self.assertEqual(len(metadata_calls), 2)  # Review and last pre-dispatch check.
        self.assertTrue(all(c[0] == "GET" and "?" not in c[1] for c in metadata_calls))
        self.assertTrue(self.make().status()["success"])  # New receipt variant roundtrips.

    def test_managed_empty_invalid_and_failed_listing_never_enables_execution(self):
        cases = [
            {"files": [], "limit": 100},
            {"files": "not a list", "limit": 100},
            {"files": [{"path": "../escape", "size": 1, "modifiedAt": 1, "downloadable": True}], "limit": 100},
            {"files": [{"path": "C:\\private", "size": 1, "modifiedAt": 1, "downloadable": True}], "limit": 100},
            {"files": [{"path": "good", "size": True, "modifiedAt": 1, "downloadable": True}], "limit": 100},
            {"files": [{"path": "good", "size": 1, "modifiedAt": float("nan"), "downloadable": True}], "limit": 100},
            p.PortfolioError("transport_unavailable"),
            RuntimeError("SECRET metadata transport exception"),
        ]
        for n, listing in enumerate(cases):
            with self.subTest(case=n):
                self.managed_project()
                self.server.files["local-project"] = listing
                out = self.client.analyze("%032x" % (5000 + n))
                self.assertTrue(out["success"], out)
                payload = self.state()["batches"][-1]["jobs"][0]["payload"]
                self.assertFalse(payload["execution"])
                self.assertNotIn("executionMode", payload)
                self.assertNotEqual(out["projects"][0]["managedFiles"]["state"], "available")
                self.assertNotIn("SECRET", json.dumps(out))
                for job in self.server.local["jobs"] + self.server.views["remote-project"]["jobs"]:
                    job["status"] = "completed"
                self.client.status()

    def test_bound_projects_never_probe_managed_metadata_and_keep_old_receipts(self):
        self.client.analyze("bound" * 4)
        self.assertFalse([c for c in self.server.calls if c[1].startswith("/api/projects/")])
        self.assertEqual(self.server.sends()[0][2]["workspaceRevision"], 1)
        self.assertTrue(self.make().status()["success"])

    def test_managed_requires_both_execution_and_readonly_capabilities(self):
        self.managed_project()
        caps = self.server.local["providers"][0]["capabilities"]
        for n, missing in enumerate(("execution", "readOnlyExecution")):
            with self.subTest(missing=missing):
                caps.update(execution=True, readOnlyExecution=True)
                caps[missing] = False
                out = self.client.analyze("%032x" % (5100 + n))
                self.assertTrue(out["success"], out)
                self.assertFalse(self.state()["batches"][-1]["jobs"][0]["payload"]["execution"])
                for job in self.server.local["jobs"] + self.server.views["remote-project"]["jobs"]:
                    job["status"] = "completed"
                self.client.status()

    def test_remote_unbound_never_uses_local_managed_metadata(self):
        self.managed_project()
        self.server.views["remote-project"]["execution"].update(allowed=False, readOnlyAllowed=False, workspaceRevision=None)
        out = self.client.analyze("remote" * 4)
        self.assertTrue(out["success"])
        remote = self.server.sends()[1][2]["payload"]
        self.assertFalse(remote["execution"])
        self.assertFalse([c for c in self.server.calls if c[1] == "/api/projects/remote-project/files"])

    def test_queued_managed_file_loss_blocks_instead_of_sending(self):
        self.managed_project()
        self.server.local["busy"] = True
        self.client.analyze("waiting" * 4)
        self.assertEqual(len(self.server.sends()), 1)
        self.server.local["busy"] = False
        self.server.files["local-project"] = {"files": [], "limit": 100}
        out = self.client.status()
        self.assertEqual(out["analysis"]["jobs"][0]["state"], "blocked")
        self.assertEqual(out["analysis"]["jobs"][0]["reason"], "read_only_access_changed")
        self.assertEqual(len(self.server.sends()), 1)

    def test_binding_appears_between_listing_and_send_managed_job_is_blocked(self):
        self.managed_project()
        calls = []
        def bind_on_recheck(method, route, payload):
            if route == "/api/projects/local-project/files":
                calls.append(route)
                if len(calls) == 2:
                    self.server.local["projects"][0]["workspace"] = {"revision": 1}
        self.server.before = bind_on_recheck
        out = self.client.analyze("race" * 8)
        self.assertTrue(out["success"])
        self.assertEqual(out["analysis"]["jobs"][0]["state"], "blocked")
        self.assertFalse([c for c in self.server.sends() if c[1] == "/api/jobs"])

    def test_managed_route_allowlist_never_accepts_content_queries_or_other_methods(self):
        client = p._HttpClient({"port": 0})
        for method, route in (("GET", "/api/projects/x/files?path=secret"),
                              ("POST", "/api/projects/x/files"), ("GET", "/api/projects/../files"),
                              ("GET", "/api/projects/x/files/secret")):
            with self.subTest(route=route, method=method):
                with self.assertRaisesRegex(p.PortfolioError, "route_denied"):
                    client.request(method, route)
        with self.assertRaisesRegex(p.PortfolioError, "daemon_unverified"):
            client.request("GET", "/api/projects/x/files")  # Exact path admitted; invalid port blocks before network.

    def test_constructor_no_io_and_review_real_contract_shape(self):
        self.assertFalse((self.state_dir / "portfolio").exists())
        out = self.client.review()
        self.assertTrue(out["success"])
        self.assertEqual(out["state"], "complete")
        self.assertEqual(out["coverage"]["registeredProjects"], 2)
        self.assertEqual(out["coverage"]["freshProjects"], 2)
        self.assertFalse(any(x["filesInspected"] for x in out["projects"]))
        self.assertFalse(self.server.sends())
        self.assertEqual(self.server.calls[-1][1], "/api/logout")
        self.assertFalse(self.state()["cleanup_uncertain"])
        self.assertEqual([x["hostName"] for x in out["projects"]], ["Mini", "Laptop"])

    def test_projection_excludes_credentials_and_bounds_text(self):
        v = self.server.views["remote-project"]
        v["messages"] = [{"role": "assistant", "text": "x" * 2500, "at": 2, "credentials": "LEAK"} for _ in range(10)]
        v["credentials"] = "LEAK"
        v["jobs"] = [{"id": "j", "status": "completed", "steps": [{"role": "master", "result": {"text": "y" * 3000, "token": "LEAK"}}], "prompt": "LEAK"}]
        out = self.client.review(); remote = out["projects"][1]
        self.assertNotIn("LEAK", json.dumps(out))
        self.assertLessEqual(len(remote["messages"]), 6)
        self.assertLessEqual(len(remote["messages"][0]["text"]), 1200)
        self.assertEqual(remote["omittedMessages"], 4)
        self.assertTrue(remote["latestJobs"][0]["resultTruncated"])

    def test_single_long_message_reports_initial_and_later_budget_omissions(self):
        self.server.views["remote-project"]["messages"] = [{"role": "assistant", "text": "x" * 5000, "at": 9}]
        out = self.client.review()
        project = out["projects"][1]
        message = project["messages"][0]
        self.assertEqual(len(message["text"]), 1200)
        self.assertTrue(message["textTruncated"])
        self.assertEqual(message["omittedTextChars"], 3800)
        self.assertTrue(project["historyTruncated"])
        self.assertEqual(project["omittedTextChars"], 3800)
        self.assertEqual(project["omittedMessages"], 0)
        self.assertEqual(out["coverage"]["omittedTextChars"], 3800)
        self.client._bound_project_text(project, 1000)
        self.assertEqual(len(message["text"]), 1000)
        self.assertEqual(message["omittedTextChars"], 4000)
        self.assertEqual(project["omittedTextChars"], 4000)

    def test_offline_and_wrong_identity_never_live(self):
        for attr in ("fail_view", "bad_node", "bad_project"):
            setattr(self.server, attr, True)
            out = self.client.review()
            self.assertEqual(out["state"], "partial")
            self.assertEqual(out["projects"][1]["source"], "cached-unverified")
            self.assertEqual(out["projects"][1]["messages"], [])
            setattr(self.server, attr, False)

    def test_logout_failure_latches_new_instance(self):
        self.server.fail_logout = True
        self.assertEqual(self.client.review()["reason"], "cleanup_uncertain")
        self.server.fail_logout = False
        self.assertEqual(self.make().review()["reason"], "cleanup_uncertain")
        self.assertEqual(self.server.auth_calls, 1)

    def test_cancel_after_pair_still_logs_out(self):
        stop = threading.Event()
        self.server.before = lambda m, r, body: stop.set() if r == "/api/desktop-pair" else None
        self.assertEqual(self.client.review(cancelled=stop)["reason"], "cancelled")
        self.assertEqual(self.server.calls[-1][1], "/api/logout")
        self.assertFalse(self.state()["cleanup_uncertain"])

    def test_pre_cancel_no_auth(self):
        stop = threading.Event(); stop.set()
        self.assertEqual(self.client.review(cancelled=stop)["reason"], "cancelled")
        self.assertFalse(self.server.calls)

    def test_durable_before_send_retry_same_id_never_resends(self):
        def before(method, route, payload):
            if route == "/api/jobs" or route == "/api/hub/remote" and payload["action"] == "send":
                request = payload.get("payload", payload)["requestId"]
                job = next(j for b in self.state()["batches"] for j in b["jobs"] if j["requestId"] == request)
                self.assertEqual(job["state"], "unknown")
        self.server.before = before
        out = self.client.analyze("a" * 32)
        self.assertEqual(len(self.server.sends()), 2)
        self.assertEqual({j["source"] for j in out["analysis"]["jobs"]}, {"read-only-agent"})
        self.make().analyze("a" * 32)
        self.assertEqual(len(self.server.sends()), 2)

    def test_unknown_send_never_duplicate_and_blocks_new_batch(self):
        self.server.fail_send = True
        self.assertEqual(self.client.analyze("b" * 32)["analysis"]["jobs"][1]["state"], "unknown")
        count = len(self.server.sends()); self.server.fail_send = False
        self.client.status(); self.client.analyze("b" * 32)
        self.assertEqual(len(self.server.sends()), count)
        self.assertEqual(self.client.analyze("c" * 32)["reason"], "previous_batch_pending_or_unknown")

    def test_refetch_changed_result_and_reject_mode_or_request_mismatch(self):
        self.client.analyze("d" * 32)
        job = self.server.views["remote-project"]["jobs"][0]
        job.update(status="completed", steps=[{"role": "master", "result": {"text": "Fresh A"}}])
        self.assertEqual(self.client.status()["analysis"]["jobs"][1]["untrustedResult"], "Fresh A")
        job["steps"][0]["result"]["text"] = "Fresh B"
        self.assertEqual(self.client.status()["analysis"]["jobs"][1]["untrustedResult"], "Fresh B")
        job["executionMode"] = "workspace-write"
        self.assertEqual(self.client.status()["reason"], "execution_mode_unverified")
        job["executionMode"] = "read-only"; job["requestId"] = "other"
        self.assertEqual(self.client.status()["reason"], "job_correlation_failed")

    def test_unicode_analysis_results_have_byte_budget_and_explicit_truncation(self):
        self.client.analyze("u" * 32)
        for job in self.server.local["jobs"] + self.server.views["remote-project"]["jobs"]:
            job.update(status="completed", steps=[{"role": "master", "result": {"text": "\U0001f7e2" * 5000}}])
        out = self.client.status()
        self.assertTrue(out["success"])
        self.assertLessEqual(sum(len(j["untrustedResult"].encode()) for j in out["analysis"]["jobs"]), 32000)
        self.assertTrue(all(j["resultTruncated"] for j in out["analysis"]["jobs"]))
        encoded = json.dumps(out, ensure_ascii=False).encode()
        self.assertLessEqual(len(encoded), 220000)
        self.assertEqual(len(json.loads(encoded)["analysis"]["jobs"]), 2)

    def test_combined_large_unicode_report_stays_whole_bounded_json(self):
        project = {"hostNodeId": "h" * 100, "peerId": "p" * 100, "projectId": "x" * 100,
                   "name": "\U0001f7e2" * 80, "hostName": "\U0001f7e2" * 80,
                   "messages": [{"text": "\U0001f7e2" * 1200} for _ in range(6)],
                   "latestJobs": [{"jobId": "j" * 100, "state": "completed", "untrustedResult": "\U0001f7e2" * 2000} for _ in range(4)]}
        report = {"projects": [copy.deepcopy(project) for _ in range(64)], "coverage": {},
                  "analysis": {"jobs": [{"jobId": "j" * 100, "untrustedResult": "\U0001f7e2" * 4000} for _ in range(64)]}}
        self.client._bound_output(report)
        raw = json.dumps(report, ensure_ascii=False).encode()
        self.assertLessEqual(len(raw), 220000)
        self.assertEqual(len(json.loads(raw)["projects"]), 64)
        self.assertGreater(report["coverage"]["outputOmittedTextBytes"], 0)

    def test_old_peer_and_absent_grant_text_only_no_unknown_flag(self):
        del self.server.views["remote-project"]["execution"]["readOnlySupported"]
        out = self.client.analyze("f" * 32)
        payload = self.server.sends()[1][2]["payload"]
        self.assertFalse(payload["execution"])
        self.assertNotIn("executionMode", payload)
        self.assertEqual(out["analysis"]["jobs"][1]["source"], "conversation-and-reports")
        self.assertEqual(out["analysis"]["jobs"][1]["fileAssessment"], "update-needed")

    def test_real_old_peer_receipt_unknown_then_correlated_status_no_resend(self):
        del self.server.views["remote-project"]["execution"]["readOnlySupported"]
        send = self.server.send
        def old_send(payload, jobs, raw=False):
            result = send(payload, jobs, raw=raw)
            return result if raw else {"jobId": result["jobId"], "reused": False}
        self.server.send = old_send
        out = self.client.analyze("o" * 32)
        self.assertEqual(out["analysis"]["jobs"][1]["state"], "unknown")
        count = len(self.server.sends())
        out = self.client.status()
        self.assertEqual(out["analysis"]["jobs"][1]["state"], "running")
        self.assertEqual(len(self.server.sends()), count)

    def test_pending_access_failure_blocks_only_affected_job(self):
        self.server.local["busy"] = True
        self.server.views["remote-project"]["busy"] = True
        self.client.analyze("j" * 32)
        self.server.local["busy"] = False
        self.server.local["providers"] = []
        self.server.views["remote-project"]["busy"] = False
        out = self.client.status()
        self.assertTrue(out["success"])
        self.assertEqual(out["analysis"]["jobs"][0]["state"], "blocked")
        self.assertEqual(out["analysis"]["jobs"][1]["state"], "accepted")
        self.assertEqual(len(self.server.sends()), 1)

    def test_terminal_batches_prune_but_retired_identity_never_replays(self):
        first = None
        for n in range(17):
            out = self.client.analyze("%032x" % (100 + n))
            self.assertTrue(out["success"], out)
            first = first or out["analysis"]["batchId"]
            for job in self.server.local["jobs"] + self.server.views["remote-project"]["jobs"]:
                job["status"] = "completed"
            self.assertTrue(self.client.status()["success"])
        self.assertEqual(len(self.state()["batches"]), 16)
        self.assertIn(first, self.state()["retiredBatches"])
        before = len(self.server.sends())
        self.assertEqual(self.client.analyze("%032x" % 100)["reason"], "batch_retired")
        self.assertEqual(len(self.server.sends()), before)

    def test_bounded_coverage_and_shared_total_text_budget(self):
        self.server.hub["peers"] = []
        for n in range(2):
            entries = [{"id": "p%d-%d" % (n, i), "name": "P"} for i in range(40)]
            self.server.hub["peers"].append({"id": "peer%d" % n, "nodeId": "remote", "work": True, "projects": entries})
            for entry in entries:
                v = view(entry["id"])
                v["messages"] = [{"role": "assistant", "text": "x" * 1200} for _ in range(6)]
                self.server.views[entry["id"]] = v
        out = self.client.review()
        self.assertEqual(out["coverage"]["registeredProjects"], 81)
        self.assertEqual(out["coverage"]["omittedProjects"], 17)
        self.assertEqual(len(out["projects"]), 64)
        text = sum(len(m["text"]) for proj in out["projects"] for m in proj["messages"])
        self.assertLessEqual(text, 64000)
        self.assertGreater(out["coverage"]["omittedTextChars"], 0)
        self.assertEqual(out["state"], "partial")

    def test_cancel_during_view_still_logout_no_dispatch(self):
        stop = threading.Event()
        self.server.before = lambda m, r, body: stop.set() if r == "/api/hub/remote" else None
        self.assertEqual(self.client.analyze("k" * 32, cancelled=stop)["reason"], "cancelled")
        self.assertFalse(self.server.sends())
        self.assertEqual(self.server.calls[-1][1], "/api/logout")

    def test_malformed_pair_after_cookie_logs_out(self):
        factory = self.server.factory
        def bad_pair(record):
            client = factory(record)
            request = client.request
            def wrapped(method, route, payload=None, **kwargs):
                result = request(method, route, payload, **kwargs)
                return {} if route == "/api/desktop-pair" else result
            client.request = wrapped
            return client
        self.client._factory = bad_pair
        self.assertEqual(self.client.review()["reason"], "authentication_failed")
        self.assertEqual(self.server.calls[-1][1], "/api/logout")
        self.assertFalse(self.state()["cleanup_uncertain"])

    def test_http_redirect_and_timeout_not_followed_or_leaked(self):
        calls = []
        class Response:
            status = 302
            def getheader(self, name, default=""):
                return "application/json"
            def getheaders(self):
                return []
        class Conn:
            sock = None
            def __init__(self, host, port, **kwargs):
                calls.append((host, port))
                self.timeout = kwargs["timeout"]
            def request(self, *args):
                pass
            def getresponse(self):
                return Response()
            def close(self):
                pass
        with patch.object(p.http.client, "HTTPConnection", Conn):
            with self.assertRaisesRegex(p.PortfolioError, "request_rejected"):
                p._HttpClient({"port": 8766}).request("GET", "/api/state")
        self.assertEqual(calls, [("127.0.0.1", 8766)])
        observed = []
        original_init = Conn.__init__
        def capture_timeout(conn, *args, **kwargs):
            original_init(conn, *args, **kwargs)
            observed.append(conn.timeout)
        with patch.object(p.http.client, "HTTPConnection", Conn), patch.object(Conn, "__init__", capture_timeout):
            with self.assertRaises(p.PortfolioError):
                p._HttpClient({"port": 8766}).request("POST", "/api/hub/refresh", {})
        self.assertGreaterEqual(observed[0], 8)
        def timeout(*args, **kwargs):
            raise TimeoutError("CREDENTIAL_SECRET")
        with patch.object(p.http.client, "HTTPConnection", Conn), patch.object(Conn, "request", timeout):
            with self.assertRaisesRegex(p.PortfolioError, "transport_unavailable"):
                p._HttpClient({"port": 8766}).request("GET", "/api/state")

    def test_revision_changes_block_pending(self):
        self.server.local["busy"] = True
        self.client.analyze("h" * 32)
        self.server.local["busy"] = False
        self.server.local["projects"][0]["workspace"]["revision"] = 2
        self.assertEqual(self.client.status()["analysis"]["jobs"][0]["state"], "blocked")
        self.assertEqual(len(self.server.sends()), 1)

    def test_queue_one_job_per_host_advances_on_status(self):
        self.server.hub["peers"][0]["projects"].append({"id": "second", "name": "Second"})
        self.server.views["second"] = view("second")
        self.assertEqual(self.client.analyze("i" * 32)["analysis"]["pending"], 1)
        self.assertEqual(len(self.server.sends()), 2)
        self.client.status(); self.assertEqual(len(self.server.sends()), 2)
        self.server.views["remote-project"]["jobs"][0]["status"] = "completed"
        self.assertEqual(self.client.status()["analysis"]["pending"], 0)
        self.assertEqual(len(self.server.sends()), 3)

    def test_fresh_offline_catalog_skips_all_views_for_that_peer(self):
        self.server.hub["peers"][0]["status"] = "offline"
        out = self.client.review()
        self.assertEqual(out["coverage"]["cachedProjects"], 1)
        self.assertEqual(out["projects"][1]["reason"], "peer_offline")
        self.assertFalse([c for c in self.server.calls if c[1] == "/api/hub/remote"])

    def test_background_step_drains_only_persisted_authorized_queue(self):
        self.server.hub["peers"][0]["projects"].append({"id": "second", "name": "Second"})
        self.server.views["second"] = view("second")
        out = self.client.analyze("w" * 32)
        batch_id = out["analysis"]["batchId"]
        self.server.views["remote-project"]["jobs"][0]["status"] = "completed"
        self.server.local["jobs"][0]["status"] = "completed"
        self.assertTrue(self.client._drain_step(batch_id))
        self.assertEqual(len(self.server.sends()), 3)
        self.server.views["second"]["jobs"][0]["status"] = "completed"
        self.assertFalse(self.client._drain_step(batch_id))
        self.assertEqual(self.state()["batches"][-1]["workerState"], "completed")
        self.assertEqual(len(self.state()["batches"]), 1)

    def test_background_unknown_and_cleanup_stop_without_retry(self):
        self.server.fail_send = True
        out = self.client.analyze("x" * 32)
        batch_id = out["analysis"]["batchId"]
        count = len(self.server.sends())
        self.assertFalse(self.client._drain_step(batch_id))
        self.assertEqual(self.state()["batches"][-1]["workerReason"], "unknown_send")
        self.assertEqual(len(self.server.sends()), count)
        self.server.fail_logout = True
        self.assertFalse(self.client._drain_step(batch_id))
        self.assertEqual(self.state()["batches"][-1]["workerReason"], "cleanup_uncertain")
        self.assertEqual(len(self.server.sends()), count)

    def test_background_timeout_is_persisted_no_network_or_real_sleep(self):
        out = self.client.analyze("y" * 32)
        batch_id = out["analysis"]["batchId"]
        clock = [0]
        self.client._clock = lambda: clock[0]
        class FakeStop:
            def wait(self, seconds):
                self_seconds = seconds
                assert self_seconds == 10
                clock[0] += 1800
                return False
        self.client._worker_stop = FakeStop()
        count = len(self.server.calls)
        self.client._background_loop(batch_id)
        self.assertEqual(len(self.server.calls), count)
        self.assertEqual(self.state()["batches"][-1]["workerReason"], "drain_timeout")

    def test_background_single_worker_and_close_blocks_future_calls(self):
        self.client._background = True
        created = []
        class FakeThread:
            def __init__(self, **kwargs):
                created.append(kwargs)
            def start(self):
                pass
        with patch.object(p.threading, "Thread", FakeThread):
            out = self.client.analyze("z" * 32)
            self.client.status()
        self.assertEqual(len(created), 1)
        self.assertEqual(out["analysis"]["workerState"], "running")
        count = len(self.server.calls)
        self.client.close()
        self.assertTrue(self.client._worker_stop.is_set())
        self.assertEqual(self.client.status()["reason"], "closed")
        self.assertEqual(len(self.server.calls), count)

    def test_worker_finalizer_hands_new_batch_over_after_terminal_run_unlocks(self):
        old = self.client.analyze("m" * 32)["analysis"]["batchId"]
        for job in self.server.local["jobs"] + self.server.views["remote-project"]["jobs"]:
            job["status"] = "completed"
        self.client._background = True
        self.client._worker_thread = object()
        self.client._worker_batch_id = old
        created, new_reports = [], []
        class FakeThread:
            def __init__(self, **kwargs):
                created.append(kwargs)
            def start(self):
                pass
        class FakeStop:
            def wait(self, seconds):
                return False
            def is_set(self):
                return False
        self.client._worker_stop = FakeStop()
        def interleaved_step(batch_id, deadline=None):
            # Old worker completed _run and released the shared lock. A new user
            # analyze arrives before its finally block clears _worker_thread.
            terminal = self.client._run("status", None, None, batch_id=batch_id)
            self.assertFalse(terminal["analysis"]["needsStatusCall"])
            new_reports.append(self.client.analyze("n" * 32))
            self.assertEqual(new_reports[-1]["analysis"]["workerState"], "scheduled")
            self.assertEqual(len(created), 0)
            return False
        with patch.object(self.client, "_drain_step", interleaved_step), patch.object(p.threading, "Thread", FakeThread):
            self.client._background_loop(old)
        new_batch = new_reports[0]["analysis"]["batchId"]
        self.assertNotEqual(new_batch, old)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["args"], (new_batch,))
        self.assertEqual(self.client._worker_batch_id, new_batch)
        self.assertIsNone(self.client._desired_batch_id)
        self.assertEqual(self.state()["batches"][-1]["workerState"], "running")

    def test_pending_peer_id_rebind_blocks_instead_of_wrong_host_send(self):
        self.server.views["remote-project"]["busy"] = True
        self.client.analyze("q" * 32)
        self.server.views["remote-project"]["busy"] = False
        self.server.hub["peers"][0]["id"] = "replacement"
        out = self.client.status()
        self.assertEqual(out["analysis"]["jobs"][1]["reason"], "peer_changed")
        self.assertEqual(len(self.server.sends()), 1)

    def test_symlink_state_rejected_and_routes_fixed(self):
        other = Path(self.tmp.name) / "other"; other.mkdir()
        (self.state_dir / "portfolio").symlink_to(other, target_is_directory=True)
        self.assertFalse(self.client.review()["success"])
        self.assertFalse(self.server.calls)
        with self.assertRaises(p.PortfolioError):
            p._HttpClient({"port": 0}).request("GET", "/api/state")
        with self.assertRaises(p.PortfolioError):
            p._HttpClient({"port": 1}).request("GET", "/arbitrary")


if __name__ == "__main__":
    unittest.main()
