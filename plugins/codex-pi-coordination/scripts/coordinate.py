#!/usr/bin/env python3
"""One bounded Pi delegation in an exclusively owned OpenShell sandbox.

The model returns work; this command never applies patches or grants acceptance.
OpenShell owns remote cleanup. No process-group-to-PID fallback is implemented.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import difflib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import tarfile
import time
import uuid


MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_FILES = 10000
KINDS = {"implementation", "research", "review", "validation"}
TOOLS = {"read", "grep", "find", "ls", "write", "edit"}
PLUGIN = Path(__file__).resolve().parents[1]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("Expected bounded regular JSON file")
    return json.loads(path.read_text(encoding="utf-8"))


def write_new_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def bounded_integer(value, label, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{label} must be between 1 and {maximum}")
    return value


def relative_file(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Expected a relative file path")
    path = PurePosixPath(value)
    if value == "." or path.is_absolute() or any(p in ("..", ".git") for p in path.parts) or str(path) != value:
        raise ValueError("Unsafe relative file path")
    return value


def validate_task(task):
    required = {"version", "task_id", "kind", "instructions", "writable_paths", "checks"}
    optional = {"repository", "revision", "max_tool_calls", "max_turns", "wall_seconds"}
    if not isinstance(task, dict) or set(task) - required - optional or required - set(task):
        raise ValueError("Task fields do not match the version 1 contract")
    if type(task["version"]) is not int or task["version"] != 1 or not isinstance(task["kind"], str) or task["kind"] not in KINDS:
        raise ValueError("Unsupported task version or kind")
    if not isinstance(task["task_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", task["task_id"]):
        raise ValueError("Invalid task_id")
    if not isinstance(task["instructions"], str) or not 1 <= len(task["instructions"].encode()) <= 32000:
        raise ValueError("Instructions must contain 1..32000 bytes")
    paths = task["writable_paths"]
    if not isinstance(paths, list) or len(paths) > 128 or any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths):
        raise ValueError("writable_paths must be a bounded unique file list")
    for path in paths:
        relative_file(path)
    if not isinstance(task["checks"], list) or len(task["checks"]) > 32:
        raise ValueError("checks must be a list of at most 32 commands")
    names = set()
    for check in task["checks"]:
        if not isinstance(check, dict) or set(check) != {"name", "argv", "timeout_seconds"}:
            raise ValueError("A check requires name, argv and timeout_seconds")
        if not isinstance(check["name"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", check["name"]) or check["name"] in names:
            raise ValueError("Check names must be safe and unique")
        names.add(check["name"])
        if not isinstance(check["argv"], list) or not check["argv"] or len(check["argv"]) > 128 or any(not isinstance(s, str) or not s or "\x00" in s or len(s) > 16000 for s in check["argv"]):
            raise ValueError("Check argv must contain bounded strings, without shell expansion")
        bounded_integer(check["timeout_seconds"], "check timeout", 600)
    for name, default, maximum in (("wall_seconds", 600, 1800), ("max_tool_calls", 40, 500), ("max_turns", 32, 200)):
        bounded_integer(task.get(name, default), name, maximum)
    if ("repository" in task) != ("revision" in task):
        raise ValueError("repository and revision must be supplied together")
    if "repository" in task and (not isinstance(task["repository"], str) or not task["repository"]):
        raise ValueError("repository must be a path string")
    return task


def safe_archive_files(raw):
    """Git archives are data; reject links, devices, duplicates and traversal."""
    files, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for item in archive:
            if item.isdir():
                relative_file(item.name.rstrip("/"))
                continue
            name = relative_file(item.name)
            total += item.size
            if not item.isfile() or name in files or total > MAX_SOURCE_BYTES or len(files) >= MAX_FILES:
                raise ValueError("Source archive exceeds bounds or contains unsafe members")
            files[name] = archive.extractfile(item).read()
    return files


def frozen_source(task):
    if "repository" not in task:
        return {}, {"kind": "empty-workspace", "files": {}, "modes": {}}
    repository = Path(task["repository"]).resolve(strict=True)
    revision = task["revision"]
    if not isinstance(revision, str) or not revision or revision.startswith("-"):
        raise ValueError("Invalid source revision")
    commit = subprocess.check_output(["git", "rev-parse", "--verify", revision + "^{commit}"], cwd=repository, text=True, timeout=30).strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ValueError("Invalid resolved commit")
    # Export committed content only; never stash, reset or silently include dirty work.
    listing = subprocess.check_output(["git", "ls-tree", "-r", "-l", "-z", commit], cwd=repository, timeout=30)
    entries = [entry.split(b"\t", 1)[0].split() for entry in listing.split(b"\0") if entry]
    if len(entries) > MAX_FILES or any(entry[0] not in {b"100644", b"100755"} for entry in entries) or sum(int(entry[3]) for entry in entries) > MAX_SOURCE_BYTES:
        raise ValueError("Source tree exceeds bounds or contains links/submodules")
    raw = subprocess.check_output(["git", "archive", "--format=tar", commit], cwd=repository, timeout=60)
    if len(raw) > MAX_SOURCE_BYTES + 16 * 1024 * 1024:
        raise ValueError("Source archive exceeds bounds")
    files = safe_archive_files(raw)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        modes = {m.name: 0o755 if m.mode & 0o111 else 0o644 for m in archive if m.isfile()}
    return files, {"kind": "git", "commit": commit, "files": {p: digest(b) for p, b in files.items()}, "modes": modes}


def snapshot(root):
    files, total = {}, 0
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            raise ValueError("Workspace symlinks are refused")
        mode = path.stat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("Workspace contains a nonregular file")
        total += path.stat().st_size
        if total > MAX_SOURCE_BYTES or len(files) >= MAX_FILES:
            raise ValueError("Workspace exceeds bounds")
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def execute_to_log(argv, cwd, log, timeout, *, remote_owner=False, env=None):
    """Cap bytes and time. Remote descendants are stopped by the external owner."""
    started = time.monotonic()
    with Path(log).open("xb") as stream:
        process = subprocess.Popen(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, env=env)
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout or Path(log).stat().st_size > MAX_OUTPUT_BYTES:
                    raise TimeoutError("Command deadline or output limit exceeded")
                time.sleep(0.05)
            if Path(log).stat().st_size > MAX_OUTPUT_BYTES:
                raise ValueError("Command output limit exceeded")
            return process.returncode
        finally:
            if not remote_owner and process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def inspect_events(path, max_tools, max_turns):
    """Observe completed Pi events; model prose never substitutes for completion."""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ValueError("Pi output exceeds limit")
    outstanding, seen, calls, turns, final_stop, ended = set(), set(), 0, 0, None, False
    executions = {}
    for line in raw.splitlines():
        event = json.loads(line)
        kind, message = event.get("type"), event.get("message", {})
        if kind in {"error", "agent_error"}:
            raise ValueError("Pi emitted an error")
        if kind == "tool_execution_start":
            call_id = event["toolCallId"]
            if call_id in seen:
                raise ValueError("Duplicate tool start")
            seen.add(call_id)
            outstanding.add(call_id)
            executions[call_id] = {"id": call_id, "name": event.get("toolName")}
            calls += 1
        elif kind == "tool_execution_end":
            call_id = event["toolCallId"]
            if call_id not in outstanding:
                raise ValueError("Unpaired tool result")
            outstanding.remove(call_id)
            executions[call_id]["is_error"] = event.get("isError") is True
        elif kind == "message_end" and message.get("role") == "assistant":
            turns += 1
            final_stop = message.get("stopReason")
            ended = False
        elif kind == "agent_end":
            ended = True
    if outstanding or not turns or not ended or final_stop != "stop" or calls > max_tools or turns > max_turns:
        raise ValueError("Pi output is incomplete or exceeded its budget")
    return {"tool_calls": calls, "assistant_turns": turns, "event_log_sha256": digest(raw), "tool_executions": list(executions.values())}


def inspect_extension_events(path, task, pi_events, task_sha256):
    """A normal Pi exit cannot override a task guard refusal or missing handoff."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError("Missing or oversized extension lifecycle log")
    raw = path.read_bytes()
    events = [json.loads(line) for line in raw.splitlines()]
    if len(raw) > MAX_OUTPUT_BYTES or not events or any(not isinstance(event, dict) for event in events):
        raise ValueError("Invalid extension lifecycle log")
    kinds = [event.get("type") for event in events]
    if kinds[0] != "task_loaded" or kinds.count("task_loaded") != 1 or kinds.count("handoff") != 1 or kinds.count("agent_settled") != 1 or kinds.count("session_shutdown") != 1 or kinds[-2:] != ["agent_settled", "session_shutdown"]:
        raise ValueError("Incomplete or unordered extension lifecycle")
    if set(kinds) - {"task_loaded", "tool_call", "handoff", "agent_settled", "session_shutdown"} or any(event.get("failure") for event in events):
        raise ValueError("Extension refused the delegated task")
    for event in events:
        if event.get("run_id") != task["run_id"] or event.get("task_id") != task["task_id"] or event.get("task_sha256") != task_sha256:
            raise ValueError("Extension lifecycle identity mismatch")
    handoff_index = kinds.index("handoff")
    if kinds[handoff_index + 1:] != ["agent_settled", "session_shutdown"] or events[handoff_index].get("reported_status") != "completed":
        raise ValueError("Extension did not finish with a completed handoff")
    calls = [event for event in events if event["type"] == "tool_call"]
    if any(type(event.get("tool_calls")) is not int for event in calls) or [event.get("tool_calls") for event in calls] != list(range(1, len(calls) + 1)):
        raise ValueError("Extension and Pi tool accounting differ")
    guarded = {event.get("tool_call_id"): event.get("tool_name") for event in calls}
    executed = {event["id"]: event for event in pi_events["tool_executions"]}
    if len(guarded) != len(calls) or any(call_id not in executed or executed[call_id]["name"] != name for call_id, name in guarded.items()):
        raise ValueError("Extension tool identities differ from Pi")
    # Pi can reject malformed arguments before emitting the extension tool_call hook.
    if any(not event["is_error"] for call_id, event in executed.items() if call_id not in guarded):
        raise ValueError("Pi executed a tool without the extension guard")
    for event in events[handoff_index:]:
        if event.get("handed_off") is not True or type(event.get("tool_calls")) is not int or event["tool_calls"] != len(calls) or type(event.get("turns")) is not int:
            raise ValueError("Extension terminal accounting differs from Pi")
    # The final assistant response follows the handoff tool in a new turn.
    if not 1 <= events[handoff_index]["turns"] <= pi_events["assistant_turns"] or any(event["turns"] != pi_events["assistant_turns"] for event in events[-2:]):
        raise ValueError("Extension turn accounting differs from Pi")
    return {"event_log_sha256": digest(raw), "model": events[0].get("model"), "tool_calls": len(calls), "assistant_turns": pi_events["assistant_turns"]}


