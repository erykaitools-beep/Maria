"""Durable single-operator work cards; only known submissions are observed.

The bridge owns transport authentication and Kritaqo owns execution permissions.
No model is used here. Unknown sends are reconciled, never submitted again.
"""
import atexit
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import threading
import time

from agent_core.llm.kritaqo_shared_state import project_shared_state

_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
_STATES = _TERMINAL | {"accepted", "queued", "running", "unknown"}
_LOGGER = __import__("logging").getLogger(__name__)


class WorkError(ValueError):
    pass


def _need(ok, reason):
    if not ok:
        raise WorkError(reason)


def _id(value):
    _need(type(value) is str and _ID.fullmatch(value), "invalid_identity")
    return value


def _path(value):
    return (type(value) is str and 0 < len(value) <= 1024 and not value.startswith("/")
            and not any(c in value for c in "\\:\x00") and all(p not in {"", ".", ".."} for p in value.split("/")))


def project_key(node, project):
    return "project_" + hashlib.sha256((_id(node) + "\0" + _id(project)).encode()).hexdigest()


class WorkService:
    def __init__(self, config, *, bridge=None, clock=None, background=False):
        self.config = copy.deepcopy(config)
        self._clock = clock or time.time
        self._bridge = bridge or self._node_bridge
        self._background = background
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._observer_cursor = 0
        self._observation_versions = {}
        self._catalog = []
        self._catalog_at = 0
        self._catalog_error = None
        self._partial = True
        self._dir = Path(config["state_dir"]) / "work"
        self._dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        info = self._dir.lstat()
        _need(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077, "private_state_required")
        self._file = self._dir / "state.json"
        if self._file.exists():
            _need(not self._file.is_symlink() and self._file.stat().st_size <= 8 * 1024 * 1024, "state_invalid")
            state = json.loads(self._file.read_text())
            _need(type(state) is dict and state.get("version") == 1 and type(state.get("tasks")) is list
                  and len(state["tasks"]) <= 500 and type(state.get("selectionEpoch")) is int, "state_invalid")
            for task in state["tasks"]:
                _need(type(task) is dict and task.get("status") in _STATES and type(task.get("target")) is dict, "state_invalid")
                _id(task.get("key")); _id(task.get("requestId")); self._validate_target(task["target"])
            self._state = state
        else:
            self._state = {"version": 1, "selection": None, "selectionEpoch": 0, "tasks": []}
            self._import_legacy()
            self._save()

    def _validate_target(self, target):
        _need(type(target) is dict, "invalid_target")
        _id(target.get("hostNodeId")); _id(target.get("projectId"))
        if target.get("peerId") is not None:
            _id(target["peerId"])
        revision = target.get("workspaceRevision")
        _need(revision is None or type(revision) is int and 1 <= revision <= 9007199254740991, "invalid_revision")
        _need(target.get("key") == project_key(target["hostNodeId"], target["projectId"]), "invalid_target")

    def _save(self):
        # Retain newest report text first; identity/dedup records are never dropped.
        remaining = 2 * 1024 * 1024
        for task in reversed(self._state["tasks"]):
            text = task.get("resultText", "")
            raw_text = text.encode("utf-8")
            if len(raw_text) > remaining:
                task["resultText"] = raw_text[:remaining].decode("utf-8", errors="ignore")
                task["resultTruncated"] = True
            remaining -= len(task.get("resultText", "").encode("utf-8"))
        raw = json.dumps(self._state, ensure_ascii=False, allow_nan=False).encode()
        _need(len(raw) <= 8 * 1024 * 1024, "state_capacity")
        fd, name = tempfile.mkstemp(prefix=".work-", dir=self._dir)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.chmod(name, 0o600); os.replace(name, self._file)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _import_legacy(self):
        """Read-only baseline import. Historical completions never emit alerts."""
        path = Path(self.config["state_dir"]) / "receipts.json"
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
            return
        try:
            legacy = json.loads(path.read_text())
            target = {"key": project_key(self.config["host_node_id"], self.config["project_id"]),
                      "hostNodeId": self.config["host_node_id"], "projectId": self.config["project_id"],
                      "peerId": self.config["peer_id"], "workspaceRevision": self.config["workspace_revision"],
                      "name": self.config["project_name"], "computerName": self.config["computer_name"]}
            for interaction, receipt in list(legacy.get("receipts", {}).items())[-100:]:
                payload = receipt.get("payload", {})
                if receipt.get("state") not in _STATES or payload.get("projectId") != target["projectId"] or not receipt.get("jobId"):
                    continue
                _id(receipt["jobId"]); _id(payload["requestId"])
                self._state["tasks"].append({"key": "legacy_" + hashlib.sha256(interaction.encode()).hexdigest(),
                    "interactionId": interaction, "target": target.copy(), "requestId": payload["requestId"],
                    "prompt": str(payload.get("text", ""))[:12000], "jobId": receipt["jobId"],
                    "status": receipt["state"], "createdAt": receipt.get("createdAt", self._clock()),
                    "updatedAt": receipt.get("createdAt", self._clock()), "historical": True,
                    "resultText": "", "artifacts": [], "available": False, "lastSeenAt": None,
                    "completionEventId": None})
        except (ValueError, KeyError, TypeError, WorkError):
            # Keep the original Roblox store intact; no guessed import.
            self._state["tasks"] = []

    def _node_bridge(self, payload):
        bridge = Path(self.config["bridge_path"]).with_name("work_bridge.mjs")
        _need(bridge.is_absolute() and bridge.is_file() and not bridge.is_symlink(), "bridge_unavailable")
        child = subprocess.run(["/usr/bin/node", str(bridge)], input=json.dumps(payload),
                               text=True, capture_output=True, timeout=12, cwd=str(bridge.parent))
        _need(len(child.stdout.encode()) <= 16 * 1024 * 1024, "response_too_large")
        result = json.loads(child.stdout)
        _need(type(result) is dict and type(result.get("ok")) is bool, "bridge_invalid")
        return result

    def _call(self, action, target=None, **fields):
        payload = {"dataDir": self.config["data_dir"], "action": action, **fields}
        if target:
            self._validate_target(target)
            payload.update(peerId=target.get("peerId"), expectedHostNodeId=target["hostNodeId"], projectId=target["projectId"])
            if target.get("workspaceRevision") is not None:
                payload["workspaceRevision"] = target["workspaceRevision"]
        try:
            result = self._bridge(payload)
            _need(type(result) is dict and type(result.get("ok")) is bool, "bridge_invalid")
            return result
        except Exception:
            return {"ok": False, "errorCode": "connection_unavailable", "uncertain": action in {"submit", "cancel"}}

    def projects(self, force=False):
        with self._lock:
            if force or not self._catalog_at or self._clock() - self._catalog_at >= 30:
                result = self._call("catalog")
                if result.get("ok"):
                    raw = result.get("projects")
                    try:
                        _need(type(raw) is list and len(raw) <= 128, "catalog_invalid")
                        projects, seen = [], set()
                        for item in raw:
                            _need(type(item) is dict, "catalog_invalid")
                            p = {k: item.get(k) for k in ("peerId", "hostNodeId", "projectId", "workspaceRevision")}
                            p["key"] = project_key(p["hostNodeId"], p["projectId"])
                            self._validate_target(p); _need(p["key"] not in seen, "catalog_invalid"); seen.add(p["key"])
                            for name in ("name", "computerName"):
                                _need(type(item.get(name)) is str and 0 < len(item[name]) <= 100, "catalog_invalid")
                                p[name] = item[name]
                            p.update({k: item.get(k) is True for k in ("available", "executionAllowed", "readOnlyAllowed")})
                            projects.append(p)
                        self._catalog, self._catalog_at, self._catalog_error = projects, self._clock(), None
                        self._partial = result.get("partial") is True
                    except WorkError:
                        self._catalog_error = "catalog_invalid"
                else:
                    self._catalog_error = "catalog_unavailable"
            selected = self._state.get("selection")
            projects = copy.deepcopy(self._catalog)
            if self._catalog_error:
                for p in projects:
                    p["available"] = False; p["executionAllowed"] = False
            return {"projects": projects, "selectedProjectKey": selected.get("key") if selected else None,
                    "updatedAt": self._catalog_at or None, "partial": self._partial or bool(self._catalog_error),
                    "error": self._catalog_error}

    def select_project(self, key):
        with self._lock:
            choices = self.projects(force=True)["projects"]
            target = next((p for p in choices if p["key"] == key and p["available"]), None)
            _need(target is not None, "choose_available_project")
            if self._state.get("selection") != target:
                self._state["selection"] = copy.deepcopy(target)
                self._state["selectionEpoch"] += 1; self._save()
            return self.projects()

    def selected(self):
        with self._lock:
            return copy.deepcopy(self._state.get("selection")), self._state["selectionEpoch"]

    def selection_matches(self, target, epoch):
        with self._lock:
            return self._state["selectionEpoch"] == epoch and self._state.get("selection") == target

    def _public(self, task):
        target = task["target"]
        return {"key": task["key"], "projectKey": target["key"], "projectName": target["name"],
                "computerName": target["computerName"], "hostNodeId": target["hostNodeId"], "projectId": target["projectId"],
                "jobId": task.get("jobId"), "requestId": task["requestId"], "status": task["status"],
                "requestText": task.get("prompt", "")[:2000], "createdAt": task["createdAt"], "updatedAt": task["updatedAt"],
                "lastSeenAt": task.get("lastSeenAt"), "resultText": task.get("resultText", ""),
                "resultTruncated": task.get("resultTruncated", False), "available": task.get("available", False),
                "stale": task["status"] not in _TERMINAL and (not task.get("available") or not task.get("lastSeenAt") or self._clock() - task["lastSeenAt"] > 60),
                "snapshot": task["status"] in _TERMINAL,
                "requiresHuman": None, "humanStep": None, "verificationState": "not-established",
                "artifacts": copy.deepcopy(task.get("artifacts", [])), "historical": task.get("historical", False),
                "completionEventId": task.get("completionEventId"), "reason": task.get("reason"),
                "sharedState": copy.deepcopy(task.get("sharedState")), "artifactReason": task.get("artifactReason")}

    def tasks(self):
        with self._lock:
            self._ensure_observer()
            return {"tasks": [self._public(t) for t in reversed(self._state["tasks"])],
                    "selectedProjectKey": (self._state.get("selection") or {}).get("key"), "updatedAt": self._clock()}

    def submit(self, interaction_id, prompt, target, epoch, cancelled=None):
        _need(type(interaction_id) is str and re.fullmatch(r"[A-Za-z0-9_-]{16,100}", interaction_id), "invalid_interaction")
        _need(type(prompt) is str and 0 < len(prompt.strip()) <= 12000, "invalid_prompt")
        with self._lock:
            existing = next((t for t in self._state["tasks"] if t["interactionId"] == interaction_id), None)
            if existing:
                _need(existing["prompt"] == prompt and existing["target"] == target, "interaction_conflict")
                return self._public(existing)
            _need(self.selection_matches(target, epoch), "selection_changed")
            current = next((p for p in self.projects(force=True)["projects"] if p["key"] == target["key"]), None)
            _need(current is not None and current == target and current["available"] and current["executionAllowed"], "target_or_permission_changed")
            _need(not any(t["target"]["key"] == target["key"] and t["status"] not in _TERMINAL for t in self._state["tasks"]), "previous_job_pending_or_unknown")
            _need(not cancelled or not cancelled.is_set(), "cancelled")
            _need(len(self._state["tasks"]) < 500, "task_capacity")
            request = "maria_work_" + hashlib.sha256((target["key"] + ":" + interaction_id).encode()).hexdigest()
            now = self._clock()
            task = {"key": "work_" + hashlib.sha256(request.encode()).hexdigest(), "interactionId": interaction_id,
                    "target": copy.deepcopy(target), "requestId": request, "prompt": prompt, "jobId": None,
                    "status": "unknown", "createdAt": now, "updatedAt": now, "lastSeenAt": None,
                    "resultText": "", "artifacts": [], "available": False, "historical": False, "completionEventId": None}
            self._state["tasks"].append(task); self._save()  # Before the only possible send.
            if cancelled and cancelled.is_set():
                task.update(status="cancelled", reason="cancelled_before_send"); self._save(); return self._public(task)
            result = self._call("submit", target, requestId=request, text=prompt)
            if result.get("ok"):
                try:
                    self._accept_job(task, result.get("job"))
                except WorkError:
                    task.update(reason="receipt_unverified", available=False)
            else:
                task.update(reason="send_outcome_unknown" if result.get("uncertain") else "submission_rejected",
                            status="unknown" if result.get("uncertain") else "failed")
            self._save(); self._ensure_observer()
            return self._public(task)

    def _accept_job(self, task, job):
        _need(type(job) is dict and job.get("projectId") == task["target"]["projectId"]
              and job.get("requestId") == task["requestId"] and job.get("status") in _STATES, "job_correlation_failed")
        _id(job.get("id"))
        _need(task.get("jobId") in {None, job["id"]}, "job_correlation_failed")
        if not task.get("historical"):
            _need(job.get("executionMode") == "workspace-write" and job.get("execution") is True, "execution_unverified")
        steps = job.get("steps", [])
        _need(type(steps) is list and len(steps) <= 32, "job_invalid")
        old = task["status"]
        task.update(jobId=job["id"], status=job["status"], available=True, lastSeenAt=self._clock(), updatedAt=self._clock(), reason=None)
        results = [s.get("result", {}) for s in steps if type(s) is dict and s.get("role") == "master" and s.get("status") == "completed"]
        if results and type(results[-1]) is dict and type(results[-1].get("text")) is str:
            text = results[-1]["text"]
            task.update(resultText=text[:24000], resultTruncated=len(text) > 24000 or results[-1].get("truncated") is True)
        if old not in _TERMINAL and task["status"] in _TERMINAL and not task.get("historical"):
            task["completionEventId"] = task.get("completionEventId") or "completion_" + hashlib.sha256((task["key"] + ":terminal").encode()).hexdigest()

    def refresh(self, task_key=None, cancelled=None):
        with self._lock:
            selected = [copy.deepcopy(t) for t in self._state["tasks"] if task_key is None or t["key"] == task_key]
            _need(task_key is None or bool(selected), "task_not_found")
        deadline = time.monotonic() + 60
        for task in selected[:8]:
            if cancelled and cancelled.is_set() or time.monotonic() >= deadline: break
            with self._lock:
                version = self._observation_versions.get(task["key"], 0) + 1
                self._observation_versions[task["key"]] = version
            result = self._call("status", task["target"], **({"jobId": task["jobId"]} if task.get("jobId") else {"requestId": task["requestId"]}))
            try:
                _need(result.get("ok"), "job_unavailable")
                view = result.get("view", result)
                job = result.get("job") or view.get("job")
                if not job:
                    matches = [j for j in view.get("jobs", []) if type(j) is dict and j.get("requestId") == task["requestId"]]
                    _need(len(matches) == 1, "job_unavailable"); job = matches[0]
                self._accept_job(task, job)
                project = view.get("project")
                if type(project) is dict and project.get("id") == task["target"]["projectId"]:
                    task["sharedState"] = project_shared_state(project.get("sharedState"), task["target"]["hostNodeId"], task["target"]["projectId"], 2000)
                if task["status"] == "completed": self._read_artifacts(task)
            except WorkError:
                task.update(available=False, reason="last_state_unconfirmed")
            with self._lock:
                if self._observation_versions.get(task["key"]) != version:
                    continue  # A newer issued observation owns this task.
                current = next((t for t in self._state["tasks"] if t["key"] == task["key"]), None)
                if current is not None:
                    reason = current.get("reason")
                    current.update(task)
                    if reason in {"cancel_requested", "cancel_outcome_unknown"} and current["status"] not in _TERMINAL:
                        current["reason"] = reason
                    self._save()
        return self.tasks()

    def _read_artifacts(self, task):
        result = self._call("artifacts", task["target"], jobId=task["jobId"])
        files = result.get("artifacts", result.get("files")) if result.get("ok") else None
        if type(files) is not list or len(files) > 100:
            task["artifacts"] = [dict(a, available=False) for a in task.get("artifacts", [])]
            task["artifactReason"] = "artifact_listing_unavailable"
            return
        task["artifactReason"] = None
        task["artifacts"] = [{"path": f["path"], "name": f["path"].split("/")[-1], "available": f.get("available", f.get("downloadable", True)) is True}
                             for f in files if type(f) is dict and _path(f.get("path"))]

    def latest(self, target, refresh=True, cancelled=None):
        with self._lock:
            tasks = [t for t in self._state["tasks"] if t["target"]["key"] == target["key"]]
            key = tasks[-1]["key"] if tasks else None
        if key is None:
            if cancelled and cancelled.is_set(): raise WorkError("cancelled")
            result = self._call("view", target)
            view = result.get("view", result)
            project = view.get("project")
            if not result.get("ok") or type(project) is not dict or project.get("id") != target["projectId"]:
                return {"status": "not_recorded", "projectKey": target["key"], "available": False, "reason": "project_view_unavailable"}
            # The work journal is not the project's complete historical job store.
            reports = []
            jobs = view.get("jobs", [])
            for job in jobs[-6:] if type(jobs) is list else []:
                if type(job) is not dict or job.get("projectId") != target["projectId"]: continue
                steps = job.get("steps", [])
                text = next((s.get("result", {}).get("text") for s in reversed(steps) if type(s) is dict and s.get("role") == "master" and type(s.get("result")) is dict and type(s["result"].get("text")) is str), "") if type(steps) is list else ""
                reports.append({"jobId": job.get("id"), "status": job.get("status"), "resultText": text[:2000], "resultTruncated": len(text) > 2000})
            return {"status": "not_recorded", "projectKey": target["key"], "available": True,
                    "reason": "no_generic_work_receipt_not_no_project_jobs", "projectName": target["name"],
                    "computerName": target["computerName"], "observedAt": self._clock(), "reports": reports,
                    "sharedState": project_shared_state(project.get("sharedState"), target["hostNodeId"], target["projectId"], 8000),
                    "verificationState": "not-established"}
        if refresh: self.refresh(key, cancelled)
        with self._lock:
            return self._public(next(t for t in self._state["tasks"] if t["key"] == key))

    def cancel(self, target):
        with self._lock:
            tasks = [t for t in self._state["tasks"] if t["target"]["key"] == target["key"] and t["status"] not in _TERMINAL]
            _need(len(tasks) == 1 and tasks[0].get("jobId"), "no_known_active_job")
            task = tasks[0]
            result = self._call("cancel", target, jobId=task["jobId"])
            task.update(reason="cancel_requested" if result.get("ok") else "cancel_outcome_unknown", updatedAt=self._clock())
            self._save(); return self._public(task)

    def artifact(self, task_key, path):
        with self._lock:
            task = next((t for t in self._state["tasks"] if t["key"] == task_key), None)
            _need(task is not None and task.get("jobId") and _path(path), "artifact_unavailable")
            self._read_artifacts(task)
            _need(any(a["path"] == path and a["available"] for a in task["artifacts"]), "artifact_unavailable")
            result = self._call("artifact", task["target"], jobId=task["jobId"], path=path)
            _need(result.get("ok") and type(result.get("content")) is str, "artifact_unavailable")
            try: raw = base64.b64decode(result["content"], validate=True)
            except (ValueError, TypeError): raise WorkError("artifact_invalid") from None
            _need(len(raw) <= 1024 * 1024, "artifact_too_large")
            digest = hashlib.sha256(raw).hexdigest()
            _need(result.get("sha256") in {None, digest}, "artifact_hash_mismatch")
            mime = str(result.get("mime", "")).split(";")[0].lower()
            mime = mime if mime in {"text/plain", "text/csv", "text/markdown", "application/json"} else "text/plain" if mime == "text/html" else "application/octet-stream"
            return {"content": result["content"], "name": path.split("/")[-1], "mime": mime, "size": len(raw), "sha256": digest, "observedAt": self._clock()}

    def observer_step(self):
        """One bounded read pass; never creates a batch or repeats a send."""
        with self._lock:
            pending = [t["key"] for t in self._state["tasks"] if t["status"] not in _TERMINAL or t.get("historical") and t.get("lastSeenAt") is None]
            offset = self._observer_cursor % max(1, len(pending))
            keys = (pending[offset:] + pending[:offset])[:8]
            self._observer_cursor += len(keys)
        deadline = time.monotonic() + 60
        for key in keys:
            if self._stop.is_set() or time.monotonic() >= deadline: break
            self.refresh(key, self._stop)
        return bool(keys)

    def _ensure_observer(self):
        if not self._background or self._stop.is_set() or self._thread is not None:
            return
        if not any(t["status"] not in _TERMINAL or t.get("historical") and t.get("lastSeenAt") is None for t in self._state["tasks"]):
            return
        def run():
            try:
                pause = 15
                while not self._stop.wait(pause):
                    try:
                        if not self.observer_step(): break
                        with self._lock:
                            pause = 60 if any(not t.get("available") for t in self._state["tasks"] if t["status"] not in _TERMINAL) else 15
                    except Exception:
                        if self._stop.wait(45): break
            finally:
                with self._lock:
                    self._thread = None
                    self._ensure_observer()
        self._thread = threading.Thread(target=run, daemon=True, name="kritaqo-known-jobs")
        self._thread.start()

    def close(self):
        self._stop.set()

    def start(self):
        with self._lock:
            self._ensure_observer()

    def stop(self):
        self.close()


_service = None
_factory_lock = threading.Lock()


def get_work_service(config=None):
    global _service
    with _factory_lock:
        if _service is None:
            if config is None:
                from agent_core.llm.kritaqo_tools import KritaqoToolsProvider
                legacy = KritaqoToolsProvider.from_env()
                if legacy is None: return None
                config = legacy.config
            _service = WorkService(config, background=True)
            atexit.register(_service.close)
        return _service
