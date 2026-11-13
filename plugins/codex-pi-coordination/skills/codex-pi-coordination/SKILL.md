---
name: codex-pi-coordination
description: Delegate scoped work from Codex to Pi in a caller-owned NVIDIA OpenShell sandbox, configure a default profile, discover exact-model thinking capabilities, continue an owned saved Pi conversation with a new assignment, inspect returned work, or recover a stopped failed run without replaying it. Use for Codex-Pi collaboration or Pi/GLM assistance; model selection and acceptance remain with the coordinator.
---

# Codex and Pi coordination

Codex owns task scope, integration and acceptance. Pi performs one bounded
assignment and returns work. Model selection comes from a private runtime
profile or exact per-task options, including GLM when the configured Pi runtime
supports it. Selection affects only the dispatched child; this workflow does not
change routes, provider configuration or global model settings.

## Prepare

Read [task and runtime contracts](references/task-contract.md). Resolve the
user's task and existing authorization. Choose implementation, research, review
or validation; specify expected outputs, exact writable files and a budget.
For repository work, choose a committed revision. Dirty working files remain
untouched and are not silently included. Without a repository, the task starts
in an empty workspace using material in its instructions.

Declare verification commands as argv arrays. Pi has scoped file tools and no
shell tool here. The runner executes checks once after handoff. Choose checks
that establish the requested behavior; exit zero alone proves no research claim.

Use an existing private profile for an exclusively owned, stopped, disposable
OpenShell sandbox with Pi, Python and the task's dependencies already present.
Preserve durable sessions and list protected sandboxes when their identity must
be checked. Runtime setup belongs to its owner. Do not adopt a similarly named
sandbox, copy credentials, read shared environment files, relax policy or
substitute ordinary shell execution when OpenShell is unavailable.

## Configure and discover

Resolve the script relative to this skill directory. Register an existing private
profile once; all paths in these examples are synthetic:

```sh
python3 ../../scripts/coordinate.py configure --profile /path/to/private/profile.json
```

The default is `~/.config/codex-pi-coordination/profile.json`. Registration
validates settings, creates private files/directories, refuses symlinks and
conflicting defaults, and is a no-op for identical settings. There is no force
overwrite. It does not provision providers, copy credentials or verify runtime
behavior. Keep repeated settings in the profile; `--profile` on operational
commands selects another existing profile.

Discover the configured runtime's available provider/model IDs and the current
model's supported thinking levels:

```sh
python3 ../../scripts/coordinate.py capabilities --output /private/evidence/new-capabilities
```

This uses the same owned disposable lifecycle with zero prompts, tools or
extensions. It reports actual idle model/thinking settings without applying
profile defaults or sending configuration setters. `capabilities_valid` reports
metadata and cleanup validity, never task delivery, real-edit qualification or
acceptance. Default Run needs no discovery step or model selection.

To inspect a particular model, supply both selectors:

```sh
python3 ../../scripts/coordinate.py capabilities --provider configured-provider --model exact-model-id --output /private/evidence/selected-capabilities
```

This selected-model query uses an ephemeral child with no prompt, tools or
extension. It may send an exact model setter, never a thinking setter. Inspect
supported levels, observed current thinking and profile-default compatibility.
Even if the profile default is unsupported, discovery can report the actual
levels; execution still requires an explicit supported choice or a supported
default. Metadata does not authorize a run or change provider/global settings.

## Run and inspect

Use task version 2 for optional `run_options`. Supply `provider` and `model`
together for an exact selection; `thinking` may appear alone. Omitted fields
inherit the profile. Default means omission, never the literal `default`.
Reject `auto`, `dynamic`, unknown/ambiguous models and unsupported thinking;
`max` requires actual support. There is no fallback or provider provisioning.
Version-1 inputs remain supported. Ordinary runs keep native RPC with
`--no-session`; saved mode is an explicit choice and uses native version 3.

```sh
python3 ../../scripts/coordinate.py run task.json --output /private/evidence/new-run
```

Outputs are exclusive. Independent assignments require separate outputs and
owned sandboxes; this command does not schedule a fleet.

Inspect `receipt.json`, `results/model-report.json`, `results/changes.json`,
`results/rpc-configuration.json`, returned files/patch and check logs/results.
Verify task/source identities, requested/inherited/effective options, the
extension's first `run_configuration` event, actual changes, exit codes and
artifact hashes. Configuration readback must match before the sole task prompt;
unsupported or clamped options admit zero task prompts. Prompt acknowledgement
and `agent_end` alone do not prove settlement. Require `agent_settled`, an idle
empty-queue readback, child exit and extension shutdown before checks.
`rpc-events.jsonl` retains sanitized control evidence; `rpc/stderr.log` is separate
diagnostic output, not protocol. Pi's handoff is a self-report.
`delivery_valid` means the bounded return/cleanup contract completed; it grants
no acceptance, merge, deployment or proof of research truth.

