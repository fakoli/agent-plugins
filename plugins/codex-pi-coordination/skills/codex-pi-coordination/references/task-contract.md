# Task and runtime contracts

Host: Python 3.10+ on POSIX and the installed OpenShell CLI. Sandbox: Python
3.10+, Pi with the supported extension API, Node 22+ for a JavaScript Pi launch,
and task dependencies. The runner installs nothing and has no third-party Python
dependencies; the extension has no npm dependencies.

## Task

```json
{
  "version": 1,
  "task_id": "repair-parser",
  "kind": "implementation",
  "instructions": "Fix empty-input handling. Change only parser.py and return an honest handoff. Verification runs after your return.",
  "repository": "/workspace/project",
  "revision": "COMMITTED_REVISION",
  "writable_paths": ["parser.py"],
  "checks": [{"name": "parser-check", "argv": ["python3", "check_parser.py"], "timeout_seconds": 30}],
  "max_tool_calls": 40,
  "max_turns": 32,
  "wall_seconds": 600
}
```

Required: version, task_id, kind, instructions, writable_paths and checks.
Repository/revision are optional together. Kinds: implementation, research,
review, validation. Writable paths are exact relative files, not globs or
directories. Research may return `findings.md`; read-only review/validation may
use no writable files and report findings through the handoff tool. Commands
are coordinator-authored argv, executed once after Pi exits; they share the
overall deadline and retain actual logs and exit status.

Bounds: source/returned workspace 64 MiB and 10,000 regular files, 128 writable
paths, 32 checks, 4 MiB per log, 1 MiB task manifest, at most 500 tool calls,
200 turns and 1,800 seconds of worker time. Source links/submodules and
nonregular files are refused. Source executable flags are retained. These
bounds establish no throughput or fleet qualification.

## Private profile

```json
{
  "sandbox_name": "owned-disposable-worker",
  "sandbox_id": "EXACT_RETAINED_SANDBOX_ID",
  "pi_argv": ["node", "--use-env-proxy", "/opt/pi/dist/bundle/cli.js"],
  "model": "configured-provider/selected-model",
  "thinking": "high",
  "python": "python3",
  "remote_parent": "/sandbox/codex-pi",
  "environment": {"PI_CODING_AGENT_DIR": "/sandbox/pi-config"},
  "protected_sandboxes": ["durable-agent"]
}
```

Keep profiles outside public repositories. They reference configured provider
storage, never credential values. Optional `openshell_argv` selects the CLI and
owner-configured gateway/workspace arguments; default `["openshell"]`.
Environment keys are restricted to runtime paths and the bytecode setting.
Extension events record the model identity exposed by Pi. An alias's actual
backend requires the provider owner's diagnostics; physical weights are not
attested by this plugin.

All cooperating callers must share the local per-sandbox lock root. A persistent
custody journal blocks reuse after uncertain outcomes. Name-based OpenShell
actions still require one external owner; a local lock is not a remote
compare-and-swap guarantee against unrelated operators. Lifecycle actions check
the retained sandbox ID and, once known, main-process instance. Only a stopped
disposable sandbox is started; cleanup stops that owned resource.

`python3 ../../scripts/coordinate.py reconcile` records an already-Stopped exact
identity. It does not stop or adopt running resources. Failed or nonzero
OpenShell execution, timeout and cancellation immediately enter managed stop;
the runner skips artifact download. `receipt.json` retains `remote_artifacts`
for the supported `recover` command after stopped custody is confirmed.
Do not collect remote artifacts while failed work may still be active. The
runtime owner handles retention. Remote runs remain for diagnosis;
preparation refuses when retained run data reaches 1 GiB.

## Return and trust

`started.json` binds the run and input archive. `receipt.json` records worker
outcome, cleanup and protected-resource readback. `results/worker-receipt.json`
records actual Pi exit, event completion, changes and checks. Every check has
exclusive started/result records and a log SHA256; interruption never fabricates
a successful terminal receipt.

`model-report.json` is Pi's task-bound self-report. `extension-events.jsonl`
records task loading, budget/tool observations and lifecycle events. These are
not independent issuer attestations. Checks run trusted coordinator-selected
code in the same OS sandbox; this does not prove arbitrary hostile test code
cannot tamper with same-user files. Stronger claims need independent validation.

`changed-files` retains changed bytes; `changes.json` includes hashes/deletions;
`changes.patch` is a convenience text diff. Binary and empty-file changes require
the manifest/bytes. Do not automatically apply patches to a newer checkout.
Verification may create outputs but must not alter returned source/artifacts.

For lower-level Pi loading, use `--extension <plugin>/extensions/coordination.js
--coordination-task <task.json>`. That manifest additionally includes run_id,
absolute workspace/output_directory, allowed_tools, source metadata and
max_tool_calls. Output/control files stay outside the workspace. Standalone
extension loading supplies neither OS isolation nor managed cleanup.

Pi's CLI `--tools` allowlist must include `coordination_status` and
`coordination_handoff` alongside the task's native tools. The extension checks
activation, records missing-tool refusal and blocks further tools. Pi 0.87.1
print/JSON mode does not wire a shutdown callback for `ctx.shutdown()`, so this
refusal does not guarantee zero model requests. The runner's wall deadline and
managed OpenShell stop remain the process boundary.

## Failed-run recovery

`python3 ../../scripts/coordinate.py recover FAILED_RUN --output NEW_DIRECTORY`
uses the normal `--profile` and `--lock-root` options. Keep the failed directory's
`started.json`, `receipt.json` and `inputs.tar` unchanged. Recovery validates their
hashes, safe archive members, task/source bindings and derived remote results
path before any lifecycle action. The latest owner journal must bind that failed
run and input with completed Stopped custody; a newer assignment, active owner,
identity drift or competing lock refuses. A worker that returned work but failed
cleanup may be recovered after reconciliation; an already-valid delivery may not.

The owner must qualify the existing sandbox entrypoint as idle on restart. The
runner starts a fresh Ready main instance and performs only a native download,
then verifies its identity, stops it and reads back protected resources. It does
not upload, exec, rerun Pi or rerun checks. For both normal runs and recovery, if a start fails before the fresh
instance is bound, an unexpected main is not stopped; custody remains unresolved.
Unknown cleanup blocks another run until supported Stopped reconciliation. A
retry retains the original failed-run identity even after recovery reconciliation.
Original inputs/receipts and the previous journal are retained separately.

The recovery receipt always declares `task_delivery_valid: false`,
`delivery_valid: false` and `acceptance: not_granted`. `recovery_valid: true` and
CLI exit zero denote completed retrieval, available-record validation, stopped
cleanup and unchanged protected resources only. `recovered_complete` means all
declared check terminal records and worker bindings are present; nonzero exits
remain failures. `recovered_partial` reports absent terminal fields as unknown.
A present manifest, task/check/model/source/patch binding that disagrees with its
bytes fails recovery. Raw interrupted logs lacking terminal bindings are retained
as partial diagnostic evidence, never passed through the successful-return gate.

Returned artifacts have the same regular-file, 64 MiB, 10,000-file and log bounds.
These checks occur after native download. The download timeout is not a hard
pre-download byte or storage quota, and same-user hashes are not an independent
issuer attestation. This is recovery from an exclusively owned trusted runtime,
not arbitrary historical sandbox browsing or hostile-output containment.