def worker(root):
    """Runs only inside the caller-owned disposable OpenShell sandbox."""
    root = Path(root).resolve(strict=True)
    task, launch = read_json(root / "task.json"), read_json(root / "launch.json")
    workspace, output = root / "workspace", root / "results"
    receipt = {"version": 1, "run_id": task["run_id"], "task_id": task["task_id"], "started_at": utc_now(), "outcome": "incomplete", "checks": []}
    write_new_json(root / "worker-started.json", receipt)
    deadline = time.monotonic() + launch["wall_seconds"]
    before = snapshot(workspace)
    try:
        if {p: digest(b) for p, b in before.items()} != task["source"]["files"]:
            raise ValueError("Exported source differs from frozen source")
        command = [*launch["pi_argv"], "--model", launch["model"], "--thinking", launch["thinking"], "--offline", "--no-session", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve", "--tools", ",".join([*task["allowed_tools"], "coordination_status", "coordination_handoff"]), "--extension", str(root / "extension.js"), "--coordination-task", str(root / "task.json"), "--mode", "json", "-p", "Complete the assigned coordination task. Use coordination_status to inspect it and coordination_handoff to return your work. Do not execute verification commands; the coordinator runs declared checks after your handoff."]
        env = os.environ.copy()
        env.update(launch["environment"])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        receipt["pi_exit_code"] = execute_to_log(command, workspace, output / "pi-events.jsonl", deadline - time.monotonic(), remote_owner=True, env=env)
        if receipt["pi_exit_code"] != 0:
            raise ValueError("Pi exited unsuccessfully")
        receipt["events"] = inspect_events(output / "pi-events.jsonl", task["max_tool_calls"], task["max_turns"])
        receipt["extension"] = inspect_extension_events(output / "extension-events.jsonl", task, receipt["events"], digest((root / "task.json").read_bytes()))
        report = read_json(output / "model-report.json")
        if report.get("run_id") != task["run_id"] or report.get("task_id") != task["task_id"] or report.get("model_self_report") is not True or report.get("task_sha256") != digest((root / "task.json").read_bytes()):
            raise ValueError("Model handoff identity mismatch")
        receipt["model_report_sha256"] = digest((output / "model-report.json").read_bytes())
        after = snapshot(workspace)
        changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
        receipt["changed_files"] = changed
        receipt["model_report_matches_changes"] = isinstance(report.get("changed_files"), list) and sorted(report["changed_files"]) == changed
        if set(changed) - set(task["writable_paths"]):
            raise ValueError("Work changed files outside the authorized scope")
        for check in launch["checks"]:
            started = {"name": check["name"], "argv": check["argv"], "started_at": utc_now()}
            write_new_json(output / (check["name"] + ".started.json"), started)
            log = output / (check["name"] + ".log")
            code = execute_to_log(check["argv"], workspace, log, min(check["timeout_seconds"], deadline - time.monotonic()), remote_owner=True, env=env)
            result = {**started, "ended_at": utc_now(), "exit_code": code, "log_bytes": log.stat().st_size, "log_sha256": digest(log.read_bytes())}
            write_new_json(output / (check["name"] + ".result.json"), result)
            receipt["checks"].append(result)
        verified = snapshot(workspace)
        if any(verified.get(name) != contents for name, contents in after.items()) or any(name in verified for name in before.keys() - after.keys()):
            raise ValueError("Verification changed the returned source or artifacts")
        changes = []
        (output / "changed-files").mkdir(exist_ok=False)
        for name in changed:
            changes.append({"path": name, "before_sha256": digest(before[name]) if name in before else None, "after_sha256": digest(after[name]) if name in after else None})
            if name in after:
                destination = output / "changed-files" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as artifact:
                    artifact.write(after[name])
        write_new_json(output / "changes.json", changes)
        with (output / "changes.patch").open("x", encoding="utf-8") as patch:
            for name in changed:
                try:
                    old, new = before.get(name, b"").decode(), after.get(name, b"").decode()
                except UnicodeDecodeError:
                    patch.write(f"Binary change: {name}; use changes.json and changed-files.\n")
                    continue
                patch.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile="a/" + name if name in before else "/dev/null", tofile="b/" + name if name in after else "/dev/null"))
        receipt["checks_passed"] = all(c["exit_code"] == 0 for c in receipt["checks"]) if receipt["checks"] else None
        receipt["model_status"] = report.get("status")
        receipt["outcome"] = "returned" if report.get("status") == "completed" and receipt["checks_passed"] is not False and receipt["model_report_matches_changes"] else "failed"
        receipt["acceptance"] = "not_granted"
        receipt["artifact_sha256"] = {name: digest(data) for name, data in snapshot(output).items()}
    except Exception as error:
        receipt["error"] = str(error)
    finally:
        receipt["ended_at"] = utc_now()
        write_new_json(output / "worker-receipt.json", receipt)
        print(json.dumps(receipt), flush=True)
    return 0 if receipt["outcome"] == "returned" else 1


