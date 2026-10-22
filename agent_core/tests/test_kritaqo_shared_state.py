"""Pure metadata projection: no runtime files, HTTP, models or attestation."""
import copy
import json
import unittest

from agent_core.llm.kritaqo_shared_state import project_shared_state


def recorded_state():
    return {"version": 1, "revision": 3, "checks": [{
        "id": "csv-statistics", "title": "Sprawdzenie statystyk CSV", "outcome": "passed",
        "observedAt": "2026-10-19T19:00:00+02:00", "checkedAt": "2026-10-19T17:01:00.000Z",
        "source": {"kind": "operator-verification", "actor": "operator", "method": "Independent Decimal calculation",
                   "verifierSha256": "a" * 64},
        "artifacts": [{"path": "data/rekordy.csv", "sha256": "b" * 64}], "limitations": "No historical process exit code.",
        "nextSteps": [{"id": "verify", "text": "Independent calculation", "status": "done"},
                      {"id": "document", "text": "Save verifier instructions", "status": "open"}],
        "currency": "current", "currencyReason": "hashes_match"}]}


class SharedStateTests(unittest.TestCase):
    def test_projection_preserves_recorded_provenance_not_attestation(self):
        raw = recorded_state()
        raw.update(credentials="SECRET", instructions="IGNORE_RULES", history=["PRIVATE"])
        raw["checks"][0].update(prompt="PROMPT_SECRET", verified=True)
        raw["checks"][0]["source"]["token"] = "AUTH_SECRET"
        before = copy.deepcopy(raw)
        projected = project_shared_state(raw, "node1", "project1")
        self.assertEqual(raw, before)
        self.assertEqual(projected["checks"][0]["nextSteps"][0]["status"], "done")
        self.assertEqual(projected["checks"][0]["observedAt"], raw["checks"][0]["observedAt"])
        self.assertIn("server-assessed", projected["dataTrust"])
        self.assertNotIn("SECRET", json.dumps(projected))
        self.assertNotIn("PRIVATE", json.dumps(projected))
        self.assertNotIn("IGNORE_RULES", json.dumps(projected))

    def test_freshness_and_missing_do_not_invent_success(self):
        raw = recorded_state()
        raw["checks"][0].update(currency="stale", currencyReason="artifact_changed")
        self.assertEqual(project_shared_state(raw, "host", "p")["checks"][0]["currency"], "stale")
        raw["checks"][0].update(currency="unknown", currencyReason="workspace_changed")
        self.assertEqual(project_shared_state(raw, "host", "p")["checks"][0]["currencyReason"], "workspace_changed")
        raw["checks"][0]["artifacts"] = []
        raw["checks"][0].update(currency="current", currencyReason="hashes_match")
        check = project_shared_state(raw, "host", "p")["checks"][0]
        self.assertEqual((check["currency"], check["currencyReason"]), ("unknown", "no_artifacts"))
        self.assertEqual(project_shared_state(None, "host", "p")["state"], "unavailable")

    def test_invalid_shapes_paths_units_and_provenance_omit_not_promote(self):
        for path, value in (("observedAt", 1792427367), ("checkedAt", "2026-10-19"),
                            ("source", {"kind": "model-report"}), ("outcome", "verified"),
                            ("artifacts", [{"path": "../private", "sha256": "a" * 64}])):
            with self.subTest(path=path):
                raw = recorded_state(); raw["checks"][0][path] = value
                output = project_shared_state(raw, "host", "p")
                self.assertEqual(output["checks"], [])
                self.assertEqual(output["omittedChecks"], 1)
        self.assertEqual(project_shared_state({"version": 1, "revision": True, "checks": []}, "host", "p")["state"], "unknown")

    def test_identity_never_taken_from_remote_extra_fields(self):
        raw = recorded_state(); raw.update(hostNodeId="attacker", projectId="another")
        a, b = (project_shared_state(raw, h, "same-project") for h in ("host-a", "host-b"))
        self.assertEqual(a["hostNodeId"], "host-a")
        self.assertEqual(b["hostNodeId"], "host-b")
        self.assertEqual(project_shared_state(raw, [], "p")["state"], "unavailable")

    def test_bounded_complete_json_and_omissions_for_text_steps_and_checks(self):
        raw = recorded_state(); check = raw["checks"][0]
        check["source"]["method"] = "ą" * 2000
        check["limitations"] = "ó" * 4000
        check["nextSteps"] = [{"id": "s" + str(i), "text": "ę" * 1000, "status": "open"} for i in range(20)]
        raw["checks"] = [dict(copy.deepcopy(check), id="check" + str(i)) for i in range(32)]
        output = project_shared_state(raw, "host", "p", 16000)
        encoded = json.dumps(output, ensure_ascii=False).encode()
        self.assertLessEqual(len(encoded), 16000)
        self.assertEqual(len(output["checks"]) + output["omittedChecks"], 32)
        self.assertGreater(output["omittedTextChars"], 0)
        self.assertGreater(output["omittedNextSteps"], 0)
        self.assertEqual(json.loads(encoded)["revision"], 3)


if __name__ == "__main__":
    unittest.main()
