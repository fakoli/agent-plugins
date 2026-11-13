# Task and runtime contracts

Host: Python 3.10+ on POSIX and the installed OpenShell CLI. Sandbox: Python
3.10+, Pi with the supported extension and native RPC APIs, Node 22+ for a
JavaScript Pi launch, and task dependencies. Missing required RPC capabilities
fail explicitly. The runner installs nothing and has no third-party Python
dependencies; the extension has no npm dependencies. Examples below are synthetic.

## Task

```json
{
  "version": 2,
  "task_id": "parser:T001",
  "kind": "implementation",
  "instructions": "Fix empty-input handling. Change only parser.py and return an honest handoff. Verification runs after your return.",
  "repository": "/workspace/project",
  "revision": "COMMITTED_REVISION",
  "writable_paths": ["parser.py"],
  "checks": [{"name": "parser-check", "argv": ["python3", "check_parser.py"], "timeout_seconds": 30}],
  "max_tool_calls": 40,
  "max_turns": 32,
  "wall_seconds": 600,
  "run_options": {"thinking": "low"}
}
```

Required: version, task_id, kind, instructions, writable_paths and checks.
Repository/revision are optional together. Kinds: implementation, research,
review, validation. Writable paths are exact relative files, not globs or
directories. Each relative path is limited to 1,024 UTF-16 code units in both
Python and the extension. Malformed Unicode, Unicode spaces that would be
normalized, traversal and noncanonical spellings refuse before owner work;
paths are never silently rewritten. Research may return `findings.md`; read-only review/validation may
use no writable files and report findings through the handoff tool. Commands
are coordinator-authored argv, executed once after Pi exits; they share the
overall deadline and retain actual logs and exit status.

Version 2 adds only optional `run_options` to the user task fields. It accepts
`provider`, `model` and `thinking`; provider/model must appear together and
thinking is independent. For example:

```json
{"provider": "configured-provider", "model": "exact-model-id", "thinking": "low"}
```

Omitted fields inherit the private profile. Reject unknown fields, empty strings,
`auto`, `dynamic` and the literal `default`; a UI Default choice must omit the
field. IDs are bounded identifiers, never argv, endpoints or environment input.
Resolve the profile's qualified model selector against exact available
provider/model identities. Zero or ambiguous matches refuse; no fuzzy matching,
fallback or provider provisioning occurs. Named `max` is permitted only when the
selected runtime/model advertises it.

Version-2 task IDs match `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`. Version-1 user
inputs keep their original fields and 80-character ID pattern
`[A-Za-z0-9][A-Za-z0-9_.-]{0,79}`; they cannot contain `run_options`. New runs
normalize either input version into native version 2 for ephemeral work.
Saved Run/Continue and selected-model metadata use explicit native version-3
variants; users still submit public version-1/2 tasks. Historical version-1/2
return/recovery artifacts keep their original interpretation.

Public assignments never supply `run_id`. Native artifacts carry a separate
coordinator-generated run identity; the extension preserves its historical
128-character pattern `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`; saved descriptors further
require the generated 32-character hexadecimal dispatch identity.
The version-1 task-ID limit does not apply to that native field. Both ID fields
must match their entire pattern, without trailing newlines.

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
An omitted profile `thinking` retains the legacy `high` default; runtime support
must still be checked before prompting. An alias's actual backend requires the
provider owner's diagnostics; physical weights are not attested by this plugin.

From the skill directory, register an existing private profile once:

```sh
python3 ../../scripts/coordinate.py configure --profile /path/to/private/profile.json
```

This validates and registers `~/.config/codex-pi-coordination/profile.json` using
exclusive private creation. Semantically identical JSON is a no-op; symlinks and
conflicting defaults refuse. There is no force/overwrite mode. Registration
copies no credentials, edits no provider storage and proves no runtime behavior.
Normal commands use this default; `--profile` selects another existing profile.

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
preparation enforces a 1 GiB retained-material bound; saved workers also observe
it during Pi and trusted-check execution and before sealing a checkpoint.
Saved session files are limited to 16 MiB and checkpoint/control JSON to 1 MiB.
Overflow refuses delivery/continuation without truncating or pruning prior data.
The remote bound includes retained source, dispatch and conversation material;
it is an observed limit, not a hard filesystem quota or hostile-process guarantee.

