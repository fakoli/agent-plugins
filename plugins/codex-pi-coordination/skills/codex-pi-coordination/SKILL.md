---
name: codex-pi-coordination
description: Delegate scoped implementation, research, review or validation from Codex to Pi in a caller-owned NVIDIA OpenShell sandbox, inspect returned work, or recover the latest stopped failed run without rerunning it. Use for Codex-Pi collaboration or Pi/GLM assistance; model selection and acceptance remain with the coordinator.
---

# Codex and Pi coordination

Codex owns task scope, integration and acceptance. Pi performs one bounded
assignment and returns work. Model selection is explicit in a private runtime
profile, including GLM when the configured Pi runtime supports it. This workflow
does not change routes, providers or global model settings.

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

## Run and inspect

Resolve the script relative to this skill directory:

```sh
python3 ../../scripts/coordinate.py run task.json --output /private/evidence/new-run
```

The default profile is `~/.config/codex-pi-coordination/profile.json`;
`--profile` selects another existing profile. Keep repeated settings there.
Outputs are exclusive. Independent assignments require separate outputs and
owned sandboxes; this command does not schedule a fleet.

Inspect `receipt.json`, `results/model-report.json`, `results/changes.json`,
returned files/patch and check logs/results. Verify task/source identities,
actual changes, exit codes and artifact hashes. Pi's handoff is a self-report.
`delivery_valid` means the bounded return/cleanup contract completed; it grants
no acceptance, merge, deployment or proof of research truth.

On a failed/nonzero OpenShell run or timeout, the runner immediately requests a
managed stop and skips downloading artifacts. After confirmed stopped custody,
recover the latest failed run with its original profile and shared lock root:

```sh
python3 ../../scripts/coordinate.py recover /private/evidence/failed-run --output /private/evidence/recovery
```

The runtime owner must have qualified the sandbox entrypoint as idle on restart.
Recovery starts a fresh idle main instance, downloads only the bound prior
results, and stops it. It never launches Pi, a worker or verification checks.
Inspect the separate recovery receipt and evidence status. `recovery_valid` and
CLI exit zero mean retrieval and available bindings passed with stopped cleanup;
task delivery stays invalid. `recovered_partial` leaves absent check exits and
worker outcomes unknown. Preserve contradictory artifacts as a failed integrity
gate. Never rewrite a failed receipt to use the successful-return verifier.

Require confirmed managed stop and unchanged protected resources. An exec
timeout does not prove remote termination. Unknown custody blocks another run.
After the exact sandbox is independently confirmed Stopped, `reconcile` records
that readback. Never delete a lock or receipt to make a retry appear fresh.
Preserve failed/partial artifacts; rework is a new assignment.

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
revision. Never retarget evidence or infer authority for additional work. Reuse
ship-loop for delivery and the target repository's benchmark/journey commands.
The plugin uses explicit task files and a native Pi extension; it launches no
recursive agents, second Codex process or persistent broker.