def verify_return(results, task, source_files, run_id):
    """Recheck returned bytes against host-held scope and source, not Pi prose."""
    results = Path(results)
    actual = snapshot(results)
    receipt = read_json(results / "worker-receipt.json")
    expected_artifacts = receipt.get("artifact_sha256")
    observed_artifacts = {name: digest(data) for name, data in actual.items() if name != "worker-receipt.json"}
    if expected_artifacts != observed_artifacts:
        raise ValueError("Returned artifact manifest differs from actual bytes")
    if receipt.get("run_id") != run_id or receipt.get("task_id") != task["task_id"] or receipt.get("outcome") != "returned" or type(receipt.get("pi_exit_code")) is not int or receipt["pi_exit_code"] != 0 or receipt.get("acceptance") != "not_granted":
        raise ValueError("Worker identity or completion contract mismatch")
    report = read_json(results / "model-report.json")
    if report.get("task_sha256") != digest(json.dumps(task).encode()) or report.get("task_id") != task["task_id"] or report.get("run_id") != run_id or report.get("model_self_report") is not True or report.get("status") != "completed":
        raise ValueError("Returned handoff does not bind this task")
    if digest(actual["model-report.json"]) != receipt.get("model_report_sha256"):
        raise ValueError("Handoff bytes changed after execution")
    events = inspect_events(results / "pi-events.jsonl", task["max_tool_calls"], task["max_turns"])
    if receipt.get("events") != events:
        raise ValueError("Recorded Pi events differ from returned log")
    extension = inspect_extension_events(results / "extension-events.jsonl", task, events, digest(json.dumps(task).encode()))
    if receipt.get("extension") != extension:
        raise ValueError("Recorded extension lifecycle differs from returned log")
    checks = receipt.get("checks")
    if not isinstance(checks, list) or len(checks) != len(task["checks"]):
        raise ValueError("Missing declared check result")
    for expected, check in zip(task["checks"], checks):
        if check.get("name") != expected["name"] or check.get("argv") != expected["argv"] or type(check.get("exit_code")) is not int or check["exit_code"] != 0:
            raise ValueError("Verification did not execute the declared passing command")
        name = expected["name"]
        if read_json(results / (name + ".result.json")) != check:
            raise ValueError("Check receipt differs from worker receipt")
        started = read_json(results / (name + ".started.json"))
        if any(started.get(key) != check.get(key) for key in ("name", "argv", "started_at")):
            raise ValueError("Check start/result binding mismatch")
        raw = actual[name + ".log"]
        if len(raw) != check["log_bytes"] or digest(raw) != check["log_sha256"]:
            raise ValueError("Check output differs from its receipt")
    changes, patch = read_json(results / "changes.json"), []
    if not isinstance(changes, list):
        raise ValueError("Invalid returned changes")
    names = [relative_file(change["path"]) for change in changes]
    if len(set(names)) != len(names) or set(names) - set(task["writable_paths"]) or sorted(names) != receipt.get("changed_files") or sorted(names) != sorted(report.get("changed_files", [])):
        raise ValueError("Returned changes differ from the authorized scope")
    artifact_names = set()
    for change in changes:
        name = change["path"]
        before = source_files.get(name)
        if change["before_sha256"] != (digest(before) if before is not None else None):
            raise ValueError("Returned change has the wrong source base")
        after = None
        if change["after_sha256"] is not None:
            artifact_names.add("changed-files/" + name)
            after = actual["changed-files/" + name]
            if digest(after) != change["after_sha256"]:
                raise ValueError("Returned change bytes mismatch")
        try:
            old, new = (before or b"").decode(), (after or b"").decode()
        except UnicodeDecodeError:
            patch.append(f"Binary change: {name}; use changes.json and changed-files.\n")
            continue
        patch.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile="a/" + name if before is not None else "/dev/null", tofile="b/" + name if after is not None else "/dev/null"))
    if artifact_names != {name for name in actual if name.startswith("changed-files/")} or actual["changes.patch"] != "".join(patch).encode():
        raise ValueError("Returned patch/files differ from the verified change manifest")
    return receipt


