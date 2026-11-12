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
if behavior in ('pre-guard-error','unguarded-success'):
    events[:0]=[{'type':'tool_execution_start','toolCallId':'schema-attempt','toolName':'coordination_handoff'},{'type':'tool_execution_end','toolCallId':'schema-attempt','isError':behavior=='pre-guard-error'}]
task_digest=hashlib.sha256(task_path.read_bytes()).hexdigest()
def extension_event(kind, calls=1, turns=1, handed_off=True, **fields):
    return {'type':kind,'at':'2000-01-01T00:00:00Z','active':True,'run_id':task['run_id'],'task_id':task['task_id'],'task_sha256':task_digest,'tool_calls':calls,'turns':turns,'handed_off':handed_off,**fields}
extension_events=[extension_event('task_loaded',0,0,False),extension_event('tool_call',handed_off=False,tool_name='coordination_handoff',tool_call_id='call-1'),extension_event('handoff',reported_status=report['status']),extension_event('agent_settled'),extension_event('session_shutdown')]
if task['version']==2:
    extension_events.insert(1,extension_event('run_configuration',0,0,False,configuration=rpc_effective))
if behavior=='extension-refused': extension_events.insert(3,extension_event('refused',failure={'code':'task_unavailable','message':'No further tools'},code='task_unavailable'))
if behavior=='extension-failure': extension_events[-1]['failure']={'code':'tool_budget_exhausted','message':'Budget exhausted'}
if behavior=='extension-wrong-run': extension_events[1]['run_id']='different-run'
if behavior=='extension-wrong-task': extension_events[1]['task_id']='different-task'
if behavior=='extension-wrong-digest': extension_events[1]['task_sha256']='0'*64
if behavior=='extension-missing-loaded': extension_events.pop(0)
if behavior=='extension-duplicate-handoff': extension_events.insert(3,dict(extension_events[2]))
if behavior=='extension-missing-settled': extension_events.pop(-2)
if behavior=='extension-missing-shutdown': extension_events.pop()
if behavior=='extension-trailing-event': extension_events.append(extension_event('tool_call',calls=2,tool_name='read',tool_call_id='late-read'))
if behavior=='extension-tool-count': extension_events[-1]['tool_calls']=2
if behavior=='extension-turn-count': extension_events[-1]['turns']=2
if behavior=='extension-tool-identity': extension_events[1]['tool_call_id']='unrelated-call'
if behavior=='extension-tool-name': extension_events[1]['tool_name']='read'
if behavior!='extension-missing':
    with (output/'extension-events.jsonl').open('x') as stream:
        for event in extension_events: stream.write(json.dumps(event)+'\n')
for event in events: print(json.dumps(event),flush=True)
raise SystemExit(7 if behavior=='exit-seven' else 0)
'''

FAKE_RPC = 'PRINT_FIXTURE = ' + repr(FAKE_PI) + '\n' + r'''
import json, pathlib, sys, os
behavior = sys.argv[1]
requests_file = pathlib.Path(__file__).with_suffix('.requests.jsonl')
model = {'provider':'example','id':'model','headers':{'Authorization':'synthetic-private-marker'},'baseUrl':'https://synthetic.invalid/private'}
thinking = 'high'
levels = ['off','minimal','low','medium','high','xhigh','max']
if behavior=='off-only': thinking='off';levels=['off']
held = None
def change_thinking(level):
    global thinking
    if level == thinking: return
    thinking = level
    event={'type':'thinking_level_changed','level':level,'private_metadata':'synthetic-private-marker'}
    if behavior=='malformed-configuration': event['level']=[]
    if behavior=='agent-before-prompt': event={'type':'agent_start'}
    if behavior not in ('missing-configuration','late-configuration'):
        print(json.dumps(event),flush=True)
        if behavior=='duplicate-configuration': print(json.dumps(event),flush=True)
def reply(request, data=None):
    value={'type':'response','id':request['id'],'command':request['type'],'success':True,'data':data}
    if behavior=='wrong-response': value['id']='foreign'
    if behavior=='wrong-command': value['command']='foreign'
    if behavior=='refused': value.update(success=False,error='synthetic-private-marker')
    line=json.dumps(value)+'\r\n'
    if behavior=='malformed': line='{bad}\n'
    if behavior=='partial': sys.stdout.write('{"type":');sys.stdout.flush();raise SystemExit(0)
    if behavior=='oversized': line='x'* (4*1024*1024+1)+'\n'
    if behavior=='stderr-overflow': sys.stderr.write('x'*(4*1024*1024+1));sys.stderr.flush()
    if behavior=='noisy': sys.stderr.write('synthetic diagnostic\n'*10000);sys.stderr.flush()
    sys.stdout.write(line);sys.stdout.flush()
    if behavior=='duplicate': sys.stdout.write(line);sys.stdout.flush()
