# Research guide

Read only the source checklist needed for this task, then the comparison gate.

## Continuing decision record

Use the project's established Page, repository ledger or other authorized store.
The tracker is a navigation and decision record, not proof of current runtime
state. Load its recommendation and matching rows before full reports or raw runs.
Create a tracker only when requested; a one-off answer needs no new store.

Keep one candidate row unless a different exact artifact, role or deployment
changes the decision. A useful row records:

| Candidate and role | Decision and rationale | Decisive evidence | Last checked | Reopen when |
| --- | --- | --- | --- | --- |
| Model/artifact revision and intended workload | Current reference, investigate, watch, complementary or defer | Direct sources/runs, evaluation version, comparison fit and missing checks | Observation date and actual checked scope | A specific new artifact, supported fit, task result or changed requirement |

Keep the baseline's model/quant/runtime identity and observation date alongside
the table. Separate best supported local choice, external quality lead and
smaller/faster alternative; do not combine unrelated quality and speed metrics
into one score. A low-bit derivative does not inherit its parent's benchmark.

Append a dated review recording the question, checked sources, material changes
or no-change outcome, superseded decision and reason, unresolved blocker and
smallest next check. Track last material change separately from last checked.
When a source retracts or corrects a result, mark the affected claim superseded
and reevaluate only decisions depending on it. Count unique entries and actual
reviews from the record; mirrors, retries and repeated summaries are not extra
models, independent evidence or experiments. Do not backfill invented review counts.

A fresh status query can reuse a still-supported decision while a material delta
reopens only its affected row. An explicitly requested broad survey may expand
coverage. Before a write, read the target and preserve concurrent edits using
its supported guards. Verify the saved rows, tally and evidence links afterward.
If access fails, retain an explicit unsaved result rather than silently creating
a competing record. Tracking does not schedule refreshes or authorize trials.

## Source selection

Read the checklist matching the question; use `sources.md` for URLs. For mixed
questions, gather performance and quality evidence separately before synthesis.

| Question | Start here | Follow through to |
| --- | --- | --- |
| What changed recently? | LIL daily summaries | Original release, issue, run or author post |
| What is fast on this hardware? | LocalMaxxing reports/matrices; LIL benchmark runs | Individual matched runs and raw artifacts |
| Does a quant retain quality? | LIL Aiderboard; named evaluation sites | Exact quant, suite/version, attempt policy and scored tasks |
| Which models merit local evaluation? | Artificial Analysis model and capability comparisons | Exact variant, relevant component benchmarks, reasoning budget and local feasibility evidence |
| Will it fit or work? | Model card and runtime release/code | Weight/host/KV requirements, supported geometry and configuration |
| Who has useful experiments? | Practitioner list, X/Reddit/Discord | Author's original worklog, code, failures and corrections |
| Why might it work? | Paper and kernel/runtime repository | Mechanism, actual experiment scope and implementation |

## Chrome access

1. For sources requiring the user's login or browser rendering, discover the
   available browser tools and select **Chrome**, using the existing authorized
   session/profile. A fresh isolated browser may lack the user's access. Use
   this path immediately when requested, or when HTTP/API reads cannot expose
   the relevant original evidence. No specific browser SDK is required.
2. Reuse a relevant tab or open a task tab. Use the rendered page to set filters,
   expand posts/tables, inspect methodology and follow original run links. Keep
   the selected filters, direct URL/run ID, access date and relevant values in
   the evidence record; do not copy unrelated account or browsing information.
3. If Chrome is disconnected, report the missing connection and the source that
   needs it. If a login or human challenge is required, let the user complete
   that step. Continue independent public-source work while access is pending.
   Do not replace the user's profile, export cookies/tokens, inspect credentials
   or install browser components as part of research.
4. Distinguish **not accessible in this session**, **partially inspected**, and
   **no matching results after applying stated filters**. Capture coverage limits;
   snippets or an unexpanded chart do not establish a complete source review.
   Research access authorizes reading, not posting, following or subscribing.

## Source checklists

### LocalMaxxing

1. Start with **Reports** for explanation or **Hardware** for exact card edition
   and GPU count. Use **Matrix runs** for context/concurrency comparisons; peaks
   across different matrix cells are not a matched comparison.
2. Filter by model/quant, engine, hardware and date using the UI or documented
   public API. Check current API docs before constructing parameters; do not
   invent GPU-count or verification filters. Query a bounded page, then narrow
   fields locally or paginate only as coverage requires.
