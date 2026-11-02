# Practitioner repository review

Reviewed October 14, 2026 (America/Los_Angeles). Scope: all 14 principal accounts
discussed, plus two peripheral accounts below. This is a targeted review of
relevant repositories, READMEs and selected code/results, not an exhaustive audit
of every repository owned by each person. No remote code was executed and no
local performance was measured. Source claims remain external evidence.

Relevance lens: discrete-GPU local serving, power-limited Blackwell hardware,
and agent-harness development. Hardware configurations below describe external
reports, not a reader's deployment. Establish the reader's actual hardware,
workload and runtime before proposing a test.

## Full account coverage

| Account | Repositories reviewed | Useful information and boundary |
| --- | --- | --- |
| Reuben Stern / @ReubenConducts | [Colfax article source](https://github.com/ColfaxResearch/cfx-article-src/tree/master/sm120_nvfp4_gemms) | SM120 NVFP4 GEMM progression, shape-specific configurations and reference-checked benchmark scripts. Organizational article code, not a personal repo. Server Edition microbenchmarks do not establish Max-Q application gains. |
| Thien Tran / @gaunernst | [gn-kernels](https://github.com/gau-nernst/gn-kernels), [learn-cuda](https://github.com/gau-nernst/learn-cuda), [MXFP6 vLLM branch](https://github.com/gau-nernst/vllm/tree/sm120-mxfp6) | Direct SM120 CuTe DSL matmul, gated NVFP4 GEMM, profiling/learning examples. PRO 6000 benchmark table is 600 W. The MXFP6 branch exists, but its code and quality were not fully audited here. |
| Elliot Arledge / @elliotarledge | [kernelbench.com](https://github.com/Infatoshi/kernelbench.com), [nvfp4-sm120](https://github.com/Infatoshi/nvfp4-sm120), [cuda-oxide fork](https://github.com/Infatoshi/cuda-oxide) | Kernel evaluation specifications and a small-model NVFP4 training prototype. Current benchmark monorepo is more useful than archived KernelBench-Hard/v3 repos. cuda-oxide is a fork; GitHub identifies NVIDIA/cuda-rust as parent. Training and B200 Rust examples are not inference evidence for SM120. |
| Ash Hart / @ashxhart | [TensorFold](https://github.com/ashhart/TensorFold) | Native engine, API dialects, cache and capability surfaces. Current 1.0.11 has an explicit model/platform qualification matrix; do not import support claims from older Python recipes. |
| Anders / @andersjw_ | [dgx-colgrep](https://github.com/ajensenwaud/dgx-colgrep) | Valuable negative retrieval result, environment pins, raw JSONL, generated reports and benchmark leakage precautions. Auxiliary model runs on Spark; main agent experiment uses Claude Opus in Hermes. |
| Mia / @MiaAI_lab | [Qwen 27B RTX recipe](https://github.com/MiaAI-Lab/Qwen3.8-27B-RTX-6000-PRO-SGLang-DSpark), [GLM dual-Spark TensorFold recipe](https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks-TensorFold) | Concrete model/parser/KV/draft configuration and patched-engine lineage. Qwen repo name still says DSpark but its README now specifies DFlash 2. GLM kit is TensorFold 0.6.0 plus 96 patches, on GB10/RoCE, not current native main. Read relevant sections of the large GLM README, not every patch. No separate released EAQ repository verified. |
| Sudo su / @sudoingX | [dgx-spark-deepseek-v41](https://github.com/sudoingX/dgx-spark-deepseek-v41) | Pinned vLLM/ExLlama versions, ordered patches, sensitivity-based precision choices, Engram/page-cache behavior and rejected experiments in FINDINGS.md. GB10/SM121, unified memory and RDMA impose different constraints from discrete SM120. |
| Joey / @aijoey | [spark-doctor](https://github.com/joeynyc/spark-doctor), [hermes-hudui](https://github.com/joeynyc/hermes-hudui) | Diagnostic rule design, OOM/Xid handling and session replay/redacted exports. Spark memory/clock rules need adaptation. HUD compatibility is version-specific; local hashes/signatures are not independent attestation. |
| Rico / @DevRico003 | [dsh-verifier-gate](https://github.com/DevRico003/dsh-verifier-gate) | Finished-turn assessment and repair-loop design. README and src/gate.ts show timeouts or zero scored criteria close turns unverified. Default same-model scoring is not an independent Anvil acceptance gate. |
| @0xSero | [harness-bridge](https://github.com/0xSero/harness-bridge), [glm-5.2-sm120](https://github.com/0xSero/glm-5.2-sm120) | Harness/endpoint/dialect integration and historical SM120 troubleshooting. Bridge launch defaults bypass approvals/sandbox; inspect its explicit safe mode. Old GLM recipe needs four 96 GB cards and cannot be treated as a two-card fit. |
| Brandon Music / @BrandonMusicKy | [sm120-kernels](https://github.com/brandonmmusic-max/sm120-kernels) | Closest power-matched tuning lead: four cards, including two Max-Q, all at 300 W, on Threadripper. CUTLASS shared-memory constraints, attention/register tuning, P2P and speculation investigations. Older Qwen3.5 campaign, different host and TP4. Contributor attribution also appears in TensorFold credits. |
| Yume_X / @yume_arasaki | [yume_benchmarks](https://github.com/yume-arasaki/yume_benchmarks) | Dated experiments, failed attempts and explicit metric corrections; especially the October 14 DeepSeek report. Reports identify artifacts, but this pass did not retrieve and independently recompute every raw run. Spark performance is not a Max-Q prediction. |
| THK / @techowknow | No personally attributable GitHub repository verified | Keep the original PGX clock experiment as a social-source lead. Search results containing other people's repos are not ownership evidence. This is an attribution gap, not a claim that no repo exists. |
| Rising Sun / @BizTripper | No personally attributable GitHub repository verified | Useful two-PRO-6000 Server Edition observations on X. A Strata benchmark or reposted repository does not establish authorship. Do not invent a GitHub mapping. |

## Highest-value findings

### 1. SM120 profiling and kernel education: Reuben, Thien, Brandon

[Colfax's article](https://research.colfax-intl.com/optimizing-an-nvfp4-blockscaled-gemm-on-rtx-pro-6000-blackwell-gpu-sm120/)
and `sm120_nvfp4_gemms/bench_common.sh` expose tile, pipeline, swizzle and register
choices. The script uses warmups, cold-L2 timing and reference PASS checks, and
warns about another GPU process. Those are useful controls; square GEMMs alone
do not represent MoE decode shapes or an agent workload.

Thien's `gn-kernels` explicitly distinguishes SM100 `tcgen05` from SM120
`mma.sync` implementations. Its SM120 non-causal attention is not a complete
paged inference attention stack. Start with these examples for engine learning
after identifying an application bottleneck.

Brandon's [eager-mode analysis](https://github.com/brandonmmusic-max/sm120-kernels/blob/master/results/enforce_eager_analysis.md)
reports a large decode regression but simultaneously changes graph mode, KV
precision, MTP count and all-reduce patches. Treat the magnitude and causal
explanation as hypotheses requiring a controlled ablation. His P2P findings and
0xSero's blanket P2P-disable recipe are topology-specific opposing leads, not
universal NCCL advice. A potential local test should change one factor at a time
and record actual PCIe/P2P behavior, power and application time.

### 2. Mia is a recipe source; the headline needs verification

The Qwen 27B repository's performance table says "measured" and lists 240+
tokens/s, but its footnote says it applies drafter-card ratios to the memory
budget and asks for remeasurement. Classify that number as extrapolated, not a
verified local run. The recipe also needs a DFlash 2 backport overlay because its
named SGLang image predates that support. Preserve image, overlay and model
revision together; a tag by itself is insufficient reproduction evidence.

This is a useful single-card candidate lead. Actual memory residency, vision,
tools, long context, draft parity and end-to-end task time still need local
qualification before it can compete with an incumbent.

### 3. TensorFold's current qualification is narrower than its surrounding ecosystem

The inspected 1.0.11 README admits Nemotron 3.5 Lightning in MLX affine 4-bit on
RTX PRO 6000. Its listed GLM combinations are on two M5 Ultras. Therefore Mia's
older patched dual-Spark GLM deployment does not demonstrate GLM support on the
current native CUDA engine or on two Max-Q cards.

The experimental Living Weights feature rewrites checkpoint files and documents
no undo. It must not be conflated with prefix caching, KV restoration or an
external memory bank. Runtime capability reporting and explicit qualification
matrices are the more immediately reusable design ideas.

### 4. Yume and Anders improve how we evaluate claims

Yume's [October 14 report](https://github.com/yume-arasaki/yume_benchmarks/blob/main/reports/2026-10-14-dsv41-sudoingx-dual-spark.md)
retires inflated rates caused by buffered SSE, missing reasoning fields and
tool-only turns. Even all-delta timing missed work before the first and after
the last streamed chunk. Use full request/task wall time, accepted token counts
and separately labelled decode estimates; keep supersession records rather than
quietly overwriting results. A TTFT-subtracted wall-companion estimate is still
not the same metric as full-turn throughput.

Anders reports no measurable ColGrep token reduction in Hermes/Opus: the
32-question comparison is −3.1%, with a 95% interval spanning −11.7% to +6.5%.
His small coding-task experiments cannot establish a general effect either.
Useful practices are frozen tasks, hidden future commits, environment pins,
per-call accounting and regenerating reports from raw runs. Benchmark the actual
harness before adding a retrieval model or assuming vendor savings transfer.

### 5. Harness ideas worth reading before borrowing

Rico's [gate implementation](https://github.com/DevRico003/dsh-verifier-gate/blob/main/src/gate.ts)
returns when assessment times out or no criteria are scored. This is useful
advisory feedback design, but neither that behavior nor same-model judging meets
an independent release or model-promotion gate.

Sero's [launch defaults](https://github.com/0xSero/harness-bridge/blob/main/packages/core/src/harnesses.ts)
include approval/sandbox bypass flags for Codex and Claude. Learn from its
protocol adaptation while preserving explicitly chosen providers and reviewing
the documented safe-mode path before any future use. No bridge was installed.

Joey's Spark Doctor corrects a useful diagnostic mistake: low power during
memory-bound decode is not automatically a fault. Require workload context and
repeated samples before declaring throttling. Its Spark-specific rules should
not be copied wholesale to discrete RTX cards.

## Additional accounts encountered

- **netrunner / @plotarmordev:** [omp-best-of](https://github.com/plotarmordev/omp-best-of)
  is a fork of [wolfiesch/omp-best-of](https://github.com/wolfiesch/omp-best-of).
  README describes isolated candidates, HEAD checks and opt-in application.
  Useful orchestration ideas, not demonstrated local task-quality gains.
- **gorilla / @gorilla0513:** [skanehira/archify](https://github.com/skanehira/archify)
  is a fork of [tt-a1i/archify](https://github.com/tt-a1i/archify). This is code
  visualization, lower priority for hardware optimization. Do not attribute its
  upstream implementation to the fork owner without inspecting their changes.

For Rust/CUDA learning, Elliot's cuda-oxide fork is dated May 2026 and GitHub now
identifies [NVIDIA/cuda-rust](https://github.com/NVIDIA/cuda-rust) as its parent.
Refresh the canonical project rather than treating old fork documentation or
B200-only examples as current SM120 support.

## Refresh and next experiment

Read the exact source and result history before reuse; a repository push time
does not date the experiment. Default-branch heads inspected here place Brandon's
top commit in April, Mia's Qwen recipe in August, Thien's kernels on October 11,
and TensorFold/Yume/Anders on October 14. These are different age classes.

The smallest useful follow-up is a bounded profile of representative local agent
turns, with prompt/cache/context/concurrency held fixed, to determine whether
decode compute, host dispatch, communication or prefill dominates. Then choose
one pinned kernel/runtime setting or a single-card recipe for a controlled
comparison, preserving task correctness and rollback. This review authorizes no
load test, launch, download, configuration change or promotion.