## Save and continue a conversation

Choose saved mode only when the task benefits from retained conversation. Both
dispatches need explicit committed repository sources:

```sh
python3 ../../scripts/coordinate.py run first-task.json --save-session --output /private/evidence/first-run
```

Verify the returned work and stopped/protected custody. Integrate reviewed
changes through the repository workflow, commit them, and prepare a new task
manifest at that revision with its own scope, checks, options and budget:

```sh
python3 ../../scripts/coordinate.py continue next-task.json --from /private/evidence/first-run --output /private/evidence/next-run
```

Use the verified prior output, never a guessed session path or partial ID.
The runner uses official `--session` and matching `--session-dir` with one stable
workspace path. It verifies the complete current-version session, full ID,
prior byte/hash/prefix bindings and full workspace file/directory modes. A fresh
process loads the current task/extension and resets counters and handoff state;
previous conversation text grants no current scope or claim authority.

Each dispatch retains separate artifacts. Workspace replacement stages the new
committed source, records intent before renames and preserves the old tree.
Missing, stale, duplicate or drifted state refuses before Pi starts; checking
remote state may require starting and stopping the managed owner. Partial/mixed transitions
remain held; do not reset files, rewrite a session header, retry a prompt or
silently start a new conversation. A successful saved return alone does not
integrate changes or satisfy Anvil's native proof/approval gates.

## Recover and reconcile

On a failed/nonzero OpenShell run or timeout, the runner immediately requests a
managed stop and skips downloading artifacts. After confirmed stopped custody,
recover a saved failure, or the latest ephemeral failure, with its original
profile and shared lock root:

```sh
python3 ../../scripts/coordinate.py recover /private/evidence/failed-run --output /private/evidence/recovery
```

The runtime owner must have qualified the sandbox entrypoint as idle on restart.
Recovery starts a fresh idle main instance, downloads only the bound prior
results, and stops it. Saved recovery additionally runs the retained bounded
conversation inspector. It never launches Pi or reruns task verification checks.
Inspect the separate recovery receipt and evidence status. `recovery_valid` and
CLI exit zero mean retrieval and available bindings passed with stopped cleanup;
task delivery stays invalid. `recovered_partial` leaves absent check exits and
worker outcomes unknown. Preserve contradictory artifacts as a failed integrity
gate. Never rewrite a failed receipt to use the successful-return verifier.

For a saved run, require the separate `conversation_valid` field before using
that recovery directory as Continue's `--from`. Failed checks can coexist with a
verified advanced conversation, but the task still failed. Missing acknowledgement,
partial history or incomplete terminal evidence never authorizes prompt replay.

For an interrupted saved-workspace transition:

```sh
python3 ../../scripts/coordinate.py reconcile --from /private/evidence/failed-run --output /private/evidence/reconciliation
```

This inspects the exact retained intent and may certify an unchanged old tree,
archiving that intent without changing workspace bytes. A fully switched new
tree without verified terminal evidence stays noncontinuable; mixed, missing or
foreign state stays held. There is no rollback or automatic restore. Inspect
`conversation_valid` separately from `recovery_valid` and CLI exit status.

Require confirmed managed stop and unchanged protected resources. An exec
timeout does not prove remote termination. Unknown custody blocks another run.
After the exact sandbox is independently confirmed Stopped, `reconcile` records
that readback using the no-argument command. This does not certify a saved
workspace transition. Never delete a lock or receipt to make a retry appear fresh.
Preserve failed/partial artifacts; rework is a new assignment. Observe the
16 MiB session, 1 MiB checkpoint/control and 1 GiB retained-remote limits.
Overflow refuses further work; do not truncate history or prune prior evidence.
These observed bounds are not a hard filesystem quota.

## Coordinate the next step

- Implementation: review returned changes and checks before integrating through
  the repository's existing development/review workflow.
- Research: verify citations and claims against the supplied sources. Broader
  access needs the runtime owner's supported path.
- Review: require concrete locations and reproducible findings. Authors are not
  independent reviewers of their own work.
- Validation: distinguish actual checks, commentary, correctness, latency and
  physical capacity; retain failed measurements.

Follow-up work gets a new manifest with relevant prior artifacts and the current
revision. Use Continue only for a verified saved checkpoint; otherwise a new
Run is a separate conversation. Never retarget evidence or infer authority for
additional work. Keep synthetic tests distinct from the pending installed
OpenShell saved-run/continue and selected-model qualification. Anvil CLI/web
claims, native checkout proofs and approval journeys remain separate gates. Reuse ship-loop for delivery and the target
repository's benchmark/journey commands.
The plugin uses explicit task files and a native Pi extension; it launches no
recursive agents, second Codex process or persistent broker.