def profile_settings(path):
    profile = read_json(path)
    required = {"sandbox_name", "sandbox_id", "pi_argv", "model"}
    optional = {"openshell_argv", "python", "remote_parent", "thinking", "environment", "protected_sandboxes"}
    if not isinstance(profile, dict) or required - set(profile) or set(profile) - required - optional:
        raise ValueError("Profile fields do not match the contract")
    for key in required - {"pi_argv"}:
        if not isinstance(profile[key], str) or not profile[key] or profile[key].startswith("-"):
            raise ValueError("Invalid profile " + key)
    for key, default in (("pi_argv", []), ("openshell_argv", ["openshell"])):
        value = profile.get(key, default)
        if not isinstance(value, list) or not value or any(not isinstance(s, str) or not s or "\x00" in s for s in value):
            raise ValueError("Invalid argv in profile")
    environment = profile.get("environment", {})
    if not isinstance(environment, dict) or set(environment) - {"PI_CODING_AGENT_DIR", "PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"} or any(not isinstance(v, str) or "\x00" in v for v in environment.values()):
        raise ValueError("Profile environment is restricted to non-secret runtime paths")
    protected = profile.get("protected_sandboxes", [])
    if not isinstance(protected, list) or any(not isinstance(name, str) or not name or name.startswith("-") for name in protected):
        raise ValueError("Invalid protected sandbox names")
    if not isinstance(profile.get("thinking", "high"), str) or profile.get("thinking", "high") not in {"off", "minimal", "low", "medium", "high", "xhigh"}:
        raise ValueError("Invalid thinking level")
    if not isinstance(profile.get("python", "python3"), str) or not profile.get("python", "python3") or "\x00" in profile.get("python", "python3"):
        raise ValueError("Invalid Python executable")
    if not isinstance(profile.get("remote_parent", "/sandbox/codex-pi"), str):
        raise ValueError("remote_parent must be a path string")
    remote_parent = PurePosixPath(profile.get("remote_parent", "/sandbox/codex-pi"))
    if not remote_parent.is_absolute() or ".." in remote_parent.parts:
        raise ValueError("remote_parent must be an absolute sandbox path")
    return profile


