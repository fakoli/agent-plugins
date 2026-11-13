# Codex–Pi coordination

Delegate implementation, research, review and validation to Pi inside an owned
NVIDIA OpenShell sandbox. Codex retains scope, integration and acceptance. A
native Pi extension returns work; a stdlib runner records actual checks, source
changes and managed cleanup. Model selection is explicit and provider-neutral,
including configured GLM routes.

From the plugin directory, register an existing private runtime profile once,
then use the default for discovery and runs. Paths below are synthetic examples:

```sh
python3 scripts/coordinate.py configure --profile /path/to/private/profile.json
python3 scripts/coordinate.py capabilities --output /private/evidence/new-capabilities
python3 scripts/coordinate.py run task.json --output /private/evidence/new-run
```

`configure` validates and registers `~/.config/codex-pi-coordination/profile.json`.
Identical settings are a no-op; conflicting defaults and symlinks refuse. It
does not copy credentials or qualify the runtime. `capabilities` uses the owned
disposable sandbox with zero prompts, tools or extensions, returning available
provider/model IDs and the current runtime model's supported thinking levels.
It reports actual idle settings without applying profile model/thinking defaults.

Version-2 tasks may add `run_options`: an exact `provider`/`model` pair,
`thinking` alone, or both. Omitted options inherit the profile. `auto`, `dynamic`
and the literal `default` are refused; use omission for Default. Unsupported or
silently clamped selections fail before the task prompt, without fallback.
Version-1 task inputs remain readable. Ordinary runs retain bounded native RPC
with `--no-session`. To keep one official Pi conversation across fresh, stopped
worker processes, use saved Run and Continue:

```sh
python3 scripts/coordinate.py run first-task.json --save-session --output /private/evidence/first-run
```

Inspect the first return, integrate its approved changes through the repository
workflow, and commit the source for a new task manifest. Then continue from the
verified prior output with that new assignment and revision:

```sh
python3 scripts/coordinate.py continue next-task.json --from /private/evidence/first-run --output /private/evidence/next-run
```

Saved runs require an explicit committed repository source. Continue preserves
the exact official session file, ID and workspace path, while each dispatch gets
fresh scope, options, budgets and artifacts. It checks the prior session hash
and history prefix and every workspace file/directory mode before switching
source. Stale, duplicate, missing or drifted checkpoints refuse before Pi starts;
the managed owner may start only to inspect that remote state. No latest-session
search, live attachment or silent fresh-session fallback occurs. Public task
versions 1/2 are unchanged; saved dispatches use native version 3.

For one exact model's thinking choices, pair both selectors:

```sh
python3 scripts/coordinate.py capabilities --provider configured-provider --model exact-model-id --output /private/evidence/selected-capabilities
```

This native version-3 metadata operation may select that model in its ephemeral
child, but sends no thinking setter, prompt, tool call or extension. It reports
the observed levels/thinking and profile-default compatibility. An unsupported
default does not block discovery; Run and Continue still require a supported
explicit or inherited thinking level. Omit all run options for the configured
default; capability discovery is optional, never a prerequisite for Default.

See the [skill](skills/codex-pi-coordination/SKILL.md) and
[task/profile contract](skills/codex-pi-coordination/references/task-contract.md).
Codex discovers the skill through the marketplace entry. The Pi package exposes
`extensions/coordination.js`; the runner loads only that explicit extension.

The extension provides `coordination_status`, `coordination_handoff` and
`/coordination-status`. File tools stay inside the assigned workspace, writes
name exact files, and tool/turn budgets stop further work. Declared verification
argv runs after Pi exits. Task policy is not an OS sandbox: OpenShell remains
the isolation and lifecycle owner. Selection is confined to the dispatched Pi
child; global provider/model settings stay unchanged. No background service,
recursive Codex launch or automatic patch application is installed.

Inspect `rpc-configuration.json` and the worker receipt's `configuration` with
the existing changes/check evidence. They bind requested, inherited and
effective options, prompt admission, settlement and shutdown. `delivery_valid`
means a bounded handoff completed, not application acceptance, latency
qualification or deployment authority. `capabilities_valid` covers metadata
discovery and cleanup only. Keep failed runs and actual operator profiles and
evidence outside public plugin source.

On execution failure, nonzero worker exit or timeout, the runner immediately
enters managed OpenShell cleanup: verify identity, stop and record the readback.
It skips artifact download. Recover a saved failure, or the latest ephemeral
failure, after confirmed stopped
custody using the same private profile and lock root:

```sh
python3 scripts/coordinate.py recover /private/evidence/failed-run --output /private/evidence/recovery
```

Recovery starts a fresh idle instance of the exclusively owned sandbox, downloads
the bound results, and stops that instance. It runs no model or checks.
`recovery_valid` means retrieval, available evidence bindings and cleanup passed;
`recovered_partial` preserves missing terminal results as unknown. Task delivery
remains invalid and acceptance is not granted. Unknown stop blocks further work
until supported `reconcile`; the original failed receipt is never rewritten.
For saved runs, recovery also reports `conversation_valid` separately. Failed
checks can leave a valid advanced conversation only when recovery verifies its
terminal session, workspace and stopped custody. Continue must reference that
valid recovery output with a new task; delivery remains failed.

Use `reconcile --from FAILED_RUN --output NEW_DIRECTORY` for a saved workspace
transition. It can certify the exact unchanged prior tree and archive its
matching pending intent. A switched-new tree without verified terminal model
evidence remains unavailable for continuation; mixed or unknown state stays
held. The same command can inspect a successful saved run after an intervening
metadata or refused stale dispatch: it returns a fresh terminal checkpoint
readback without Pi or checks. `recover` remains failed-run-only, and inspection
still reports `delivery_valid: false`. It never restores files, rolls back a workspace, rewrites history or
replays a prompt. The existing no-argument `reconcile` only records independently
confirmed stopped owner custody.

Sessions are limited to 16 MiB, checkpoint/control JSON to 1 MiB, and retained
remote material to an observed 1 GiB limit. These are checked bounds, not a hard
filesystem quota; overflow refuses further work without pruning prior runs.
The native download has a timeout and post-download file/byte checks, not a hard
pre-download storage quota. Use only an owner-qualified idle runtime.

Development checks:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/extension.test.mjs
```

These synthetic checks run in repository CI without a model or OpenShell
runtime. The saved two-edit journey and selected-model query still require separate
qualification through the installed OpenShell command. Anvil CLI/web admission,
current claims, integration, native checkout proofs and final approval also
require their own journey checks; plugin sandbox checks do not satisfy them.

API reference: [Pi extension contract](https://github.com/earendil-works/pi/blob/v0.87.1/packages/coding-agent/docs/extensions.md).
Anvil and ship-loop continue to own their scale and delivery workflows.
