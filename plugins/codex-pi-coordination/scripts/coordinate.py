#!/usr/bin/env python3
"""Bounded Pi delegation and stopped-run evidence recovery in owned OpenShell.

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
import selectors
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
MAX_SESSION_BYTES = 16 * 1024 * 1024
MAX_RETAINED_BYTES = 1024 * 1024 * 1024
KINDS = {"implementation", "research", "review", "validation"}
TOOLS = {"read", "grep", "find", "ls", "write", "edit"}
THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
MODEL_IDENTIFIER_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}"
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
    try:
        units = len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        raise ValueError("Relative file path contains invalid Unicode") from None
    if units > 1024 or re.search(r"[\u00A0\u2000-\u200A\u202F\u205F\u3000]", value):
        raise ValueError("Relative file path exceeds native bounds or requires Unicode-space normalization")
    path = PurePosixPath(value)
    if value == "." or path.is_absolute() or any(p in ("..", ".git") for p in path.parts) or str(path) != value:
        raise ValueError("Unsafe relative file path")
    return value


def validate_task(task):
    required = {"version", "task_id", "kind", "instructions", "writable_paths", "checks"}
    optional = {"repository", "revision", "max_tool_calls", "max_turns", "wall_seconds"}
    if isinstance(task, dict) and type(task.get("version")) is int and task["version"] == 2:
        optional.add("run_options")
    if not isinstance(task, dict) or set(task) - required - optional or required - set(task):
        raise ValueError("Task fields do not match the versioned contract")
    if type(task["version"]) is not int or task["version"] not in (1, 2) or not isinstance(task["kind"], str) or task["kind"] not in KINDS:
        raise ValueError("Unsupported task version or kind")
    pattern = r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}" if task["version"] == 2 else r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}"
    if not isinstance(task["task_id"], str) or not re.fullmatch(pattern, task["task_id"]):
        raise ValueError("Invalid task_id")
    validate_run_options(task.get("run_options", {}))
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


def model_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(MODEL_IDENTIFIER_PATTERN, value) or "://" in value:
        raise ValueError("Expected a bounded model identifier, not a URL or command")
    return value


def validate_run_options(options):
    if not isinstance(options, dict) or set(options) - {"provider", "model", "thinking"} or (("provider" in options) != ("model" in options)):
        raise ValueError("run_options requires a provider/model pair and optional thinking")
    for key in ("provider", "model"):
        if key in options:
            model_identifier(options[key])
    if "thinking" in options and (not isinstance(options["thinking"], str) or options["thinking"] not in THINKING_LEVELS):
        raise ValueError("Unsupported thinking selection; omit it to inherit the profile")
    return options


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


def private_control_bytes(value):
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    if len(raw) > 1024 * 1024:
        raise ValueError("Conversation control exceeds 1 MiB")
    return raw


def write_private_control(path, value):
    raw = private_control_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def refuse_path_links(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("Conversation paths must be absolute")
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("Conversation path traverses a symbolic link")


def workspace_manifest(workspace):
    refuse_path_links(workspace)
    files = snapshot(workspace)
    directories = {".": stat.S_IMODE(Path(workspace).stat().st_mode)}
    for path in Path(workspace).rglob("*"):
        if path.is_dir():
            directories[relative_file(path.relative_to(workspace).as_posix())] = stat.S_IMODE(path.stat().st_mode)
    result = {"files": {name: {"sha256": digest(data), "mode": stat.S_IMODE((Path(workspace) / name).stat().st_mode)} for name, data in files.items()}, "directories": directories}
    if len(directories) > MAX_FILES or any(mode > 0o777 for mode in directories.values()) or any(value["mode"] > 0o777 for value in result["files"].values()):
        raise ValueError("Workspace directory or permission bounds exceeded")
    private_control_bytes(result)
    return result


def retained_storage_guard(parent):
    refuse_path_links(parent)
    total = 0
    for path in Path(parent).rglob("*"):
        if path.is_symlink():
            raise ValueError("Retained material contains a symbolic link")
        mode = path.stat().st_mode
        if stat.S_ISREG(mode):
            total += path.stat().st_size
        elif not stat.S_ISDIR(mode):
            raise ValueError("Retained material is not regular")
        if total > MAX_RETAINED_BYTES:
            raise ValueError("Retained material exceeds 1 GiB")
    return total


def saved_session_snapshot(path, workspace, *, expected=None, prefix=None):
    refuse_path_links(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_SESSION_BYTES:
            raise ValueError("Session must be a nonempty bounded regular file")
        raw = stream.read(MAX_SESSION_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(raw) != before.st_size or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or not raw.endswith(b"\n"):
        raise ValueError("Session changed while reading or has an incomplete tail")
    lines = raw[:-1].split(b"\n")
    entries = [json.loads(line.decode("utf-8")) for line in lines]
    header = entries[0]
    if not isinstance(header, dict) or header.get("type") != "session" or header.get("version") != 3 or not isinstance(header.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", header["id"]) or header.get("cwd") != str(workspace):
        raise ValueError("Session header identity, version or cwd differs")
    identifiers = set()
    for entry in entries[1:]:
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str) or entry["type"] == "session" or not isinstance(entry.get("id"), str) or not entry["id"] or entry["id"] in identifiers or "parentId" not in entry or entry["parentId"] is not None and entry["parentId"] not in identifiers:
            raise ValueError("Session contains an invalid or incomplete entry")
        identifiers.add(entry["id"])
    if not any(entry.get("type") == "message" and isinstance(entry.get("message"), dict) and entry["message"].get("role") == "assistant" for entry in entries[1:]):
        raise ValueError("Saved session has no persisted assistant history")
    result = {"id": header["id"], "file": str(path), "cwd": str(workspace), "bytes": len(raw), "sha256": digest(raw), "header_sha256": digest(lines[0])}
    if expected is not None and result != expected:
        raise ValueError("Session bytes or identity changed since checkpoint")
    if prefix is not None and (len(raw) < prefix["bytes"] or digest(raw[:prefix["bytes"]]) != prefix["sha256"] or any(result[key] != prefix[key] for key in ("id", "file", "cwd", "header_sha256"))):
        raise ValueError("Session replaced or rewrote its prior history")
    return result


def saved_descriptor(task):
    if task.get("version") != 3 or task.get("operation") not in {"run", "continue"}:
        raise ValueError("Expected saved version 3 task")
    session = task.get("session")
    if not isinstance(session, dict) or set(session) != {"conversation_id", "directory", "file", "prior", "prior_sha256"} or not re.fullmatch(r"[0-9a-f]{32}", str(session["conversation_id"])):
        raise ValueError("Invalid saved conversation descriptor")
    dispatch = Path(task["output_directory"]).parent
    directory = dispatch.parent / "conversations" / session["conversation_id"]
    if not dispatch.is_absolute() or dispatch.name != task["run_id"] or session["directory"] != str(directory) or session["file"] != str(directory / "session.jsonl") or task["workspace"] != str(directory / "workspace"):
        raise ValueError("Saved conversation paths differ from the owned dispatch")
    if task["operation"] == "run":
        if session["prior"] is not None or session["prior_sha256"] is not None or session["conversation_id"] != task["run_id"]:
            raise ValueError("New saved run must reserve its own fresh conversation")
    else:
        prior = session["prior"]
        if not isinstance(prior, dict) or prior.get("conversation_id") != session["conversation_id"] or not re.fullmatch(r"[0-9a-f]{32}", str(prior.get("run_id"))) or prior["run_id"] == task["run_id"] or digest(private_control_bytes(prior)) != session["prior_sha256"]:
            raise ValueError("Invalid prior conversation checkpoint binding")
    for path in (directory, dispatch, Path(task["workspace"]), Path(session["file"])):
        refuse_path_links(path)
    return session


def validate_native_task(task):
    if not isinstance(task, dict) or type(task.get("version")) is not int or task["version"] not in (1, 2, 3):
        raise ValueError("Unknown native task version")
    if task["version"] != 3:
        return
    fields = {"version", "run_id", "task_id", "kind", "instructions", "workspace", "output_directory", "writable_paths", "allowed_tools", "max_tool_calls", "max_turns", "source", "checks", "operation", "run_options", "runtime_defaults"}
    metadata = task.get("operation") == "capabilities_selected"
    if set(task) != fields | ({"selected_model"} if metadata else {"session"}):
        raise ValueError("Native version 3 fields differ from its explicit variant")
    public = {key: task[key] for key in ("task_id", "kind", "instructions", "writable_paths", "checks", "max_tool_calls", "max_turns", "run_options")}
    validate_task({"version": 2, **public})
    if metadata:
        if task["writable_paths"] or task["checks"] or task["run_options"] or set(validate_run_options(task["selected_model"])) != {"provider", "model"}:
            raise ValueError("Selected metadata cannot execute a task")
    else:
        saved_descriptor(task)
        if task["source"].get("kind") != "git" or not re.fullmatch(r"[0-9a-f]{40,64}", str(task["source"].get("commit"))):
            raise ValueError("Saved runs require an explicit committed source")


def prepare_saved_workspace(root, task):
    session = saved_descriptor(task)
    directory = Path(session["directory"])
    stable, staged = Path(task["workspace"]), root / "workspace"
    retained_storage_guard(root.parent)
    staged_manifest = workspace_manifest(staged)
    if {name: value["sha256"] for name, value in staged_manifest["files"].items()} != task["source"]["files"] or {name: value["mode"] for name, value in staged_manifest["files"].items()} != task["source"]["modes"]:
        raise ValueError("Staged source bytes or modes differ from approved source")
    prior = session["prior"]
    if prior is None:
        directory.parent.mkdir(mode=0o700, exist_ok=True)
        directory.mkdir(mode=0o700, exist_ok=False)
        backup = None
    else:
        if (directory / "pending.json").exists():
            raise ValueError("Conversation transition requires reconciliation")
        if read_json(directory / "checkpoint.json") != prior or digest((directory / "checkpoint.json").read_bytes()) != session["prior_sha256"]:
            raise ValueError("Stale or duplicate continuation checkpoint")
        saved_session_snapshot(Path(session["file"]), stable, expected=prior["session"])
        if workspace_manifest(stable) != prior["workspace"]:
            raise ValueError("Prior workspace bytes or modes changed")
        (directory / "retained").mkdir(mode=0o700, exist_ok=True)
        backup = directory / "retained" / prior["run_id"]
        if backup.exists():
            raise ValueError("Prior workspace backup already exists")
    intent = {"version": 1, "conversation_id": session["conversation_id"], "run_id": task["run_id"], "task_sha256": digest((root / "task.json").read_bytes()), "prior_sha256": session["prior_sha256"], "old_workspace": prior["workspace"] if prior else None, "new_workspace": staged_manifest, "staged": str(staged), "stable": str(stable), "backup": str(backup) if backup else None}
    write_private_control(directory / "pending.json", intent)
    if backup is not None:
        stable.rename(backup)
    staged.rename(stable)
    if workspace_manifest(stable) != staged_manifest:
        raise ValueError("Activated workspace differs from staged source")
    return session


def complete_saved_conversation(root, task, configuration, session_after):
    session = saved_descriptor(task)
    directory, workspace = Path(session["directory"]), Path(task["workspace"])
    prior = session["prior"]
    observed = saved_session_snapshot(Path(session["file"]), workspace, expected=session_after, prefix=prior["session"] if prior else None)
    if observed["id"] != configuration["session_id"] or observed["file"] != configuration["session_file"]:
        raise ValueError("Terminal session differs from admitted RPC identity")
    checkpoint = {"version": 1, "conversation_id": session["conversation_id"], "run_id": task["run_id"], "task_id": task["task_id"], "task_sha256": digest((root / "task.json").read_bytes()), "source_commit": task["source"]["commit"], "prior_run_id": prior["run_id"] if prior else None, "prior_checkpoint_sha256": session["prior_sha256"], "session": observed, "workspace": workspace_manifest(workspace)}
    retained_storage_guard(root.parent)
    checkpoint_path = directory / "checkpoint.json"
    if prior is None:
        if checkpoint_path.exists():
            raise ValueError("New conversation checkpoint already exists")
    elif digest(checkpoint_path.read_bytes()) != session["prior_sha256"]:
        raise ValueError("Conversation checkpoint changed during dispatch")
    write_private_control(root / "results/conversation.json", checkpoint)
    staged = directory / (task["run_id"] + ".checkpoint.json")
    write_private_control(staged, checkpoint)
    staged.replace(checkpoint_path)
    (directory / "pending.json").rename(root / "transition-completed.json")
    return {"checkpoint_sha256": digest(private_control_bytes(checkpoint)), "session_before": prior["session"] if prior else None, "session_after": observed, "prior_prefix_sha256": prior["session"]["sha256"] if prior else digest(b""), "continuable": True}


def verify_conversation(results, task, receipt):
    session = saved_descriptor(task)
    checkpoint = read_json(Path(results) / "conversation.json")
    prior = session["prior"]
    expected = {"version": 1, "conversation_id": session["conversation_id"], "run_id": task["run_id"], "task_id": task["task_id"], "task_sha256": digest(json.dumps(task).encode()), "source_commit": task["source"]["commit"], "prior_run_id": prior["run_id"] if prior else None, "prior_checkpoint_sha256": session["prior_sha256"]}
    if set(checkpoint) != set(expected) | {"session", "workspace"} or any(checkpoint.get(key) != value for key, value in expected.items()):
        raise ValueError("Conversation checkpoint task/source identity mismatch")
    saved = checkpoint["session"]
    configuration = receipt["configuration"]
    if not isinstance(saved, dict) or set(saved) != {"id", "file", "cwd", "bytes", "sha256", "header_sha256"} or saved["id"] != configuration["session_id"] or saved["file"] != session["file"] or saved["cwd"] != task["workspace"] or type(saved["bytes"]) is not int or not 0 < saved["bytes"] <= MAX_SESSION_BYTES or any(not re.fullmatch(r"[0-9a-f]{64}", str(saved[key])) for key in ("sha256", "header_sha256")):
        raise ValueError("Returned session does not bind the admitted identity")
    if prior and (saved["bytes"] < prior["session"]["bytes"] or any(saved[key] != prior["session"][key] for key in ("id", "file", "cwd", "header_sha256"))):
        raise ValueError("Returned session changed its prior identity")
    manifest = checkpoint["workspace"]
    if not isinstance(manifest, dict) or set(manifest) != {"files", "directories"} or any(not isinstance(manifest[key], dict) or len(manifest[key]) > MAX_FILES for key in manifest) or "." not in manifest["directories"]:
        raise ValueError("Invalid terminal workspace manifest")
    for name, value in manifest["files"].items():
        relative_file(name)
        if not isinstance(value, dict) or set(value) != {"sha256", "mode"} or not re.fullmatch(r"[0-9a-f]{64}", str(value["sha256"])) or type(value["mode"]) is not int or not 0 <= value["mode"] <= 0o777:
            raise ValueError("Invalid terminal file identity")
    for name, mode in manifest["directories"].items():
        if name != ".":
            relative_file(name)
        if type(mode) is not int or not 0 <= mode <= 0o777 or name in manifest["files"]:
            raise ValueError("Invalid terminal directory identity")
    expected_conversation = {"checkpoint_sha256": digest(private_control_bytes(checkpoint)), "session_before": prior["session"] if prior else None, "session_after": saved, "prior_prefix_sha256": prior["session"]["sha256"] if prior else digest(b""), "continuable": True}
    if receipt.get("conversation") != expected_conversation or receipt.get("extension", {}).get("session") != {"id": saved["id"], "file": saved["file"], "cwd": saved["cwd"], "version": 3}:
        raise ValueError("Returned conversation differs from terminal worker/extension bindings")
    return checkpoint


def inspect_saved_conversation(root, task, reconcile=False):
    """Inspect a stopped dispatch's files; never invoke Pi, checks or rollback."""
    session = saved_descriptor(task)
    directory, stable = Path(session["directory"]), Path(task["workspace"])
    retained_storage_guard(root.parent)
    checkpoint = read_json(directory / "checkpoint.json")
    current_session = saved_session_snapshot(Path(session["file"]), stable, expected=checkpoint["session"])
    pending = directory / "pending.json"
    if checkpoint.get("run_id") == task["run_id"]:
        if checkpoint != read_json(root / "results/conversation.json") or workspace_manifest(stable) != checkpoint["workspace"]:
            raise ValueError("Completed conversation checkpoint changed")
        if pending.exists():
            raise ValueError("Terminal checkpoint still has an unresolved transition")
        return {"disposition": "terminal_checkpoint", "continuable": True, "checkpoint": checkpoint, "session": current_session}
    if checkpoint != session["prior"] or digest((directory / "checkpoint.json").read_bytes()) != session["prior_sha256"]:
        raise ValueError("Saved conversation no longer matches this dispatch")
    if not pending.exists():
        if workspace_manifest(stable) != checkpoint["workspace"]:
            raise ValueError("Retained old workspace changed")
        return {"disposition": "unchanged_prior_checkpoint", "continuable": True, "checkpoint": checkpoint, "session": current_session}
    intent = read_json(pending)
    staged, backup = root / "workspace", directory / "retained" / checkpoint["run_id"]
    expected = {"version": 1, "conversation_id": session["conversation_id"], "run_id": task["run_id"], "task_sha256": digest((root / "task.json").read_bytes()), "prior_sha256": session["prior_sha256"], "old_workspace": checkpoint["workspace"], "staged": str(staged), "stable": str(stable), "backup": str(backup)}
    if set(intent) != set(expected) | {"new_workspace"} or any(intent[key] != value for key, value in expected.items()):
        raise ValueError("Transition intent does not bind this saved dispatch")
    if stable.exists() and not backup.exists() and staged.exists() and workspace_manifest(stable) == checkpoint["workspace"] and workspace_manifest(staged) == intent["new_workspace"]:
        if reconcile:
            destination = root / "transition-reconciled.json"
            if destination.exists():
                raise ValueError("Transition reconciliation evidence already exists")
            pending.rename(destination)
        return {"disposition": "old_checkpoint_reconciled" if reconcile else "old_checkpoint_requires_reconcile", "continuable": bool(reconcile), "checkpoint": checkpoint, "session": current_session}
    if stable.exists() and backup.exists() and not staged.exists() and workspace_manifest(stable) == intent["new_workspace"] and workspace_manifest(backup) == checkpoint["workspace"]:
        return {"disposition": "new_workspace_dispatch_unresolved", "continuable": False, "checkpoint": checkpoint, "session": current_session}
    raise ValueError("Partial or mixed saved workspace transition requires owner investigation")


