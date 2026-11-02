# Sources and search recipes

Source directory assembled October 14, 2026; benchmark portals added November 1,
2026. These are starting points, not
permanent rankings or endorsements. Refresh the relevant pages at research time;
repositories, branches, supported models and licenses can change. Read only the
categories relevant to the question. Use the source-specific checklists in
[Research guide](research-guide.md#source-selection) before comparing results.

## LocalMaxxing: community reports, speed tests and evaluations

| Source | Use | Boundary |
| --- | --- | --- |
| [Reports](https://www.localmaxxing.com/en/reports) | Author explanations, linked runs, recipes, failed trials and corrections | Reported measurements require inspection of underlying evidence |
| [Hardware](https://www.localmaxxing.com/en/hardware) / [Leaderboard](https://www.localmaxxing.com/en/leaderboard) | Find exact card edition/count, model, engine and quant | Mixed-workload hardware medians and maxima are not comparative GPU scores |
| [Matrix runs](https://www.localmaxxing.com/en/inference-benchmarks) | Prefill/decode across context lengths and concurrency | Compare matching cells, not separate peak values |
| [Benchmarks](https://www.localmaxxing.com/en/benchmarks) | Task-quality leads | Read suite, sample count, attempts, harness and verifier separately from speed |
| [API docs](https://www.localmaxxing.com/en/api-docs) | Public read queries and current filter definitions | `verified` filters user verification, not independent replication |
| [CLI source](https://github.com/LottoLottoLotto/localmaxxing-cli) | Inspect measurement implementation and artifact format | Reading is sufficient for research; installation, inference and submission are separate actions |

Public read routes documented as of November 1, 2026: `/api/speed-tests`,
`/api/leaderboard`, `/api/models` under `https://www.localmaxxing.com`.
Speed tests support exact `gpuName`, `hfId`, `dateFrom`, `dateTo`, `limit` and
`offset`; leaderboard filters differ. Read live docs before use and inspect
returned configurations. Never assume an undocumented query parameter worked.
Keep queries small and retain the original report/run URL in the evidence record.
Use the browser if a JS table is empty in a text fetch; report access gaps if
neither UI nor API is readable. No account or submission is needed to research.

## Additional benchmark portals

Primary pages and methodology inspected November 1, 2026. These complement
LocalMaxxing and LIL; availability and coverage must be checked at research time.
Read [the portal checklists](research-guide.md#additional-benchmark-portals) for
retrieval guidance. A signature or upload approval does not establish quality.

| Source | Use | Boundary |
| --- | --- | --- |
| [llm-speed open data](https://llm-speed.com/data) / [methodology](https://llm-speed.com/methodology) | Versioned CSV/JSON, source-run links, workloads, runtime settings and provenance | Separate site-measured and community runs; canned agent traces measure timing, not agent task success |
| [llamaBench](https://llamabench.ai/) / [methodology](https://llamabench.ai/methodology) | Exact model-file hashes, runtime/configuration details and reproduction evidence | Distinguish hash checks, speed verification and limited behavior evaluations; hosted intelligence scores do not grade local quants |
| [LocalScore](https://www.localscore.ai/) / [methodology](https://www.localscore.ai/about) | Standardized prompt/generation/TTFT hardware baselines and public run details | Llamafile-based suite and limited model coverage; composite score is not task quality or a modern serving-stack qualification |
| [ComputeArena](https://computearena.ai/) | Model/quant/runtime/chip comparisons with explicit PP512/TG128 workloads | Small contributor pool and substantial BaseRT coverage; compare actual matching samples |
| [oMLX performance](https://omlx.ai/benchmarks/performance) / [quality](https://omlx.ai/benchmarks/intelligence) | Apple Silicon chip/RAM/context comparisons and separately recorded evaluation results | Runtime-specific; quality rows may be partial suites and include acceleration/settings differences |
| [Anubis leaderboard](https://devpadapp.com/leaderboard.html) / [methodology](https://uncsoft.github.io/anubis-oss/methodology.html) / [explorer](https://devpadapp.com/explorer.html) | Apple Silicon performance, power, memory and latency across backends | Live rows required browser rendering in the initial review; methodology versions changed token and energy accounting |

## Local Inference Lab: community benchmark portal

| Source | Use | Boundary |
| --- | --- | --- |
| [Benchmark runs](https://docker.local-inference-lab.ai/bench/runs) | Filter and compare public lil-bench uploads by hardware/model/topology | All-runs inventory includes modified, incomplete or unknown-build evidence |
| [JSON database](https://docker.local-inference-lab.ai/api/bench/runs) | Structured source linked from the run list | Inspect current schema; preserve missing fields and run IDs; avoid dumping the full database into context |
| [Configurator](https://docker.local-inference-lab.ai/) | Relate a selected model/build/preset to lab and community measurements | Changing defaults, lab results and filtered community aggregates are separate authorities |

Read [the LIL checklist](research-guide.md#local-inference-lab-benchmark-runs-and-configurator).
Run-list, JSON and run-detail links were checked November 1, 2026. The run table
labels decode C1/C8/C16 at empty context separately from Prefill 32K. Retain card
edition, power, TP versus physical count, PCIe link/topology, image/build,
speculation and context shards. The configurator's summary can apply stricter
inclusion rules than the public inventory; read its current methodology.

This performance portal complements the **Aiderboard** below; it does not replace
quality evaluation. No benchmark execution, upload or deployment is part of reading it.

See [Practitioner repository review](practitioner-repositories.md) for the
October 14, 2026 survey of all 14 discussed accounts, useful implementation and
benchmark sources, attribution gaps, and hardware/version caveats. It is a dated
research snapshot; refresh relevant revisions before reusing its conclusions.

## Local Inference Lab: daily summaries and RTX field wiki

| Source | Use | Boundary |
| --- | --- | --- |
| [Daily summaries](https://github.com/local-inference-lab/rtx6kpro/tree/master/daily-summaries) | Recent community experiments, fixes and failures; follow original-message links | Automated summaries, not independent measurements |
| [RTX PRO wiki](https://github.com/local-inference-lab/rtx6kpro) | Hardware notes, recipes and benchmark artifacts | Check date, card variant and exact topology |
| [Blackwell images](https://github.com/local-inference-lab/blackwell-llm-docker) | Releases, build inputs, configurator and image changes | Beta tags move; configuration generation is not validation |
| [vLLM fork](https://github.com/local-inference-lab/vllm) / [FlashInfer fork](https://github.com/local-inference-lab/flashinfer) | Trace a reported fix into code and its image | Fork support does not imply upstream release support |
| [Hugging Face models](https://huggingface.co/local-inference-lab) | Quant lineage, precision, loader requirements and validation caveats | Inspect pinned revision and current card separately |
| [Inference benchmark](https://github.com/local-inference-lab/llm-inference-bench) | Definitions and raw throughput-run methodology | Check shared prefixes, warmup, accepted tokens and concurrency |
| [Aiderboard](https://evals.local-inference-lab.ai/aider) | Quant-level editing outcomes and per-run details | Retry scores are not first-pass or repository-agent success |

GitHub access patterns, replacing placeholders with the selected month/date and
the repository's verified default branch:

```text
https://api.github.com/repos/local-inference-lab/rtx6kpro
https://api.github.com/repos/local-inference-lab/rtx6kpro/contents/daily-summaries/YYYY-MM?ref=BRANCH
https://raw.githubusercontent.com/local-inference-lab/rtx6kpro/BRANCH/daily-summaries/YYYY-MM/YYYY-MM-DD.md
```

Use the connected GitHub tool, web browser, or bounded HTTP reads as available.
List files before fetching; include the previous month when the window crosses
a boundary. If the API is limited, use the public tree/raw pages rather than
claiming there are no new summaries. Retain a commit permalink when reproducibility
matters. Strip navigation/markup if helpful; preserve facts, dates and source links.

## Other field wikis, benchmark worklogs and recipe collections

Repository metadata and README coverage checked October 14, 2026. These are
complementary sources; not all publish daily digests. Hardware boundaries below
describe inspected reports, not every configuration the project might support.

| Repository | Why read it | Relevance and limits |
| --- | --- | --- |
| [ambientlight/rtx-pro-6000-bench](https://github.com/ambientlight/rtx-pro-6000-bench) | Real coding-agent traffic, cache/latency/error accounting, pinned serving comparisons, SWE-bench results | Strong Max-Q lead; reported host has four cards at 300 W and 512 GB RAM. Request success is distinct from task correctness |
| [loswald/rtxpro6000-bench](https://github.com/loswald/rtxpro6000-bench) | SM120 kernel selection, agent-shaped workloads, quality checks, failed configurations and reproducible scripts | Four Server Edition 600 W GPUs and eight 5090s; September campaign, not a two-Max-Q performance prediction. Treat its general rules as claims bounded by tested builds |
| [gisenberg/local-model-eval](https://github.com/gisenberg/local-model-eval) | Single-PRO-6000 evaluation, task outcomes and serving controls | Useful one-card comparison source already in the practitioner list; inspect individual run dates, power and scoring methodology |
| [ressl/llm-inference-recipes](https://github.com/ressl/llm-inference-recipes) | Exact model/runtime revisions, topology, cache capacity tests, native vision and documented speculation rollback | Inspected recipe uses six PRO 6000s; useful methodology and fixes, not evidence of two-card feasibility |
| [cloudrift-ai/emmy](https://github.com/cloudrift-ai/emmy) | Benchmark/deployment recipes and compiler/kernel experiments | Formerly `cloudrift-ai/server-benchmark`; follow canonical redirects and locate dated raw results. Compiler microbenchmarks and cloud runs need separate applicability checks |
| [PixelML/club-dgx-spark](https://github.com/PixelML/club-dgx-spark) | Community field guide indexing model-family experiments, diagnostics, benchmarks and failures | Close in format to the RTX wiki, but GB10/SM121 unified memory. Follow original authors and avoid counting reused results as independent reproductions |
| [eugr/spark-vllm-docker](https://github.com/eugr/spark-vllm-docker) | Single/multi-Spark recipes, image changes, loading/caching fixes and networking documentation | Maintained implementation source; Spark-specific settings are not RTX defaults; pin images rather than trusting `latest` |
| [NVIDIA/dgx-spark-playbooks](https://github.com/NVIDIA/dgx-spark-playbooks) | Official practical guides for inference, agents, quantization, multimodal work and multi-node setups | Vendor implementation reference; distinguish Spark, Station and other playbooks, and verify independent performance evidence |
| [marksunner/dgx-spark](https://github.com/marksunner/dgx-spark) | Detailed workshop notes, engine investigations, failures and links to raw artifacts | Historical/adjacent-platform reading; latest observed push was July 13, 2026. Some research is explicitly paused or superseded |

For RTX questions, prioritize the RTX worklogs before Spark collections. Read
Spark sources for mechanisms, new models and linked upstream fixes, keeping their
performance and memory numbers attached to Spark. For new repository discovery,
search both GitHub and the web, then follow credits, linked reproductions and
issue discussions one hop outward; avoid an unbounded list of forks.

```text
site:github.com "RTX PRO 6000" "benchmarks" "recipes"
site:github.com "Max-Q" "real traffic"
site:github.com "SM120" "quality" "failures"
site:github.com "local inference" "wiki"
site:github.com "DGX Spark" "community" "benchmarks"
```

A repository push date is an activity hint, not a measurement date. Read the
relevant result's history, check whether archived recipes were superseded, and
prefer canonical GitHub pages over third-party mirrors in search results.

## Official artifacts and runtime implementations

- Model publishers: [Qwen](https://huggingface.co/Qwen),
  [DeepSeek](https://huggingface.co/deepseek-ai), [Z.ai](https://huggingface.co/zai-org),
  [Xiaomi MiMo](https://huggingface.co/XiaomiMiMo),
  [MiniMax](https://huggingface.co/MiniMaxAI), [NVIDIA](https://huggingface.co/nvidia),
  [LiquidAI](https://huggingface.co/LiquidAI). Start from official cards and linked
  release posts; inspect the exact derivative/quant separately.
- General runtimes: [vLLM](https://github.com/vllm-project/vllm),
  [SGLang](https://github.com/sgl-project/sglang),
  [llama.cpp](https://github.com/ggml-org/llama.cpp),
  [ExLlamaV3](https://github.com/turboderp-org/exllamav3),
  [MLX LM](https://github.com/ml-explore/mlx-lm).
- Specialized runtime: [gpillon/ignis](https://github.com/gpillon/ignis), a
  Rust/CUDA engine for Qwen3.8 and single-card Blackwell agent workloads.
  Read its [releases](https://github.com/gpillon/ignis/releases), exact-version
  API contracts, and raw benchmark evidence; separate RTX 5090 measurements
  from PRO 6000 Max-Q results and GPU expert caching from host-RAM residency.
  Follow [Ignis #327](https://github.com/gpillon/ignis/issues/327)
  for admission/retry behavior, health probes, and recipe corrections;
  [#287](https://github.com/gpillon/ignis/issues/287) tracks structured output.
  Recheck issue and release state at research time. Maintainer explanations
  and shipped fixes do not establish local requalification.
- Hardware-specific practitioner work:
  [ormandj GLM SM120](https://github.com/ormandj/sglang-glm53-flash-sm120),
  [SSHdotCodes MiMo PRO6000](https://github.com/SSHdotCodes/mimo-v2.6-flash-pro6000),
  [lukaLLM DSpark worklog](https://github.com/lukaLLM/deepseek-v4-flash-dspark-rtx6000pro),
  [gisenberg local-model-eval](https://github.com/gisenberg/local-model-eval).
  Prefer exact configurations, failed trials, raw tasks and corrections; these
  projects are discovery leads, not universal winners or guaranteed current support.
- Quantization: [NVIDIA Model Optimizer](https://github.com/NVIDIA/Model-Optimizer),
  [llm-compressor](https://github.com/vllm-project/llm-compressor),
  [Unsloth](https://github.com/unslothai/unsloth),
  [Intel AutoRound](https://github.com/intel/auto-round).
- Kernels and hardware contracts: [FlashInfer](https://github.com/flashinfer-ai/flashinfer),
  [CUTLASS](https://github.com/NVIDIA/cutlass),
  [CUDA documentation](https://docs.nvidia.com/cuda/),
  [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM).
  Match compute capability, build, tensor geometry, dtype and runtime use.

## Independent evaluation and community discovery

- [Artificial Analysis](https://artificialanalysis.ai/) and its
  [model comparisons](https://artificialanalysis.ai/models),
  [intelligence methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking),
  and [capability-index methodology](https://artificialanalysis.ai/methodology/capability-indices):
  priority source for model capability, task-specific evaluations, reasoning/token
  cost and hosted performance context. Follow the
  [Artificial Analysis checklist](research-guide.md#artificial-analysis).
  Record exact model/reasoning variant, index version, provider and observation
  date; hosted scores and speed do not establish the local quant's quality or speed.
- [SWE-bench](https://www.swebench.com/),
  [Terminal-Bench](https://github.com/harbor-framework/terminal-bench),
  [Aider](https://aider.chat/docs/leaderboards/),
  [LiveCodeBench](https://github.com/LiveCodeBench/LiveCodeBench): inspect split,
  agent, retries, budgets, dates, tests and failure denominators.
- [r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/),
  [r/LocalLLM](https://www.reddit.com/r/LocalLLM/), X author posts, and Discord
  originals linked from LIL: discover firsthand reports and contrary follow-ups.
  Prefer authors publishing artifacts and corrections over engagement metrics.
- [arXiv](https://arxiv.org/) and authors' linked code: mechanism and harness
  research. Preserve paper version, evaluation scope, supporting relationships
  and conflicts. A paper's result is not a local reproduction.

## X practitioners: Blackwell and DGX Spark

Original posts inspected through Chrome on October 14, 2026 (local date).
Dates below are the dates displayed by X. These are source-reported experiments,
not locally reproduced measurements or permanent endorsements.

| Person and original post | What makes them useful | Boundary |
| --- | --- | --- |
| [Reuben Stern / @ReubenConducts](https://x.com/ReubenConducts/status/2086837331219149183), Aug 10 | Colfax researcher sharing an original walkthrough on optimizing NVFP4 blockscaled GEMM specifically for RTX PRO 6000 SM120 | Kernel-level evidence; inspect full article and code, workload geometry and power before applying to end-to-end Max-Q serving |
| [Thien Tran / @gaunernst](https://x.com/gaunernst), checked Oct 14 | Publishes SM120 quantization work, including Qwen MXFP6 with a linked gau-nernst/vllm sm120-mxfp6 patch branch, plus CuTe DSL and torch.compile bug reports | Inspected quant work targets RTX 5090, with quality described as limited testing; shared SM120 does not equate memory capacity, power or whole-model performance |
| [Elliot Arledge / @elliotarledge](https://x.com/elliotarledge/status/2098577337407484408), Sep 11 | RTX PRO 6000 KernelBench-CUDA measurements, CUDA education, kernel source/transcript links and explicit roofline interpretation | Kernel synthesis benchmark results are not a full inference-engine speedup; profile reports four cards, not a TP2 Max-Q comparison |
| [Rico / @DevRico003](https://x.com/DevRico003/status/2108176596695962050), Oct 8 | Builds a four-Spark cluster and his own DSH agent harness; shares model configurations and actual agent-session observations with linked recipes | Explicitly says his one-to-four-node chart uses different workloads, not a head-to-head scaling benchmark; distinguish his implementation work from reused Mia recipes |
| [Ash Hart / @ashxhart](https://x.com/ashxhart), profile checked Oct 14 | TensorFold builder; profile links tensorfold.dev and github.com/ashhart. Direct implementation source for inference-engine changes, quant integration and experimental adaptation | Author claims need independent tests and pinned code; experimental announcements are not evidence of correctness or production readiness |
| [Brandon Music / @BrandonMusicKy](https://x.com/BrandonMusicKy/status/2107619278190993831), Oct 6 | Priority LIL contributor source: links the b12x integration into FlashInfer and ongoing LIL fork work. Also reports real GLM serving workloads and [TP5 RTX PRO 6000 experiments with corrections](https://x.com/BrandonMusicKy/status/2106958690058436959) | Profile identifies LIL affiliation, so this is a contributor report, not independent confirmation. Trace linked commits into actual released images; TP5 results do not predict TP2 Max-Q performance |
| [0xSero](https://x.com/0xSero/status/2110496681049661748), Oct 14 | Firsthand homelab workload reports involving four Sparks, four cards described as 6000s and two Intel systems; [NVMe-offload experiment](https://x.com/0xSero/status/2110495065751826628) explores running Qwen EXL3 with limited memory | Hardware edition is unspecified in the inspected homelab post. Security outcomes and offload speeds are self-reported; the inspected offload thread lacks a reproducible topology/recipe and long-context measurements |
| [Mia / @MiaAI_lab](https://x.com/MiaAI_lab/status/2110477955923313060), Oct 14 | Priority practitioner source for TensorFold recipes and engine-aware quantization (EAQ); reports coding/tool tests on Spark and RTX 5090 and 32k/128k context checks; credits access to an RTX PRO 6000 | EAQ v1 was still undergoing final tests, with release expected in coming days. Compressed embeddings require TensorFold. Lower KL is not proof of better agent outcomes; access to a PRO 6000 is not a published Max-Q result |
| [Rising Sun / @BizTripper](https://x.com/BizTripper/status/2110524979888669132), Oct 14 | Tests two RTX PRO 6000 Blackwell Server Edition 96 GB cards without NVLink; specifies Strata version, Qwen NVFP4, context and benchmark settings | Evaluation machine, dual Xeon and 504 GB RAM; different from Max-Q. Posted throughput does not clearly establish aggregate versus per-client accounting |
| [Anders / @andersjw_](https://x.com/andersjw_/status/2110591923530723367), Oct 14 | Two-Spark inference and Hermes experiments; reports a 32-question ColGrep A/B test with no measurable token saving and links code | Harness experiment uses Claude Opus; hosting the auxiliary model on Spark does not make this an all-local agent result |
| [Sudo su / @sudoingX](https://x.com/sudoingX/status/2110588980546937228), Oct 14 | Publishes dual-Spark DeepSeek-V4.1-Flash EXL3 recipe and weight links | Linked repository title: sudoingX/dgx-spark-deepseek-v41. Inspect code and model card before use; a headline speed claim is not an independent reproduction |
| [Joey / @aijoey](https://x.com/aijoey/status/2106779652689674557), Oct 4 | Spark Doctor diagnostics: fixes incomplete scans, adds OOM/Xid checks, corrects false low-power alerts during memory-bound decode; links joeynyc/spark-doctor | Maintainer release report, not a validation of every diagnostic rule |
| [Yume_X / @yume_arasaki](https://x.com/yume_arasaki/status/2106837882870886438), Oct 4 | Reports three own-Spark TensorFold recipe tests, long-context measurements, and community quality/stability caveats | Mixed firsthand and collected evidence. Separate the author's runs from quoted authors; verify exactness and speed claims against pinned code and independent quality tests |
| [THK / @techowknow](https://x.com/techowknow/status/2110600259995054215), Oct 14 | Tests clock limits on two ThinkStation PGX units; reports reduced performance at 2200 versus 2400 MHz and explicitly limits generalization across OEMs | Japanese-language, personal hardware report; neither a universal Spark clock recommendation nor an RTX tuning result |

For X discovery, use the user's requested browser and its search UI. Start with
the requested date window, inspect Latest as well as Top, and open original posts
including replies/corrections. Example queries:

```text
"DGX Spark" since:YYYY-MM-DD
("RTX PRO 6000" OR "6000 Blackwell") (benchmark OR inference OR tokens) since:YYYY-MM-DD
from:AUTHOR (recipe OR benchmark OR regression) since:YYYY-MM-DD
```

Follow credits and linked repositories one hop to find practitioners. Prefer
reproducible configurations, negative results and corrections; distinguish authors,
maintainers, independent reproductions and reposts. Expand truncated posts before
using their claims. Record original post and artifact URLs, date, hardware and
evidence limits. Reading recommendations do not imply following accounts or posting.

## Targeted search templates

Replace brackets with public model/hardware names and an explicit date window.
Do not send private host names, paths, topology or account identifiers to search.

```text
site:github.com/local-inference-lab/rtx6kpro "daily-summaries" "[YYYY-MM]"
"[model]" "RTX PRO 6000" "Max-Q" "TP2"
"[model or image revision]" regression recall tool calling
site:huggingface.co/[publisher] "[model]" "[quant]"
site:github.com/[owner]/[runtime] "[model]" "[error or fix]"
site:reddit.com/r/LocalLLaMA "[model]" "96GB" after:[YYYY-MM-DD]
site:x.com "[model]" "300W" after:[YYYY-MM-DD]
"[model]" "[Pi or Hermes or OpenClaw]" reasoning parser cache
```

Search-engine date filters are discovery aids; verify dates on originals. Broaden
queries if punctuation, abbreviations or sparse indexing hide results. For a
small-model request, search TP1 and single-card reports explicitly; for a two-GPU
request, do not let four-GPU leaderboards dominate. Stop when the leading claims
are attributable, material contradictions are understood or disclosed, and each
recommendation has a clear relevance/uncertainty judgment.
