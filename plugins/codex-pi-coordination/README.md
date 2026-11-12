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
provider/model IDs and the configured model's supported thinking levels.

Version-2 tasks may add `run_options`: an exact `provider`/`model` pair,
`thinking` alone, or both. Omitted options inherit the profile. `auto`, `dynamic`
and the literal `default` are refused; use omission for Default. Unsupported or
silently clamped selections fail before the task prompt, without fallback.
Version-1 task inputs remain readable. All new runs use bounded native RPC with
`--no-session`; saved-session continuation remains future work (P1b).

See the [skill](skills/codex-pi-coordination/SKILL.md) and
[task/profile contract](skills/codex-pi-coordination/references/task-contract.md).
Codex discovers the skill through the marketplace entry. The Pi package exposes
`extensions/coordination.js`; the runner loads only that explicit extension.

The extension provides `coordination_status`, `coordination_handoff` and
`/coordination-status`. File tools stay inside the assigned workspace, writes
name exact files, and tool/turn budgets stop further work. Declared verification
argv runs after Pi exits. Task policy is not an OS sandbox: OpenShell remains
the isolation and lifecycle owner. Selection is confined to the ephemeral Pi
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
It skips artifact download. Recover the latest failed run after confirmed stopped
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
The native download has a timeout and post-download file/byte checks, not a hard
pre-download storage quota. Use only an owner-qualified idle runtime.

Development checks:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/extension.test.mjs
```

These synthetic checks run in repository CI without a model or OpenShell
runtime. Native loading and real model task evidence require separate runtime
validation.

API reference: [Pi extension contract](https://github.com/earendil-works/pi/blob/v0.87.1/packages/coding-agent/docs/extensions.md).
Anvil and ship-loop continue to own their scale and delivery workflows.
