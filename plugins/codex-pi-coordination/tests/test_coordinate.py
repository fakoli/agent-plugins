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
if behavior in ('change','out-scope') or behavior.startswith('saved-'):
    name='answer.txt' if behavior=='change' else 'unapproved.txt'
    if behavior.startswith('saved-'): name='answer.txt'
    (workspace/name).write_text(task['instructions']+'\n' if behavior.startswith('saved-') else 'after\n'); changed=[name]
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
    return {'type':kind,'at':'2000-01-01T00:00:00Z','active':True,'run_id':task['run_id'],'task_id':task['task_id'],'task_sha256':task_digest,'tool_calls':calls,'turns':turns,'handed_off':handed_off,**({'session':rpc_saved_identity} if task['version']==3 else {}),**fields}
extension_events=[extension_event('task_loaded',0,0,False),extension_event('tool_call',handed_off=False,tool_name='coordination_handoff',tool_call_id='call-1'),extension_event('handoff',reported_status=report['status']),extension_event('agent_settled'),extension_event('session_shutdown')]
if task['version'] in (2,3):
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
import json, pathlib, sys, os, uuid
behavior = sys.argv[1]
requests_file = pathlib.Path(__file__).with_suffix('.requests.jsonl')
model = {'provider':'example','id':'model','headers':{'Authorization':'synthetic-private-marker'},'baseUrl':'https://synthetic.invalid/private'}
thinking = 'high'
levels = ['off','minimal','low','medium','high','xhigh','max']
if behavior=='off-only': thinking='off';levels=['off']
session_path = pathlib.Path(sys.argv[sys.argv.index('--session')+1]) if '--session' in sys.argv else None
session_id = 'session-one'
entries = []
if session_path:
    assert '--no-session' not in sys.argv
    assert str(session_path.parent) == sys.argv[sys.argv.index('--session-dir')+1]
    if session_path.exists():
        entries = [json.loads(line) for line in session_path.read_text().splitlines()]
        assert entries[0]['cwd'] == os.getcwd()
        for entry in entries[1:]:
            if entry['type']=='model_change': model={'provider':entry['provider'],'id':entry['modelId']}
            if entry['type']=='thinking_level_change': thinking=entry['thinkingLevel']
    else:
        entries=[{'type':'session','version':3,'id':str(uuid.uuid4()),'timestamp':'2000-01-01T00:00:00Z','cwd':os.getcwd()}]
    session_id=entries[0]['id']
    assert not session_path.exists() or session_path.stat().st_size
def persist_entry(kind, **fields):
    if not session_path: return
    entry={'type':kind,'id':uuid.uuid4().hex[:8],'parentId':entries[-1].get('id') if len(entries)>1 else None,'timestamp':'2000-01-01T00:00:00Z',**fields}
    entries.append(entry)
    if session_path.exists():
        with session_path.open('a') as stream: stream.write(json.dumps(entry)+'\n')
    elif any(item.get('message',{}).get('role')=='assistant' for item in entries):
        with session_path.open('x') as stream:
            for item in entries: stream.write(json.dumps(item)+'\n')
held = None
def change_thinking(level):
    global thinking
    if level == thinking: return
    thinking = level
    persist_entry('thinking_level_change',thinkingLevel=level)
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
        if behavior=='selected-duplicate-model': data['models'].append(dict(data['models'][1]))
        if behavior in ('out-of-order','selected-out-of-order'): held=(request,data);continue
    elif command=='get_state':
        data={'model':model,'thinkingLevel':thinking,'sessionId':session_id,'sessionFile':str(session_path) if session_path else None,'isStreaming':False,'isCompacting':False,'pendingMessageCount':0}
        if behavior=='busy': data['pendingMessageCount']=1
        if behavior=='saved-wrong-id': data['sessionId']='foreign-session'
        if behavior=='selected-wrong-model' and model['provider']=='second': data['model']={'provider':'foreign','id':'model'}
        if behavior=='selected-wrong-level' and model['provider']=='second': data['thinkingLevel']='high'
    elif command=='get_available_thinking_levels': data={'levels':['low'] if behavior=='only-low' else levels}
    elif command=='set_model':
        model={'provider':request['provider'],'id':request['modelId']};data=model
        persist_entry('model_change',provider=model['provider'],modelId=model['id'])
        if behavior.startswith('selected-') and model['provider']=='second':
            levels=['off'];change_thinking('off')
        else: change_thinking('low')
    elif command=='set_thinking_level':
        change_thinking('low' if behavior=='clamped' else request['level']);data=None
    elif command=='prompt':
        if behavior=='no-prompt-ack': continue
        reply(request)
        namespace={'rpc_effective':{'provider':model['provider'],'model':model['id'],'thinking':thinking},'rpc_saved_identity':{'id':session_id,'file':str(session_path),'cwd':os.getcwd(),'version':3}}
        try: exec(PRINT_FIXTURE,namespace)
        except SystemExit as result:
            if result.code: raise
        persist_entry('message',message={'role':'assistant','content':[{'type':'text','text':'Synthetic completed dispatch'}]})
        if behavior=='saved-partial-tail':
            with session_path.open('a') as stream: stream.write('{')
        if behavior not in ('no-settlement','saved-no-settlement'): print(json.dumps({'type':'agent_settled'}),flush=True)
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