for line in sys.stdin:
    request=json.loads(line)
    with requests_file.open('a') as stream: stream.write(json.dumps(request)+'\n')
    command=request['type']
    if behavior=='no-response': continue
    if command=='get_available_models':
        if behavior=='unsolicited-configuration': print(json.dumps({'type':'thinking_level_changed','level':'low'}),flush=True)
        data={'models':[model,{'provider':'second','id':'model-two','headers':{'secret':'synthetic-private-marker'}}]}
        if behavior=='out-of-order': held=(request,data);continue
    elif command=='get_state':
        data={'model':model,'thinkingLevel':thinking,'sessionId':'session-one','sessionFile':None,'isStreaming':False,'isCompacting':False,'pendingMessageCount':0}
        if behavior=='busy': data['pendingMessageCount']=1
    elif command=='get_available_thinking_levels': data={'levels':['low'] if behavior=='only-low' else levels}
    elif command=='set_model':
        model={'provider':request['provider'],'id':request['modelId']};data=model
        change_thinking('low')
    elif command=='set_thinking_level':
        change_thinking('low' if behavior=='clamped' else request['level']);data=None
    elif command=='prompt':
        if behavior=='no-prompt-ack': continue
        reply(request)
        namespace={'rpc_effective':{'provider':model['provider'],'model':model['id'],'thinking':thinking}}
        try: exec(PRINT_FIXTURE,namespace)
        except SystemExit as result:
            if result.code: raise
        if behavior!='no-settlement': print(json.dumps({'type':'agent_settled'}),flush=True)
        continue
    else: raise AssertionError(command)
    reply(request,data)
    if behavior=='late-configuration' and command=='set_thinking_level': print(json.dumps({'type':'thinking_level_changed','level':thinking}),flush=True)
    if held:
        reply(*held);held=None
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
    def test_version_two_options_and_namespaced_ids_are_strict(self):
        task = {**task_template(), "version": 2, "task_id": "project:T001", "run_options": {"thinking": "max"}}
        self.assertEqual(coordinate.validate_task(task), task)
        for options in [{"model": "unpaired"}, {"provider": "unpaired"}, {"thinking": "auto"}, {"thinking": "dynamic"}, {"thinking": "default"}, {"thinking": []}, {"extra": "value"}, {"provider": "https://example.invalid", "model": "id"}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                coordinate.validate_task({**task, "run_options": options})
        with self.assertRaises(ValueError):
            coordinate.validate_task({**task, "version": 1})

    def test_default_registration_is_private_idempotent_and_refuses_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            profile = {"sandbox_name": "fixture", "sandbox_id": "exact-id", "pi_argv": ["pi"], "model": "example/model"}
            dump(source, profile)
            destination = root / "settings/profile.json"
            first = coordinate.configure_profile(source, destination)
            self.assertTrue(first["changed"])
            self.assertFalse(first["runtime_verified"])
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)
            original = destination.read_bytes()
            dump(source, dict(reversed(list(profile.items()))))
            self.assertFalse(coordinate.configure_profile(source, destination)["changed"])
            self.assertEqual(destination.read_bytes(), original)
            dump(source, {**profile, "thinking": "low"})
            with self.assertRaises(ValueError): coordinate.configure_profile(source, destination)
            link = root / "linked"; link.symlink_to(destination.parent, target_is_directory=True)
            with self.assertRaises(ValueError): coordinate.configure_profile(source, link / "profile.json")
            destination.unlink(); destination.symlink_to(source)
            with self.assertRaises(ValueError): coordinate.configure_profile(source, destination)

    def test_profile_model_syntax_refuses_unusable_defaults_before_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            profile = {"sandbox_name": "fixture", "sandbox_id": "exact-id", "pi_argv": ["pi"], "model": "example/model"}
            for index, model in enumerate(["bad model", "example/bad model", "https://example.invalid/model", "unqualified", "a" * 257 + "/model", "example/" + "b" * 257, "a" * 10000, "example/model\n"]):
                with self.subTest(model=model[:40]):
                    dump(source, {**profile, "model": model})
                    destination = root / str(index) / "profile.json"
                    with self.assertRaises(ValueError): coordinate.configure_profile(source, destination)
                    self.assertFalse(destination.parent.exists())
                    with self.assertRaises(ValueError): coordinate.profile_settings(source)
            for model in ["one/two/three", "provider/model:revision", "a" * 256 + "/" + "b" * 256, "a/" + "b" * 254 + "/c/" + "d" * 254]:
                with self.subTest(valid_model=model[:40]):
                    dump(source, {**profile, "model": model})
                    self.assertEqual(coordinate.profile_settings(source), {**profile, "model": model})

    def test_default_registration_compares_effective_defaults_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            profile = {"sandbox_name": "fixture", "sandbox_id": "exact-id", "pi_argv": ["pi"], "model": "example/model"}
            defaults = {"openshell_argv": ["openshell"], "python": "python3", "remote_parent": "/sandbox/codex-pi", "thinking": "high", "environment": {}, "protected_sandboxes": []}
            cases = [{key: value} for key, value in defaults.items()] + [defaults]
            for index, explicit in enumerate(cases):
                for reverse in [False, True]:
                    with self.subTest(explicit=explicit, reverse=reverse):
                        initial, repeated = (profile, {**profile, **explicit}) if not reverse else ({**profile, **explicit}, profile)
                        dump(source, initial)
                        destination = root / f"{index}-{reverse}" / "profile.json"
                        self.assertTrue(coordinate.configure_profile(source, destination)["changed"])
                        before = (destination.read_bytes(), destination.stat().st_ino, destination.stat().st_mtime_ns)
                        dump(source, repeated)
                        self.assertFalse(coordinate.configure_profile(source, destination)["changed"])
                        self.assertEqual((destination.read_bytes(), destination.stat().st_ino, destination.stat().st_mtime_ns), before)
            for key, value in {"openshell_argv": ["different-owner"], "python": "different-python", "remote_parent": "/sandbox/different", "thinking": "low", "environment": {"PYTHONDONTWRITEBYTECODE": "1"}, "protected_sandboxes": ["other-sandbox"]}.items():
                with self.subTest(conflict=key):
                    dump(source, {**profile, key: value})
                    with self.assertRaises(ValueError): coordinate.configure_profile(source, destination)
                    self.assertEqual(destination.read_bytes(), before[0])
            dump(source, profile)
            destination.chmod(0o644)
            with self.assertRaises(ValueError): coordinate.configure_profile(source, destination)
            destination.chmod(0o600); destination.parent.chmod(0o755)
            with self.assertRaises(ValueError): coordinate.configure_profile(source, destination)
            self.assertEqual(destination.read_bytes(), before[0])

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
                "source": {"kind": "synthetic", "modes": {}, "files": {"answer.txt": coordinate.digest(b"before\n")}}}
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

    def test_missing_refused_or_inconsistent_extension_proof_never_returns_success(self):
        for behavior in ["extension-missing", "extension-refused", "extension-failure",
                         "extension-wrong-run", "extension-wrong-task", "extension-wrong-digest",
                         "extension-missing-loaded", "extension-duplicate-handoff",
                         "extension-missing-settled", "extension-missing-shutdown",
                         "extension-trailing-event", "extension-tool-count", "extension-turn-count",
                         "extension-tool-identity", "extension-tool-name"]:
            with self.subTest(behavior=behavior):
                root = self.prepare(name=behavior, behavior=behavior)
                self.assertEqual(coordinate.worker(root), 1)
                receipt = coordinate.read_json(root / "results/worker-receipt.json")
                self.assertNotEqual(receipt["outcome"], "returned")
                # Each negative still has a normally completed Pi stream. The
                # extension's task-policy proof must independently gate return.
                observed = coordinate.inspect_events(root / "results/pi-events.jsonl", 10, 10)
                self.assertEqual(observed["tool_calls"], 1)
                self.assertEqual(observed["assistant_turns"], 1)

    def test_native_schema_error_can_recover_but_unguarded_success_cannot(self):
        for behavior, expected_exit in [("pre-guard-error", 0), ("unguarded-success", 1)]:
            with self.subTest(behavior=behavior):
                root = self.prepare(name=behavior, behavior=behavior)
                self.assertEqual(coordinate.worker(root), expected_exit)
                results = root / "results"
                task = coordinate.read_json(root / "task.json")
                receipt = coordinate.read_json(results / "worker-receipt.json")
                native = coordinate.inspect_events(results / "pi-events.jsonl", 10, 10)
                self.assertEqual(native["tool_calls"], 2)
                if expected_exit == 0:
                    verified = coordinate.verify_return(results, task, {"answer.txt": b"before\n"}, "run-one")
                    self.assertEqual(verified["outcome"], "returned")
                    self.assertEqual(verified["extension"]["tool_calls"], 1)
                else:
                    self.assertNotEqual(receipt["outcome"], "returned")

    def test_host_rejects_resealed_invalid_extension_proof(self):
        root = self.prepare()
        self.assertEqual(coordinate.worker(root), 0)
        pristine = root / "results"
        task = coordinate.read_json(root / "task.json")
        source = {"answer.txt": b"before\n"}
        self.assertIn("extension", coordinate.verify_return(pristine, task, source, "run-one"))
        for corruption in ["missing", "refused", "identity", "terminal", "counters", "receipt-summary"]:
            with self.subTest(corruption=corruption):
                results = root / corruption; shutil.copytree(pristine, results)
                path = results / "extension-events.jsonl"
                events = [json.loads(line) for line in path.read_text().splitlines()]
                receipt = coordinate.read_json(results / "worker-receipt.json")
                if corruption == "missing":
                    path.unlink()
                else:
                    if corruption == "refused":
                        denied = {**events[2], "type": "refused", "failure": {"code": "task_unavailable"}}
                        events.insert(3, denied)
                    elif corruption == "identity":
                        events[1]["task_sha256"] = "0" * 64
                    elif corruption == "terminal":
                        events.pop()
                    elif corruption == "counters":
                        events[-1]["turns"] += 1
                    elif corruption == "receipt-summary":
                        receipt["extension"] = {"forged": True}
                    path.write_text("".join(json.dumps(event) + "\n" for event in events))
                receipt["artifact_sha256"] = {name: coordinate.digest(raw) for name, raw in coordinate.snapshot(results).items() if name != "worker-receipt.json"}
                dump(results / "worker-receipt.json", receipt)
                with self.assertRaises(ValueError):
                    coordinate.verify_return(results, task, source, "run-one")

    @unittest.skipUnless(shutil.which("node"), "Cross-layer fixture needs Node, as does the Pi extension")
    def test_real_extension_refusal_blocks_otherwise_normal_pi_finish(self):
        root = self.prepare()
        adapter = root / "fake-pi.mjs"
        extension_url = (SCRIPT.parent.parent / "extensions/coordination.js").as_uri()
        adapter.write_text("import extension from " + json.dumps(extension_url) + ";\n" + r'''
import fs from 'node:fs';
const taskPath=process.argv[process.argv.indexOf('--coordination-task')+1];
const task=JSON.parse(fs.readFileSync(taskPath,'utf8'));
const handlers=new Map(), tools=new Map(); let active=[];
const ctx={cwd:task.workspace,hasUI:false,abort(){},shutdown(){}};
extension({registerFlag(){},getFlag:()=>taskPath,registerCommand(){},registerTool:t=>tools.set(t.name,t),on:(name,handler)=>handlers.set(name,handler),getActiveTools:()=>active,setActiveTools:n=>{active=n;}});
const emit=async(name,event={})=>handlers.get(name)?.(event,ctx);
await emit('session_start'); await emit('turn_start');
const handoff={toolName:'coordination_handoff',toolCallId:'handoff-1',input:{status:'completed',summary:'Synthetic handoff',evidence:['answer.txt'],changed_files:[],limitations:[]}};
await emit('tool_call',handoff); await tools.get(handoff.toolName).execute(handoff.toolCallId,handoff.input);
const denied=await emit('tool_call',{toolName:'read',toolCallId:'late-read',input:{path:'answer.txt'}});
if(!denied?.block) throw Error('Expected the actual extension to refuse a post-handoff tool');
await emit('agent_settled'); await emit('session_shutdown');
for(const event of [{type:'tool_execution_start',toolCallId:'handoff-1',toolName:'coordination_handoff'},{type:'tool_execution_end',toolCallId:'handoff-1',isError:false},{type:'tool_execution_start',toolCallId:'late-read',toolName:'read'},{type:'tool_execution_end',toolCallId:'late-read',isError:true},{type:'message_end',message:{role:'assistant',stopReason:'stop'}},{type:'agent_end'}]) console.log(JSON.stringify(event));
''')
        launch = coordinate.read_json(root / "launch.json")
        launch["pi_argv"] = ["node", str(adapter)]; dump(root / "launch.json", launch)
        self.assertEqual(coordinate.worker(root), 1)
        receipt = coordinate.read_json(root / "results/worker-receipt.json")
        self.assertEqual(receipt["pi_exit_code"], 0)
        self.assertNotEqual(receipt["outcome"], "returned")
        events = [json.loads(line) for line in (root / "results/extension-events.jsonl").read_text().splitlines()]
        self.assertTrue(any(event["type"] == "refused" for event in events))
        self.assertEqual(coordinate.inspect_events(root / "results/pi-events.jsonl", 10, 10)["tool_calls"], 2)

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