def execute_to_log(argv, cwd, log, timeout, *, remote_owner=False, env=None, storage_parent=None):
    """Cap bytes and time. Remote descendants are stopped by the external owner."""
    started = time.monotonic()
    next_storage_check = started
    with Path(log).open("xb") as stream:
        process = subprocess.Popen(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, env=env)
        try:
            while process.poll() is None:
                if storage_parent is not None and time.monotonic() >= next_storage_check:
                    retained_storage_guard(storage_parent)
                    next_storage_check = time.monotonic() + 1
                if time.monotonic() - started > timeout or Path(log).stat().st_size > MAX_OUTPUT_BYTES:
                    raise TimeoutError("Command deadline or output limit exceeded")
                time.sleep(0.05)
            if Path(log).stat().st_size > MAX_OUTPUT_BYTES:
                raise ValueError("Command output limit exceeded")
            if storage_parent is not None:
                retained_storage_guard(storage_parent)
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
    allowed_kinds = {"task_loaded", "tool_call", "handoff", "agent_settled", "session_shutdown"}
    if task["version"] in (2, 3):
        allowed_kinds.add("run_configuration")
        if kinds.count("run_configuration") != 1 or kinds[1] != "run_configuration":
            raise ValueError("Missing or unordered extension run configuration")
    if set(kinds) - allowed_kinds or any(event.get("failure") for event in events):
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
    result = {"event_log_sha256": digest(raw), "model": events[0].get("model"), "tool_calls": len(calls), "assistant_turns": pi_events["assistant_turns"]}
    if task["version"] in (2, 3):
        result["configuration"] = validate_run_options(events[1].get("configuration"))
        if set(result["configuration"]) != {"provider", "model", "thinking"}:
            raise ValueError("Incomplete extension run configuration")
    if task.get("session"):
        saved_descriptor(task)
        session = events[0].get("session")
        if not isinstance(session, dict) or set(session) != {"id", "file", "cwd", "version"} or session.get("version") != 3 or session.get("file") != task["session"]["file"] or session.get("cwd") != task["workspace"] or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", str(session.get("id"))) or any(event.get("session") != session for event in events):
            raise ValueError("Extension saved session identity changed")
        if task["session"]["prior"] and session["id"] != task["session"]["prior"]["session"]["id"]:
            raise ValueError("Extension resumed a different official session")
        result["session"] = session
    return result


RPC_PROMPT = "Complete the assigned coordination task. Use coordination_status to inspect it and coordination_handoff to return your work. Do not execute verification commands; the coordinator runs declared checks after your handoff."


def rpc_model(value):
    if not isinstance(value, dict):
        raise ValueError("Missing RPC model identity")
    return {"provider": model_identifier(value.get("provider")), "id": model_identifier(value.get("id"))}


