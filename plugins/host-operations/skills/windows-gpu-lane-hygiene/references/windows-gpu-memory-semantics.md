# Windows GPU memory semantics

Use multiple counters because no single Windows, WSL, or NVIDIA view explains
every allocation.

| Observation | What it establishes | What it does not establish |
|---|---|---|
| CUDA process with PID and memory | A managed compute context is attributable | Total WDDM or driver reservation |
| Dedicated GPU memory in Windows | Windows accounts memory to a process or engine | That the process is actively computing |
| WSL `nvidia-smi` memory total | The paravirtualized NVIDIA view sees allocation | Exact ownership of every Windows graphics client |
| Low utilization with nonzero memory | Work may be idle while a context remains resident | That the lane is available for a peak allocation |
| Memory with no listed compute PID | Reservation or non-compute ownership remains possible | A leak, by itself |

Use this attribution order:

1. exact managed serve or container;
2. CUDA/compute PID;
3. Windows graphics PID or service;
4. WSL/Docker virtualization state;
5. display/driver reservation;
6. unresolved.

For an exclusive test, report two numbers: reclaimable active allocation and
non-reclaimable or intentionally retained reservation. Capacity planning should
use the measured available memory after the retained reservation, not the GPU's
marketing capacity.