class RpcTests(unittest.TestCase):
    def setUp(self):
        WorkerTests.setUp(self)
        self.fake_pi_processes = []
        real_initialize = coordinate.PiRpc.__init__

        def retain_fake_pi_process(instance, *args, **kwargs):
            real_initialize(instance, *args, **kwargs)
            self.fake_pi_processes.append(instance.process)

        patcher = mock.patch.object(coordinate.PiRpc, "__init__", retain_fake_pi_process)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.join_fake_pi_processes)

    def join_fake_pi_processes(self):
        # The worker closes its streams; the fixture owns the local children
        # that stand in for the managed remote runtime's cleanup responsibility.
        running_processes = []
        for process in self.fake_pi_processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                running_processes.append(process.pid)
        self.assertEqual(running_processes, [], "Fake Pi children did not exit after worker cleanup")

    def prepare(self, name="rpc", behavior="change", options=None, metadata=False):
        root = WorkerTests.prepare(self, name=name, behavior=behavior)
        (root / "fake-pi.py").write_text(FAKE_RPC)
        task = coordinate.read_json(root / "task.json")
        task.update(version=2, task_id="project:T001", operation="capabilities" if metadata else "run", run_options=options or {}, runtime_defaults={"model": "example/model", "thinking": "high"})
        if metadata:
            task.update(writable_paths=[], checks=[])
        dump(root / "task.json", task)
        launch = coordinate.read_json(root / "launch.json"); launch["wall_seconds"] = 1
        dump(root / "launch.json", launch)
        return root

    def requests(self, root):
        path = root / "fake-pi.requests.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_default_and_exact_overrides_return_real_changes_with_private_metadata_removed(self):
        for index, options in enumerate([{}, {"thinking": "low"}, {"provider": "second", "model": "model-two", "thinking": "max"}]):
            with self.subTest(options=options):
                root = self.prepare(name=str(index), options=options)
                launch_before = (root / "launch.json").read_bytes()
                self.assertEqual(coordinate.worker(root), 0)
                task = coordinate.read_json(root / "task.json")
                receipt = coordinate.verify_return(root / "results", task, {"answer.txt": b"before\n"}, "run-one")
                effective = receipt["configuration"]["effective"]
                self.assertEqual(effective["thinking"], options.get("thinking", "high"))
                self.assertEqual(effective["provider"], options.get("provider", "example"))
                self.assertEqual((root / "results/changed-files/answer.txt").read_bytes(), b"after\n")
                self.assertEqual((root / "launch.json").read_bytes(), launch_before)
                self.assertEqual(sum(request["type"] == "prompt" for request in self.requests(root)), 1)
                for contents in coordinate.snapshot(root / "results").values():
                    self.assertNotIn(b"synthetic-private-marker", contents)
                    self.assertNotIn(b"synthetic.invalid", contents)

    def test_options_refuse_before_prompt_without_fallback(self):
        cases = [("unchanged", {"provider": "absent", "model": "absent"}), ("only-low", {}), ("clamped", {"thinking": "max"}), ("busy", {})]
        for index, (behavior, options) in enumerate(cases):
            with self.subTest(behavior=behavior):
                root = self.prepare(name=str(index), behavior=behavior, options=options)
                self.assertEqual(coordinate.worker(root), 1)
                self.assertFalse(any(request["type"] == "prompt" for request in self.requests(root)))
                self.assertFalse((root / "results/model-report.json").exists())

    def test_native_configuration_events_bind_setters_without_changing_metadata_defaults(self):
        cases = [("thinking", {"thinking": "low"}, False, "high", ["set_thinking_level"]),
                 ("model", {"provider": "second", "model": "model-two", "thinking": "max"}, False, "high", ["set_model", "set_thinking_level"]),
                 ("same-value", {}, False, "high", []),
                 ("metadata", {}, True, "low", [])]
        for name, options, metadata, default_thinking, expected in cases:
            with self.subTest(case=name):
                root = self.prepare(name=name, options=options, metadata=metadata)
                task = coordinate.read_json(root / "task.json")
                task["runtime_defaults"]["thinking"] = default_thinking
                dump(root / "task.json", task)
                self.assertEqual(coordinate.worker(root), 0)
                coordinate.verify_return(root / "results", task, {"answer.txt": b"before\n"}, "run-one")
                records = [json.loads(line) for line in (root / "results/rpc-events.jsonl").read_text().splitlines()]
                changes = [record for record in records if record["type"] == "configuration_event"]
                self.assertEqual([record["command"] for record in changes], expected)
                for event in changes:
                    request_index = next(index for index, record in enumerate(records) if record["type"] == "request" and record["id"] == event["id"])
                    response_index = next(index for index, record in enumerate(records) if record["type"] == "response" and record["id"] == event["id"])
                    self.assertLess(request_index, records.index(event))
                    self.assertLess(records.index(event), response_index)
                self.assertNotIn(b"synthetic-private-marker", (root / "results/rpc-events.jsonl").read_bytes())
                if metadata: self.assertFalse(self.requests(root)[-1]["type"] == "prompt")

    def test_unsolicited_malformed_or_unacknowledged_configuration_refuses_before_prompt(self):
        for behavior in ["unsolicited-configuration", "malformed-configuration", "duplicate-configuration", "missing-configuration", "late-configuration", "agent-before-prompt"]:
            with self.subTest(behavior=behavior):
                root = self.prepare(name=behavior, behavior=behavior, options={"thinking": "low"})
                self.assertEqual(coordinate.worker(root), 1)
                self.assertFalse(any(request["type"] == "prompt" for request in self.requests(root)))
                self.assertFalse((root / "results/rpc-configuration.json").exists())

    def test_returned_configuration_event_reordering_or_rebinding_is_rejected(self):
        root = self.prepare(options={"thinking": "low"})
        self.assertEqual(coordinate.worker(root), 0)
        task = coordinate.read_json(root / "task.json")
        for change in ["late", "foreign", "wrong-level", "duplicate", "missing"]:
            with self.subTest(change=change):
                output = root / change; shutil.copytree(root / "results", output)
                records = [json.loads(line) for line in (output / "rpc-events.jsonl").read_text().splitlines()]
                event_index = next(index for index, record in enumerate(records) if record["type"] == "configuration_event")
                event = records[event_index]
                if change == "late":
                    records.pop(event_index); records.insert(event_index + 1, event)
                elif change == "foreign": event["id"] = "request-foreign"
                elif change == "wrong-level": event["level"] = "medium"
                elif change == "duplicate": records.insert(event_index, dict(event))
                else: records.pop(event_index)
                (output / "rpc-events.jsonl").write_text(''.join(json.dumps(record)+'\n' for record in records))
                configuration = coordinate.read_json(output / "rpc-configuration.json"); configuration["rpc_log_sha256"] = coordinate.digest((output / "rpc-events.jsonl").read_bytes()); dump(output / "rpc-configuration.json", configuration)
                receipt = coordinate.read_json(output / "worker-receipt.json"); receipt["configuration"] = configuration; receipt["artifact_sha256"] = {name: coordinate.digest(raw) for name, raw in coordinate.snapshot(output).items() if name != "worker-receipt.json"}; dump(output / "worker-receipt.json", receipt)
                with self.assertRaises(ValueError): coordinate.verify_return(output, task, {"answer.txt": b"before\n"}, "run-one")
                with self.assertRaises(ValueError): coordinate.verify_recovered_artifacts(output, task, {"answer.txt": b"before\n"})

    def test_correlated_metadata_accepts_out_of_order_responses(self):
        root = self.prepare(behavior="out-of-order")
        self.assertEqual(coordinate.worker(root), 0)
        coordinate.verify_return(root / "results", coordinate.read_json(root / "task.json"), {"answer.txt": b"before\n"}, "run-one")

    def test_stderr_backpressure_is_drained_without_becoming_protocol(self):
        root = self.prepare(behavior="noisy")
        self.assertEqual(coordinate.worker(root), 0)
        self.assertGreater((root / "results/rpc/stderr.log").stat().st_size, 65536)
        self.assertNotIn(b"synthetic diagnostic", (root / "results/rpc-events.jsonl").read_bytes())
        coordinate.verify_return(root / "results", coordinate.read_json(root / "task.json"), {"answer.txt": b"before\n"}, "run-one")

    def test_interruption_closes_exact_child_stdin_without_fabricating_completion(self):
        root = self.prepare(behavior="no-response")
        children = []
        real_init = coordinate.PiRpc.__init__
        def track_child(instance, *args, **kwargs):
            real_init(instance, *args, **kwargs)
            children.append(instance.process)
        with mock.patch.object(coordinate.PiRpc, "__init__", track_child), mock.patch.object(coordinate.PiRpc, "pump", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): coordinate.worker(root)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].wait(timeout=2), 0)
        self.assertFalse((root / "results/rpc-configuration.json").exists())
        self.assertEqual(coordinate.read_json(root / "results/worker-receipt.json")["outcome"], "incomplete")

    def test_bad_protocol_and_bounds_never_prompt_or_return_success(self):
        for behavior in ["wrong-response", "wrong-command", "duplicate", "refused", "malformed", "partial", "oversized", "stderr-overflow", "no-response"]:
            with self.subTest(behavior=behavior):
                root = self.prepare(name=behavior, behavior=behavior)
                self.assertEqual(coordinate.worker(root), 1)
                self.assertFalse(any(request["type"] == "prompt" for request in self.requests(root)))
                self.assertFalse((root / "results/rpc-configuration.json").exists())

    def test_missing_ack_or_settlement_is_not_retried_and_checks_do_not_run(self):
        for behavior in ["no-prompt-ack", "no-settlement"]:
            root = self.prepare(name=behavior, behavior=behavior)
            self.assertEqual(coordinate.worker(root), 1)
            self.assertEqual(sum(request["type"] == "prompt" for request in self.requests(root)), 1)
            self.assertFalse((root / "results/changes.json").exists())

    def test_metadata_only_has_no_prompt_extension_or_change_artifacts(self):
        root = self.prepare(metadata=True)
        self.assertEqual(coordinate.worker(root), 0)
        task = coordinate.read_json(root / "task.json")
        receipt = coordinate.verify_return(root / "results", task, {"answer.txt": b"before\n"}, "run-one")
        self.assertEqual(receipt["outcome"], "capabilities")
        self.assertFalse(receipt["configuration"]["prompt_sent"])
        self.assertFalse(any(request["type"] in {"prompt", "set_model", "set_thinking_level"} for request in self.requests(root)))

    def test_metadata_reports_off_only_model_without_applying_profile_defaults(self):
        for index, default_model in enumerate(["example/model", "unavailable/profile-default"]):
            with self.subTest(default_model=default_model):
                root = self.prepare(name=str(index), behavior="off-only", metadata=True)
                task = coordinate.read_json(root / "task.json")
                task["runtime_defaults"]["model"] = default_model
                dump(root / "task.json", task)
                self.assertEqual(coordinate.worker(root), 0)
                receipt = coordinate.verify_return(root / "results", task, {"answer.txt": b"before\n"}, "run-one")
                self.assertEqual(receipt["configuration"]["supported_thinking_levels"], ["off"])
                self.assertEqual(receipt["configuration"]["effective"], {"provider": "example", "model": "model", "thinking": "off"})
                self.assertEqual([request["type"] for request in self.requests(root)], ["get_available_models", "get_state", "get_available_thinking_levels", "get_state"])
        task_run = self.prepare(name="task-run", behavior="off-only")
        self.assertEqual(coordinate.worker(task_run), 1)
        self.assertFalse(any(request["type"] == "prompt" for request in self.requests(task_run)))

    def test_check_named_pi_stderr_keeps_independent_diagnostics_and_recovery_bindings(self):
        for exit_code in [0, 7]:
            with self.subTest(exit_code=exit_code):
                root = self.prepare(name=str(exit_code))
                check = {"name": "pi-stderr", "argv": [sys.executable, "-c", f"print('declared check output'); raise SystemExit({exit_code})"], "timeout_seconds": 2}
                task = coordinate.read_json(root / "task.json"); task["checks"] = [check]; dump(root / "task.json", task)
                launch = coordinate.read_json(root / "launch.json"); launch["checks"] = [check]; dump(root / "launch.json", launch)
                self.assertEqual(coordinate.worker(root), int(exit_code != 0))
                self.assertEqual((root / "results/pi-stderr.log").read_bytes(), b"declared check output\n")
                self.assertEqual((root / "results/rpc/stderr.log").read_bytes(), b"")
                if exit_code == 0:
                    coordinate.verify_return(root / "results", task, {"answer.txt": b"before\n"}, "run-one")
                coordinate.verify_recovered_artifacts(root / "results", task, {"answer.txt": b"before\n"})
        root = self.prepare(name="before-check", behavior="refused")
        task = coordinate.read_json(root / "task.json"); task["checks"] = [check]; dump(root / "task.json", task)
        launch = coordinate.read_json(root / "launch.json"); launch["checks"] = [check]; dump(root / "launch.json", launch)
        self.assertEqual(coordinate.worker(root), 1)
        self.assertFalse((root / "results/pi-stderr.log").exists())
        coordinate.verify_recovered_artifacts(root / "results", task, {"answer.txt": b"before\n"})

    def test_trusted_check_observes_changed_bytes_after_shutdown(self):
        root = self.prepare()
        task = coordinate.read_json(root / "task.json")
        check = {"name": "after-shutdown", "argv": [sys.executable, "-c", "import json,pathlib; p=pathlib.Path; assert p('answer.txt').read_text()=='after\\n'; assert json.loads(p('../results/extension-events.jsonl').read_text().splitlines()[-1])['type']=='session_shutdown'; print('checked returned bytes after shutdown')"], "timeout_seconds": 2}
        task["checks"] = [check]; dump(root / "task.json", task)
        launch = coordinate.read_json(root / "launch.json"); launch["checks"] = [check]; dump(root / "launch.json", launch)
        self.assertEqual(coordinate.worker(root), 0)
        receipt = coordinate.verify_return(root / "results", task, {"answer.txt": b"before\n"}, "run-one")
        self.assertTrue(receipt["checks_passed"])
        self.assertIn(b"checked returned bytes", (root / "results/after-shutdown.log").read_bytes())

    def test_resealed_configuration_contradictions_are_rejected(self):
        root = self.prepare()
        self.assertEqual(coordinate.worker(root), 0)
        configuration = coordinate.read_json(root / "results/rpc-configuration.json")
        configuration["effective"]["thinking"] = "low"
        dump(root / "results/rpc-configuration.json", configuration)
        worker = coordinate.read_json(root / "results/worker-receipt.json")
        worker["configuration"] = configuration
        worker["artifact_sha256"] = {name: coordinate.digest(raw) for name, raw in coordinate.snapshot(root / "results").items() if name != "worker-receipt.json"}
        dump(root / "results/worker-receipt.json", worker)
        task = coordinate.read_json(root / "task.json")
        with self.assertRaises(ValueError): coordinate.verify_return(root / "results", task, {"answer.txt": b"before\n"}, "run-one")
        with self.assertRaises(ValueError): coordinate.verify_recovered_artifacts(root / "results", task, {"answer.txt": b"before\n"})