def rpc_data(command, data, session=None):
    """Discard model API objects, headers, URLs and free-form error messages."""
    if command == "get_available_models":
        if not isinstance(data, dict) or not isinstance(data.get("models"), list) or len(data["models"]) > 1000:
            raise ValueError("Invalid RPC model catalog")
        models = [rpc_model(model) for model in data["models"]]
        if len({(model["provider"], model["id"]) for model in models}) != len(models):
            raise ValueError("Duplicate RPC model identity")
        return {"models": models}
    if command == "get_available_thinking_levels":
        levels = data.get("levels") if isinstance(data, dict) else None
        if not isinstance(levels, list) or not levels or any(not isinstance(level, str) or level not in THINKING_LEVELS for level in levels) or len(set(levels)) != len(levels):
            raise ValueError("Invalid RPC thinking capabilities")
        return {"levels": levels}
    if command == "get_state":
        if not isinstance(data, dict) or any(type(data.get(key)) is not bool for key in ("isStreaming", "isCompacting")) or type(data.get("pendingMessageCount")) is not int or data["pendingMessageCount"] < 0:
            raise ValueError("Invalid RPC state")
        expected_file = session["file"] if session else None
        expected_id = session["prior"]["session"]["id"] if session and session["prior"] else None
        if data.get("sessionFile") != expected_file or not isinstance(data.get("sessionId"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", data["sessionId"]) or expected_id is not None and data["sessionId"] != expected_id:
            raise ValueError("RPC session differs from the exact saved or ephemeral contract")
        thinking = data.get("thinkingLevel")
        if not isinstance(thinking, str) or thinking not in THINKING_LEVELS:
            raise ValueError("Invalid effective thinking level")
        return {"model": rpc_model(data.get("model")), "thinkingLevel": thinking,
                "isStreaming": data["isStreaming"], "isCompacting": data["isCompacting"],
                "pendingMessageCount": data["pendingMessageCount"], "sessionId": data["sessionId"], "sessionFile": expected_file}
    if command == "set_model":
        return rpc_model(data)
    if command in {"set_thinking_level", "prompt"}:
        return None
    raise ValueError("Unexpected RPC command")


def configuration_event_record(value, request_id, command, arguments, previous_level):
    """Accept only the native, changing-level event of one authorized setter."""
    level = value.get("level")
    if value.get("type") != "thinking_level_changed" or not isinstance(level, str) or level not in THINKING_LEVELS or level == previous_level or command not in {"set_model", "set_thinking_level"}:
        raise ValueError("Unexpected or malformed RPC configuration event")
    if command == "set_thinking_level" and arguments.get("level") != level:
        raise ValueError("RPC thinking event differs from the requested selection")
    return {"type": "configuration_event", "id": request_id, "command": command,
            "event": "thinking_level_changed", "level": level}


class PiRpc:
    """One bounded stdlib RPC child; OpenShell remains its lifecycle owner."""
    def __init__(self, command, workspace, output, deadline, env, session=None):
        self.deadline, self.output = deadline, output
        self.session = session
        self.next_storage_check = 0
        self.pending, self.responses, self.records = {}, {}, []
        self.pending_arguments, self.configuration_events = {}, set()
        self.observed_thinking = None
        self.sequence, self.bytes_seen, self.settled = 0, 0, 0
        self.prompt_sent, self.stdin_closed = False, False
        self.buffer, self.outgoing = b"", b""
        self.selector = selectors.DefaultSelector()
        self.events = (output / "pi-events.jsonl").open("xb")
        (output / "rpc").mkdir(mode=0o700)
        self.stderr = (output / "rpc/stderr.log").open("xb")
        self.control = (output / "rpc-events.jsonl").open("x", encoding="utf-8")
        self.process = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            os.set_blocking(stream.fileno(), False)
        self.selector.register(self.process.stdout, selectors.EVENT_READ, "stdout")
        self.selector.register(self.process.stderr, selectors.EVENT_READ, "stderr")

    def record(self, value):
        self.records.append(value)
        if len(self.records) > 10000:
            raise ValueError("RPC record count exceeded")
        self.control.write(json.dumps(value, ensure_ascii=True) + "\n")
        self.control.flush()
        if self.control.tell() > MAX_OUTPUT_BYTES:
            raise ValueError("RPC control output exceeded")

    def send(self, command, **arguments):
        self.sequence += 1
        request_id = f"request-{self.sequence}"
        if command == "prompt":
            if self.prompt_sent:
                raise ValueError("A run permits exactly one prompt")
            self.prompt_sent = True
        self.pending[request_id] = command
        self.pending_arguments[request_id] = arguments
        retained = {"message_sha256": digest(arguments["message"].encode())} if command == "prompt" else arguments
        self.record({"type": "request", "id": request_id, "command": command, "arguments": retained})
        self.outgoing += (json.dumps({"id": request_id, "type": command, **arguments}) + "\n").encode()
        try:
            self.selector.register(self.process.stdin, selectors.EVENT_WRITE, "stdin")
        except KeyError:
            pass
        return request_id

    def consume(self, raw):
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise ValueError("Malformed Pi RPC JSONL") from None
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise ValueError("Malformed Pi RPC record")
        if value["type"] == "response":
            request_id = value.get("id")
            if not isinstance(request_id, str) or request_id not in self.pending or value.get("command") != self.pending[request_id]:
                raise ValueError("Unmatched or duplicate RPC response")
            command = self.pending.pop(request_id)
            arguments = self.pending_arguments.pop(request_id)
            if value.get("success") is not True:
                self.record({"type": "response", "id": request_id, "command": command, "success": False})
                raise ValueError("Pi RPC command refused: " + command)
            safe = rpc_data(command, value.get("data"), self.session)
            if command == "get_state":
                if self.observed_thinking is not None and safe["thinkingLevel"] != self.observed_thinking:
                    raise ValueError("RPC thinking changed without a bound configuration event")
                self.observed_thinking = safe["thinkingLevel"]
            elif command == "set_thinking_level" and arguments["level"] != self.observed_thinking:
                raise ValueError("RPC thinking acknowledgement lacks the requested level change")
            self.record({"type": "response", "id": request_id, "command": command, "success": True, "data": safe})
            self.responses[request_id] = safe
            return
        if value["type"] == "thinking_level_changed":
            if self.prompt_sent or len(self.pending) != 1:
                raise ValueError("Unsolicited RPC configuration event")
            request_id, command = next(iter(self.pending.items()))
            if request_id in self.configuration_events:
                raise ValueError("Repeated RPC configuration event")
            record = configuration_event_record(value, request_id, command, self.pending_arguments[request_id], self.observed_thinking)
            self.configuration_events.add(request_id)
            self.observed_thinking = record["level"]
            self.record(record)
            return
        if not self.prompt_sent or value["type"] in {"extension_ui_request", "error"}:
            raise ValueError("Unexpected activity outside the approved task prompt")
        if value["type"] == "agent_settled":
            self.settled += 1
            if self.settled != 1:
                raise ValueError("Unexpected repeated RPC settlement")
            self.record({"type": "event", "event": "agent_settled"})
        self.events.write(json.dumps(value, ensure_ascii=True).encode() + b"\n")
        self.events.flush()
        if self.events.tell() > MAX_OUTPUT_BYTES:
            raise ValueError("Pi event output exceeded")

    def pump(self):
        if self.session:
            if time.monotonic() >= self.next_storage_check:
                retained_storage_guard(Path(self.session["directory"]).parent.parent)
                self.next_storage_check = time.monotonic() + 1
            session_path = Path(self.session["file"])
            if session_path.is_symlink() or session_path.exists() and (not session_path.is_file() or session_path.stat().st_size > MAX_SESSION_BYTES) or self.session["prior"] is not None and not session_path.exists():
                raise ValueError("Saved session disappeared or exceeded observed bounds")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Pi RPC deadline exceeded")
        for key, _mask in self.selector.select(min(0.1, remaining)):
            if key.data == "stdin":
                try:
                    count = os.write(key.fd, self.outgoing)
                except BrokenPipeError:
                    raise ValueError("Pi RPC stdin closed before acknowledgement") from None
                self.outgoing = self.outgoing[count:]
                if not self.outgoing:
                    self.selector.unregister(key.fileobj)
                continue
            raw = os.read(key.fd, 65536)
            if not raw:
                self.selector.unregister(key.fileobj)
                if key.data == "stdout" and self.buffer:
                    raise ValueError("Partial Pi RPC JSONL at EOF")
                continue
            self.bytes_seen += len(raw)
            if self.bytes_seen > MAX_OUTPUT_BYTES:
                raise ValueError("Pi RPC aggregate output exceeded")
            if key.data == "stderr":
                self.stderr.write(raw)
                self.stderr.flush()
            else:
                self.buffer += raw
                while b"\n" in self.buffer:
                    line, self.buffer = self.buffer.split(b"\n", 1)
                    self.consume(line.removesuffix(b"\r"))
        if self.process.poll() is not None and not self.selector.get_map() and not self.stdin_closed:
            raise ValueError("Pi RPC exited before orderly shutdown")

    def wait(self, request_id):
        while request_id not in self.responses:
            self.pump()
        return self.responses[request_id]

    def call(self, command, **arguments):
        return self.wait(self.send(command, **arguments))

    def finish(self):
        if self.pending or self.outgoing:
            raise ValueError("RPC has unacknowledged commands")
        self.stdin_closed = True
        self.record({"type": "stdin_closed"})
        self.process.stdin.close()
        while self.process.poll() is None or self.selector.get_map():
            self.pump()
        if self.process.wait() != 0:
            raise ValueError("Pi RPC exited unsuccessfully")
        self.record({"type": "exit", "exit_code": 0})

    def close(self):
        # On error EOF is best effort, never proof of remote cleanup. The host
        # immediately enters its existing managed OpenShell stop path.
        if not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        self.selector.close()
        for stream in (self.process.stdout, self.process.stderr, self.events, self.stderr, self.control):
            stream.close()


def desired_configuration(task, models):
    requested = validate_run_options(task["run_options"])
    defaults = task["runtime_defaults"]
    if not isinstance(defaults, dict) or set(defaults) != {"model", "thinking"} or not isinstance(defaults["model"], str) or not isinstance(defaults["thinking"], str) or defaults["thinking"] not in THINKING_LEVELS:
        raise ValueError("Invalid bound runtime defaults")
    if "provider" in requested:
        candidates = [model for model in models if model["provider"] == requested["provider"] and model["id"] == requested["model"]]
    else:
        candidates = [model for model in models if model["provider"] + "/" + model["id"] == defaults["model"]]
    if len(candidates) != 1:
        raise ValueError("Requested model is unavailable or ambiguous")
    return {"provider": candidates[0]["provider"], "model": candidates[0]["id"], "thinking": requested.get("thinking", defaults["thinking"])}


def metadata_task(task):
    return task.get("operation") in {"capabilities", "capabilities_selected"}


def selected_metadata_model(task, models):
    selection = validate_run_options(task["selected_model"])
    if set(selection) != {"provider", "model"}:
        raise ValueError("Selected metadata requires exactly provider and model")
    matches = [model for model in models if model == {"provider": selection["provider"], "id": selection["model"]}]
    if len(matches) != 1:
        raise ValueError("Selected metadata model is unavailable or ambiguous")
    return selection


def require_rpc_idle(state, effective=None, session_id=None):
    if state["isStreaming"] or state["isCompacting"] or state["pendingMessageCount"] != 0:
        raise ValueError("Pi RPC is not idle with an empty queue")
    actual = {"provider": state["model"]["provider"], "model": state["model"]["id"], "thinking": state["thinkingLevel"]}
    if (effective is not None and actual != effective) or (session_id is not None and state["sessionId"] != session_id):
        raise ValueError("Pi effective model/thinking/session differs from the approved selection")
    return actual


def rpc_configuration_record(task, models, levels, effective, session_id, results):
    task_run = not metadata_task(task)
    record = {"version": 1, "operation": task["operation"], "requested": task["run_options"],
            "defaults": task["runtime_defaults"], "available_models": models,
            "supported_thinking_levels": levels, "effective": effective,
            "session_id": session_id, "session_file": None, "prompt_sent": task_run,
            "settled": task_run, "shutdown": "stdin-eof",
            "rpc_log_sha256": digest((results / "rpc-events.jsonl").read_bytes()),
            "stderr_sha256": digest((results / "rpc/stderr.log").read_bytes())}
    if task["operation"] == "capabilities_selected":
        record.update(version=2, requested=task["selected_model"],
                      profile_default_supported=task["runtime_defaults"]["thinking"] in levels)
    elif task.get("session"):
        record.update(version=2, session_file=task["session"]["file"])
    return record


def run_rpc(root, task, launch, deadline, env):
    metadata = metadata_task(task)
    selected_metadata = task["operation"] == "capabilities_selected"
    session = saved_descriptor(task) if task.get("session") else None
    session_arguments = ["--no-session"]
    if session:
        if session["prior"]:
            saved_session_snapshot(Path(session["file"]), Path(task["workspace"]), expected=session["prior"]["session"])
        elif Path(session["file"]).exists():
            raise ValueError("New saved session file must be absent")
        session_arguments = ["--session", session["file"], "--session-dir", session["directory"]]
    command = [*launch["pi_argv"], "--offline", *session_arguments, "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve", "--tools", "" if metadata else ",".join([*task["allowed_tools"], "coordination_status", "coordination_handoff"]), "--mode", "rpc"]
    if not metadata:
        command += ["--extension", str(root / "extension.js"), "--coordination-task", str(root / "task.json")]
    rpc = PiRpc(command, Path(task["workspace"]), root / "results", deadline, env, session=session)
    try:
        models_request = rpc.send("get_available_models")
        initial_request = rpc.send("get_state")
        models = rpc.wait(models_request)["models"]
        initial = rpc.wait(initial_request)
        observed = require_rpc_idle(initial)
        effective = observed if metadata else desired_configuration(task, models)
        if selected_metadata:
            effective = {**selected_metadata_model(task, models), "thinking": observed["thinking"]}
        model_changed = initial["model"] != {"provider": effective["provider"], "id": effective["model"]}
        if model_changed:
            selected = rpc.call("set_model", provider=effective["provider"], modelId=effective["model"])
            if selected != {"provider": effective["provider"], "id": effective["model"]}:
                raise ValueError("Pi selected a different model")
        levels = rpc.call("get_available_thinking_levels")["levels"]
        if not selected_metadata and effective["thinking"] not in levels:
            raise ValueError("Selected model does not support requested thinking")
        if not selected_metadata and (model_changed or initial["thinkingLevel"] != effective["thinking"]):
            rpc.call("set_thinking_level", level=effective["thinking"])
        admitted = rpc.call("get_state")
        if selected_metadata:
            effective = {**selected_metadata_model(task, models), "thinking": admitted["thinkingLevel"]}
            if effective["thinking"] not in levels:
                raise ValueError("Selected metadata thinking is not supported")
        require_rpc_idle(admitted, effective, initial["sessionId"])
        if not metadata:
            rpc.call("prompt", message=RPC_PROMPT)
            while not rpc.settled:
                rpc.pump()
            require_rpc_idle(rpc.call("get_state"), effective, initial["sessionId"])
        rpc.finish()
        configuration = rpc_configuration_record(task, models, levels, effective, initial["sessionId"], root / "results")
        write_new_json(root / "results/rpc-configuration.json", configuration)
        return configuration
    except Exception as error:
        if rpc.process.poll() is not None:
            error.pi_exit_code = rpc.process.returncode
        raise
    finally:
        rpc.close()


def verify_rpc_configuration(results, task):
    """Reconstruct configuration from sanitized control records and bound input."""
    raw = (results / "rpc-events.jsonl").read_bytes()
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ValueError("RPC transcript exceeds bounds")
    records = [json.loads(line) for line in raw.split(b"\n") if line]
    if not records or len(records) > 10000 or records[-2:] != [{"type": "stdin_closed"}, {"type": "exit", "exit_code": 0}]:
        raise ValueError("RPC transcript lacks orderly shutdown")
    requests, responses, events = [], {}, []
    observed_thinking, configuration_requests = None, set()
    for index, record in enumerate(records[:-2]):
        if not isinstance(record, dict):
            raise ValueError("Invalid RPC transcript record")
        kind = record.get("type")
        if kind == "request":
            if set(record) != {"type", "id", "command", "arguments"} or record["id"] != f"request-{len(requests) + 1}" or not isinstance(record["arguments"], dict):
                raise ValueError("Invalid RPC request binding")
            requests.append((index, record))
        elif kind == "response":
            if set(record) != {"type", "id", "command", "success", "data"} or record["success"] is not True or not isinstance(record["id"], str) or record["id"] in responses:
                raise ValueError("Invalid RPC response binding")
            matched = [request for _position, request in requests if request["id"] == record["id"]]
            if len(matched) != 1 or record["command"] != matched[0]["command"] or rpc_data(record["command"], record["data"], task.get("session")) != record["data"]:
                raise ValueError("RPC response differs from its safe request contract")
            if record["command"] == "get_state":
                thinking = record["data"]["thinkingLevel"]
                if observed_thinking is not None and thinking != observed_thinking:
                    raise ValueError("RPC state thinking differs from configuration events")
                observed_thinking = thinking
            elif record["command"] == "set_thinking_level" and matched[0]["arguments"].get("level") != observed_thinking:
                raise ValueError("RPC setter acknowledgement lacks its level change")
            responses[record["id"]] = (index, record["data"])
        elif kind == "configuration_event":
            pending = [request for _position, request in requests if request["id"] not in responses]
            if len(pending) != 1 or any(request["command"] == "prompt" for _position, request in requests):
                raise ValueError("Unsolicited returned RPC configuration event")
            request = pending[0]
            if request["id"] in configuration_requests:
                raise ValueError("Repeated returned RPC configuration event")
            expected_event = configuration_event_record({"type": record.get("event"), "level": record.get("level")}, request["id"], request["command"], request["arguments"], observed_thinking)
            if record != expected_event:
                raise ValueError("RPC configuration event is not bound to its operation")
            configuration_requests.add(request["id"])
            observed_thinking = record["level"]
        elif record == {"type": "event", "event": "agent_settled"}:
            events.append(index)
        else:
            raise ValueError("Unknown RPC control record")
    if len(requests) != len(responses) or len(requests) < 4:
        raise ValueError("Incomplete RPC command sequence")
    for number, (index, request) in enumerate(requests):
        # Only the first two metadata queries may be outstanding together.
        if number >= 2 and any(responses[prior["id"]][0] > index for _position, prior in requests[:number]):
            raise ValueError("RPC admission precedes required acknowledgement")
    def data(number):
        if number >= len(requests):
            raise ValueError("Incomplete RPC command sequence")
        return responses[requests[number][1]["id"]][1]
    if [request["command"] for _index, request in requests[:2]] != ["get_available_models", "get_state"]:
        raise ValueError("RPC metadata preflight missing")
    models, initial = data(0)["models"], data(1)
    observed = require_rpc_idle(initial)
    metadata = metadata_task(task)
    selected_metadata = task["operation"] == "capabilities_selected"
    effective = observed if metadata else desired_configuration(task, models)
    if selected_metadata:
        effective = {**selected_metadata_model(task, models), "thinking": observed["thinking"]}
    target_model = {"provider": effective["provider"], "id": effective["model"]}
    changed = initial["model"] != target_model
    expected = [("get_available_models", {}), ("get_state", {})]
    if changed:
        expected.append(("set_model", {"provider": effective["provider"], "modelId": effective["model"]}))
        if data(2) != target_model:
            raise ValueError("RPC returned the wrong selected model")
    levels_index = len(expected)
    expected.append(("get_available_thinking_levels", {}))
    levels = data(levels_index)["levels"]
    if not selected_metadata and effective["thinking"] not in levels:
        raise ValueError("RPC selected unsupported thinking")
    if not selected_metadata and (changed or initial["thinkingLevel"] != effective["thinking"]):
        expected.append(("set_thinking_level", {"level": effective["thinking"]}))
    admitted_index = len(expected)
    expected.append(("get_state", {}))
    if selected_metadata:
        effective = {**selected_metadata_model(task, models), "thinking": data(admitted_index)["thinkingLevel"]}
        if effective["thinking"] not in levels:
            raise ValueError("RPC selected metadata thinking is unsupported")
    if not metadata:
        expected += [("prompt", {"message_sha256": digest(RPC_PROMPT.encode())}), ("get_state", {})]
    if [(request["command"], request["arguments"]) for _index, request in requests] != expected:
        raise ValueError("RPC commands differ from approved options")
    require_rpc_idle(data(admitted_index), effective, initial["sessionId"])
    if metadata:
        if events or (results / "pi-events.jsonl").read_bytes():
            raise ValueError("Metadata discovery performed model activity")
    else:
        if len(events) != 1 or not requests[-2][0] < events[0] < requests[-1][0]:
            raise ValueError("RPC completion did not settle before final state read")
        require_rpc_idle(data(len(requests) - 1), effective, initial["sessionId"])
    expected_configuration = rpc_configuration_record(task, models, levels, effective, initial["sessionId"], results)
    if read_json(results / "rpc-configuration.json") != expected_configuration:
        raise ValueError("RPC configuration receipt differs from actual control records")
    return expected_configuration


def worker(root):
    """Runs only inside the caller-owned disposable OpenShell sandbox."""
    root = Path(root).resolve(strict=True)
    task, launch = read_json(root / "task.json"), read_json(root / "launch.json")
    validate_native_task(task)
    workspace, output = Path(task["workspace"]), root / "results"
    receipt = {"version": task["version"], "run_id": task["run_id"], "task_id": task["task_id"], "started_at": utc_now(), "outcome": "incomplete", "checks": []}
    write_new_json(root / "worker-started.json", receipt)
    deadline = time.monotonic() + launch["wall_seconds"]
    try:
        if task.get("session"):
            prepare_saved_workspace(root, task)
        before = snapshot(workspace)
        if {p: digest(b) for p, b in before.items()} != task["source"]["files"]:
            raise ValueError("Exported source differs from frozen source")
        command = [*launch["pi_argv"], "--model", launch["model"], "--thinking", launch["thinking"], "--offline", "--no-session", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve", "--tools", ",".join([*task["allowed_tools"], "coordination_status", "coordination_handoff"]), "--extension", str(root / "extension.js"), "--coordination-task", str(root / "task.json"), "--mode", "json", "-p", "Complete the assigned coordination task. Use coordination_status to inspect it and coordination_handoff to return your work. Do not execute verification commands; the coordinator runs declared checks after your handoff."]
        env = os.environ.copy()
        env.update(launch["environment"])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if task["version"] in (2, 3):
            receipt["configuration"] = run_rpc(root, task, launch, deadline, env)
            receipt["pi_exit_code"] = 0
            if metadata_task(task):
                if snapshot(workspace) != before:
                    raise ValueError("Metadata discovery changed source")
                receipt["outcome"] = "capabilities"
                receipt["acceptance"] = "not_granted"
                receipt["artifact_sha256"] = {name: digest(data) for name, data in snapshot(output).items()}
                return 0
        else:
            receipt["pi_exit_code"] = execute_to_log(command, workspace, output / "pi-events.jsonl", deadline - time.monotonic(), remote_owner=True, env=env)
        if receipt["pi_exit_code"] != 0:
            raise ValueError("Pi exited unsuccessfully")
        receipt["events"] = inspect_events(output / "pi-events.jsonl", task["max_tool_calls"], task["max_turns"])
        receipt["extension"] = inspect_extension_events(output / "extension-events.jsonl", task, receipt["events"], digest((root / "task.json").read_bytes()))
        if task["version"] in (2, 3) and receipt["extension"].get("configuration") != receipt["configuration"]["effective"]:
            raise ValueError("Extension effective options differ from RPC admission")
        if task.get("session"):
            session_after = saved_session_snapshot(Path(task["session"]["file"]), workspace, prefix=task["session"]["prior"]["session"] if task["session"]["prior"] else None)
            if receipt["extension"].get("session") != {"id": receipt["configuration"]["session_id"], "file": task["session"]["file"], "cwd": task["workspace"], "version": 3}:
                raise ValueError("Extension saved-session identity differs from RPC")
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
            code = execute_to_log(check["argv"], workspace, log, min(check["timeout_seconds"], deadline - time.monotonic()), remote_owner=True, env=env, storage_parent=root.parent if task.get("session") else None)
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
        if task.get("session"):
            receipt["conversation"] = complete_saved_conversation(root, task, receipt["configuration"], session_after)
        receipt["outcome"] = "returned" if report.get("status") == "completed" and receipt["checks_passed"] is not False and receipt["model_report_matches_changes"] else "failed"
        receipt["acceptance"] = "not_granted"
        receipt["artifact_sha256"] = {name: digest(data) for name, data in snapshot(output).items()}
    except Exception as error:
        if getattr(error, "pi_exit_code", None) is not None:
            receipt["pi_exit_code"] = error.pi_exit_code
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
    if receipt.get("version") != task["version"]:
        raise ValueError("Worker receipt version differs from task")
    metadata = metadata_task(task)
    if receipt.get("run_id") != run_id or receipt.get("task_id") != task["task_id"] or receipt.get("outcome") != ("capabilities" if metadata else "returned") or type(receipt.get("pi_exit_code")) is not int or receipt["pi_exit_code"] != 0 or receipt.get("acceptance") != "not_granted":
        raise ValueError("Worker identity or completion contract mismatch")
    if task["version"] in (2, 3):
        configuration = verify_rpc_configuration(results, task)
        if receipt.get("configuration") != configuration:
            raise ValueError("Worker configuration differs from the verified RPC return")
        if metadata:
            if set(actual) != {"worker-receipt.json", "rpc-events.jsonl", "pi-events.jsonl", "rpc/stderr.log", "rpc-configuration.json"} or task["writable_paths"] or task["checks"]:
                raise ValueError("Metadata return contains task execution artifacts")
            return receipt
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
    if task["version"] in (2, 3) and extension.get("configuration") != configuration["effective"]:
        raise ValueError("Extension configuration differs from the verified RPC return")
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
    verify_changes(results, actual, task, source_files, receipt, report)
    if task.get("session"):
        verify_conversation(results, task, receipt)
    return receipt


def verify_changes(results, actual, task, source_files, receipt, report):
    """Bind a complete change manifest to source and scope for either outcome."""
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


def profile_settings(path, *, require_qualified_model=False):
    profile = read_json(path)
    required = {"sandbox_name", "sandbox_id", "pi_argv", "model"}
    optional = {"openshell_argv", "python", "remote_parent", "thinking", "environment", "protected_sandboxes"}
    if not isinstance(profile, dict) or required - set(profile) or set(profile) - required - optional:
        raise ValueError("Profile fields do not match the contract")
    for key in required - {"pi_argv"}:
        if not isinstance(profile[key], str) or not profile[key] or profile[key].startswith("-"):
            raise ValueError("Invalid profile " + key)
    # New defaults/runs need qualified syntax without choosing a slash boundary.
    # Recovery/reconcile preserve legacy selectors without executing model work.
    # Exact provider/model selection still requires an unambiguous runtime catalog.
    if require_qualified_model and (not re.fullmatch(f"{MODEL_IDENTIFIER_PATTERN}/{MODEL_IDENTIFIER_PATTERN}", profile["model"]) or "://" in profile["model"]):
        raise ValueError("Profile model must be a bounded provider/model identifier")
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
    if not isinstance(profile.get("thinking", "high"), str) or profile.get("thinking", "high") not in THINKING_LEVELS:
        raise ValueError("Invalid thinking level")
    if not isinstance(profile.get("python", "python3"), str) or not profile.get("python", "python3") or "\x00" in profile.get("python", "python3"):
        raise ValueError("Invalid Python executable")
    if not isinstance(profile.get("remote_parent", "/sandbox/codex-pi"), str):
        raise ValueError("remote_parent must be a path string")
    remote_parent = PurePosixPath(profile.get("remote_parent", "/sandbox/codex-pi"))
    if not remote_parent.is_absolute() or ".." in remote_parent.parts:
        raise ValueError("remote_parent must be an absolute sandbox path")
    return profile


def effective_profile_settings(profile):
    return {"openshell_argv": ["openshell"], "python": "python3", "remote_parent": "/sandbox/codex-pi",
            "thinking": "high", "environment": {}, "protected_sandboxes": [], **profile}


def configure_profile(source, destination=None):
    """Register private settings without overwriting another default or provider."""
    profile = profile_settings(source, require_qualified_model=True)
    destination = Path(destination) if destination is not None else Path.home() / ".config/codex-pi-coordination/profile.json"
    destination = destination.absolute()
    for path in (destination, *destination.parents):
        if path.is_symlink():
            raise ValueError("Default profile path must not traverse symlinks")
    missing = []
    parent = destination.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir(mode=0o700)
    directory = destination.parent.stat()
    if directory.st_uid != os.getuid() or stat.S_IMODE(directory.st_mode) != 0o700:
        raise ValueError("Default profile directory must be owned and private (0700)")
    if destination.exists():
        current = destination.stat()
        if current.st_uid != os.getuid() or stat.S_IMODE(current.st_mode) != 0o600 or effective_profile_settings(profile_settings(destination)) != effective_profile_settings(profile):
            raise ValueError("Existing default profile differs or is not private; preserved")
        return {"configured": True, "changed": False, "runtime_verified": False}
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(profile, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    return {"configured": True, "changed": True, "runtime_verified": False}


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


@contextlib.contextmanager
def owner_interruptions():
    """Restore caller handlers even when cleanup or receipt persistence fails."""
    previous_handlers = {}
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt("Owner cancellation requested")
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, interrupted)
        yield previous_handlers
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def start_owned_instance(owner, profile, receipt, save_journal):
    """Bind only a fresh Ready main observed after a successful start RPC."""
    admitted_main = receipt["sandbox_before"]["main_process_instance_id"]
    owner.main_instance = admitted_main
    owner.command("start", profile["sandbox_name"])
    state = owner.get()
    if state.get("id") != profile["sandbox_id"]:
        raise ValueError("Sandbox ownership identity changed after start")
    if state["phase"] != "Ready" or not state.get("main_process_instance_id") or state["main_process_instance_id"] == admitted_main:
        raise ValueError("Start requires a fresh Ready main instance")
    owner.main_instance = state["main_process_instance_id"]
    receipt["sandbox_running"] = selected_state(state)
    save_journal()


def cleanup_owner(owner, profile, receipt, protected):
    """Stop only the bound fresh instance and retain uncertain cleanup."""
    try:
        state = owner.verify()
        if "sandbox_running" in receipt:
            owner.command("stop", profile["sandbox_name"])
            state = owner.verify()
        elif selected_state(state) != receipt["sandbox_before"]:
            raise ValueError("Fresh instance was not bound; refusing stop")
        receipt["sandbox_after"] = selected_state(state)
        receipt["cleanup_complete"] = state["phase"] == "Stopped"
    except BaseException as error:
        receipt["cleanup_error"] = str(error)
    try:
        receipt["protected_unchanged"] = all(selected_state(owner.get(name)) == before for name, before in protected.items())
    except BaseException as error:
        receipt["protected_readback_error"] = str(error)


def continuation_checkpoint(previous_directory, profile):
    previous_directory = Path(previous_directory).absolute()
    previous = read_json(previous_directory / "receipt.json")
    recovered = previous.get("operation") == "recovery"
    origin = Path(previous["recovered_from"]) if recovered and "recovered_from" in previous else previous_directory
    original, task, files, hashes = recovery_inputs(origin, profile, allow_saved_success=True)
    if task["version"] != 3 or not task.get("session") or previous.get("cleanup_complete") is not True or previous.get("protected_unchanged") is not True:
        raise ValueError("Continue requires verified stopped saved-session custody")
    if recovered:
        if previous.get("recovery_valid") is not True or previous.get("original_artifact_sha256") != hashes or previous.get("failed_run_id") != task["run_id"]:
            raise ValueError("Recovery does not bind the original saved dispatch")
        evidence = verify_recovered_artifacts(previous_directory / "results", task, files)
        checkpoint = previous.get("continuation_checkpoint")
        inspection = read_json(previous_directory / "conversation-inspection.json")
        if previous.get("conversation_valid") is not True or previous.get("inspection_sha256") != digest((previous_directory / "conversation-inspection.json").read_bytes()) or inspection.get("continuable") is not True or inspection.get("checkpoint") != checkpoint:
            raise ValueError("Recovered conversation is not continuable")
        if checkpoint != task["session"]["prior"]:
            if evidence.get("conversation_valid") is not True or checkpoint != read_json(previous_directory / "results/conversation.json"):
                raise ValueError("Recovered terminal checkpoint differs from evidence")
        return checkpoint
    else:
        if original.get("delivery_valid") is not True:
            raise ValueError("Recover the failed saved dispatch before continuing")
        verify_return(previous_directory / "results", task, files, task["run_id"])
    checkpoint = read_json(previous_directory / "results/conversation.json")
    return checkpoint


def run_task(task_file, profile_file, output, lock_root, *, capabilities_only=False, selected_model=None, save_session=False, previous_directory=None):
    if selected_model is not None:
        if not capabilities_only or set(validate_run_options(selected_model)) != {"provider", "model"}:
            raise ValueError("Selected metadata requires exactly provider and model")
    task = validate_task({"version": 2, "task_id": "capabilities", "kind": "validation", "instructions": "Inspect configured runtime metadata without model work.", "writable_paths": [], "checks": [], "wall_seconds": 30} if capabilities_only else read_json(task_file))
    profile = profile_settings(profile_file, require_qualified_model=True)
    files, source = frozen_source(task)
    if capabilities_only and (save_session or previous_directory is not None):
        raise ValueError("Metadata cannot create or continue a saved conversation")
    saved = save_session or previous_directory is not None
    if saved and source.get("kind") != "git":
        raise ValueError("Saved dispatch requires an explicit committed source")
    prior = continuation_checkpoint(previous_directory, profile) if previous_directory is not None else None
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    owner, run_id = OpenShellOwner(profile), uuid.uuid4().hex
    remote_parent = PurePosixPath(profile.get("remote_parent", "/sandbox/codex-pi"))
    if not remote_parent.is_absolute() or ".." in remote_parent.parts:
        raise ValueError("remote_parent must be an absolute sandbox path")
    remote = str(remote_parent / run_id)
    remote_archive = str(remote_parent.parent / ("codex-pi-" + run_id + ".tar"))
    native_task = {"version": 2, "run_id": run_id, "task_id": task["task_id"], "kind": task["kind"], "instructions": task["instructions"], "workspace": remote + "/workspace", "output_directory": remote + "/results", "writable_paths": task["writable_paths"], "allowed_tools": sorted(TOOLS if task["writable_paths"] else TOOLS - {"write", "edit"}), "max_tool_calls": task.get("max_tool_calls", 40), "max_turns": task.get("max_turns", 32), "source": source, "checks": task["checks"], "operation": "capabilities" if capabilities_only else "run", "run_options": task.get("run_options", {}), "runtime_defaults": {"model": profile["model"], "thinking": profile.get("thinking", "high")}}
    if selected_model is not None:
        native_task.update(version=3, operation="capabilities_selected", selected_model=selected_model)
    if saved:
        conversation_id = prior["conversation_id"] if prior else run_id
        conversation_directory = str(remote_parent / "conversations" / conversation_id)
        native_task.update(version=3, operation="continue" if prior else "run", workspace=conversation_directory + "/workspace", session={"conversation_id": conversation_id, "directory": conversation_directory, "file": conversation_directory + "/session.jsonl", "prior": prior, "prior_sha256": digest(private_control_bytes(prior)) if prior else None})
    validate_native_task(native_task)
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
    receipt = {"version": native_task["version"], "run_id": run_id, "task_id": task["task_id"], "kind": task["kind"], "started_at": utc_now(), "source": source, "input_sha256": digest(archive_path.read_bytes()), "remote_artifacts": remote + "/results", "cleanup_complete": False, "outcome": "incomplete"}
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
        with owner_interruptions() as previous_handlers:
            try:
                start_owned_instance(owner, profile, receipt, save_journal)
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
                cleanup_owner(owner, profile, receipt, protected)
                receipt["ended_at"] = utc_now()
                receipt["delivery_valid"] = receipt["cleanup_complete"] and receipt.get("protected_unchanged", False) and receipt.get("artifacts_verified", False) and receipt.get("exec_exit_code") == 0 and receipt["outcome"] == "returned"
                receipt["capabilities_valid"] = receipt["cleanup_complete"] and receipt.get("protected_unchanged", False) and receipt.get("artifacts_verified", False) and receipt.get("exec_exit_code") == 0 and receipt["outcome"] == "capabilities"
                receipt["acceptance"] = "not_granted"
                save_journal()
                write_new_json(output / "receipt.json", receipt)
    return receipt


def recovery_inputs(failed_directory, profile, *, allow_saved_success=False):
    """Read only the retained export, never the current repository or remote path."""
    failed_directory = Path(failed_directory)
    if failed_directory.is_symlink() or not failed_directory.is_dir():
        raise ValueError("Expected a regular failed-run directory")
    started = read_json(failed_directory / "started.json")
    original = read_json(failed_directory / "receipt.json")
    if not isinstance(started, dict) or not isinstance(original, dict) or original.get("delivery_valid") is not False and not (allow_saved_success and original.get("version") == 3 and original.get("delivery_valid") is True):
        raise ValueError("Only a retained unsuccessful delivery may be recovered")
    run_id = original.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("Invalid failed run identity")
    for key in ("version", "run_id", "task_id", "kind", "started_at", "source", "input_sha256", "remote_artifacts"):
        if key not in started or started[key] != original.get(key):
            raise ValueError("Original start/receipt binding mismatch")
    archive_path = failed_directory / "inputs.tar"
    if archive_path.is_symlink() or not archive_path.is_file() or archive_path.stat().st_size > MAX_SOURCE_BYTES + 16 * 1024 * 1024:
        raise ValueError("Expected bounded regular retained input archive")
    archive_bytes = archive_path.read_bytes()
    if digest(archive_bytes) != original["input_sha256"]:
        raise ValueError("Original input archive digest mismatch")
    payload = safe_archive_files(archive_bytes)
    required = {"task.json", "launch.json", "coordinate.py", "extension.js", "package.json"}
    if required - payload.keys() or any(name not in required and not name.startswith("workspace/") for name in payload):
        raise ValueError("Unexpected retained input members")
    if any(len(payload[name]) > 1024 * 1024 for name in ("task.json", "launch.json")):
        raise ValueError("Retained task/launch exceeds JSON bound")
    task, launch = json.loads(payload["task.json"]), json.loads(payload["launch.json"])
    if not isinstance(task, dict) or not isinstance(launch, dict):
        raise ValueError("Invalid retained task/launch")
    expected_keys = {"version", "run_id", "task_id", "kind", "instructions", "workspace", "output_directory", "writable_paths", "allowed_tools", "max_tool_calls", "max_turns", "source", "checks"}
    if task.get("version") in (2, 3):
        expected_keys |= {"operation", "run_options", "runtime_defaults"}
        if task.get("version") == 3:
            expected_keys.add("session")
        if task.get("operation") not in ({"run", "continue"} if task.get("version") == 3 else {"run"}):
            raise ValueError("Only task execution evidence is recoverable")
    if set(task) != expected_keys:
        raise ValueError("Unexpected retained native task fields")
    public_task = {key: task[key] for key in ("version", "task_id", "kind", "instructions", "writable_paths", "checks", "max_tool_calls", "max_turns")}
    if task["version"] in (2, 3):
        public_task["version"] = 2
        public_task["run_options"] = task["run_options"]
        if task["runtime_defaults"] != {"model": launch.get("model"), "thinking": launch.get("thinking")}:
            raise ValueError("Retained runtime defaults differ from launch")
    validate_task(public_task)
    validate_native_task(task)
    remote = str(PurePosixPath(profile.get("remote_parent", "/sandbox/codex-pi")) / run_id)
    expected_workspace = task["session"]["directory"] + "/workspace" if task.get("session") else remote + "/workspace"
    if task["run_id"] != run_id or task["task_id"] != original["task_id"] or task["kind"] != original["kind"] or task["source"] != original["source"] or task["workspace"] != expected_workspace or task["output_directory"] != remote + "/results" or original["remote_artifacts"] != task["output_directory"]:
        raise ValueError("Retained task/source/remote identity mismatch")
    if task["allowed_tools"] != sorted(TOOLS if task["writable_paths"] else TOOLS - {"write", "edit"}) or launch.get("checks") != task["checks"]:
        raise ValueError("Retained tools/check contract mismatch")
    source_files = {relative_file(name.removeprefix("workspace/")): data for name, data in payload.items() if name.startswith("workspace/")}
    source = task["source"]
    if not isinstance(source, dict) or source.get("files") != {name: digest(data) for name, data in source_files.items()} or not isinstance(source.get("modes"), dict) or set(source["modes"]) != set(source_files) or any(mode not in (0o644, 0o755) for mode in source["modes"].values()):
        raise ValueError("Retained source bytes differ from source manifest")
    if payload["task.json"] != json.dumps(task).encode():
        raise ValueError("Retained native task serialization mismatch")
    hashes = {name: digest((failed_directory / name).read_bytes()) for name in ("started.json", "receipt.json", "inputs.tar")}
    return original, task, source_files, hashes


def verify_recovered_artifacts(results, task, source_files):
    """Validate available failure evidence without granting a successful return.

    Missing terminal records are unknown. Contradictory present records fail.
    Hashes establish byte consistency, not independent issuer authenticity.
    """
    results = Path(results)
    if results.is_symlink() or not results.is_dir():
        raise ValueError("Expected a regular recovered results directory")
    actual = snapshot(results)
    allowed = {"worker-receipt.json", "model-report.json", "pi-events.jsonl", "extension-events.jsonl", "changes.json", "changes.patch"}
    if task["version"] in (2, 3):
        allowed |= {"rpc-events.jsonl", "rpc/stderr.log", "rpc-configuration.json"}
    if task.get("session"):
        allowed.add("conversation.json")
    allowed.update(check["name"] + suffix for check in task["checks"] for suffix in (".started.json", ".result.json", ".log"))
    if any(name not in allowed and not name.startswith("changed-files/") for name in actual):
        raise ValueError("Unexpected recovered artifact")
    worker_receipt = read_json(results / "worker-receipt.json") if "worker-receipt.json" in actual else {}
    if not isinstance(worker_receipt, dict):
        raise ValueError("Invalid recovered worker receipt")
    if "worker-receipt.json" in actual and (worker_receipt.get("run_id") != task["run_id"] or worker_receipt.get("task_id") != task["task_id"] or worker_receipt.get("outcome") not in {"returned", "failed", "incomplete"}):
        raise ValueError("Recovered worker identity/outcome mismatch")
    if "version" in worker_receipt and worker_receipt["version"] != task["version"]:
        raise ValueError("Recovered worker version differs from task")
    if "acceptance" in worker_receipt and worker_receipt["acceptance"] != "not_granted":
        raise ValueError("Recovered worker claims unauthorized acceptance")
    if task["version"] in (2, 3):
        for name in ("rpc-events.jsonl", "rpc/stderr.log"):
            if len(actual.get(name, b"")) > MAX_OUTPUT_BYTES:
                raise ValueError("Recovered RPC output exceeds limit")
        if "rpc-configuration.json" in actual:
            configuration = verify_rpc_configuration(results, task)
            if "configuration" in worker_receipt and worker_receipt["configuration"] != configuration:
                raise ValueError("Recovered RPC configuration differs from worker")
        elif "configuration" in worker_receipt:
            raise ValueError("Recovered worker configuration lacks its artifact")
        if {"events", "extension", "model_report_sha256", "checks_passed"} & worker_receipt.keys() and "configuration" not in worker_receipt:
            raise ValueError("Recovered post-Pi records lack RPC admission evidence")
    manifest = {name: digest(data) for name, data in actual.items() if name != "worker-receipt.json"}
    if "artifact_sha256" in worker_receipt and worker_receipt["artifact_sha256"] != manifest:
        raise ValueError("Recovered artifact manifest differs from actual bytes")
    if "pi_exit_code" in worker_receipt and type(worker_receipt["pi_exit_code"]) is not int:
        raise ValueError("Invalid recovered Pi exit code")
    if any(len(actual.get(name, b"")) > MAX_OUTPUT_BYTES for name in ("pi-events.jsonl", "extension-events.jsonl")):
        raise ValueError("Recovered event output exceeds limit")
    task_hash = digest(json.dumps(task).encode())
    report = read_json(results / "model-report.json") if "model-report.json" in actual else {}
    if "model-report.json" in actual:
        if not isinstance(report, dict) or report.get("task_sha256") != task_hash or report.get("task_id") != task["task_id"] or report.get("run_id") != task["run_id"] or report.get("model_self_report") is not True or report.get("status") not in {"completed", "blocked", "failed"}:
            raise ValueError("Recovered model report does not bind this task")
        if not isinstance(report.get("changed_files"), list) or any(not isinstance(name, str) for name in report["changed_files"]) or set(report["changed_files"]) - set(task["writable_paths"]):
            raise ValueError("Recovered report changed-file scope mismatch")
    if "model_report_sha256" in worker_receipt:
        recorded_hash = worker_receipt["model_report_sha256"]
        if not isinstance(recorded_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded_hash) or recorded_hash != manifest.get("model-report.json"):
            raise ValueError("Recovered model report bytes mismatch")
    for record in (worker_receipt, report):
        if "changed_files" in record:
            names = record["changed_files"]
            if not isinstance(names, list) or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
                raise ValueError("Recovered changed-file list is invalid")
            if set(relative_file(name) for name in names) - set(task["writable_paths"]):
                raise ValueError("Recovered changed-file list exceeds scope")
    if "changed_files" in worker_receipt and "changed_files" in report:
        lists_match = sorted(worker_receipt["changed_files"]) == sorted(report["changed_files"])
        if not lists_match:
            raise ValueError("Recovered worker/report changed-file binding mismatch")
        if "model_report_matches_changes" in worker_receipt and worker_receipt["model_report_matches_changes"] is not lists_match:
            raise ValueError("Recovered change-match summary contradicts present lists")
    if "model_report_matches_changes" in worker_receipt and type(worker_receipt["model_report_matches_changes"]) is not bool:
        raise ValueError("Recovered change-match summary must be boolean")
    events = None
    if "events" in worker_receipt:
        if "pi-events.jsonl" not in actual:
            raise ValueError("Recorded Pi events are missing")
        events = inspect_events(results / "pi-events.jsonl", task["max_tool_calls"], task["max_turns"])
        if worker_receipt["events"] != events:
            raise ValueError("Recovered Pi event binding mismatch")
    if "extension" in worker_receipt:
        if events is None or "extension-events.jsonl" not in actual or worker_receipt["extension"] != inspect_extension_events(results / "extension-events.jsonl", task, events, task_hash):
            raise ValueError("Recovered extension binding mismatch")
        if task["version"] in (2, 3) and worker_receipt["extension"].get("configuration") != worker_receipt.get("configuration", {}).get("effective"):
            raise ValueError("Recovered extension/RPC configuration differs")
    # An interrupted final JSONL write may be incomplete. Every complete extension
    # record that is present must still bind the retained task, even without a receipt.
    if "extension-events.jsonl" in actual:
        lines = actual["extension-events.jsonl"].splitlines(keepends=True)
        for index, line in enumerate(lines):
            try:
                event = json.loads(line)
            except ValueError:
                if index == len(lines) - 1 and not line.endswith(b"\n") and "extension" not in worker_receipt:
                    break
                raise ValueError("Malformed recovered extension record") from None
            if not isinstance(event, dict) or any(event.get(key) != expected for key, expected in (("run_id", task["run_id"]), ("task_id", task["task_id"]), ("task_sha256", task_hash))):
                raise ValueError("Recovered extension task binding mismatch")
    checks, completed_results = [], []
    for expected in task["checks"]:
        name = expected["name"]
        started = read_json(results / (name + ".started.json")) if name + ".started.json" in actual else None
        result = read_json(results / (name + ".result.json")) if name + ".result.json" in actual else None
        log = actual.get(name + ".log")
        for record in (started, result):
            if record is not None and (not isinstance(record, dict) or record.get("name") != name or record.get("argv") != expected["argv"] or not isinstance(record.get("started_at"), str)):
                raise ValueError("Recovered check does not bind declared argv")
        if (log is not None or result is not None) and started is None:
            raise ValueError("Recovered check lacks its start binding")
        if log is not None and len(log) > MAX_OUTPUT_BYTES:
            raise ValueError("Recovered check output exceeds limit")
        if result is not None:
            if result.get("started_at") != started["started_at"] or type(result.get("exit_code")) is not int or not isinstance(result.get("ended_at"), str) or log is None or result.get("log_bytes") != len(log) or result.get("log_sha256") != digest(log):
                raise ValueError("Recovered check result/log binding mismatch")
            completed_results.append(result)
        checks.append({"name": name, "state": "completed" if result is not None else "unknown", "exit_code": result["exit_code"] if result is not None else None})
    if "checks" in worker_receipt:
        recorded_checks = worker_receipt["checks"]
        if not isinstance(recorded_checks, list) or recorded_checks != completed_results[:len(recorded_checks)] or ("artifact_sha256" in worker_receipt and recorded_checks != completed_results):
            raise ValueError("Recovered checks differ from worker receipt")
    if "checks_passed" in worker_receipt:
        expected_passed = all(result["exit_code"] == 0 for result in completed_results) if completed_results else None
        if len(completed_results) != len(task["checks"]) or worker_receipt["checks_passed"] is not expected_passed:
            raise ValueError("Recovered check summary contradicts command results")
    if "model_status" in worker_receipt and (not isinstance(worker_receipt["model_status"], str) or worker_receipt["model_status"] not in {"completed", "blocked", "failed"} or worker_receipt["model_status"] != report.get("status")):
        raise ValueError("Recovered model status contradicts its report")
    # These fields are produced only after Pi exits zero. A partial export may
    # omit records, but cannot reverse the worker's already-observed ordering.
    if worker_receipt.get("pi_exit_code", 0) != 0:
        after_pi_fields = {"events", "extension", "model_report_sha256", "changed_files", "model_report_matches_changes", "checks_passed", "model_status"}
        has_check_artifacts = any(check["name"] + suffix in actual for check in task["checks"] for suffix in (".started.json", ".result.json", ".log"))
        if after_pi_fields & worker_receipt.keys() or has_check_artifacts or completed_results:
            raise ValueError("Recovered post-Pi records contradict its nonzero exit")
    if worker_receipt.get("outcome") == "returned":
        if worker_receipt.get("pi_exit_code", 0) != 0 or any(result["exit_code"] != 0 for result in completed_results) or worker_receipt.get("checks_passed") is False or worker_receipt.get("model_report_matches_changes") is False or any(record.get(key, "completed") != "completed" for record, key in ((worker_receipt, "model_status"), (report, "status"))):
            raise ValueError("Recovered returned outcome contradicts present failure evidence")
    if worker_receipt.get("outcome") == "failed" and worker_receipt.get("model_status") == "completed" and "checks_passed" in worker_receipt and worker_receipt["checks_passed"] is not False and worker_receipt.get("model_report_matches_changes") is True:
        raise ValueError("Recovered failed outcome contradicts present completion evidence")
    has_changes = "changes.json" in actual
    if has_changes:
        if "changes.patch" not in actual:
            raise ValueError("Recovered change manifest lacks its patch")
        changes = read_json(results / "changes.json")
        if not isinstance(changes, list) or any(not isinstance(change, dict) or set(change) != {"path", "before_sha256", "after_sha256"} for change in changes):
            raise ValueError("Invalid recovered change manifest")
        names = sorted(relative_file(change["path"]) for change in changes)
        verify_changes(results, actual, task, source_files, {"changed_files": worker_receipt.get("changed_files", names)}, {"changed_files": report.get("changed_files", names)})
    elif "changes.patch" in actual or any(name.startswith("changed-files/") for name in actual):
        raise ValueError("Recovered change bytes lack their source manifest")
    complete = all(key in worker_receipt for key in ("artifact_sha256", "events", "extension", "model_report_sha256", "pi_exit_code", "checks", "checks_passed", "model_status", "acceptance", "ended_at")) and has_changes and len(completed_results) == len(task["checks"])
    if complete:
        if task["version"] in (2, 3) and "configuration" not in worker_receipt:
            raise ValueError("Recovered terminal RPC configuration is missing")
        expected_outcome = "returned" if report.get("status") == "completed" and worker_receipt["checks_passed"] is not False and worker_receipt.get("model_report_matches_changes") is True else "failed"
        if worker_receipt["outcome"] != expected_outcome or worker_receipt["pi_exit_code"] != 0:
            raise ValueError("Recovered worker outcome contradicts terminal evidence")
    conversation_valid = False
    if task.get("session") and "conversation.json" in actual:
        if complete:
            verify_conversation(results, task, worker_receipt)
            conversation_valid = True
        elif "conversation" in worker_receipt:
            raise ValueError("Incomplete worker cannot claim a continuable conversation")
    return {"evidence_status": "complete" if complete else "partial", "available_bindings_valid": True,
            **({"conversation_valid": conversation_valid} if task.get("session") else {}),
            "worker_outcome": worker_receipt.get("outcome"), "checks": checks,
            "artifact_sha256": {name: digest(data) for name, data in actual.items()},
            "provenance": "retained-input and available-record byte bindings; not independent issuer attestation"}


def recover_task(failed_directory, profile_file, output, lock_root, *, reconcile_conversation=False):
    profile = profile_settings(profile_file)
    original, task, source_files, original_hashes = recovery_inputs(failed_directory, profile, allow_saved_success=reconcile_conversation)
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    owner = OpenShellOwner(profile)
    receipt = {"version": 1, "operation": "recovery", "run_id": uuid.uuid4().hex,
               "failed_run_id": original["run_id"], "failed_input_sha256": original["input_sha256"],
               "task_id": original["task_id"], "original_outcome": original.get("outcome"),
               "original_receipt_sha256": original_hashes["receipt.json"], "original_artifact_sha256": original_hashes,
               "remote_artifacts": original["remote_artifacts"], "started_at": utc_now(),
               "cleanup_complete": False, "outcome": "incomplete", "recovery_valid": False,
               "delivery_valid": False, "task_delivery_valid": False, "acceptance": "not_granted"}
    if task.get("session"):
        receipt.update(version=2, recovered_from=str(Path(failed_directory).absolute()), conversation_valid=False)
    elif reconcile_conversation:
        raise ValueError("Conversation reconciliation requires a saved dispatch")
    with exclusive_owner(profile, lock_root) as journal:
        prior = read_json(journal)
        origin = prior.get("failed_run_id", prior.get("run_id"))
        input_hash = prior.get("failed_input_sha256", prior.get("input_sha256"))
        legacy_mismatch = origin != original["run_id"] or input_hash != original["input_sha256"] or prior.get("task_id") != original["task_id"] or prior.get("delivery_valid") is True
        if prior.get("cleanup_complete") is not True or (not task.get("session") and legacy_mismatch) or task.get("session") and prior.get("protected_unchanged") is not True:
            raise ValueError("Latest failed run does not have resolved owner custody")
        if not task.get("session") and prior.get("operation") == "recovery" and prior.get("original_receipt_sha256") != original_hashes["receipt.json"]:
            raise ValueError("Recovery origin receipt changed")
        expected = prior.get("sandbox_running", prior.get("sandbox_before", {}))
        stopped = prior.get("sandbox_after", {})
        state = owner.verify()
        if state["phase"] != "Stopped" or state["id"] != expected.get("id") or not state.get("main_process_instance_id") or selected_state(state) != stopped or ("sandbox_running" in prior and state["main_process_instance_id"] != expected.get("main_process_instance_id")):
            raise ValueError("Exact stopped custody has not been established")
        protected = {name: selected_state(owner.get(name)) for name in profile.get("protected_sandboxes", [])}
        if profile["sandbox_name"] in protected:
            raise ValueError("Disposable sandbox is also protected")
        receipt["sandbox_before"] = selected_state(state)
        # Preserve exact journal bytes before replacing it with uncertain recovery custody.
        with (output / "prior-journal.json").open("xb") as stream:
            stream.write(journal.read_bytes())
        write_new_json(output / "started.json", receipt)
        def save_journal():
            journal.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        save_journal()
        with owner_interruptions() as previous_handlers:
            try:
                start_owned_instance(owner, profile, receipt, save_journal)
                owner.verify()
                owner.command("download", profile["sandbox_name"], receipt["remote_artifacts"], str(output / "results"))
                receipt["download_complete"] = True
                receipt["evidence"] = verify_recovered_artifacts(output / "results", task, source_files)
                if task.get("session"):
                    # Execute only the retained, hash-bound runner's inspection function.
                    remote = str(PurePosixPath(original["remote_artifacts"]).parent)
                    payload = safe_archive_files((Path(failed_directory) / "inputs.tar").read_bytes())
                    script = "import hashlib,json,pathlib,runpy,sys; p=pathlib.Path(sys.argv[1]); assert hashlib.sha256(p.read_bytes()).hexdigest()==sys.argv[2]; t=p.parent/'task.json'; assert hashlib.sha256(t.read_bytes()).hexdigest()==sys.argv[3]; m=runpy.run_path(str(p)); print(json.dumps(m['inspect_saved_conversation'](p.parent,json.loads(t.read_text()),sys.argv[4]=='true')))"
                    owner.verify()
                    inspected = owner.command("exec", profile["sandbox_name"], "--no-login-shell", "--no-tty", "--timeout", "60", "--", profile.get("python", "python3"), "-c", script, remote + "/coordinate.py", digest(payload["coordinate.py"]), digest(payload["task.json"]), "true" if reconcile_conversation else "false")
                    if len(inspected.stdout.encode()) > 1024 * 1024:
                        raise ValueError("Conversation inspection exceeds bound")
                    inspection = json.loads(inspected.stdout)
                    write_private_control(output / "conversation-inspection.json", inspection)
                    receipt["inspection_sha256"] = digest((output / "conversation-inspection.json").read_bytes())
                    checkpoint = inspection.get("checkpoint")
                    if inspection.get("continuable") is True and (checkpoint == task["session"]["prior"] or receipt["evidence"].get("conversation_valid") is True and checkpoint == read_json(output / "results/conversation.json")):
                        receipt.update(conversation_valid=True, continuation_checkpoint=checkpoint)
                receipt["outcome"] = "recovered_" + receipt["evidence"]["evidence_status"]
            except BaseException as error:
                receipt["error"] = str(error)
            finally:
                for sig in previous_handlers:
                    signal.signal(sig, signal.SIG_IGN)
                cleanup_owner(owner, profile, receipt, protected)
                receipt["ended_at"] = utc_now()
                receipt["recovery_valid"] = receipt["cleanup_complete"] and receipt.get("protected_unchanged", False) and receipt.get("download_complete", False) and receipt.get("evidence", {}).get("available_bindings_valid", False)
                if task.get("session"):
                    receipt["recovery_valid"] = receipt["recovery_valid"] and "inspection_sha256" in receipt and "error" not in receipt
                    receipt["conversation_valid"] = receipt["conversation_valid"] and receipt["recovery_valid"] and "error" not in receipt
                save_journal()
                write_new_json(output / "receipt.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    run = sub.add_parser("run", help="Delegate one task using a private runtime profile")
    run.add_argument("task", type=Path)
    run.add_argument("--profile", type=Path, default=Path.home() / ".config/codex-pi-coordination/profile.json")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--lock-root", type=Path, default=Path.home() / ".local/state/codex-pi-coordination")
    run.add_argument("--save-session", action="store_true")
    continuation = sub.add_parser("continue", help="Assign a fresh task to an exact saved Pi conversation")
    continuation.add_argument("task", type=Path)
    continuation.add_argument("--from", dest="previous_directory", type=Path, required=True)
    continuation.add_argument("--profile", type=Path, default=Path.home() / ".config/codex-pi-coordination/profile.json")
    continuation.add_argument("--output", type=Path, required=True)
    continuation.add_argument("--lock-root", type=Path, default=Path.home() / ".local/state/codex-pi-coordination")
    configure = sub.add_parser("configure", help="Register an existing private profile as the default, without replacing one")
    configure.add_argument("--profile", type=Path, required=True)
    capabilities = sub.add_parser("capabilities", help="Inspect sanitized model capabilities without sending a prompt")
    capabilities.add_argument("--profile", type=Path, default=Path.home() / ".config/codex-pi-coordination/profile.json")
    capabilities.add_argument("--output", type=Path, required=True)
    capabilities.add_argument("--lock-root", type=Path, default=Path.home() / ".local/state/codex-pi-coordination")
    capabilities.add_argument("--provider")
    capabilities.add_argument("--model")
    recover = sub.add_parser("recover", help="Download evidence from the latest stopped failed run without rerunning it")
    recover.add_argument("failed_directory", type=Path)
    recover.add_argument("--profile", type=Path, default=Path.home() / ".config/codex-pi-coordination/profile.json")
    recover.add_argument("--output", type=Path, required=True)
    recover.add_argument("--lock-root", type=Path, default=Path.home() / ".local/state/codex-pi-coordination")
    remote = sub.add_parser("worker", help=argparse.SUPPRESS)
    remote.add_argument("root", type=Path)
    reconcile = sub.add_parser("reconcile", help="Reconcile unresolved custody only after the exact sandbox is Stopped")
    reconcile.add_argument("--profile", type=Path, default=Path.home() / ".config/codex-pi-coordination/profile.json")
    reconcile.add_argument("--lock-root", type=Path, default=Path.home() / ".local/state/codex-pi-coordination")
    reconcile.add_argument("--from", dest="failed_directory", type=Path)
    reconcile.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == "configure":
            print(json.dumps(configure_profile(args.profile)))
            return 0
        if args.operation == "capabilities":
            selected = None
            if args.provider is not None or args.model is not None:
                selected = {"provider": model_identifier(args.provider), "model": model_identifier(args.model)}
            receipt = run_task(None, args.profile, args.output, args.lock_root, capabilities_only=True, selected_model=selected)
            print(json.dumps({"run_id": receipt["run_id"], "capabilities_valid": receipt["capabilities_valid"], "delivery_valid": False, "acceptance": "not_granted", "receipt": str(args.output / "receipt.json")}))
            return 0 if receipt["capabilities_valid"] else 1
        if args.operation == "worker":
            return worker(args.root)
        if args.operation == "reconcile":
            if args.failed_directory is not None or args.output is not None:
                if args.failed_directory is None or args.output is None:
                    raise ValueError("Conversation reconciliation requires --from and --output together")
                receipt = recover_task(args.failed_directory, args.profile, args.output, args.lock_root, reconcile_conversation=True)
                print(json.dumps({"recovery_valid": receipt["recovery_valid"], "conversation_valid": receipt.get("conversation_valid", False), "delivery_valid": False, "acceptance": "not_granted", "receipt": str(args.output / "receipt.json")}))
                return 0 if receipt["recovery_valid"] else 1
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
        if args.operation == "recover":
            receipt = recover_task(args.failed_directory, args.profile, args.output, args.lock_root)
            print(json.dumps({"run_id": receipt["run_id"], "failed_run_id": receipt["failed_run_id"], "outcome": receipt["outcome"], "recovery_valid": receipt["recovery_valid"], **({"conversation_valid": receipt["conversation_valid"]} if "conversation_valid" in receipt else {}), "task_delivery_valid": False, "acceptance": "not_granted", "receipt": str(args.output / "receipt.json")}))
            return 0 if receipt["recovery_valid"] else 1
        receipt = run_task(args.task, args.profile, args.output, args.lock_root, save_session=getattr(args, "save_session", False), previous_directory=getattr(args, "previous_directory", None))
        print(json.dumps({"run_id": receipt["run_id"], "outcome": receipt["outcome"], "delivery_valid": receipt["delivery_valid"], "receipt": str(args.output / "receipt.json")}))
        return 0 if receipt["delivery_valid"] else 1
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error), "delivery_valid": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
