---
name: skill-improvement
description: Improve an agent skill from observed evidence using a frozen baseline, matched controls, independent judgment, and holdout cases. Use at a campaign boundary or after a material process failure; do not use for speculative rewrites or account-wide memory changes.
---

# Evidence-driven skill improvement

Use this at a campaign boundary, after a material process failure, or when the
caller requests a focused workflow improvement. A retrospective is a hypothesis,
not proof that a new instruction works. If no actionable evidence exists, record
no change and finish.

## Bind the evaluation

Obtain the project bindings: permitted target skills and files; evidence and
retention locations; available roles, models, effort settings, tools, and judge;
write and external-action authority; success criteria; and a shared budget with
a reserve for the primary work, required restoration, and reporting. Do not create account-wide memories, change
unrelated instructions, provider settings, or project authority through this
loop. Preserve configured model identities and effort by default.

If the configured lead is GPT-6 Astra, load the conditional guidance in
[references/astra.md](references/astra.md). Otherwise do not apply its
model-specific checklist.

## Capture one evidence-backed lesson

Use existing evidence rather than a new memory store. Seek repeated waste, a
verified root cause, a missed capability, or a material operator correction.
Separate the owning layer: harness or transport, runtime or product behavior,
workload or validator, source interpretation, agent decision, or skill text.
Correct that layer. A broken validator invalidates comparisons; do not weaken it
while optimizing a skill.

For a proposed lesson retain the observation and evidence path, causal
hypothesis, applicable scope and revisions, instruction delta, counterevidence,
evaluation result, expiry trigger, and accepted/rejected/unresolved disposition.
Keep private traces in the project's permitted store.

## Propose, evaluate, then adopt

1. Freeze the baseline: skill revision and reference hashes, roles/models/effort,
   tools, inputs/history, budget, evidence policy, cases, rubric, and judge.
   Never mix an instruction edit into a running evaluation; a changed skill has
   a new identity.
2. State one falsifiable improvement: the observed bad decision, desired next
   action, and smallest source-of-truth edit. Prefer deleting contradictory or
   obsolete text to adding an unconditional rule.
3. Predeclare a matched comparison: the triggering development case, a known
   successful case, and a case where the rule must not apply. Keep task, tools,
   context, model/effort, and budget comparable. If anything else changes,
   attribute the outcome to the combined configuration.
4. Run isolated replays without live side effects unless already authorized.
   Score decisions, evidence fidelity, authority behavior, stopping behavior,
   and completion. Use executable checks when deterministic; otherwise use an
   independent judge with explicit pass/fail criteria. The optimizer does not
   grade itself. Blind variant identity and counterbalance order when feasible;
   permit ties and insufficient evidence.
5. Freeze the candidate before independently prepared holdout/transfer cases.
   Once a holdout informs an edit, it becomes development evidence; use a fresh
   holdout before claiming transfer. Repeat noisy or consequential cases.
6. Adopt only when independent behavioral evidence preserves correctness,
   reliability, evidence integrity, and authority gates. Keep the baseline on
   unexplained regression. A tie can support clearer text, never a capability
   claim.

## Keep meta-work bounded

Default to one focused proposal and one paired comparison. Account for elapsed
time, calls/retries, observable usage, research, evaluation, failures, and
accepted work. Do not infer total token cost from response length. Stop before
this work consumes the reserve needed for the caller's primary outcome.

Return the baseline and candidate identities, evidence, comparison result,
scope, remaining uncertainty, cost/coverage, and disposition. Structural skill
validation confirms packaging only; it does not establish behavioral improvement.

## Retain narrowly and revalidate

Retrieve only lessons matching the next task's scope and revisions. Keep a
compact rule and evidence pointer in active context. At relevant upgrades or
contradictory evidence, revalidate, narrow, or supersede the lesson. Replace
duplicated rules instead of accumulating an unlimited playbook. A single
verified consequential failure can justify a scoped fix; an unexplained
isolated incident cannot establish a universal rule.

Claim speed or token gains only from matched evidence including discarded
attempts and evaluation overhead. Separate subscription usage from API dollar
estimates; retain unavailable counts as unknown. Use compatible installed
session accounting and skill-authoring helpers when useful, without making
an absent optional helper block closure. If no independent judge or suitable
executable check is available, retain an unresolved proposal rather than
self-approving it. Reverting a skill does not authorize reverting a deployment.

The [research review](https://github.com/fakoli/anvil-serving/blob/main/docs/benchmarks/skill-improvement-research.md)
provides rationale and limitations; it is optional background, not an Anvil
runtime dependency.
