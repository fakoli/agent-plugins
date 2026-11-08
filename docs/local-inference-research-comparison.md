# Continuing research workflow comparison

Reviewed November 8, 2026. The intended workload is repeated model/runtime
decisions, not an exhaustive academic research platform. The observed failure
was repeating candidate discovery without a durable decision and reopening
condition. Improve the existing local-inference skill rather than install a
second research system.

## Comparable implementations

| Workflow and inspected revision | Useful behavior | Decision for this skill |
| --- | --- | --- |
| [hec-ovi research-skill](https://github.com/hec-ovi/research-skill/blob/109589751168ab42f929f3cd1741bd2946b4880b/plugins/research-codex/skills/research/SKILL.md) | Reads an index, then a matching summary; refreshes stale findings; keeps discarded approaches and verifies storage. | Consult the existing project record first, escalate detail only as needed, preserve superseded decisions and verify authorized writes. Reuse the user's store rather than require its `.research` layout. |
| [Hyperresearch citation check](https://github.com/jordan-gibbs/hyperresearch/blob/d4725a2bc384bc9c49f86d2032307bbfd6f3327e/src/hyperresearch/skills/hyperresearch-14-5-cite-check.md) and [implementation](https://github.com/jordan-gibbs/hyperresearch/blob/d4725a2bc384bc9c49f86d2032307bbfd6f3327e/src/hyperresearch/core/citecheck.py) | Resolves citations to retained sources, triages claim/source pairs and checks unsupported or wrong-source claims. Its full pipeline adds a skeptical citation check after patching. | Verify decisive claims against the cited variant, date and metric before delivery. Keep existing origin deduplication and counterevidence checks; no new vault, database, hooks or orchestration runtime. |
| [robertnowell deep-research](https://github.com/robertnowell/deep-research/blob/feb53f298ef8965ad059f742bc5a57f541c65ff4/skills/deep-research/SKILL.md) | Requires sourced findings, an explicit answered/partial outcome, disclosed failed angles and persisted reports. | Preserve explicit coverage gaps and incomplete saves. Scale effort to the actual request; do not require its fixed agent counts or full report for a historical lookup. |

These are source-level observations from the inspected revisions. Source and
benchmark claims in their READMEs do not establish comparative performance here.
Third-party code and instructions were inspected as evidence, not installed or
executed. Search discovery used Exa and Firecrawl, then original files were read.

## Adopted change

The local-inference skill now resolves an established tracker, reuses dated
historical answers, refreshes material changes for current questions, and
maintains decisions with evidence and reopening conditions. It distinguishes
last checked from last material change, preserves corrections, and reports an
unreadable or unsaved tracker instead of creating a competing record.

Existing checks remain in force: original-run deduplication, targeted contrary
evidence, hardware/workload comparison gates, quant-versus-parent distinction,
source access limits and separation of research from live-operation authority.
The [continuing decision record guide](../plugins/session-improvement-loop/skills/local-inference-research/references/research-guide.md#continuing-decision-record)
describes the minimal schema and update rules. Project-specific locations stay
in the project's own instructions rather than this public skill.

## Validation scope

Structural validation and the repository suite verify packaging and existing
invariants. Isolated synthetic before/after decision replays separately check
historical reuse, new quant evidence, one-off research, inaccessible tracking,
retracted metrics and partial source coverage. Review results belong to the PR
validation record. These checks do not establish better research accuracy,
latency, token efficiency or ranking against the compared plugins. Such claims
require a matched end-to-end evaluation, which was not performed.
