"""Synthetic subprocess and ownership checks; no live sandbox/model is used."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coordinate.py"
spec = importlib.util.spec_from_file_location("coordinate", SCRIPT)
coordinate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coordinate)

FAKE_PI = r'''
import hashlib,json,pathlib,sys
behavior=sys.argv[1]
task_path=pathlib.Path(sys.argv[sys.argv.index('--coordination-task')+1])
task=json.loads(task_path.read_text()); workspace=pathlib.Path(task['workspace']); output=pathlib.Path(task['output_directory'])
tools=set(sys.argv[sys.argv.index('--tools')+1].split(','))
assert tools == set(task['allowed_tools']) | {'coordination_status','coordination_handoff'}, 'Pi hard allowlist must include extension handoff tools'
counter=task_path.parent/'invocations.txt'
counter.write_text(counter.read_text()+'1' if counter.exists() else '1')
changed=[]
if behavior in ('change','out-scope'):
    name='answer.txt' if behavior=='change' else 'unapproved.txt'
    (workspace/name).write_text('after\n'); changed=[name]
report={'run_id':task['run_id'],'task_id':task['task_id'],'task_sha256':hashlib.sha256(task_path.read_bytes()).hexdigest(),'model_self_report':True,'status':'blocked' if behavior=='blocked' else 'completed','changed_files':changed,'summary':'Synthetic handoff','evidence':[],'limitations':[]}
if behavior=='wrong-identity': report['run_id']='different-run'
if behavior=='wrong-digest': report['task_sha256']='0'*64
if behavior=='wrong-files': report['changed_files']=['invented.txt']
if behavior!='missing-report':
    with (output/'model-report.json').open('x') as stream: json.dump(report,stream)
events=[{'type':'tool_execution_start','toolCallId':'call-1','toolName':'coordination_handoff'}, {'type':'tool_execution_end','toolCallId':'call-1','isError':False}, {'type':'message_end','message':{'role':'assistant','stopReason':'stop'}}, {'type':'agent_end'}]
if behavior=='missing-end': events.pop()
if behavior=='duplicate-id': events[2:2]=events[:2]
for event in events: print(json.dumps(event),flush=True)
raise SystemExit(7 if behavior=='exit-seven' else 0)
'''

FAKE_EXEC = r'''
import subprocess,sys
command=sys.argv[sys.argv.index('--')+1:]
raise SystemExit(subprocess.run(command).returncode)
'''


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def task_template():
    return {"version": 1, "task_id": "task-one", "kind": "validation",
            "instructions": "Check the supplied fixture.", "writable_paths": [], "checks": []}


def make_archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.REGTYPE:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            else:
                info.linkname = "../outside"
                archive.addfile(info)
    return output.getvalue()


class ContractTests(unittest.TestCase):
    def test_malformed_tasks_fail_as_validation_errors(self):
        bad_fields = [("version", True), ("kind", []), ("task_id", "../escape"),
                      ("instructions", ""), ("writable_paths", ["."]),
                      ("writable_paths", ["../escape"]), ("writable_paths", ["a", "a"]),
                      ("writable_paths", [{}]), ("max_tool_calls", True),
                      ("max_turns", 0), ("wall_seconds", 1801),
                      ("repository", "/unpaired"), ("unexpected", 1)]
        for name, value in bad_fields:
            with self.subTest(field=name, value=value):
                task = task_template(); task[name] = value
                with self.assertRaises(ValueError):
                    coordinate.validate_task(task)
        for check in [
            {"name": "ok", "argv": [], "timeout_seconds": 1},
            {"name": "../escape", "argv": ["true"], "timeout_seconds": 1},
            {"name": "ok", "argv": ["true"], "timeout_seconds": True},
        ]:
            task = task_template(); task["checks"] = [check]
            with self.assertRaises(ValueError):
                coordinate.validate_task(task)

    def test_profile_refuses_embedded_secrets_and_malformed_runtime_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            valid = {"sandbox_name": "disposable", "sandbox_id": "sandbox-id",
                     "pi_argv": ["pi"], "model": "example/model"}
            dump(path, valid)
            self.assertEqual(coordinate.profile_settings(path)["model"], "example/model")
            for name, value in [("environment", {"API_KEY": "synthetic-placeholder"}),
                                ("thinking", []), ("protected_sandboxes", "owner"),
                                ("pi_argv", "pi"), ("python", ""), ("model", "-bad"),
                                ("remote_parent", []), ("remote_parent", "relative")]:
                with self.subTest(field=name):
                    dump(path, {**valid, name: value})
                    with self.assertRaises(ValueError):
                        coordinate.profile_settings(path)

    def test_archive_refuses_traversal_links_duplicates_and_size_overflow(self):
        self.assertEqual(coordinate.safe_archive_files(make_archive([("a.txt", b"a", tarfile.REGTYPE)])), {"a.txt": b"a"})
        for entries in [[("../escape", b"x", tarfile.REGTYPE)],
                        [("/escape", b"x", tarfile.REGTYPE)],
                        [("link", b"", tarfile.SYMTYPE)],
                        [("pipe", b"", tarfile.FIFOTYPE)],
                        [("a", b"x", tarfile.REGTYPE), ("a", b"y", tarfile.REGTYPE)]]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                coordinate.safe_archive_files(make_archive(entries))
        with mock.patch.object(coordinate, "MAX_SOURCE_BYTES", 1), self.assertRaises(ValueError):
            coordinate.safe_archive_files(make_archive([("a", b"xx", tarfile.REGTYPE)]))

    def test_frozen_git_export_preserves_dirty_checkout_and_executable_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)
            git("init")
            (root / "run.sh").write_text("#!/bin/sh\nexit 0\n")
            (root / "run.sh").chmod(0o755)
            git("add", "run.sh")
            git("-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
            commit = git("rev-parse", "HEAD").decode().strip()
            (root / "run.sh").write_text("uncommitted change\n")
            (root / "untracked.txt").write_text("preserve me\n")
            before = git("status", "--porcelain=v1")
            files, source = coordinate.frozen_source({"repository": str(root), "revision": commit})
            self.assertEqual(files, {"run.sh": b"#!/bin/sh\nexit 0\n"})
            self.assertEqual(source["modes"]["run.sh"], 0o755)
            self.assertEqual(source["commit"], commit)
            self.assertEqual(git("status", "--porcelain=v1"), before)
            self.assertEqual((root / "run.sh").read_text(), "uncommitted change\n")

    def test_json_reader_refuses_symlink_and_nonregular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); dump(root / "real.json", {})
            (root / "link.json").symlink_to(root / "real.json")
            with self.assertRaises(ValueError): coordinate.read_json(root / "link.json")
            with self.assertRaises(ValueError): coordinate.read_json(root)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        captured_output = contextlib.redirect_stdout(io.StringIO())
        captured_output.__enter__()
        self.addCleanup(captured_output.__exit__, None, None, None)

    def prepare(self, name="run", behavior="unchanged", kind="validation", checks=None):
        root = self.root / name; root.mkdir()
        workspace = root / "workspace"; workspace.mkdir()
        output = root / "results"; output.mkdir()
        (workspace / "answer.txt").write_text("before\n")
        fake = root / "fake-pi.py"; fake.write_text(FAKE_PI)
        task = {"version": 1, "run_id": "run-one", "task_id": "task-one", "kind": kind,
                "instructions": "Synthetic fixture task", "workspace": str(workspace),
                "output_directory": str(output), "writable_paths": ["answer.txt"],
                "allowed_tools": ["read", "write"], "max_tool_calls": 10, "max_turns": 10,
                "checks": checks or [],
                "source": {"files": {"answer.txt": coordinate.digest(b"before\n")}}}
        dump(root / "task.json", task)
        dump(root / "launch.json", {"pi_argv": [sys.executable, str(fake), behavior],
                                   "model": "example/model", "thinking": "high", "environment": {},
                                   "checks": checks or [], "wall_seconds": 5})
        return root

    def test_four_task_kinds_return_isolated_artifacts_and_no_acceptance(self):
        for kind in sorted(coordinate.KINDS):
            with self.subTest(kind=kind):
                root = self.prepare(name=kind, behavior="change", kind=kind)
                self.assertEqual(coordinate.worker(root), 0)
                receipt = coordinate.read_json(root / "results/worker-receipt.json")
                self.assertEqual(receipt["outcome"], "returned")
                self.assertEqual(receipt["acceptance"], "not_granted")
                self.assertEqual(receipt["changed_files"], ["answer.txt"])
                self.assertEqual((root / "results/changed-files/answer.txt").read_text(), "after\n")
                self.assertIn("-before", (root / "results/changes.patch").read_text())

    def test_checks_keep_real_exit_log_hash_and_exclusive_invocation(self):
        check = {"name": "proof", "argv": [sys.executable, "-c", "from pathlib import Path; p=Path('count'); p.write_text(p.read_text()+'x' if p.exists() else 'x'); print('looks successful'); raise SystemExit(7)"], "timeout_seconds": 2}
        root = self.prepare(checks=[check])
        self.assertEqual(coordinate.worker(root), 1)
        receipt = coordinate.read_json(root / "results/worker-receipt.json")
        result = receipt["checks"][0]; raw = (root / "results/proof.log").read_bytes()
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["log_bytes"], len(raw))
        self.assertEqual(result["log_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertFalse(receipt["checks_passed"])
        with self.assertRaises(FileExistsError): coordinate.worker(root)
        self.assertEqual((root / "workspace/count").read_text(), "x")
        self.assertEqual((root / "invocations.txt").read_text(), "1")

    def test_positive_check_runs_against_returned_bytes(self):
        check = {"name": "proof", "argv": [sys.executable, "-c", "from pathlib import Path; assert Path('answer.txt').read_text() == 'after\\n'; print('verified returned bytes')"], "timeout_seconds": 2}
        root = self.prepare(behavior="change", checks=[check])
        self.assertEqual(coordinate.worker(root), 0)
        receipt = coordinate.read_json(root / "results/worker-receipt.json")
        self.assertTrue(receipt["checks_passed"])
        result = receipt["checks"][0]
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["argv"], check["argv"])
        self.assertEqual((root / "results/proof.log").read_text(), "verified returned bytes\n")

    def test_incomplete_or_false_handoffs_never_return_success(self):
        for behavior in ["missing-end", "missing-report", "wrong-identity", "wrong-digest",
                         "wrong-files", "exit-seven", "out-scope", "duplicate-id", "blocked"]:
            with self.subTest(behavior=behavior):
                root = self.prepare(name=behavior, behavior=behavior)
                self.assertEqual(coordinate.worker(root), 1)
                receipt = coordinate.read_json(root / "results/worker-receipt.json")
                self.assertNotEqual(receipt["outcome"], "returned")
                self.assertTrue((root / "results/pi-events.jsonl").exists())

    def test_changed_source_and_check_mutation_are_refused(self):
        root = self.prepare(name="changed-before")
        (root / "workspace/answer.txt").write_text("different bytes")
        self.assertEqual(coordinate.worker(root), 1)
        self.assertFalse((root / "invocations.txt").exists())
        check = {"name": "mutator", "argv": [sys.executable, "-c", "from pathlib import Path; Path('answer.txt').write_text('changed by check')"], "timeout_seconds": 2}
        root = self.prepare(name="changed-by-check", checks=[check])
        self.assertEqual(coordinate.worker(root), 1)
        receipt = coordinate.read_json(root / "results/worker-receipt.json")
        self.assertEqual(receipt["checks"][0]["exit_code"], 0)
        self.assertNotEqual(receipt["outcome"], "returned")

    def test_log_and_deadline_limits_retain_failed_output(self):
        log = self.root / "large.log"
        with mock.patch.object(coordinate, "MAX_OUTPUT_BYTES", 10), self.assertRaises((ValueError, TimeoutError)):
            coordinate.execute_to_log([sys.executable, "-c", "print('x'*100)"], self.root, log, 2)
        self.assertTrue(log.exists())
        with self.assertRaises(TimeoutError):
            coordinate.execute_to_log([sys.executable, "-c", "import time; time.sleep(10)"], self.root, self.root / "timeout.log", 0.05)

    def test_checks_cannot_replace_returned_files_or_patch(self):
        for artifact in ["changed-files/answer.txt", "changes.patch"]:
            with self.subTest(artifact=artifact):
                code = "from pathlib import Path; p=Path('../results') / " + repr(artifact) + "; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('forged bytes\\n')"
                check = {"name": "mutator", "argv": [sys.executable, "-c", code], "timeout_seconds": 2}
                root = self.prepare(name=artifact.replace("/", "-"), behavior="change", checks=[check])
                self.assertEqual(coordinate.worker(root), 1)
                receipt = coordinate.read_json(root / "results/worker-receipt.json")
                self.assertEqual(receipt["checks"][0]["exit_code"], 0)
                self.assertNotEqual(receipt["outcome"], "returned")
                self.assertEqual((root / "workspace/answer.txt").read_text(), "after\n")

    def test_check_symlink_cannot_redirect_exported_files(self):
        outside = self.root / "outside"; outside.mkdir()
        protected = outside / "answer.txt"; protected.write_text("preserve this\n")
        code = "from pathlib import Path; Path('../results/changed-files').symlink_to(" + repr(str(outside)) + ", target_is_directory=True)"
        check = {"name": "mutator", "argv": [sys.executable, "-c", code], "timeout_seconds": 2}
        root = self.prepare(behavior="change", checks=[check])
        self.assertEqual(coordinate.worker(root), 1)
        self.assertEqual(protected.read_text(), "preserve this\n")

    def test_host_verifier_binds_artifacts_logs_task_and_source(self):
        check = {"name": "proof", "argv": [sys.executable, "-c", "print('actual verification output')"], "timeout_seconds": 2}
        root = self.prepare(behavior="change", checks=[check])
        self.assertEqual(coordinate.worker(root), 0)
        pristine = root / "results"
        task = coordinate.read_json(root / "task.json")
        source = {"answer.txt": b"before\n"}
        receipt = coordinate.verify_return(pristine, task, source, "run-one")
        self.assertEqual(receipt["outcome"], "returned")

        # Updating the returned manifest must not conceal inconsistencies with
        # host-held source, declared commands, or the command's own log receipt.
        for corruption in ["changed-file", "patch", "log", "source-base", "declared-command", "task-binding", "extra-file"]:
            with self.subTest(corruption=corruption):
                results = root / corruption; shutil.copytree(pristine, results)
                altered_task = copy.deepcopy(task)
                worker_receipt = coordinate.read_json(results / "worker-receipt.json")
                if corruption == "changed-file":
                    (results / "changed-files/answer.txt").write_text("forged return\n")
                elif corruption == "patch":
                    (results / "changes.patch").write_text("forged patch\n")
                elif corruption == "log":
                    (results / "proof.log").write_text("forged proof\n")
                elif corruption == "source-base":
                    changes = coordinate.read_json(results / "changes.json")
                    changes[0]["before_sha256"] = coordinate.digest(b"unrelated source\n")
                    dump(results / "changes.json", changes)
                elif corruption == "declared-command":
                    substituted = [sys.executable, "-c", "print('different command')"]
                    worker_receipt["checks"][0]["argv"] = substituted
                    for name in ["proof.started.json", "proof.result.json"]:
                        record = coordinate.read_json(results / name); record["argv"] = substituted
                        dump(results / name, record)
                elif corruption == "task-binding":
                    altered_task["instructions"] = "Different requested task"
                elif corruption == "extra-file":
                    (results / "changed-files/unapproved.txt").write_text("unauthorized return\n")
                worker_receipt["artifact_sha256"] = {name: coordinate.digest(raw) for name, raw in coordinate.snapshot(results).items() if name != "worker-receipt.json"}
                dump(results / "worker-receipt.json", worker_receipt)
                with self.assertRaises(ValueError):
                    coordinate.verify_return(results, altered_task, source, "run-one")

        with self.assertRaises(ValueError):
            coordinate.verify_return(pristine, task, {"answer.txt": b"different source\n"}, "run-one")
        with self.assertRaises(ValueError):
            coordinate.verify_return(pristine, task, source, "unrelated-run")


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profile = {"sandbox_name": "disposable", "sandbox_id": "sandbox-id",
                        "pi_argv": [sys.executable, str(self.root / "fake-pi.py"), "unchanged"],
                        "model": "example/model", "remote_parent": str(self.root / "remote"),
                        "python": sys.executable, "protected_sandboxes": ["protected"]}
        (self.root / "fake-pi.py").write_text(FAKE_PI)
        (self.root / "fake-exec.py").write_text(FAKE_EXEC)
        self.profile["openshell_argv"] = [sys.executable, str(self.root / "fake-exec.py")]
        self.profile_path = self.root / "profile.json"; dump(self.profile_path, self.profile)
        self.task_path = self.root / "task.json"; dump(self.task_path, task_template())
        self.instances = []

    def factory(self, mode="normal"):
        test = self
        class FakeOwner(coordinate.OpenShellOwner):
            def __init__(self, profile):
                super().__init__(profile)
                self.state = {"id": "sandbox-id", "name": "disposable", "phase": "Stopped", "main_process_instance_id": "old", "restart_count": 0}
                self.calls = []; test.instances.append(self)
                if mode == "initial-wrong-id": self.state["id"] = "other"
                if mode == "initial-ready": self.state["phase"] = "Ready"
                if mode == "reconciled": self.state["main_process_instance_id"] = "new-main"
            def get(self, name=None):
                if name == "protected":
                    return {"id": "protected-id", "name": name, "phase": "Ready", "main_process_instance_id": "protected-main", "restart_count": 0}
                return copy.deepcopy(self.state)
            def command(self, *args, timeout=60):
                self.calls.append(args[0])
                if args[0] == "start":
                    self.state.update(phase="Ready", main_process_instance_id="new-main")
                    if mode == "start-error": raise subprocess.CalledProcessError(1, "synthetic start")
                elif args[0] == "upload":
                    shutil.copyfile(args[-2], args[-1])
                    if mode == "replaced-after-upload": self.state["main_process_instance_id"] = "replacement"
                elif args[0] == "exec":
                    if mode == "exec-error": raise subprocess.CalledProcessError(1, "synthetic exec")
                    subprocess.run(list(args[args.index("--") + 1:]), check=True, capture_output=True, timeout=timeout)
                elif args[0] == "download":
                    if self.state["phase"] != "Ready":
                        raise subprocess.CalledProcessError(1, "download requires running sandbox")
                    shutil.copytree(args[-2], args[-1])
                    if mode == "forged-download":
                        receipt_path = Path(args[-1]) / "worker-receipt.json"
                        receipt = coordinate.read_json(receipt_path)
                        receipt["run_id"] = "unrelated-run"
                        dump(receipt_path, receipt)
                elif args[0] == "stop":
                    if mode == "stop-error": raise subprocess.CalledProcessError(1, "synthetic stop")
                    self.state["phase"] = "Stopped"
                else: raise AssertionError(args)
                return subprocess.CompletedProcess(args, 0, "", "")
        return FakeOwner

    def run_fake(self, mode="normal", name="out"):
        with mock.patch.object(coordinate, "OpenShellOwner", self.factory(mode)):
            return coordinate.run_task(self.task_path, self.profile_path, self.root / name, self.root / "locks")

    def test_complete_fake_transport_uses_real_worker_and_stopped_custody(self):
        receipt = self.run_fake()
        self.assertTrue(receipt["delivery_valid"])
        self.assertTrue(receipt["cleanup_complete"])
        self.assertTrue(receipt["protected_unchanged"])
        self.assertEqual(receipt["acceptance"], "not_granted")
        self.assertEqual(self.instances[0].calls.count("start"), 1)
        self.assertEqual(self.instances[0].calls.count("stop"), 1)

    def test_identity_or_ready_refusal_has_no_lifecycle_side_effect(self):
        for mode in ["initial-wrong-id", "initial-ready"]:
            with self.subTest(mode=mode), self.assertRaises(ValueError): self.run_fake(mode, mode)
            self.assertEqual(self.instances[-1].calls, [])

    def test_downloaded_identity_mismatch_is_rejected_before_delivery(self):
        receipt = self.run_fake("forged-download")
        self.assertFalse(receipt["delivery_valid"])
        self.assertFalse(receipt.get("artifacts_verified", False))
        self.assertTrue(receipt["cleanup_complete"])
        self.assertTrue(receipt["download_complete"])
        self.assertEqual(self.instances[-1].calls.count("stop"), 1)
        self.assertEqual(receipt["acceptance"], "not_granted")

    def test_failed_start_or_exec_stops_exact_owned_sandbox(self):
        for mode in ["start-error", "exec-error"]:
            with self.subTest(mode=mode):
                receipt = self.run_fake(mode, mode)
                self.assertFalse(receipt["delivery_valid"])
                self.assertTrue(receipt["cleanup_complete"])
                self.assertEqual(self.instances[-1].calls.count("stop"), 1)
                self.assertNotIn("download", self.instances[-1].calls)

    def test_failed_worker_stops_without_attempting_download(self):
        self.profile["pi_argv"][-1] = "exit-seven"; dump(self.profile_path, self.profile)
        receipt = self.run_fake()
        self.assertEqual(receipt["exec_exit_code"], 1)
        self.assertFalse(receipt["delivery_valid"])
        self.assertTrue(receipt["cleanup_complete"])
        self.assertEqual(self.instances[-1].calls.count("stop"), 1)
        self.assertNotIn("download", self.instances[-1].calls)
        self.assertTrue(Path(receipt["remote_artifacts"]).is_dir())
        self.assertFalse((self.root / "out/results").exists())
        self.assertEqual(coordinate.read_json(self.root / "out/receipt.json"), receipt)

    def test_timeout_and_output_overflow_stop_without_attempting_download(self):
        for name, error in [("timeout", TimeoutError("synthetic deadline")),
                            ("overflow", ValueError("synthetic output limit"))]:
            with self.subTest(failure=name):
                # Inject only the transport boundary; bootstrap and cleanup still
                # run through the fake owner's real local subprocess lifecycle.
                with mock.patch.object(coordinate, "execute_to_log", side_effect=error):
                    receipt = self.run_fake(name=name)
                self.assertFalse(receipt["delivery_valid"])
                self.assertTrue(receipt["cleanup_complete"])
                self.assertEqual(self.instances[-1].calls.count("stop"), 1)
                self.assertNotIn("download", self.instances[-1].calls)
                self.assertTrue(Path(receipt["remote_artifacts"]).is_dir())
                self.assertFalse((self.root / name / "results").exists())
                self.assertEqual(coordinate.read_json(self.root / name / "receipt.json"), receipt)

    def test_replaced_main_is_never_stopped_and_blocks_next_run(self):
        receipt = self.run_fake("replaced-after-upload")
        self.assertFalse(receipt["cleanup_complete"])
        self.assertNotIn("stop", self.instances[-1].calls)
        with self.assertRaises(ValueError): self.run_fake(name="next")
        self.assertEqual(self.instances[-1].calls, [])

    def test_failed_stop_keeps_unresolved_journal(self):
        receipt = self.run_fake("stop-error")
        self.assertFalse(receipt["delivery_valid"])
        self.assertFalse(receipt["cleanup_complete"])
        journal = self.root / "locks" / (coordinate.digest(b"sandbox-id") + ".json")
        before = journal.read_bytes()
        with self.assertRaises(ValueError): self.run_fake(name="next")
        self.assertEqual(journal.read_bytes(), before)

    def test_reconcile_requires_matching_stopped_main_and_changes_no_runtime(self):
        self.run_fake("stop-error")
        arguments = ["reconcile", "--profile", str(self.profile_path), "--lock-root", str(self.root / "locks")]
        journal = self.root / "locks" / (coordinate.digest(b"sandbox-id") + ".json")
        before = journal.read_bytes()
        with mock.patch.object(coordinate, "OpenShellOwner", self.factory()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(coordinate.main(arguments), 1)
        self.assertEqual(journal.read_bytes(), before)
        with mock.patch.object(coordinate, "OpenShellOwner", self.factory("reconciled")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(coordinate.main(arguments), 0)
        self.assertTrue(coordinate.read_json(journal)["cleanup_complete"])
        self.assertEqual(self.instances[-1].calls, [])

    def test_owner_lock_excludes_another_process(self):
        with coordinate.exclusive_owner(self.profile, self.root / "locks"):
            code = "import importlib.util,pathlib,sys; s=importlib.util.spec_from_file_location('c',sys.argv[1]); c=importlib.util.module_from_spec(s); s.loader.exec_module(c)\ntry:\n with c.exclusive_owner({'sandbox_id':'sandbox-id'},pathlib.Path(sys.argv[2])): raise SystemExit(0)\nexcept BlockingIOError: raise SystemExit(23)\n"
            result = subprocess.run([sys.executable, "-c", code, str(SCRIPT), str(self.root / "locks")], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 23, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