## Native RPC execution and capabilities

An ordinary `run TASK --output NEW_DIRECTORY` starts an ephemeral `--no-session`
native RPC child in the owned OpenShell worker, with only the explicit
coordination extension and scoped tools. Saved Run and Continue use the official
session path described below; neither attaches to an interactive process.

Before the single task prompt, the runner queries available models, selects an
exact provider/model, queries `get_available_thinking_levels`, validates and
sets the requested/inherited thinking level, then reads `get_state`. Effective
provider, model and thinking must match exactly; the child must be idle,
noncompacting and have an empty pending queue. Unsupported options, clamping or
missing RPC capabilities refuse with zero task prompts. No uncertain prompt
acknowledgement is retried.

The reader continuously consumes strict LF-framed JSONL, correlates command IDs
and enforces byte, line, wall, tool and turn bounds, including incomplete lines
and backpressure. Malformed/oversized data, unexpected EOF and missing, duplicate
or wrong response IDs fail. Stderr remains bounded and separate from protocol.
Full model objects are not retained; control evidence allowlists identity, level
and state fields before persistence.

Pi can emit `thinking_level_changed` before acknowledging a model or thinking
setter. The runner retains only its level and binds the event to that one
outstanding setter. Unsolicited, repeated, malformed or mismatched configuration
events refuse; other pre-prompt agent/tool/UI activity remains forbidden. The
returned transcript must preserve this ordering and agree with effective-state
readback. A same-value setter needs no change event.

After one valid handoff, require `agent_settled` and an idle/empty-queue readback.
The runner closes stdin for orderly shutdown and requires child exit and
extension shutdown before executing checks. Prompt acknowledgement or
`agent_end` alone is insufficient. Timeout/cancellation retains managed
OpenShell stop; no arbitrary PID or process-group fallback is authorized.

```sh
python3 ../../scripts/coordinate.py capabilities --output /private/evidence/new-capabilities
```

`capabilities` accepts the normal `--profile` and `--lock-root` options. It uses
the same owned disposable lifecycle with zero prompts, tools or extensions and
returns only available provider/model IDs, the current runtime model's supported
thinking levels and sanitized actual idle settings. It sends no model or thinking
setters and does not require profile defaults to be supported by the current model.
Task runs still require exact supported options before their one prompt. Its CLI reports
`capabilities_valid`; the receipt retains `delivery_valid: false` and
`acceptance: not_granted`. Metadata discovery is separate from actual setup,
model execution and real-edit qualification. Default Run does not require a
capability query.

For selected-model metadata, supply an exact pair:

```sh
python3 ../../scripts/coordinate.py capabilities --provider configured-provider --model exact-model-id --output /private/evidence/selected-capabilities
```

Missing, malformed, unavailable or duplicate selector matches refuse. Native
version 3 uses `operation: capabilities_selected`, separate from execution
options. It starts an ephemeral no-session child without tools or extensions,
queries initial state/catalog, sends official non-persistent `set_model` only
if needed, then obtains that model's thinking levels and exact idle readback.
It permits the narrowly correlated model-induced thinking event, but sends no
`set_thinking_level` and no prompt. Evidence retains the selected identity,
observed current thinking/levels and profile-default compatibility. Unsupported
profile thinking does not block this metadata query; ordinary Run/Continue
still refuse that default unless the task explicitly selects a supported level.
Observed metadata is not execution approval, a fallback choice or an invented
`auto`/`dynamic` capability. Existing no-option metadata remains native version 2
and sends no setters.

## Official saved Run and Continue

```sh
python3 ../../scripts/coordinate.py run first-task.json --save-session --output /private/evidence/first-run
python3 ../../scripts/coordinate.py continue next-task.json --from /private/evidence/first-run --output /private/evidence/next-run
```

