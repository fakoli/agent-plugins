# Codex–Pi coordination

Delegate implementation, research, review and validation to Pi inside an owned
NVIDIA OpenShell sandbox. Codex retains scope, integration and acceptance. A
native Pi extension returns work; a stdlib runner records actual checks, source
changes and managed cleanup. Model selection is explicit and provider-neutral,
including configured GLM routes.

From the plugin directory, with an existing private runtime profile:

```sh
python3 scripts/coordinate.py run task.json --output /private/evidence/new-run
```

See the [skill](skills/codex-pi-coordination/SKILL.md) and
[task/profile contract](skills/codex-pi-coordination/references/task-contract.md).
Codex discovers the skill through the marketplace entry. The Pi package exposes
`extensions/coordination.js`; the runner loads only that explicit extension.

The extension provides `coordination_status`, `coordination_handoff` and
`/coordination-status`. File tools stay inside the assigned workspace, writes
name exact files, and tool/turn budgets stop further work. Declared verification
argv runs after Pi exits. Task policy is not an OS sandbox: OpenShell remains
the isolation and lifecycle owner. No background service, recursive Codex launch,
provider change or automatic patch application is installed.

`delivery_valid` means a bounded handoff completed, not application acceptance,
latency qualification or deployment authority. Keep failed runs and actual
operator profiles/evidence outside public plugin source.

On execution failure, nonzero worker exit or timeout, the runner immediately
enters managed OpenShell cleanup: verify identity, stop and record the readback.
It skips artifact download;
`receipt.json` retains the remote artifact path for the runtime owner to recover
after confirming stopped custody. An unknown stop blocks another run.

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
