---
name: windows-gpu-lane-hygiene
description: Diagnose and clear an NVIDIA compute lane shared by Windows, WDDM, WSL2, Docker Desktop, CUDA, and desktop applications. Use when GPU memory differs between Windows and Linux views, a supposedly idle GPU is occupied, applications should use an iGPU, a benchmark needs exclusive dGPU capacity, or a user asks what is using an NVIDIA GPU.
---

# Windows GPU Lane Hygiene

Establish who owns GPU memory before changing graphics policy or terminating
anything. Treat Windows and WSL as views of one physical device, not separate
capacity pools.

Read [windows-gpu-memory-semantics.md](references/windows-gpu-memory-semantics.md)
before attributing an unexplained memory difference.

## Workflow

1. Define the lane contract.

   Record the exact GPU identity, the desired idle headroom, whether the machine
   must retain a display workload, and which benchmark or application will own
   the lane. Do not equate `0% utilization` with `0 MiB allocated`.

2. Capture both host views.

   On Windows, query GPU identity, memory, utilization, compute applications,
   and active graphics processes. In WSL, run the equivalent `nvidia-smi`
   queries from the same distro and record Docker/WSL state. Preserve timestamps
   and units. Do not dump full command lines, environment blocks, or user data.

3. Classify every allocation.

   Separate managed CUDA processes, graphics/WDDM clients, driver or display
   reservations, WSL/Docker virtualization overhead, and unattributed memory.
   Correlate exact PIDs to executable names using read-only OS inspection.
   Absence from the CUDA process table does not prove the allocation is free.

4. Trace process ancestry and launch ownership.

   Determine whether an allocation belongs to a Windows app, WSL process,
   Docker container, background service, browser, overlay, capture tool, or the
   desktop compositor. Inspect managed container status and logs through the
   owning product before using raw Docker inspection.

5. Choose the narrowest remedy.

   Prefer closing an optional application, changing that application's Windows
   per-app graphics preference, or stopping the exact managed workload. Do not
   disable a GPU, change global graphics policy, restart Docker/WSL, terminate a
   process, or alter firmware settings without an explicit human gate and an
   exact rollback plan. A per-app iGPU preference is advisory unless a
   post-change measurement proves placement.

6. Verify the clean baseline.

   Re-run the same Windows and WSL queries after the remedy. Require memory and
   process state to stabilize across at least two samples. Report residual
   reservation separately from active compute allocation.

7. Prove test ownership and cleanup.

   Start only the intended test, show that its PID/container receives the
   expected allocation, run the test, stop it through its managed lifecycle,
   and demonstrate return to the recorded baseline.

## Evidence packet

Return GPU identity, Windows and WSL timestamps, memory by class, attributed
processes, residual unattributed memory, actions taken, human gates, baseline
stability, test peak, and cleanup result. Use `clean`, `clean_with_reservation`,
`occupied`, or `unresolved` as the lane result.

Never claim a clean lane from Task Manager percentage alone, and never expose
credentials or private command-line arguments while identifying processes.