Before Continue, inspect and integrate the first approved return through the
repository workflow, commit it, and set the new task's explicit repository and
revision. Saved dispatches require committed Git source. The public task does
not carry a session path or executable. The host derives a native version-3
`run` or `continue` variant with an owned conversation ID, stable workspace,
exact session file and prior checkpoint digest/run identity. Each dispatch has
new task/source hashes and separate controls/results. Anvil's outer request
must bind its current task, actor, claim and generation separately.

The first saved run exclusively creates its conversation and requires the
session path to be absent. Pi receives exact absolute `--session FILE` and
matching `--session-dir DIRECTORY`, without `--no-session`. Continue requires
a bounded nonempty regular file containing complete JSONL, a current version-3
header, full official ID, the stable cwd and persisted assistant history.
Missing/empty/header-only, malformed, partial, foreign, symlinked, migrated or
drifted history refuses before Pi starts. RPC and extension readbacks must match
the actual session ID/file/cwd. There is no latest-session lookup, partial-ID
match, `--continue`/`--resume` shortcut, fork, header rewrite or cwd shim.

Before switching source, verify the complete old workspace bytes and all file
and directory modes against its terminal checkpoint, including check-created
files. Stage the new committed source separately with exact modes. Write an
intent naming old/staged/new manifests before any rename; preserve the old
workspace under its dispatch identity and move the staged source to the same
stable cwd. Duplicate/stale `--from` or a pending/mixed transition refuses.
No automatic rollback, deletion or reset resolves uncertain outcomes.

A fresh Pi process loads only the current task and coordination extension.
Session-start/before-agent-start evidence binds official session ID, stable cwd,
dispatch and task hash; counters and handoff state restart for this dispatch.
The complete current assignment, source, writable scope, checks, options and
limits supply authority. Historical conversation content grants none of them.
Exact supported options and idle, noncompacting, empty-queue session state are
required before the single prompt; uncertain acknowledgement is never replayed.

After settled handoff, idle readback, orderly exit and extension shutdown, run
the fresh checks and record terminal session/workspace bindings. Saved receipts
include before/after session byte lengths and hashes, unchanged header identity,
the prior-prefix hash, prior/current dispatch/task hashes, source revision and
the complete final workspace manifest. The checkpoint advances only with those
bindings. The returned source-change manifest remains separate and does not
turn check-created files into approved source changes. The saved conversation
file stays in owned remote storage; current dispatch events and model output
remain private evidence and must not be published.

## Return and trust

`started.json` binds the run and input archive. `receipt.json` records worker
outcome, cleanup and protected-resource readback. `results/worker-receipt.json`
records actual Pi exit, event completion, changes and checks. Every check has
exclusive started/result records and a log SHA256; interruption never fabricates
a successful terminal receipt.

New return evidence includes `rpc-events.jsonl` (sanitized control transcript),
`rpc/stderr.log` (diagnostics outside the check-log namespace) and
`rpc-configuration.json`. Check logs retain `<check-name>.log`, including the
valid name `pi-stderr`; started/result receipts and hash checks remain unchanged.
The worker receipt's `configuration` binds requested options, profile defaults,
effective options, supported levels, actual session ID/file variant, prompt admission,
settlement, shutdown and RPC/stderr hashes. Input/task/source hashes bind this
evidence to the assignment. The extension's `run_configuration` event
at the first `before_agent_start` records actual provider/model from its context
and thinking from `pi.getThinkingLevel()`. `task_loaded.model` records startup
state and does not prove the later RPC selection. Normal verification and
recovery decode native versions 1/2/3 explicitly; old evidence cannot acquire
new saved-session claims.

`model-report.json` is Pi's task-bound self-report. `extension-events.jsonl`
records task loading, budget/tool observations and lifecycle events. These are
not independent issuer attestations. Checks run trusted coordinator-selected
code in the same OS sandbox; this does not prove arbitrary hostile test code
cannot tamper with same-user files. Stronger claims need independent validation.