3. Open the individual report/run. Extract actual input/output lengths, occupied
   versus allocated context, concurrent requests, cache/draft state, quant/KV
   precision, engine revision, timing definition and raw evidence links. Read
   warm/fresh companion results, failed trials and corrections.
4. Read quality runs separately: suite version, denominator, harness, retries,
   reasoning budget and verifier. Do not attach a base model's score to a
   different quant or runtime configuration without evidence.
5. Keep **verified account**, **approved submission**, **verified run** and
   **independent reproduction** separate. The documented API `verified` filter
   refers to user verification; inspect the run's own evidence and methodology.
   Repeat-prompt n-gram speed is not established speed on novel agent work.

### Local Inference Lab benchmark runs and configurator

1. Start at **Benchmark runs**, not the configurator's currently selected model.
   Filter by model, card edition, tensor parallelism, PCIe link and topology.
   Record physical GPU count separately from TP; inspect a run if these disagree.
2. Open relevant run detail pages or follow the linked JSON database. Retain run
   ID/URL, upload and measurement dates separately, checkpoint, build/digest,
   stock/modified/unknown image status, DCP/context shards, speculation, power,
   clocks, PCIe generation/width and topology. Missing metadata stays unknown.
3. Read the metric definition: decode C1/C8/C16 **@ 0** is aggregate output at
   those concurrency levels with empty starting context. It is not per-user
   decode at 32K; **Prefill 32K** is a different measurement. A dash is missing,
   never zero. KV pool capacity is not per-request usable context.
4. Use side-by-side run comparison for matched rows. Separate the site's **lab**
   measurements from **community** aggregates. Record run and unique-user counts,
   date range and spread when provided; repeated uploads are not independent rigs.
5. Read the selected configurator panel's inclusion rules. Its community summary
   may exclude incomplete, modified or unknown builds even though the all-runs
   list includes them. Keep the exact selected configuration URL; generated
   launch commands and newest builds are not measurements of that configuration.
   Consult build history only to resolve a relevant change; do not execute it.

### Additional benchmark portals

- **llm-speed:** start with the open-data page and follow its current manifest to
  a dated CSV/JSON export. Filter before loading into model context; preserve
  `run_id`, source, suite/runtime version, quant, actual token lengths and batch
  scope. Open decisive run permalinks and study limitations. The export's date is
  not the measurement date, and a fixed agent trace is not a quality evaluation.
- **llamaBench:** filter hardware/model/quant, then open the individual result
  and its configuration/reproduction evidence. Keep model SHA, runtime revision,
  KV precision, effective context and speculation together. Read current
  verification definitions; separate file identity, reproduced throughput and
  behavior checks. The API page primarily documents submissions; do not assume
  its GET endpoint exposes a full downloadable dataset.
- **LocalScore:** select the same model tier and inspect individual latest/run
  results. Record suite/runtime version, hardware and separate prompt, generation
  and TTFT values. Use composite scores only under the same benchmark contract;
  they do not measure coding quality or all speculative/concurrent workloads.
- **ComputeArena:** select model, quant, runtime, chip and actual PP/TG workload
  before opening Compare. Check matching-run and contributor counts, backend,
  runtime version and cooldown settings. A tiny-model peak is not a useful-model
  recommendation; sparse or vendor-concentrated samples need independent evidence.
- **oMLX:** choose Performance or Intelligence first. For speed, match chip/core
  variant, RAM, quant, input context and acceleration. For quality, inspect exact
  repository, oMLX version, benchmark and sample count/denominator. Open row
  details; keep partial suites, unknown quants and accelerated runs explicit.
- **Anubis:** use Chrome for the dynamic leaderboard/explorer and export only the
  relevant rows if the page offers it. Record app/methodology version, backend,
  prompt length, thinking/cache/load state and the available telemetry fields.
  Do not mix older token-rate or energy formulas with current results. Prefer
  native backend timing where recorded; a stream chunk is not necessarily a token.

### LIL Aiderboard and other quality leaderboards

1. Select the exact model/quant and open run details. Confirm suite/version,
   language/task subset, sample count, harness/version and verifier.
2. Extract first-attempt and retry/best-of results separately, reasoning settings,
   token/time limits, tool protocol and any failures excluded from the denominator.
3. Compare scores only under compatible evaluation contracts. Aider edit scores,
   Terminal-Bench agent scores, tool-call tests and hosted capability indices
   answer different questions. Read the site's methodology, not just its rank.
4. If raw runs or methodology are inaccessible, label the score source-reported
   with missing details. Do not promote it to a locally qualified result.