def selected_state(state):
    return {key: state.get(key) for key in ("id", "name", "phase", "main_process_instance_id", "restart_count")}


class OpenShellOwner:
    def __init__(self, profile):
        self.profile = profile
        self.argv = profile.get("openshell_argv", ["openshell"])
        self.main_instance = None

    def command(self, *args, timeout=60):
        return subprocess.run([*self.argv, "sandbox", *args], capture_output=True, text=True, timeout=timeout, check=True)

    def get(self, name=None):
        return json.loads(self.command("get", name or self.profile["sandbox_name"], "-o", "json", timeout=30).stdout)

    def verify(self):
        state = self.get()
        if state["id"] != self.profile["sandbox_id"] or (self.main_instance is not None and state["main_process_instance_id"] != self.main_instance):
            raise ValueError("Sandbox ownership identity changed; refusing owner action")
        return state


@contextlib.contextmanager
def exclusive_owner(profile, lock_root):
    lock_root.mkdir(parents=True, exist_ok=True)
    key = digest(profile["sandbox_id"].encode())
    with (lock_root / (key + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield lock_root / (key + ".json")


def run_task(task_file, profile_file, output, lock_root):
    task, profile = validate_task(read_json(task_file)), profile_settings(profile_file)
    files, source = frozen_source(task)
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    owner, run_id = OpenShellOwner(profile), uuid.uuid4().hex
    remote_parent = PurePosixPath(profile.get("remote_parent", "/sandbox/codex-pi"))
    if not remote_parent.is_absolute() or ".." in remote_parent.parts:
        raise ValueError("remote_parent must be an absolute sandbox path")
    remote = str(remote_parent / run_id)
    remote_archive = str(remote_parent.parent / ("codex-pi-" + run_id + ".tar"))
    native_task = {"version": 1, "run_id": run_id, "task_id": task["task_id"], "kind": task["kind"], "instructions": task["instructions"], "workspace": remote + "/workspace", "output_directory": remote + "/results", "writable_paths": task["writable_paths"], "allowed_tools": sorted(TOOLS if task["writable_paths"] else TOOLS - {"write", "edit"}), "max_tool_calls": task.get("max_tool_calls", 40), "max_turns": task.get("max_turns", 32), "source": source, "checks": task["checks"]}
    if len(json.dumps(native_task).encode()) > 1024 * 1024:
        raise ValueError("Exported task manifest exceeds 1 MiB")
    launch = {"pi_argv": profile["pi_argv"], "model": profile["model"], "thinking": profile.get("thinking", "high"), "environment": profile.get("environment", {}), "checks": task["checks"], "wall_seconds": task.get("wall_seconds", 600)}
    archive_path = output / "inputs.tar"
    payload = {"task.json": json.dumps(native_task).encode(), "launch.json": json.dumps(launch).encode(), "coordinate.py": Path(__file__).read_bytes(), "extension.js": (PLUGIN / "extensions/coordination.js").read_bytes(), "package.json": b'{"type":"module"}'}
    payload.update({"workspace/" + p: b for p, b in files.items()})
    with tarfile.open(archive_path, "x") as archive:
        for name, data in payload.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = source["modes"].get(name.removeprefix("workspace/"), 0o600) if name.startswith("workspace/") else 0o600
            archive.addfile(info, io.BytesIO(data))
    receipt = {"version": 1, "run_id": run_id, "task_id": task["task_id"], "kind": task["kind"], "started_at": utc_now(), "source": source, "input_sha256": digest(archive_path.read_bytes()), "remote_artifacts": remote + "/results", "cleanup_complete": False, "outcome": "incomplete"}
    write_new_json(output / "started.json", receipt)
    with exclusive_owner(profile, lock_root) as journal:
        if journal.exists() and not read_json(journal).get("cleanup_complete"):
            raise ValueError("Earlier custody is unresolved; use reconcile after confirming the sandbox stopped")
        state = owner.verify()
        if state["phase"] != "Stopped":
            raise ValueError("Only an explicitly owned stopped disposable sandbox may be started")
        protected = {name: selected_state(owner.get(name)) for name in profile.get("protected_sandboxes", [])}
        if profile["sandbox_name"] in protected:
            raise ValueError("Disposable sandbox is also protected")
        receipt["sandbox_before"] = selected_state(state)
        def save_journal():
            journal.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        save_journal()  # Persist uncertain custody BEFORE the start RPC.
        previous_handlers = {}
        def interrupted(_signum, _frame):
            raise KeyboardInterrupt("Owner cancellation requested")
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, interrupted)
        try:
            owner.command("start", profile["sandbox_name"])
            state = owner.verify()
            if state["phase"] != "Ready" or not state.get("main_process_instance_id"):
                raise ValueError("Started sandbox is not Ready with a main instance")
            owner.main_instance = state["main_process_instance_id"]
            receipt["sandbox_running"] = selected_state(state)
            save_journal()
            owner.command("upload", "--no-git-ignore", profile["sandbox_name"], str(archive_path), remote_archive)
            bootstrap = """import pathlib,tarfile,hashlib,sys
p=pathlib.Path(sys.argv[1]); r=pathlib.Path(sys.argv[2])
assert hashlib.sha256(p.read_bytes()).hexdigest()==sys.argv[3]
assert sum(f.stat().st_size for f in r.parent.rglob('*') if f.is_file()) < 1024*1024*1024, 'retained sandbox workspace limit'
r.mkdir(parents=True,exist_ok=False)
with tarfile.open(p) as archive:
 for m in archive:
  assert m.isfile() and not pathlib.PurePosixPath(m.name).is_absolute() and '..' not in pathlib.PurePosixPath(m.name).parts
  target=r/m.name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(archive.extractfile(m).read()); target.chmod(m.mode & 0o777)
(r/'workspace').mkdir(exist_ok=True); (r/'results').mkdir(); p.unlink()
"""
            python = profile.get("python", "python3")
            owner.verify()
            owner.command("exec", profile["sandbox_name"], "--no-login-shell", "--no-tty", "--timeout", "60", "--", python, "-c", bootstrap, remote_archive, remote, receipt["input_sha256"])
            owner.verify()
            command = [*owner.argv, "sandbox", "exec", profile["sandbox_name"], "--no-login-shell", "--no-tty", "--timeout", str(launch["wall_seconds"] + 30), "--", python, remote + "/coordinate.py", "worker", remote]
            receipt["exec_exit_code"] = execute_to_log(command, output, output / "owner-exec.log", launch["wall_seconds"] + 45)
            if receipt["exec_exit_code"] != 0:
                raise ValueError("Remote worker failed; stop immediately before collecting artifacts")
            owner.verify()
            owner.command("download", profile["sandbox_name"], remote + "/results", str(output / "results"))
            receipt["download_complete"] = True
            worker_receipt = verify_return(output / "results", native_task, files, run_id)
            receipt["worker"] = worker_receipt
            receipt["artifacts_verified"] = True
            receipt["outcome"] = worker_receipt["outcome"]
        except BaseException as error:
            receipt["error"] = str(error)
        finally:
            for sig in previous_handlers:
                signal.signal(sig, signal.SIG_IGN)
            try:
                owner.verify()
                owner.command("stop", profile["sandbox_name"])
                state = owner.verify()
                receipt["sandbox_after"] = selected_state(state)
                receipt["cleanup_complete"] = state["phase"] == "Stopped"
            except BaseException as error:
                receipt["cleanup_error"] = str(error)
            try:
                receipt["protected_unchanged"] = all(selected_state(owner.get(name)) == before for name, before in protected.items())
            except BaseException as error:
                receipt["protected_readback_error"] = str(error)
            receipt["ended_at"] = utc_now()
            receipt["delivery_valid"] = receipt["cleanup_complete"] and receipt.get("protected_unchanged", False) and receipt.get("artifacts_verified", False) and receipt.get("exec_exit_code") == 0 and receipt["outcome"] == "returned"
            receipt["acceptance"] = "not_granted"
            save_journal()
            write_new_json(output / "receipt.json", receipt)
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    run = sub.add_parser("run", help="Delegate one task using a private runtime profile")
    run.add_argument("task", type=Path)
    run.add_argument("--profile", type=Path, default=Path.home() / ".config/codex-pi-coordination/profile.json")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--lock-root", type=Path, default=Path.home() / ".local/state/codex-pi-coordination")
    remote = sub.add_parser("worker", help=argparse.SUPPRESS)
    remote.add_argument("root", type=Path)
    reconcile = sub.add_parser("reconcile", help="Reconcile unresolved custody only after the exact sandbox is Stopped")
    reconcile.add_argument("--profile", type=Path, default=Path.home() / ".config/codex-pi-coordination/profile.json")
    reconcile.add_argument("--lock-root", type=Path, default=Path.home() / ".local/state/codex-pi-coordination")
    args = parser.parse_args(argv)
    try:
        if args.operation == "worker":
            return worker(args.root)
        if args.operation == "reconcile":
            profile = profile_settings(args.profile)
            with exclusive_owner(profile, args.lock_root) as journal:
                prior = read_json(journal)
                state = OpenShellOwner(profile).verify()
                expected = prior.get("sandbox_running", prior.get("sandbox_before", {}))
                if state["phase"] != "Stopped" or state["id"] != expected.get("id") or ("sandbox_running" in prior and state["main_process_instance_id"] != expected.get("main_process_instance_id")):
                    raise ValueError("Stopped custody has not been established")
                prior.update(cleanup_complete=True, reconciled_at=utc_now(), sandbox_after=selected_state(state))
                journal.write_text(json.dumps(prior, indent=2) + "\n")
            print(json.dumps({"cleanup_complete": True}))
            return 0
        receipt = run_task(args.task, args.profile, args.output, args.lock_root)
        print(json.dumps({"run_id": receipt["run_id"], "outcome": receipt["outcome"], "delivery_valid": receipt["delivery_valid"], "receipt": str(args.output / "receipt.json")}))
        return 0 if receipt["delivery_valid"] else 1
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error), "delivery_valid": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