`changed-files` retains changed bytes; `changes.json` includes hashes/deletions;
`changes.patch` is a convenience text diff. Binary and empty-file changes require
the manifest/bytes. Do not automatically apply patches to a newer checkout.
Verification may create outputs but must not alter returned source/artifacts.
The byte-change receipt does not attest mode-only edits.

For lower-level Pi loading, use `--extension <plugin>/extensions/coordination.js
--coordination-task <task.json>`. That manifest additionally includes run_id,
absolute workspace/output_directory, allowed_tools, source metadata and
max_tool_calls. Output/control files stay outside the workspace. Standalone
extension loading supplies neither OS isolation nor managed cleanup.

Pi's CLI `--tools` allowlist must include `coordination_status` and
`coordination_handoff` alongside the task's native tools. The extension checks
activation, records missing-tool refusal and blocks further tools. Standalone
extension refusal does not establish the runner's pre-prompt configuration or
managed-stop guarantees. The runner's wall deadline and managed OpenShell stop
remain the process boundary.

## Failed-run recovery

`python3 ../../scripts/coordinate.py recover FAILED_RUN --output NEW_DIRECTORY`
uses the normal `--profile` and `--lock-root` options. Keep the failed directory's
`started.json`, `receipt.json` and `inputs.tar` unchanged. Recovery validates their
hashes, safe archive members, task/source bindings and derived remote results
path before any lifecycle action. For legacy ephemeral recovery, the latest
owner journal must bind that failed run and input with completed Stopped custody;
a newer assignment refuses. Saved recovery instead binds its independent
conversation checkpoint to fresh resolved Stopped custody, so an intervening
metadata or ephemeral run does not invalidate it. Active owners, identity drift
or competing locks refuse. A worker that returned work but failed
cleanup may be recovered after reconciliation; an already-valid delivery may not.

The owner must qualify the existing sandbox entrypoint as idle on restart. The
runner starts a fresh Ready main instance and performs only a native download,
then verifies its identity, stops it and reads back protected resources.
Legacy recovery does not exec a worker. Saved recovery may run the retained,
hash-bound conversation inspector to read checkpoint/session/workspace state;
it never launches Pi or reruns task checks. For both normal runs and recovery, if a start fails before the fresh
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


For a failed saved dispatch, `conversation_valid` is a separate recovery field.
A failed trusted check can leave a verified advanced session/checkpoint while
`delivery_valid` and `task_delivery_valid` stay false. Only explicit successful
recovery with `conversation_valid: true` supplies a continuation checkpoint;
use that recovery output as `--from` with a newly approved task. Partial session
tails, missing acknowledgement, incomplete shutdown or ambiguous checkpoint
bindings leave continuation unavailable. An earlier valid conversation does not
justify replaying an uncertain task prompt.

```sh
python3 ../../scripts/coordinate.py reconcile --from /private/evidence/failed-run --output /private/evidence/reconciliation
```

This saved-conversation variant requires both `--from` and a new `--output`.
After exact stopped custody, it inspects the retained transition intent and
session/checkpoint binding. An unchanged old tree with the exact staged source
can be certified by archiving its pending intent; workspace/session bytes are
not restored or rewritten. A completed-new tree without verified terminal
model evidence remains noncontinuable. Mixed, missing or foreign state refuses.
The existing no-argument `reconcile` remains a stopped-owner custody readback,
not conversation certification. Preserve all previous journal and dispatch
artifacts; neither path rolls back files, prunes evidence or reruns a prompt.

Synthetic process/file fixtures, installed command discovery, actual default
OpenShell two-edit/same-session qualification and selected-model metadata are
separate checks. The actual installed journeys remain delivery gates. Anvil
must separately validate CLI/web admission, fresh claim bindings, integration,
native checkout proofs, `needs_review` and approval. Plugin sandbox checks and
conversation validity confer no native acceptance, latency or fleet-scale claim.