### Artificial Analysis

1. Use model comparisons to shortlist candidates, then open the model and the
   evaluation relevant to the task. Prefer coding/tool-use or other relevant
   component results over a universal intelligence rank alone.
2. Record the exact model release, reasoning variant/effort, provider when shown,
   index and benchmark versions, observation date, token budget/use and reported
   sample coverage. Do not compare different index versions as a performance trend.
3. Read the current methodology and distinguish model intelligence, domain
   capability indexes, coding-agent results, and provider speed/latency. Separate
   hosted token price from local operating cost; end-to-end task time and token
   use can matter more than output tokens per second.
4. Pair capability evidence with hardware-matched local runs from the other
   sources. State any model, quant, harness or reasoning-setting mismatch. Use
   hosted results as candidate priors; leave the exact local quality and speed
   unknown until measured. Do not transfer a base-model score onto a quant row.
5. Use public pages or an already-authorized documented API/export if available.
   Do not assume public chart data implies an unauthenticated API or request new
   account access just to complete a public-source review.

### LIL daily summaries

1. Enumerate actual dated files, including adjacent months across a date boundary.
   Read files, not just an index. Keep file date, event date and access date apart.
2. Extract hardware-relevant releases, experiments, failures and corrections;
   follow original discussion/run/code links for decisive claims.
3. Check later summaries/replies for retractions. If originals are inaccessible,
   mark the claim secondhand and the original unverified. Do not search private
   email to obtain public summaries or invent missing days.

### Model publishers and Hugging Face

1. Read the exact repository card, revision, license and model/config metadata;
   distinguish base model, derivative, quant, drafter and required loader.
2. Record weight size and declared VRAM/host/KV/workspace requirements separately.
   File size alone does not establish runtime fit. Check required capabilities
   such as tools, JSON, vision or context against the selected runtime version.
3. Follow validation links and known issues. A modification timestamp is not a
   release date; a current card does not validate every historical checkpoint.

### Runtime, recipe, field-wiki and kernel repositories

1. Confirm canonical repository, fork parent, archived status and exact revision.
   Read README plus the implementation/results relevant to the claim, not the
   whole repository. Record read scope and the hardware used.
2. Trace fixes through issue/PR, merged commit, released image and measured build;
   these are different states. Inspect launch defaults and failure paths for
   approval bypass, provider changes, unsafe workarounds and fail-open judging.
3. Prefer raw runs, matched controls, negative results and table footnotes over
   stars or push dates. For Ignis and other specialized engines, check exact API
   support, admission/retry behavior and host-RAM versus GPU-cache residency.
4. Kernels require matching GPU, build, dtype and geometry. A microbenchmark or
   old patched recipe does not qualify the current engine or whole application.

### X, Reddit, Discord and practitioner repositories

1. Use the requested browser/authorized connector. Open original posts and
   replies, expand truncated text, and inspect corrections and linked artifacts.
2. Verify social-to-GitHub identity through original links; preserve attribution
   gaps. A fork host is not necessarily the implementation author. Record every
   requested account in a survey, including unresolved ones.
3. Separate firsthand measurements, maintainers, independent reproductions and
   reposts. Follow credits one hop for discovery; expand only for a concrete gap.
   Prefer artifacts and corrections over engagement metrics.

### Papers and evaluation-methodology sources

Read the versioned paper and linked code/results. Extract the actual hypothesis,
test population, hardware, baselines, budgets, judge/verifier, held-out data and
limitations. Mark analytical estimates separately from measurements. Search for
corrections or contrary findings. A proposed mechanism is a research lead, not
proof of local speed, quality, or compatibility.

## Evidence record

Use one compact record per decisive claim, not one per scraped page. This is a
working/handoff format; omit irrelevant fields, but mark missing decisive fields
`unknown`. Never fill missing settings with defaults from another run.

```text
ID: E1
Claim: one observable result
Source: direct URL; original run/artifact ID; author; primary or secondhand
Dates: measured/event; published; accessed (unknown where unavailable)
Configuration: model + revision; quant; engine + revision/image; hardware + count/power
Workload: actual input/output; context capacity/occupancy; concurrency; cache; speculation
Measurement: metric + value + unit + scope (per-request/aggregate); timing; samples/spread
Quality: suite/version; pass count/denominator; attempts; budget; independent verifier
Limits: failed trials; contradictions; missing fields; source access scope
Assessment: evidence type; hardware/workload fit; inference; decision; next check
```