def native_extension_load_results(cases):
    # Exercise the actual extension, without Pi, an owner or a model prompt.
    program = """import fs from 'node:fs';
const {loadTask} = await import(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
console.log(JSON.stringify(cases.map(item => { try { loadTask(item.task, item.cwd); return true; } catch { return false; } })));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", program, (SCRIPT.parent.parent / "extensions/coordination.js").as_uri()], input=json.dumps(cases), text=True, capture_output=True, timeout=10, check=True)
    return json.loads(result.stdout)


class ContractTests(unittest.TestCase):
    def test_selected_metadata_requires_paired_valid_flags_before_owner(self):
        for flags in (["--provider", "example"], ["--model", "model"], ["--provider", "bad provider", "--model", "model"]):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as directory, mock.patch.object(coordinate, "OpenShellOwner") as owner, contextlib.redirect_stderr(io.StringIO()):
                output = Path(directory) / "output"
                self.assertEqual(coordinate.main(["capabilities", "--output", str(output), *flags]), 1)
                owner.assert_not_called()
                self.assertFalse(output.exists())

    def test_relative_path_utf16_boundary_matches_native_loader_before_owner(self):
        ascii_prefix = ("a" * 200 + "/") * 5
        astral_prefix = ("\U0001f600" * 50 + "/") * 10
        paths = [(ascii_prefix + "b" * 19, True), (ascii_prefix + "b" * 20, False),
                 (astral_prefix + "b" * 14, True), (astral_prefix + "b" * 15, False),
                 ("bad\ud800.txt", False), ("bad\udfff.txt", False)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"; workspace.mkdir()
            output = root / "results"; output.mkdir()
            cases = []
            for version in (1, 2, 3):
                if version == 3:
                    dispatch = root / "remote" / ("a" * 32)
                    workspace = root / "remote/conversations" / ("a" * 32) / "workspace"
                    output = dispatch / "results"
                    workspace.mkdir(parents=True); output.mkdir(parents=True)
                for path, expected in paths:
                    public = {**task_template(), "version": min(version, 2), "writable_paths": [path]}
                    task_path = root / f"public-{len(cases)}.json"; dump(task_path, public)
                    if expected:
                        self.assertEqual(coordinate.validate_task(public), public)
                        (workspace / path).parent.mkdir(parents=True, exist_ok=True)
                    else:
                        with self.assertRaises(ValueError): coordinate.validate_task(public)
                        with mock.patch.object(coordinate, "OpenShellOwner") as owner, contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(coordinate.main(["run", str(task_path), "--profile", str(root / "absent-profile"), "--output", str(root / "absent-output")]), 1)
                            owner.assert_not_called()
                        self.assertFalse((root / "absent-output").exists())
                    native = {**public, "run_id": "run-one", "workspace": str(workspace), "output_directory": str(output), "allowed_tools": ["read", "write"], "max_tool_calls": 8}
                    if version in (2, 3):
                        native.update(operation="run", run_options={}, runtime_defaults={"model": "example/model", "thinking": "high"})
                    if version == 3:
                        native.update(version=3, run_id="a" * 32, session={"conversation_id": "a" * 32, "directory": str(workspace.parent), "file": str(workspace.parent / "session.jsonl"), "prior": None, "prior_sha256": None})
                    native_path = (dispatch if version == 3 else root) / f"native-{len(cases)}.json"; dump(native_path, native)
                    cases.append({"task": str(native_path), "cwd": str(workspace), "expected": expected})
            self.assertEqual(native_extension_load_results(cases), [case["expected"] for case in cases])
            self.assertEqual(list(output.iterdir()), [])

    def test_python_versioned_task_boundary_matches_actual_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"; workspace.mkdir()
            output = root / "results"; output.mkdir()
            cases = []
            for version, maximum in [(1, 80), (2, 128)]:
                variants = [(identifier, {}, valid) for identifier, valid in [("task-one", True), ("t" * maximum, True), ("project:T001", version == 2), ("t" * (maximum + 1), False), ("task-one\n", False), ("task-one\r\n", False)]]
                variants += [("task-one", {"run_options": options}, version == 2) for options in [{}, {"thinking": "low"}]]
                for identifier, fields, expected in variants:
                    public = {**task_template(), "version": version, "task_id": identifier, **fields}
                    if expected:
                        self.assertEqual(coordinate.validate_task(public), public)
                    else:
                        with self.assertRaises(ValueError): coordinate.validate_task(public)
                    task_path = root / f"task-{len(cases)}.json"
                    native = {**public, "run_id": "run-one", "workspace": str(workspace), "output_directory": str(output), "allowed_tools": ["read"], "max_tool_calls": 8}
                    if version == 2:
                        native.update(operation="run", run_options=public.get("run_options", {}), runtime_defaults={"model": "example/model", "thinking": "high"})
                    dump(task_path, native)
                    cases.append({"task": str(task_path), "cwd": str(workspace), "expected": expected})
                # The public assignment never chooses a run ID; native artifacts do.
                with self.assertRaises(ValueError):
                    coordinate.validate_task({**task_template(), "version": version, "run_id": "run-one"})
            self.assertEqual(native_extension_load_results(cases), [case["expected"] for case in cases])
            self.assertEqual(list(output.iterdir()), [])

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
            task_file = root / "task.json"; dump(task_file, task_template())
            for index, model in enumerate(["bad model", "example/bad model", "https://example.invalid/model", "unqualified", "a" * 257 + "/model", "example/" + "b" * 257, "a" * 10000, "example/model\n"]):
                with self.subTest(model=model[:40]):
                    dump(source, {**profile, "model": model})
                    destination = root / str(index) / "profile.json"
                    with self.assertRaises(ValueError): coordinate.configure_profile(source, destination)
                    self.assertFalse(destination.parent.exists())
                    with self.assertRaises(ValueError): coordinate.profile_settings(source, require_qualified_model=True)
                    self.assertEqual(coordinate.profile_settings(source)["model"], model)
                    output = root / f"run-{index}"
                    with mock.patch.object(coordinate, "OpenShellOwner") as owner, contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(coordinate.main(["run", str(task_file), "--profile", str(source), "--output", str(output)]), 1)
                        owner.assert_not_called()
                    self.assertFalse(output.exists())
            for model in ["one/two/three", "provider/model:revision", "a" * 256 + "/" + "b" * 256, "a/" + "b" * 254 + "/c/" + "d" * 254]:
                with self.subTest(valid_model=model[:40]):
                    dump(source, {**profile, "model": model})
                    self.assertEqual(coordinate.profile_settings(source, require_qualified_model=True), {**profile, "model": model})

    def test_python_qualified_defaults_match_actual_extension_loading(self):
        valid_pairs = [("p", "m"), ("p", "m" * 255), ("p" * 256, "m" * 256), ("a/" + "b" * 254, "c/" + "d" * 254)]
        invalid_models = ["bare", "p/", "/m", "_p/m", "p/_m", "https://example/model", "p/m\n", "p/m\r\n", "p/bad model", "p" * 257 + "/m", "p/" + "m" * 257, "p" * 256 + "/" + "m" * 257]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"; workspace.mkdir()
            output = root / "results"; output.mkdir()
            source = root / "profile.json"
            cases = []
            for index, (model, pair) in enumerate([(provider + "/" + model, (provider, model)) for provider, model in valid_pairs] + [(model, None) for model in invalid_models]):
                profile = {"sandbox_name": "fixture", "sandbox_id": "exact-id", "pi_argv": ["pi"], "model": model}
                dump(source, profile)
                destination = root / f"default-{index}" / "profile.json"
                if pair:
                    self.assertTrue(coordinate.configure_profile(source, destination)["changed"])
                    defaults = {"model": coordinate.profile_settings(destination, require_qualified_model=True)["model"], "thinking": "high"}
                    self.assertEqual(coordinate.desired_configuration({"run_options": {}, "runtime_defaults": defaults}, [{"provider": pair[0], "id": pair[1]}]), {"provider": pair[0], "model": pair[1], "thinking": "high"})
                else:
                    with self.assertRaises(ValueError): coordinate.configure_profile(source, destination)
                    self.assertFalse(destination.parent.exists())
                    defaults = {"model": model, "thinking": "high"}
                task_path = root / f"task-{index}.json"
                dump(task_path, {**task_template(), "version": 2, "run_id": "run-one", "operation": "run", "run_options": {}, "runtime_defaults": defaults, "workspace": str(workspace), "output_directory": str(output), "allowed_tools": ["read"], "max_tool_calls": 8})
                cases.append({"task": str(task_path), "cwd": str(workspace), "expected": pair is not None})
            self.assertEqual(native_extension_load_results(cases), [case["expected"] for case in cases])
            self.assertEqual(list(output.iterdir()), [])
            ambiguous = [{"provider": "one/two", "id": "three"}, {"provider": "one", "id": "two/three"}]
            selection = {"run_options": {}, "runtime_defaults": {"model": "one/two/three", "thinking": "high"}}
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                coordinate.desired_configuration(selection, ambiguous)
            selection["run_options"] = {"provider": "one/two", "model": "three"}
            self.assertEqual(coordinate.desired_configuration(selection, ambiguous), {"provider": "one/two", "model": "three", "thinking": "high"})

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

    def test_selected_metadata_queries_off_only_model_without_thinking_setter(self):
        for behavior in ('selected-off', 'selected-out-of-order'):
            root = self.prepare(name=behavior, behavior=behavior, metadata=True)
            task = coordinate.read_json(root / "task.json")
            task.update(version=3, operation="capabilities_selected", selected_model={"provider": "second", "model": "model-two"})
            task["runtime_defaults"]["thinking"] = "low"; dump(root / "task.json", task)
            before = coordinate.snapshot(root / "workspace")
            self.assertEqual(coordinate.worker(root), 0)
            receipt = coordinate.verify_return(root / "results", task, before, "run-one")
            configuration = receipt["configuration"]
            self.assertEqual(configuration["effective"], {"provider": "second", "model": "model-two", "thinking": "off"})
            self.assertEqual(configuration["supported_thinking_levels"], ["off"])
            self.assertFalse(configuration["profile_default_supported"])
            self.assertEqual(configuration["requested"], task["selected_model"])
            self.assertEqual([r["type"] for r in self.requests(root)], ["get_available_models", "get_state", "set_model", "get_available_thinking_levels", "get_state"])
            self.assertEqual(coordinate.snapshot(root / "workspace"), before)
            self.assertFalse((root / "results/extension-events.jsonl").exists())
            self.assertEqual((root / "results/pi-events.jsonl").read_bytes(), b"")

    def test_selected_metadata_refuses_catalog_readback_and_resealed_evidence(self):
        for behavior in ('selected-duplicate-model', 'selected-wrong-model', 'selected-wrong-level', 'refused', 'selected-absent-model'):
            root = self.prepare(name=behavior, behavior=behavior, metadata=True)
            task = coordinate.read_json(root / "task.json")
            task.update(version=3, operation="capabilities_selected", selected_model={"provider": "absent" if behavior == 'selected-absent-model' else "second", "model": "model-two"})
            dump(root / "task.json", task)
            self.assertEqual(coordinate.worker(root), 1)
            self.assertFalse(any(r['type'] in ('prompt', 'set_thinking_level') for r in self.requests(root)))
        root = self.prepare(name="resealed-selected", behavior="selected-off", metadata=True)
        task = coordinate.read_json(root / "task.json")
        task.update(version=3, operation="capabilities_selected", selected_model={"provider": "second", "model": "model-two"})
        dump(root / "task.json", task)
        self.assertEqual(coordinate.worker(root), 0)
        output = root / "results"
        configuration = coordinate.read_json(output / "rpc-configuration.json")
        configuration["profile_default_supported"] = True; dump(output / "rpc-configuration.json", configuration)
        receipt = coordinate.read_json(output / "worker-receipt.json")
        receipt["configuration"] = configuration
        receipt["artifact_sha256"] = {name: coordinate.digest(raw) for name, raw in coordinate.snapshot(output).items() if name != "worker-receipt.json"}
        dump(output / "worker-receipt.json", receipt)
        with self.assertRaises(ValueError): coordinate.verify_return(output, task, {"answer.txt": b"before\n"}, "run-one")

    def test_off_only_selected_run_requires_explicit_supported_thinking(self):
        for thinking in ('low', 'off'):
            root = self.prepare(name=thinking, behavior="selected-off", options={"provider": "second", "model": "model-two", "thinking": thinking})
            self.assertEqual(coordinate.worker(root), 0 if thinking == 'off' else 1)
            self.assertEqual(sum(r['type'] == 'prompt' for r in self.requests(root)), 1 if thinking == 'off' else 0)

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
                if mode == "persistent" and hasattr(test, "last_owner_state"):
                    self.state = copy.deepcopy(test.last_owner_state)
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
                    if mode == "persistent": self.state["main_process_instance_id"] += "-" + str(len(test.instances))
                    if mode == "start-error": raise subprocess.CalledProcessError(1, "synthetic start")
                elif args[0] == "upload":
                    shutil.copyfile(args[-2], args[-1])
                    if mode == "replaced-after-upload": self.state["main_process_instance_id"] = "replacement"
                elif args[0] == "exec":
                    if mode == "exec-error": raise subprocess.CalledProcessError(1, "synthetic exec")
                    return subprocess.run(list(args[args.index("--") + 1:]), check=True, capture_output=True, text=True, timeout=timeout)
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
                    if mode == "persistent": test.last_owner_state = copy.deepcopy(self.state)
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

    def test_legacy_bare_model_profile_reconciles_and_recovers_v1_without_execution(self):
        for index, model in enumerate(["llm.primary", "sonnet:high"]):
            with self.subTest(model=model):
                self.profile["model"] = model; dump(self.profile_path, self.profile)
                run_id = format(index + 1, "032x")
                remote = Path(self.profile["remote_parent"]) / run_id
                results = remote / "results"; results.mkdir(parents=True)
                source = {"kind": "empty-workspace", "files": {}, "modes": {}}
                check = {"name": "never-run", "argv": [sys.executable, "-c", "raise AssertionError('Recovery cannot execute checks')"], "timeout_seconds": 2}
                native = {"version": 1, "run_id": run_id, "task_id": "legacy-task", "kind": "validation", "instructions": "Retained legacy task", "workspace": str(remote / "workspace"), "output_directory": str(results), "writable_paths": [], "allowed_tools": sorted(coordinate.TOOLS - {"write", "edit"}), "max_tool_calls": 10, "max_turns": 10, "source": source, "checks": [check]}
                launch = {"model": model, "thinking": "high", "checks": [check]}
                payload = {"task.json": json.dumps(native).encode(), "launch.json": json.dumps(launch).encode(), "coordinate.py": b"# retained v1 worker", "extension.js": b"// retained v1 extension", "package.json": b'{"type":"module"}'}
                archive = make_archive([(name, raw, tarfile.REGTYPE) for name, raw in payload.items()])
                failed = self.root / f"legacy-{index}"; failed.mkdir()
                (failed / "inputs.tar").write_bytes(archive)
                stopped = {"id": "sandbox-id", "name": "disposable", "phase": "Stopped", "main_process_instance_id": "legacy-main", "restart_count": 0}
                original = {"version": 1, "run_id": run_id, "task_id": "legacy-task", "kind": "validation", "started_at": "2000-01-01T00:00:00Z", "source": source, "input_sha256": coordinate.digest(archive), "remote_artifacts": str(results), "delivery_valid": False, "cleanup_complete": False, "sandbox_running": {**stopped, "phase": "Ready"}, "sandbox_after": stopped}
                dump(failed / "started.json", original); dump(failed / "receipt.json", original)
                dump(results / "worker-receipt.json", {"version": 1, "run_id": run_id, "task_id": "legacy-task", "outcome": "incomplete", "pi_exit_code": 7})
                locks = self.root / "locks"; locks.mkdir(exist_ok=True)
                journal = locks / (coordinate.digest(b"sandbox-id") + ".json"); dump(journal, original)
                preserved = {path: path.read_bytes() for path in [self.profile_path, failed / "started.json", failed / "receipt.json", failed / "inputs.tar"]}
                reconcile = ["reconcile", "--profile", str(self.profile_path), "--lock-root", str(locks)]
                before = journal.read_bytes()
                with mock.patch.object(coordinate, "OpenShellOwner", self.recovery_factory("initial-wrong-main")), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(coordinate.main(reconcile), 1)
                self.assertEqual(journal.read_bytes(), before)
                with mock.patch.object(coordinate, "OpenShellOwner", self.recovery_factory()), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(coordinate.main(reconcile), 0)
                self.assertEqual(self.instances[-1].calls, [])
                output = self.root / f"recovered-legacy-{index}"
                with mock.patch.object(coordinate, "OpenShellOwner", self.recovery_factory()), mock.patch.object(coordinate, "execute_to_log", side_effect=AssertionError("Recovery cannot run Pi or checks")), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(coordinate.main(["recover", str(failed), "--profile", str(self.profile_path), "--output", str(output), "--lock-root", str(locks)]), 0)
                recovered = coordinate.read_json(output / "receipt.json")
                self.assertTrue(recovered["recovery_valid"])
                self.assertFalse(recovered["delivery_valid"]); self.assertFalse(recovered["task_delivery_valid"])
                self.assertEqual(recovered["outcome"], "recovered_partial")
                self.assertEqual(recovered["evidence"]["checks"], [{"name": "never-run", "state": "unknown", "exit_code": None}])
                self.assertEqual(self.instances[-1].calls, ["start", "download", "stop"])
                self.assertEqual(preserved, {path: path.read_bytes() for path in preserved})

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
        with self.assertRaisesRegex(ValueError, 'unsuccessful'):
            coordinate.recover_task(self.root / 'out', self.profile_path, self.root / 'inspected', self.root / 'locks', reconcile_conversation=True)
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


class SavedConversationTests(unittest.TestCase):
    factory = OwnerTests.factory

    def setUp(self):
        OwnerTests.setUp(self)
        self.profile["pi_argv"][-1] = "saved-edit"
        dump(self.profile_path, self.profile)
        self.repository = self.root / "repository"; self.repository.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repository, check=True, timeout=10)
        (self.repository / "answer.txt").write_text("before\n")
        self.commit()
        self.owner_patch = mock.patch.object(coordinate, "OpenShellOwner", self.factory("persistent"))
        self.owner_patch.start(); self.addCleanup(self.owner_patch.stop)
        self.stdout = contextlib.redirect_stdout(io.StringIO()); self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def commit(self):
        subprocess.run(["git", "add", "--all"], cwd=self.repository, check=True, timeout=10)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Fixture revision"], cwd=self.repository, check=True, timeout=10)
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repository, text=True, timeout=10).strip()

    def assignment(self, text, *, checks=None):
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repository, text=True, timeout=10).strip()
        task = {**task_template(), "version": 2, "task_id": "project:T001", "instructions": text, "writable_paths": ["answer.txt"], "repository": str(self.repository), "revision": revision, "run_options": {"thinking": "low"}, "checks": checks or [{"name": "verify", "argv": [sys.executable, "-c", "from pathlib import Path; assert Path('answer.txt').read_text()==" + repr(text + '\n') + "; Path('check-created.txt').write_text('retained')"], "timeout_seconds": 5}]}
        dump(self.task_path, task)
        return task

    def test_saved_run_then_new_source_continue_keeps_official_id_and_history(self):
        first_task = self.assignment("first edit")
        first = coordinate.run_task(self.task_path, self.profile_path, self.root / "first", self.root / "locks", save_session=True)
        self.assertTrue(first["delivery_valid"], first)
        checkpoint = coordinate.read_json(self.root / "first/results/conversation.json")
        session_path = Path(checkpoint["session"]["file"])
        before_session = session_path.read_bytes()
        before_artifacts = coordinate.snapshot(self.root / "first")
        self.assertIn("check-created.txt", checkpoint["workspace"]["files"])
        metadata = coordinate.run_task(None, self.profile_path, self.root / "metadata", self.root / "locks", capabilities_only=True, selected_model={"provider": "second", "model": "model-two"})
        self.assertTrue(metadata["capabilities_valid"], metadata)
        self.assertEqual(session_path.read_bytes(), before_session)
        (self.repository / "answer.txt").write_bytes((self.root / "first/results/changed-files/answer.txt").read_bytes())
        self.commit(); second_task = self.assignment("second edit")
        self.assertNotEqual(first_task["revision"], second_task["revision"])
        second = coordinate.run_task(self.task_path, self.profile_path, self.root / "second", self.root / "locks", previous_directory=self.root / "first")
        self.assertTrue(second["delivery_valid"], second)
        second_checkpoint = coordinate.read_json(self.root / "second/results/conversation.json")
        self.assertEqual(second_checkpoint["session"]["id"], checkpoint["session"]["id"])
        self.assertEqual(second_checkpoint["session"]["file"], str(session_path))
        self.assertTrue(session_path.read_bytes().startswith(before_session))
        self.assertGreater(len(session_path.read_bytes()), len(before_session))
        self.assertEqual((self.root / "second/results/changed-files/answer.txt").read_bytes(), b"second edit\n")
        self.assertEqual(coordinate.snapshot(self.root / "first"), before_artifacts)
        self.assertTrue(all(instance.calls.count("start") == instance.calls.count("stop") == 1 for instance in self.instances))
        self.assertEqual(second["acceptance"], "not_granted")
        stale = coordinate.run_task(self.task_path, self.profile_path, self.root / "stale", self.root / "locks", previous_directory=self.root / "first")
        self.assertFalse(stale["delivery_valid"])
        stale_remote = Path(stale["remote_artifacts"]).parent
        self.assertFalse((stale_remote / "invocations.txt").exists())
        self.assertIn("Stale or duplicate", coordinate.read_json(stale_remote / "results/worker-receipt.json")["error"])
        self.assertEqual(coordinate.snapshot(self.root / "first"), before_artifacts)
        # The successful checkpoint can be inspected after a newer refused
        # dispatch changed the owner journal, without reexecuting either task.
        second_artifacts = coordinate.snapshot(self.root / "second")
        terminal_session = session_path.read_bytes()
        terminal_workspace = coordinate.workspace_manifest(Path(second_checkpoint["session"]["cwd"]))
        count = len(self.instances)
        with self.assertRaisesRegex(ValueError, "unsuccessful delivery"):
            coordinate.recover_task(self.root / "second", self.profile_path, self.root / "invalid-recovery", self.root / "locks")
        self.assertEqual(len(self.instances), count)
        self.assertEqual(coordinate.main(["reconcile", "--from", str(self.root / "second"), "--output", str(self.root / "inspected"), "--profile", str(self.profile_path), "--lock-root", str(self.root / "locks")]), 0)
        inspection_receipt = coordinate.read_json(self.root / "inspected/receipt.json")
        inspection = coordinate.read_json(self.root / "inspected/conversation-inspection.json")
        self.assertTrue(inspection_receipt["recovery_valid"], inspection_receipt)
        self.assertTrue(inspection_receipt["conversation_valid"], inspection_receipt)
        self.assertFalse(inspection_receipt["delivery_valid"])
        self.assertEqual(inspection["disposition"], "terminal_checkpoint")
        self.assertEqual(inspection["checkpoint"], second_checkpoint)
        self.assertEqual(session_path.read_bytes(), terminal_session)
        self.assertEqual(coordinate.workspace_manifest(Path(second_checkpoint["session"]["cwd"])), terminal_workspace)
        self.assertEqual(coordinate.snapshot(self.root / "second"), second_artifacts)
        self.assertEqual(len(self.instances), count + 1)
        self.assertEqual(self.instances[-1].calls, ["start", "download", "exec", "stop"])
        self.assertEqual((Path(second["remote_artifacts"]).parent / "invocations.txt").read_text(), "1")
        self.assertFalse((stale_remote / "invocations.txt").exists())

    def first_saved(self, *, checks=None):
        self.assignment("first edit", checks=checks)
        first = coordinate.run_task(self.task_path, self.profile_path, self.root / "first", self.root / "locks", save_session=True)
        remote = Path(first["remote_artifacts"]).parent
        return first, remote, coordinate.read_json(remote / "task.json")

    def test_failed_checks_recover_advanced_conversation_without_replay(self):
        failed, remote, native = self.first_saved(checks=[{"name": "failing", "argv": [sys.executable, "-c", "raise SystemExit(7)"], "timeout_seconds": 5}])
        self.assertFalse(failed["delivery_valid"])
        self.assertTrue(failed["cleanup_complete"])
        prior_bytes = coordinate.snapshot(self.root / "first")
        with self.assertRaisesRegex(ValueError, "Recover the failed"):
            coordinate.run_task(self.task_path, self.profile_path, self.root / "forbidden", self.root / "locks", previous_directory=self.root / "first")
        coordinate.run_task(None, self.profile_path, self.root / "metadata", self.root / "locks", capabilities_only=True)
        recovered = coordinate.recover_task(self.root / "first", self.profile_path, self.root / "recovered", self.root / "locks")
        self.assertTrue(recovered["recovery_valid"], recovered)
        self.assertTrue(recovered["conversation_valid"], recovered)
        self.assertFalse(recovered["task_delivery_valid"])
        self.assertEqual(recovered["evidence"]["checks"][0]["exit_code"], 7)
        self.assertEqual((remote / "invocations.txt").read_text(), "1")
        self.assertEqual(coordinate.snapshot(self.root / "first"), prior_bytes)
        (self.repository / "answer.txt").write_text("first edit\n"); self.commit()
        self.assignment("second edit")
        second = coordinate.run_task(self.task_path, self.profile_path, self.root / "second", self.root / "locks", previous_directory=self.root / "recovered")
        self.assertTrue(second["delivery_valid"], second)
        self.assertEqual(second["worker"]["conversation"]["session_after"]["id"], recovered["continuation_checkpoint"]["session"]["id"])

    def test_session_and_full_workspace_drift_refuse_without_prompt(self):
        first, remote, native = self.first_saved()
        self.assertTrue(first["delivery_valid"], first)
        session = Path(native["session"]["file"]); original = session.read_bytes()
        header = json.loads(original.splitlines()[0])
        variants = [b"", original[:-1], b"{invalid}\n", json.dumps(header).encode() + b"\n", json.dumps({**header, "version": 2}).encode() + b"\n", json.dumps({**header, "cwd": "/foreign"}).encode() + b"\n", original + b'{"type":"message","id":"orphan","parentId":"missing"}\n']
        for index, raw in enumerate(variants):
            with self.subTest(index=index):
                session.write_bytes(raw)
                refused = coordinate.run_task(self.task_path, self.profile_path, self.root / f"bad-{index}", self.root / "locks", previous_directory=self.root / "first")
                self.assertFalse(refused["delivery_valid"])
                self.assertTrue(refused["cleanup_complete"])
                self.assertFalse((Path(refused["remote_artifacts"]).parent / "invocations.txt").exists())
        session.write_bytes(original)
        session.unlink()
        refused = coordinate.run_task(self.task_path, self.profile_path, self.root / "missing", self.root / "locks", previous_directory=self.root / "first")
        self.assertFalse(refused["delivery_valid"])
        self.assertFalse(session.exists())
        self.assertFalse((Path(refused["remote_artifacts"]).parent / "invocations.txt").exists())
        session.write_bytes(original)
        session.unlink(); session.symlink_to(remote / "task.json")
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            coordinate.run_task(self.task_path, self.profile_path, self.root / "linked", self.root / "locks", previous_directory=self.root / "first")
        session.unlink(); session.write_bytes(original)
        created = Path(native["workspace"]) / "check-created.txt"
        original_mode = created.stat().st_mode & 0o777
        for index, change in enumerate((lambda: created.write_text("changed"), lambda: created.chmod(original_mode ^ 0o100))):
            change()
            refused = coordinate.run_task(self.task_path, self.profile_path, self.root / f"workspace-{index}", self.root / "locks", previous_directory=self.root / "first")
            self.assertFalse(refused["delivery_valid"])
            self.assertFalse((Path(refused["remote_artifacts"]).parent / "invocations.txt").exists())
            created.write_text("retained"); created.chmod(original_mode)

    def test_interrupted_workspace_transitions_are_inspected_without_rollback(self):
        first, first_remote, native = self.first_saved()
        self.assertTrue(first["delivery_valid"], first)
        prior = coordinate.read_json(first_remote / "results/conversation.json")
        original_tree = coordinate.workspace_manifest(Path(native["workspace"]))
        # Separate isolated copies exercise each rename boundary without replaying Pi.
        for boundary in (0, 1, 2):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory) / "remote"; parent.mkdir()
                run_id = "b" * 32; conversation_id = native["session"]["conversation_id"]
                dispatch = parent / run_id; (dispatch / "workspace").mkdir(parents=True)
                (dispatch / "workspace/answer.txt").write_text("new source\n")
                conversation = parent / "conversations" / conversation_id
                shutil.copytree(Path(native["session"]["directory"]), conversation)
                workspace = conversation / "workspace"
                history = (conversation / "session.jsonl").read_bytes().splitlines()
                header = json.loads(history[0]); header["cwd"] = str(workspace)
                (conversation / "session.jsonl").write_bytes(json.dumps(header).encode() + b"\n" + b"\n".join(history[1:]) + b"\n")
                checkpoint = copy.deepcopy(prior); checkpoint["session"] = coordinate.saved_session_snapshot(conversation / "session.jsonl", workspace)
                (conversation / "checkpoint.json").write_bytes(coordinate.private_control_bytes(checkpoint))
                task = {**native, "run_id": run_id, "operation": "continue", "workspace": str(workspace), "output_directory": str(dispatch / "results"), "session": {"conversation_id": conversation_id, "directory": str(conversation), "file": str(conversation / "session.jsonl"), "prior": checkpoint, "prior_sha256": coordinate.digest(coordinate.private_control_bytes(checkpoint))}}
                manifest = coordinate.workspace_manifest(dispatch / "workspace")
                task["source"] = {**native["source"], "files": {k: v["sha256"] for k, v in manifest["files"].items()}, "modes": {k: v["mode"] for k, v in manifest["files"].items()}}
                (dispatch / "task.json").write_bytes(json.dumps(task).encode())
                real_rename = Path.rename; renamed = []
                def interrupt_rename(path, target):
                    if len(renamed) == boundary: raise OSError("Synthetic rename interruption")
                    result = real_rename(path, target); renamed.append(str(path)); return result
                with mock.patch.object(Path, "rename", interrupt_rename):
                    if boundary < 2:
                        with self.assertRaises(OSError): coordinate.prepare_saved_workspace(dispatch, task)
                    else:
                        coordinate.prepare_saved_workspace(dispatch, task)
                self.assertTrue((conversation / "pending.json").is_file())
                if boundary == 0:
                    observed = coordinate.inspect_saved_conversation(dispatch, task)
                    self.assertFalse(observed["continuable"])
                    reconciled = coordinate.inspect_saved_conversation(dispatch, task, reconcile=True)
                    self.assertTrue(reconciled["continuable"])
                    self.assertEqual(coordinate.workspace_manifest(workspace), original_tree)
                    self.assertTrue((dispatch / "transition-reconciled.json").is_file())
                elif boundary == 1:
                    with self.assertRaises((ValueError, FileNotFoundError)): coordinate.inspect_saved_conversation(dispatch, task, reconcile=True)
                    self.assertFalse(workspace.exists())
                else:
                    observed = coordinate.inspect_saved_conversation(dispatch, task, reconcile=True)
                    self.assertFalse(observed["continuable"])
                    self.assertEqual(observed["disposition"], "new_workspace_dispatch_unresolved")
                    self.assertEqual((workspace / "answer.txt").read_text(), "new source\n")
                    self.assertTrue((conversation / "pending.json").is_file())

    def test_saved_controls_and_storage_limits_never_truncate(self):
        first, remote, native = self.first_saved()
        self.assertTrue(first["delivery_valid"], first)
        session = Path(native["session"]["file"]); raw = session.read_bytes()
        with mock.patch.object(coordinate, "MAX_SESSION_BYTES", len(raw) - 1), self.assertRaisesRegex(ValueError, "bounded regular"):
            coordinate.saved_session_snapshot(session, Path(native["workspace"]))
        with mock.patch.object(coordinate, "MAX_RETAINED_BYTES", 1), self.assertRaisesRegex(ValueError, "1 GiB"):
            coordinate.retained_storage_guard(remote.parent)
        self.assertEqual(session.read_bytes(), raw)
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            coordinate.private_control_bytes({"too_large": "x" * (1024 * 1024)})
        with self.assertRaisesRegex(ValueError, "Unknown native"):
            coordinate.validate_native_task({**native, "version": 4})

    def test_reconcile_command_certifies_unchanged_old_checkpoint_without_replay(self):
        first, first_remote, native = self.first_saved()
        self.assertTrue(first["delivery_valid"], first)
        stable = Path(native["workspace"])
        session_before = Path(native["session"]["file"]).read_bytes()
        self.assignment("second edit")
        execute = coordinate.execute_to_log
        def interrupted_worker(argv, cwd, log, timeout, **options):
            if "worker" not in argv:
                return execute(argv, cwd, log, timeout, **options)
            Path(log).write_bytes(b"Synthetic pre-rename interruption\n")
            rename = Path.rename
            def refuse_first_rename(path, destination):
                if path == stable: raise OSError("Synthetic before-first-rename interruption")
                return rename(path, destination)
            with mock.patch.object(Path, "rename", refuse_first_rename):
                return coordinate.worker(Path(argv[-1]))
        with mock.patch.object(coordinate, "execute_to_log", interrupted_worker):
            failed = coordinate.run_task(self.task_path, self.profile_path, self.root / "failed", self.root / "locks", previous_directory=self.root / "first")
        self.assertFalse(failed["delivery_valid"])
        failed_remote = Path(failed["remote_artifacts"]).parent
        self.assertFalse((failed_remote / "invocations.txt").exists())
        original_artifacts = coordinate.snapshot(self.root / "failed")
        self.assertEqual(coordinate.main(["reconcile", "--from", str(self.root / "failed"), "--output", str(self.root / "reconciled"), "--profile", str(self.profile_path), "--lock-root", str(self.root / "locks")]), 0)
        recovery = coordinate.read_json(self.root / "reconciled/receipt.json")
        self.assertTrue(recovery["recovery_valid"], recovery)
        self.assertTrue(recovery["conversation_valid"], recovery)
        self.assertFalse(recovery["delivery_valid"])
        self.assertEqual(Path(native["session"]["file"]).read_bytes(), session_before)
        self.assertEqual(coordinate.snapshot(self.root / "failed"), original_artifacts)
        self.assertFalse((failed_remote / "invocations.txt").exists())
        second = coordinate.run_task(self.task_path, self.profile_path, self.root / "second", self.root / "locks", previous_directory=self.root / "reconciled")
        self.assertTrue(second["delivery_valid"], second)

    def test_unacknowledged_unsettled_and_partial_saved_runs_cannot_continue(self):
        for behavior in ("no-prompt-ack", "saved-no-settlement", "saved-partial-tail", "saved-wrong-id"):
            with self.subTest(behavior=behavior):
                self.profile["pi_argv"][-1] = behavior; dump(self.profile_path, self.profile)
                task = self.assignment("attempted edit"); task["wall_seconds"] = 1; dump(self.task_path, task)
                output = self.root / behavior
                failed = coordinate.run_task(self.task_path, self.profile_path, output, self.root / "locks", save_session=True)
                self.assertFalse(failed["delivery_valid"])
                self.assertTrue(failed["cleanup_complete"])
                remote = Path(failed["remote_artifacts"]).parent
                self.assertFalse((remote / "results/verify.started.json").exists())
                calls = (remote / "invocations.txt").read_bytes() if (remote / "invocations.txt").exists() else b""
                recovery = coordinate.recover_task(output, self.profile_path, self.root / (behavior + "-recovery"), self.root / "locks")
                self.assertFalse(recovery["conversation_valid"])
                self.assertFalse(recovery["recovery_valid"])
                self.assertEqual((remote / "invocations.txt").read_bytes() if (remote / "invocations.txt").exists() else b"", calls)
                with self.assertRaises(ValueError):
                    coordinate.run_task(self.task_path, self.profile_path, self.root / (behavior + "-continue"), self.root / "locks", previous_directory=self.root / (behavior + "-recovery"))

    def test_unknown_saved_stop_refuses_continue_before_new_owner(self):
        self.assignment("first edit")
        with mock.patch.object(coordinate, "OpenShellOwner", self.factory("stop-error")):
            first = coordinate.run_task(self.task_path, self.profile_path, self.root / "first", self.root / "locks", save_session=True)
        self.assertFalse(first["cleanup_complete"])
        self.assertTrue(first["artifacts_verified"])
        self.assertFalse(first["delivery_valid"])
        count = len(self.instances)
        with self.assertRaisesRegex(ValueError, "stopped saved-session"):
            coordinate.run_task(self.task_path, self.profile_path, self.root / "second", self.root / "locks", previous_directory=self.root / "first")
        self.assertEqual(len(self.instances), count)

    def test_checkpoint_failure_keeps_worker_nonzero_and_delivery_incomplete(self):
        self.assignment("first edit")
        execute = coordinate.execute_to_log
        def failed_checkpoint(argv, cwd, log, timeout, **options):
            if "worker" not in argv:
                return execute(argv, cwd, log, timeout, **options)
            Path(log).write_bytes(b"Synthetic checkpoint-write refusal\n")
            with mock.patch.object(coordinate, "complete_saved_conversation", side_effect=OSError("Synthetic checkpoint-write refusal")):
                return coordinate.worker(Path(argv[-1]))
        with mock.patch.object(coordinate, "execute_to_log", failed_checkpoint):
            first = coordinate.run_task(self.task_path, self.profile_path, self.root / "first", self.root / "locks", save_session=True)
        self.assertFalse(first["delivery_valid"])
        self.assertTrue(first["cleanup_complete"])
        self.assertEqual(first["exec_exit_code"], 1)
        remote = Path(first["remote_artifacts"]).parent
        worker_receipt = coordinate.read_json(remote / "results/worker-receipt.json")
        self.assertEqual(worker_receipt["outcome"], "incomplete")
        self.assertTrue(worker_receipt["checks_passed"])
        self.assertFalse((remote / "results/conversation.json").exists())


if __name__ == "__main__":
    unittest.main()
