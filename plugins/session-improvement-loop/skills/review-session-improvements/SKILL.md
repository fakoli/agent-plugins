---
name: review-session-improvements
description: Review recent Codex or Claude session logs for recurring token waste, accuracy failures, slow manual work, and user-experience friction; then propose, create, or update only evidence-backed skills and plugins. Use for daily session reviews, cross-session improvement audits, proactive skill discovery, or deciding whether repeated agent work should become reusable automation.
---

# Review Session Improvements

Turn recent session evidence into fewer repeated mistakes, smaller prompts, and faster workflows without manufacturing a new skill every day.

## Workflow

1. Inventory before reading transcripts.

   Run `python scripts/scan_recent_sessions.py inventory --since-hours 24 --output <temporary-json>` from this skill directory. Keep the output outside any repository. Exclude sessions reported as active unless the user explicitly requests them.

2. Rank the evidence.

   Start with completed sessions that have tool failures, human-correction signals, repeated tool sequences, or high output-token cost. Inspect at most three sessions initially. Use `slice --session <path> --line <n>` to read small windows around signal lines; widen only when the cause is still unclear.

3. Search for an existing solution.

   Search installed skills, both target plugin repositories, applicable `AGENTS.md` files, and open issues before creating anything. Prefer fixing or extending the narrowest existing artifact. Do not duplicate a capability under a new name.

4. Apply the evidence gate.

   Build or update an artifact only when at least one condition holds:

   - the same friction appears in two independent sessions;
   - one incident exposes a severe security, data-loss, or correctness risk;
   - a deterministic helper replaces a repeated, measurably expensive sequence;
   - the user explicitly requests the artifact.

   Otherwise report the candidate and why it did not clear the gate. A day with no change is a successful run.

5. Choose the smallest artifact.

   - Update guidance for a stable repository convention.
   - Add a script for deterministic parsing, validation, or mechanical work.
   - Add a skill for a reusable judgment-heavy workflow.
   - Add a plugin only when marketplace packaging or multiple coordinated components improve discovery or reuse.

6. Classify before writing.

   Read [publishing-policy.md](references/publishing-policy.md). Put portable, sanitized work in the public repository and personal or operational workflows in the private repository. Put secrets, raw transcripts, credentials, and capability-bearing endpoints in neither.

7. Author and verify.

   Use the installed plugin-creator and skill-creator workflows. Keep skills concise and deterministic helpers stdlib-only when practical. Run skill validation, plugin validation, relevant tests, secret scanning when available, and `git diff --check`. Never claim an improvement is proven without recorded validation.

8. Publish conservatively.

   Preserve unrelated work. Work on a dated `codex/` branch. Commit only the files created for this review. Push and open a draft pull request only when the scheduled-task prompt grants those actions; never merge automatically.

9. Return the daily summary.

   Report sessions considered, evidence count, what changed, expected token/time/accuracy benefit, validation, public/private disposition, branch or draft PR, and noteworthy candidates rejected. Do not quote session text or expose private paths, identifiers, prompts, URLs, or tool output.