Use a fixed term for evidence type: **publisher claim**, **firsthand measurement**,
**independent reproduction**, **local measurement**, or **secondhand report**.
An estimate remains explicitly an estimate even if published by a reputable lab.
Do not manufacture numerical confidence. Source accessibility, evidence strength,
freshness and applicability are separate judgments.

## Comparison gate

1. State the question: faster runtime, better quant quality, system capacity, or
   successful agent tasks. Identify the intended differing variable.
2. Align model/artifact, hardware/power/topology, runtime settings, input/output
   lengths, concurrency, context/cache state, speculation and metric definition.
   For quality, also align suite, harness, attempts, budgets and verifier.
3. Mark **matched** when material controls are known and aligned except for the
   intended difference; **partially matched** when explicit differences limit
   applicability; **not comparable** when metric/contracts differ or decisive
   fields are unknown. Partial results can nominate experiments, not prove wins.
4. Compute a ratio only for matched nonzero baselines and consistent units;
   label whether higher or lower is better. Show samples/range when available.
   Do not pool different models, weight duplicate uploads as independent trials,
   or average percentages with different task denominators.
5. If no matched baseline exists, say so and recommend the missing measurement.
   Do not make one overall “best” rank by mixing speed, quality and feasibility.

Synthetic examples (not actual benchmark claims):
- A reports 800 aggregate tok/s at C8; B reports 140 per-request tok/s at C1.
  These do not establish a speedup. Dividing 800 by eight does not measure any
  user's latency or fairness; seek matching concurrency and per-request timing.
- A configures 180K context but uses 3K input; B occupies 180K. Separate capacity
  from measured depth; do not call A's short-prompt speed its 180K decode speed.
- A passes 62/89 first try and 70/89 cumulatively after retries. Compare 62/89
  only with a compatible first-attempt contract; report 70/89 as adaptive best-of.

## Detailed comparison checks


- **Evidence:** publisher claim, firsthand community measurement, independently
  reproduced result, or local measurement. A summary quoting a report is still
  secondhand. A model card, its runtime README and their reposts may be one source.
- **Freshness:** within the requested window, older but still relevant, or
  superseded. Freshness and evidence quality are independent.
- **Hardware fit:** close match, partial match, or different platform. Separate
  Max-Q from Workstation/Server cards; SM120 from Spark/SM121 and datacenter
  Blackwell; PCIe from NVLink; one GPU from TP2/TP4; discrete from unified memory.
  Account for clocks, power, PCIe width/P2P, host RAM and CPU offload. Never sum
  discrete VRAM into one automatically usable pool or extrapolate a TP4 gain to TP2.
- **Workload fit:** distinguish prefill from decode, per-request from aggregate
  throughput, drafted from accepted tokens, cold from cached prompts, and pooled
  KV capacity from a validated per-request context window. Capture concurrency,
  input/output lengths, reasoning effort, token limits, template, speculation,
  precision, cache state and quality metric when they affect the comparison.
- **Timing integrity:** distinguish model generation from network chunk delivery.
  Buffered speculative output can inflate first-to-last-delta rates. Count
  reasoning and tool arguments as well as visible prose, inspect parser field
  names, and corroborate with full request wall time and task completion time.
  Report TTFT-subtracted decode estimates separately from end-to-end rates;
  retain corrections and explicitly retire superseded numbers.
- **Confounds:** repeated shared prefixes can inflate throughput; lengthy reasoning
  can raise both scores and cost; changed quant/runtime/harness arms cannot isolate
  one cause. Kernel microbenchmarks do not establish end-to-end gains. Successful
  requests or token volume do not establish successful agent tasks.
- **Resource/quality boundary:** disk weight size is not runtime residency. Include
  KV, workspaces, host staging, offload and co-resident workloads. Lossless scale
  compression does not make other precision or vision changes lossless. Unknown
  residency or untested quality remains unknown, not a fit or acceptance claim.

For engine/harness research, connect findings to concrete components: scheduling,
collectives, prefix caching, KV restoration, tool parsing, or kernels. Recommend
profiling the application bottleneck before custom implementation.

Check the exact model/platform qualification matrix of the reviewed runtime
version. An older patched recipe does not qualify a rewritten main branch. For
harnesses, inspect launch defaults and failure paths: approval bypass, provider
changes, checkpoint writes, same-model judging, and unscored/fail-open verdicts
matter to adoption. A learned weight update is distinct from a reversible cache;
an LLM verifier is advisory unless independent acceptance checks establish success.