class RecoveryChangeTests(unittest.TestCase):
    setUp = WorkerTests.setUp
    prepare = WorkerTests.prepare

    def test_historical_v1_inputs_and_failed_artifacts_remain_recoverable(self):
        root = self.prepare(name="a" * 32, checks=[{"name": "failed", "argv": [sys.executable, "-c", "raise SystemExit(9)"], "timeout_seconds": 2}])
        task = coordinate.read_json(root / "task.json")
        task["run_id"] = root.name
        task["source"]["modes"] = {"answer.txt": 0o644}
        task["allowed_tools"] = sorted(coordinate.TOOLS)
        dump(root / "task.json", task)
        self.assertEqual(coordinate.worker(root), 1)
        payload = {"task.json": json.dumps(task).encode(), "launch.json": (root / "launch.json").read_bytes(), "coordinate.py": b"# retained version one worker", "extension.js": b"// retained version one extension", "package.json": b'{"type":"module"}', "workspace/answer.txt": b"before\n"}
        archive = make_archive([(name, raw, tarfile.REGTYPE) for name, raw in payload.items()])
        (root / "inputs.tar").write_bytes(archive)
        original = {"version": 1, "run_id": root.name, "task_id": task["task_id"], "kind": task["kind"], "started_at": "2000-01-01T00:00:00Z", "source": task["source"], "input_sha256": coordinate.digest(archive), "remote_artifacts": str(root / "results"), "delivery_valid": False}
        dump(root / "started.json", original); dump(root / "receipt.json", original)
        profile = {"remote_parent": str(self.root)}
        before = {name: (root / name).read_bytes() for name in ["started.json", "receipt.json", "inputs.tar"]}
        _original, retained_task, source, _hashes = coordinate.recovery_inputs(root, profile)
        self.assertEqual(retained_task, task)
        recovered = coordinate.verify_recovered_artifacts(root / "results", retained_task, source)
        self.assertEqual(recovered["evidence_status"], "complete")
        self.assertEqual(recovered["worker_outcome"], "failed")
        self.assertEqual(recovered["checks"][0]["exit_code"], 9)
        self.assertEqual(before, {name: (root / name).read_bytes() for name in before})

    def test_failed_check_change_bindings_remain_strict(self):
        check = {'name': 'proof', 'argv': [sys.executable, '-c', 'raise SystemExit(9)'], 'timeout_seconds': 2}
        root = self.prepare(behavior='change', checks=[check])
        self.assertEqual(coordinate.worker(root), 1)
        task = coordinate.read_json(root / 'task.json')
        source = {'answer.txt': b'before\n'}
        result = coordinate.verify_recovered_artifacts(root / 'results', task, source)
        self.assertEqual(result['evidence_status'], 'complete')
        self.assertEqual(result['checks'][0]['exit_code'], 9)
        for kind in ['base', 'bytes', 'patch', 'scope']:
            with self.subTest(kind=kind):
                output = root / kind; shutil.copytree(root / 'results', output)
                if kind == 'base':
                    changes = coordinate.read_json(output / 'changes.json'); changes[0]['before_sha256'] = '0' * 64; dump(output / 'changes.json', changes)
                elif kind == 'bytes': (output / 'changed-files/answer.txt').write_text('forged')
                elif kind == 'patch': (output / 'changes.patch').write_text('forged')
                else: (output / 'changed-files/unapproved.txt').write_text('forged')
                receipt = coordinate.read_json(output / 'worker-receipt.json'); receipt['artifact_sha256'] = {name: coordinate.digest(raw) for name, raw in coordinate.snapshot(output).items() if name != 'worker-receipt.json'}; dump(output / 'worker-receipt.json', receipt)
                with self.assertRaises(ValueError): coordinate.verify_recovered_artifacts(output, task, source)


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profile = {"sandbox_name": "disposable", "sandbox_id": "sandbox-id",
                        "pi_argv": [sys.executable, str(self.root / "fake-pi.py"), "unchanged"],
                        "model": "example/model", "remote_parent": str(self.root / "remote"),
                        "python": sys.executable, "protected_sandboxes": ["protected"]}
        (self.root / "fake-pi.py").write_text(FAKE_RPC)
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
                    if mode == "start-no-change-error": raise subprocess.CalledProcessError(1, "synthetic unchanged start")
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

    def test_registered_default_supports_capabilities_and_run_without_profile_flag(self):
        with mock.patch.object(Path, "home", return_value=self.root), mock.patch.object(coordinate, "OpenShellOwner", self.factory()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(coordinate.main(["configure", "--profile", str(self.profile_path)]), 0)
            default = self.root / ".config/codex-pi-coordination/profile.json"
            original = default.read_bytes()
            self.assertEqual(coordinate.main(["capabilities", "--output", str(self.root / "metadata")]), 0)
            metadata = coordinate.read_json(self.root / "metadata/receipt.json")
            self.assertTrue(metadata["capabilities_valid"])
            self.assertFalse(metadata["delivery_valid"])
            self.assertTrue(metadata["cleanup_complete"])
            self.assertEqual(coordinate.main(["run", str(self.task_path), "--output", str(self.root / "default-run")]), 0)
            self.assertTrue(coordinate.read_json(self.root / "default-run/receipt.json")["delivery_valid"])
            self.assertEqual(default.read_bytes(), original)

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

    def test_failed_exec_stops_exact_owned_sandbox(self):
        receipt = self.run_fake("exec-error")
        self.assertFalse(receipt["delivery_valid"])
        self.assertTrue(receipt["cleanup_complete"])
        self.assertEqual(self.instances[-1].calls.count("stop"), 1)
        self.assertNotIn("download", self.instances[-1].calls)

    def test_failed_start_with_unbound_changed_main_never_stops_it(self):
        receipt = self.run_fake("start-error")
        self.assertFalse(receipt["delivery_valid"])
        self.assertFalse(receipt["cleanup_complete"])
        self.assertEqual(self.instances[-1].calls, ["start"])
        self.assertEqual(self.instances[-1].main_instance, "old")
        with self.assertRaises(ValueError): self.run_fake(name="blocked-next")

    def test_failed_start_that_keeps_exact_stopped_state_needs_no_stop(self):
        receipt = self.run_fake("start-no-change-error")
        self.assertFalse(receipt["delivery_valid"])
        self.assertTrue(receipt["cleanup_complete"])
        self.assertEqual(self.instances[-1].calls, ["start"])
        self.assertEqual(receipt["sandbox_before"], receipt["sandbox_after"])

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


class RecoveryTests(unittest.TestCase):
    setUp = OwnerTests.setUp
    factory = OwnerTests.factory
    run_fake = OwnerTests.run_fake

    def failed_run(self, *, partial=False, returned=False):
        if not returned:
            task = task_template()
            task['checks'] = [{'name': 'intentional-failure', 'argv': [sys.executable, '-c', "print('failure evidence'); raise SystemExit(19)"], 'timeout_seconds': 2}]
            dump(self.task_path, task)
        receipt = self.run_fake('stop-error' if returned else 'normal')
        self.assertFalse(receipt['delivery_valid'])
        if partial:
            results = Path(receipt['remote_artifacts'])
            for name in ['worker-receipt.json', 'intentional-failure.result.json', 'changes.json', 'changes.patch']:
                (results / name).unlink()
        return receipt

    def recovery_factory(self, mode='normal'):
        test = self
        journal_path = self.root / 'locks' / (coordinate.digest(b'sandbox-id') + '.json')
        prior = coordinate.read_json(journal_path)
        class RecoveryOwner(coordinate.OpenShellOwner):
            def __init__(self, profile):
                super().__init__(profile)
                self.state = copy.deepcopy(prior.get('sandbox_after', prior.get('sandbox_running')))
                self.calls = []; test.instances.append(self)
                if mode == 'initial-active': self.state['phase'] = 'Ready'
                if mode == 'initial-wrong-main': self.state['main_process_instance_id'] = 'unrelated-main'
                if mode == 'initial-wrong-id': self.state['id'] = 'unrelated-sandbox'
                if mode == 'reconciled': self.state['phase'] = 'Stopped'
            def get(self, name=None):
                if name == 'protected':
                    return {'id': 'protected-id', 'name': name, 'phase': 'Ready', 'main_process_instance_id': 'changed' if mode == 'protected-drift' and self.calls else 'protected-main', 'restart_count': 0}
                return copy.deepcopy(self.state)
            def command(self, *args, timeout=60):
                self.calls.append(args[0])
                if args[0] == 'start':
                    self.state.update(phase='Ready', main_process_instance_id='fresh-' + prior['run_id'] if mode != 'reused-main' else self.state['main_process_instance_id'])
                    self.state['restart_count'] += 1
                    if mode == 'start-error': raise subprocess.CalledProcessError(1, 'synthetic start')
                elif args[0] == 'download':
                    if mode == 'download-error': raise subprocess.CalledProcessError(1, 'synthetic download')
                    if mode == 'timeout': raise subprocess.TimeoutExpired('synthetic download', timeout)
                    if mode == 'cancel': raise KeyboardInterrupt('synthetic cancellation')
                    shutil.copytree(args[-2], args[-1])
                    if mode == 'replaced': self.state['main_process_instance_id'] = 'unowned-replacement'
                    if mode == 'manifest-tamper': (Path(args[-1]) / 'intentional-failure.log').write_text('tampered')
                elif args[0] == 'stop':
                    if mode == 'stop-error': raise subprocess.CalledProcessError(1, 'synthetic stop')
                    self.state['phase'] = 'Stopped'
                else: raise AssertionError('Recovery must not launch ' + args[0])
                return subprocess.CompletedProcess(args, 0, '', '')
        return RecoveryOwner

    def recover(self, mode='normal', output='recovered'):
        with mock.patch.object(coordinate, 'OpenShellOwner', self.recovery_factory(mode)):
            return coordinate.recover_task(self.root / 'out', self.profile_path, self.root / output, self.root / 'locks')

    def test_nonzero_check_recovers_without_reexecution_or_task_success(self):
        original = self.failed_run()
        before = {name: (self.root / 'out' / name).read_bytes() for name in ['receipt.json', 'inputs.tar', 'started.json']}
        remote = Path(original['remote_artifacts']).parent
        model_calls = (remote / 'invocations.txt').read_bytes()
        receipt = self.recover()
        self.assertTrue(receipt['recovery_valid']); self.assertFalse(receipt['task_delivery_valid'])
        self.assertFalse(receipt['delivery_valid']); self.assertEqual(receipt['acceptance'], 'not_granted')
        self.assertEqual(receipt['outcome'], 'recovered_complete')
        self.assertEqual(receipt['evidence']['checks'], [{'name': 'intentional-failure', 'state': 'completed', 'exit_code': 19}])
        self.assertEqual(self.instances[-1].calls, ['start', 'download', 'stop'])
        self.assertEqual((remote / 'invocations.txt').read_bytes(), model_calls)
        self.assertEqual(before, {name: (self.root / 'out' / name).read_bytes() for name in before})
        self.assertEqual(coordinate.read_json(self.root / 'recovered/prior-journal.json'), original)
        original_task = json.loads(coordinate.safe_archive_files(before['inputs.tar'])['task.json'])
        with self.assertRaises(ValueError): coordinate.verify_return(self.root / 'recovered/results', original_task, {}, original['run_id'])
        self.assertEqual(receipt['sandbox_after']['phase'], 'Stopped')
        self.assertNotEqual(receipt['sandbox_before']['main_process_instance_id'], receipt['sandbox_running']['main_process_instance_id'])

    def test_partial_evidence_keeps_missing_exit_code_unknown(self):
        self.failed_run(partial=True)
        receipt = self.recover()
        self.assertTrue(receipt['recovery_valid'])
        self.assertEqual(receipt['outcome'], 'recovered_partial')
        self.assertIsNone(receipt['evidence']['worker_outcome'])
        self.assertEqual(receipt['evidence']['checks'][0], {'name': 'intentional-failure', 'state': 'unknown', 'exit_code': None})

    def test_failed_cleanup_returned_worker_is_recoverable_after_reconcile(self):
        original = self.failed_run(returned=True)
        self.assertEqual(original['outcome'], 'returned')
        self.assertFalse(original['cleanup_complete'])
        arguments = ['reconcile', '--profile', str(self.profile_path), '--lock-root', str(self.root / 'locks')]
        with mock.patch.object(coordinate, 'OpenShellOwner', self.recovery_factory('reconciled')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(coordinate.main(arguments), 0)
        self.assertTrue(self.recover()['recovery_valid'])

    def test_refuses_successful_input_before_lifecycle(self):
        self.run_fake()
        with self.assertRaisesRegex(ValueError, 'unsuccessful'):
            coordinate.recover_task(self.root / 'out', self.profile_path, self.root / 'recovered', self.root / 'locks')
        self.assertEqual(len(self.instances), 1)

    def test_recovery_retry_keeps_original_identity_after_reconcile(self):
        original = self.failed_run()
        failed = self.recover('stop-error')
        self.assertFalse(failed['cleanup_complete'])
        with self.assertRaises(ValueError): self.recover(output='unresolved')
        arguments = ['reconcile', '--profile', str(self.profile_path), '--lock-root', str(self.root / 'locks')]
        with mock.patch.object(coordinate, 'OpenShellOwner', self.recovery_factory('reconciled')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(coordinate.main(arguments), 0)
        result = self.recover(output='retry')
        self.assertTrue(result['recovery_valid'])
        self.assertEqual(result['failed_run_id'], original['run_id'])
        self.assertEqual(result['failed_input_sha256'], original['input_sha256'])
        with self.assertRaises(FileExistsError): self.recover(output='retry')

    def test_input_tampering_and_newer_custody_refuse_before_start(self):
        self.failed_run()
        original = self.root / 'out/receipt.json'
        pristine = original.read_bytes()
        for key, value in [('input_sha256', '0' * 64), ('remote_artifacts', '/arbitrary/results'), ('run_id', '../escape')]:
            with self.subTest(key=key):
                receipt = json.loads(pristine); receipt[key] = value; dump(original, receipt)
                with self.assertRaises(ValueError): self.recover(output=key)
                original.write_bytes(pristine)
        archive = self.root / 'out/inputs.tar'; archive_bytes = archive.read_bytes()
        archive.write_bytes(archive_bytes + b'changed')
        with self.assertRaises(ValueError): self.recover(output='changed-archive')
        archive.write_bytes(archive_bytes)
        journal = self.root / 'locks' / (coordinate.digest(b'sandbox-id') + '.json')
        prior = coordinate.read_json(journal); prior['run_id'] = 'b' * 32; dump(journal, prior)
        with self.assertRaises(ValueError): self.recover(output='newer')
        self.assertEqual(self.instances[-1].calls, [])

    def test_active_or_changed_owner_refuses_without_action(self):
        self.failed_run()
        for mode in ['initial-active', 'initial-wrong-main', 'initial-wrong-id']:
            with self.subTest(mode=mode), self.assertRaises(ValueError): self.recover(mode, mode)
            self.assertEqual(self.instances[-1].calls, [])

    def test_download_faults_retain_cleanup_and_no_task_launch(self):
        self.failed_run()
        for mode in ['download-error', 'timeout', 'cancel', 'manifest-tamper', 'protected-drift']:
            with self.subTest(mode=mode):
                receipt = self.recover(mode, mode)
                self.assertFalse(receipt['recovery_valid'])
                self.assertTrue(receipt['cleanup_complete'])
                self.assertTrue(set(self.instances[-1].calls) <= {'start', 'download', 'stop'})
                if mode == 'protected-drift': self.assertFalse(receipt['protected_unchanged'])

    def test_reused_main_is_not_a_fresh_recovery_owner(self):
        self.failed_run()
        receipt = self.recover('reused-main')
        self.assertFalse(receipt['cleanup_complete'])
        self.assertFalse(receipt['recovery_valid'])
        self.assertEqual(self.instances[-1].calls, ['start'])

    def test_replacement_is_not_stopped_and_blocks_reuse(self):
        self.failed_run()
        result = self.recover('replaced')
        self.assertFalse(result['cleanup_complete']); self.assertFalse(result['recovery_valid'])
        self.assertNotIn('stop', self.instances[-1].calls)
        with self.assertRaises(ValueError): self.recover(output='retry')

    def test_artifact_tampering_cannot_hide_behind_updated_manifest(self):
        original = self.failed_run()
        _, task, source, _ = coordinate.recovery_inputs(self.root / 'out', self.profile)
        pristine = Path(original['remote_artifacts'])
        for kind in ['check-argv', 'check-log', 'check-exit-type', 'model-task', 'worker-task', 'extension-task', 'unexpected', 'symlink', 'manifest', 'partial-extension']:
            with self.subTest(kind=kind):
                result = self.root / kind; shutil.copytree(pristine, result)
                receipt = coordinate.read_json(result / 'worker-receipt.json')
                if kind in ['check-argv', 'check-exit-type']:
                    check = coordinate.read_json(result / 'intentional-failure.result.json')
                    check['argv' if kind == 'check-argv' else 'exit_code'] = ['unapproved'] if kind == 'check-argv' else True
                    dump(result / 'intentional-failure.result.json', check); receipt['checks'] = [check]
                elif kind == 'check-log': (result / 'intentional-failure.log').write_text('forged')
                elif kind == 'model-task':
                    report = coordinate.read_json(result / 'model-report.json'); report['task_sha256'] = '0' * 64; dump(result / 'model-report.json', report)
                    receipt['model_report_sha256'] = coordinate.digest((result / 'model-report.json').read_bytes())
                elif kind == 'worker-task': receipt['task_id'] = 'wrong'
                elif kind in ['extension-task', 'partial-extension']:
                    events = (result / 'extension-events.jsonl').read_text(); (result / 'extension-events.jsonl').write_text(events.replace(task['run_id'], 'wrong'))
                    if kind == 'partial-extension': receipt.pop('extension'); receipt.pop('events')
                elif kind == 'unexpected': (result / 'extra.json').write_text('{}')
                elif kind == 'symlink': (result / 'linked').symlink_to(self.task_path)
                elif kind == 'manifest': receipt['artifact_sha256'] = {}
                if kind != 'symlink' and kind != 'manifest': receipt['artifact_sha256'] = {name: coordinate.digest(raw) for name, raw in coordinate.snapshot(result).items() if name != 'worker-receipt.json'}
                dump(result / 'worker-receipt.json', receipt)
                with self.assertRaises(ValueError): coordinate.verify_recovered_artifacts(result, task, source)

    def test_failed_start_never_stops_an_unbound_new_main(self):
        self.failed_run()
        receipt = self.recover('start-error')
        self.assertFalse(receipt['cleanup_complete'])
        self.assertNotIn('stop', self.instances[-1].calls)
        self.assertNotIn('download', self.instances[-1].calls)
        with self.assertRaises(ValueError): self.recover(output='retry')

    def test_recovery_lock_and_unknown_custody_refuse(self):
        self.failed_run()
        with coordinate.exclusive_owner(self.profile, self.root / 'locks'):
            with self.assertRaises(BlockingIOError): self.recover(output='locked')
        journal = self.root / 'locks' / (coordinate.digest(b'sandbox-id') + '.json')
        receipt = coordinate.read_json(journal); receipt['cleanup_complete'] = False; dump(journal, receipt)
        with self.assertRaises(ValueError): self.recover(output='unknown')
        self.assertEqual(self.instances[-1].calls, [])

    def test_available_artifact_bounds_and_partial_log_tail(self):
        original = self.failed_run(partial=True)
        _, task, source, _ = coordinate.recovery_inputs(self.root / 'out', self.profile)
        results = Path(original['remote_artifacts'])
        extension = results / 'extension-events.jsonl'
        with extension.open('ab') as stream: stream.write(b'{"interrupted":')
        self.assertEqual(coordinate.verify_recovered_artifacts(results, task, source)['evidence_status'], 'partial')
        with mock.patch.object(coordinate, 'MAX_FILES', 1), self.assertRaises(ValueError): coordinate.verify_recovered_artifacts(results, task, source)
        with mock.patch.object(coordinate, 'MAX_SOURCE_BYTES', 10), self.assertRaises(ValueError): coordinate.verify_recovered_artifacts(results, task, source)
        with mock.patch.object(coordinate, 'MAX_OUTPUT_BYTES', 1), self.assertRaises(ValueError): coordinate.verify_recovered_artifacts(results, task, source)

    def test_archive_source_and_task_changes_refuse_even_with_resealed_input(self):
        self.failed_run()
        failed = self.root / 'out'
        pristine = {name: (failed / name).read_bytes() for name in ['inputs.tar', 'started.json', 'receipt.json']}
        for kind in ['task', 'source', 'members', 'unsafe']:
            with self.subTest(kind=kind):
                payload = coordinate.safe_archive_files(pristine['inputs.tar'])
                if kind == 'task':
                    task = json.loads(payload['task.json']); task['run_id'] = 'wrong'; payload['task.json'] = json.dumps(task).encode()
                elif kind == 'source': payload['workspace/unbound.txt'] = b'changed'
                elif kind == 'members': payload['unexpected'] = b'changed'
                else: payload['../escape'] = b'changed'
                raw = make_archive([(name, data, tarfile.REGTYPE) for name, data in payload.items()])
                (failed / 'inputs.tar').write_bytes(raw)
                for name in ['started.json', 'receipt.json']:
                    value = json.loads(pristine[name]); value['input_sha256'] = coordinate.digest(raw); dump(failed / name, value)
                with self.assertRaises(ValueError): coordinate.recovery_inputs(failed, self.profile)
                for name, data in pristine.items(): (failed / name).write_bytes(data)

    def test_partial_present_metadata_must_not_contradict_itself(self):
        original = self.failed_run()
        _, task, source, _ = coordinate.recovery_inputs(self.root / 'out', self.profile)
        pristine = Path(original['remote_artifacts'])
        cases = ['scope', 'duplicate-files', 'different-lists', 'returned-failed-check', 'returned-failed-check-no-summary', 'nonzero-pi-after-check', 'null-missing-report-hash', 'invalid-report-hash', 'false-change-match', 'nonboolean-change-match', 'null-model-status']
        for kind in cases:
            with self.subTest(kind=kind):
                result = self.root / kind; shutil.copytree(pristine, result)
                for name in ['changes.json', 'changes.patch']: (result / name).unlink()
                receipt = coordinate.read_json(result / 'worker-receipt.json'); receipt.pop('artifact_sha256')
                altered_task = copy.deepcopy(task)
                if kind == 'scope': receipt['changed_files'] = ['unapproved.txt']
                elif kind == 'duplicate-files': receipt['changed_files'] = ['answer.txt', 'answer.txt']; altered_task['writable_paths'] = ['answer.txt']
                elif kind == 'different-lists':
                    receipt['changed_files'] = ['answer.txt']; altered_task['writable_paths'] = ['answer.txt']
                elif kind in ('returned-failed-check', 'returned-failed-check-no-summary'):
                    receipt['outcome'] = 'returned'
                    if kind.endswith('no-summary'): receipt.pop('checks_passed')
                elif kind == 'nonzero-pi-after-check': receipt['pi_exit_code'] = 9
                elif kind == 'null-missing-report-hash':
                    (result / 'model-report.json').unlink(); receipt['model_report_sha256'] = None; receipt.pop('model_status')
                elif kind == 'invalid-report-hash': receipt['model_report_sha256'] = 0
                elif kind == 'false-change-match': receipt['model_report_matches_changes'] = False
                elif kind == 'nonboolean-change-match': receipt['model_report_matches_changes'] = 1
                elif kind == 'null-model-status': receipt['model_status'] = None; (result / 'model-report.json').unlink(); receipt.pop('model_report_sha256')
                # Changing the task would independently break its hash. Rebind the
                # report/events so list scope/consistency remains the tested guard.
                if altered_task != task:
                    old_hash = coordinate.digest(json.dumps(task).encode()); new_hash = coordinate.digest(json.dumps(altered_task).encode())
                    for name in ['model-report.json', 'extension-events.jsonl']:
                        file = result / name; file.write_bytes(file.read_bytes().replace(old_hash.encode(), new_hash.encode()))
                    receipt['model_report_sha256'] = coordinate.digest((result / 'model-report.json').read_bytes())
                    receipt.pop('extension')
                dump(result / 'worker-receipt.json', receipt)
                with self.assertRaises(ValueError): coordinate.verify_recovered_artifacts(result, altered_task, source)

    def test_nonzero_pi_before_checks_is_valid_partial_failure_evidence(self):
        self.profile['pi_argv'][-1] = 'exit-seven'; dump(self.profile_path, self.profile)
        task = task_template(); task['checks'] = [{'name': 'not-started', 'argv': [sys.executable, '-c', 'raise AssertionError("must not run")'], 'timeout_seconds': 2}]; dump(self.task_path, task)
        original = self.run_fake()
        result = self.recover()
        self.assertTrue(result['recovery_valid'])
        self.assertEqual(result['outcome'], 'recovered_partial')
        self.assertEqual(result['evidence']['checks'], [{'name': 'not-started', 'state': 'unknown', 'exit_code': None}])
        self.assertEqual(coordinate.read_json(self.root / 'recovered/results/worker-receipt.json')['pi_exit_code'], 7)
        self.assertEqual(self.instances[-1].calls, ['start', 'download', 'stop'])
        self.assertFalse(original['delivery_valid'])

    def test_absent_terminal_worker_fields_remain_partial_unknown(self):
        original = self.failed_run(partial=True)
        results = Path(original['remote_artifacts'])
        # Keep only a minimally attributed interrupted worker receipt. Presence
        # checks must not turn unknown exit/status/change fields into requirements.
        dump(results / 'worker-receipt.json', {'run_id': original['run_id'], 'task_id': original['task_id'], 'outcome': 'incomplete', 'checks': []})
        receipt = self.recover()
        self.assertTrue(receipt['recovery_valid'])
        self.assertEqual(receipt['outcome'], 'recovered_partial')
        self.assertIsNone(receipt['evidence']['checks'][0]['exit_code'])

    def test_signal_handlers_restore_even_when_final_receipt_or_journal_fails(self):
        for operation in ['run', 'recover']:
            for destination in ['receipt', 'journal']:
                with self.subTest(operation=operation, destination=destination):
                    fixture = RecoveryTests(); fixture.setUp()
                    previous = {sig: coordinate.signal.getsignal(sig) for sig in (coordinate.signal.SIGINT, coordinate.signal.SIGTERM)}
                    try:
                        if operation == 'recover': fixture.failed_run()
                        output_name = 'failed-finalization'
                        target = fixture.root / output_name / 'receipt.json'
                        journal = fixture.root / 'locks' / (coordinate.digest(b'sandbox-id') + '.json')
                        original_new = coordinate.write_new_json; original_write = Path.write_text
                        def fail_new(path, value):
                            if destination == 'receipt' and Path(path) == target: raise OSError('injected final receipt persistence failure')
                            return original_new(path, value)
                        def fail_write(path, data, *args, **kwargs):
                            if destination == 'journal' and path == journal and 'ended_at' in json.loads(data): raise OSError('injected final journal persistence failure')
                            return original_write(path, data, *args, **kwargs)
                        with mock.patch.object(coordinate, 'write_new_json', fail_new), mock.patch.object(Path, 'write_text', fail_write):
                            with self.assertRaises(OSError):
                                fixture.run_fake(name=output_name) if operation == 'run' else fixture.recover(output=output_name)
                        self.assertEqual({sig: coordinate.signal.getsignal(sig) for sig in previous}, previous)
                        self.assertEqual(fixture.instances[-1].calls.count('stop'), 1)
                        self.assertEqual(fixture.instances[-1].state['phase'], 'Stopped')
                        if destination == 'journal':
                            self.assertFalse(coordinate.read_json(journal)['cleanup_complete'])
                            with self.assertRaises(ValueError): fixture.run_fake(name='blocked-reuse')
                    finally:
                        for sig, handler in previous.items(): coordinate.signal.signal(sig, handler)
                        fixture.doCleanups()


    def test_cli_reports_recovery_separately_from_delivery(self):
        self.failed_run()
        with mock.patch.object(coordinate, 'OpenShellOwner', self.recovery_factory()), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = coordinate.main(['recover', str(self.root / 'out'), '--profile', str(self.profile_path), '--output', str(self.root / 'recovered'), '--lock-root', str(self.root / 'locks')])
        summary = json.loads(stdout.getvalue())
        self.assertEqual(code, 0); self.assertTrue(summary['recovery_valid']); self.assertFalse(summary['task_delivery_valid'])
        self.assertEqual(summary['acceptance'], 'not_granted')


if __name__ == "__main__":
    unittest.main()
