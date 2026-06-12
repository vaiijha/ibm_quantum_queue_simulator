# IBM Quantum Queue Logger — Cron Job Specification

> **For Cursor Agent** — Feed this document directly. All API references are verified against the latest
> `qiskit-ibm-runtime` and IBM Quantum REST API documentation as of June 2026.

***

## 1. Purpose & Scope

Build a configurable polling daemon (run as a cron job) that:

1. Collects **queue-behaviour telemetry** from every IBM Quantum backend accessible on the Open Plan.
2. Captures **two granularity levels**: device-level (no QPU cost) and job-level (small QPU cost).
3. Exposes a single `RUNS_PER_DAY` knob that automatically spreads poll ticks across 24 hours.

Output: one append-only NDJSON log file per run day, ready for downstream simulation/analysis.

***

## 2. Official IBM Documentation Links

Use these as primary references when implementing. All are confirmed live as of June 2026.

| Topic | URL |
|---|---|
| `IBMBackend` class (latest) | https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/ibm-backend |
| `BackendStatus` model (latest) | https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/models-backend-status |
| `BackendStatus` (v0.42, confirmed field list) | https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/0.42/models-backend-status |
| `QiskitRuntimeService.backends()` + `least_busy()` | https://qiskit.qotlabs.org/guides/get-qpu-information |
| `RuntimeJobV2` (latest job object) | https://qiskit.qotlabs.org/docs/api/qiskit-ibm-runtime/runtime-job-v2 |
| Monitor / cancel a job | https://qiskit.qotlabs.org/docs/guides/monitor-job |
| Qiskit Runtime REST API — Workloads | https://docs.quantum.ibm.com/api/runtime/tags/workloads |
| Quantum System REST API — Backends | https://quantum.cloud.ibm.com/docs/en/api/quantum-system-rest/tags/backends |
| IBM Quantum Plans overview | https://quantum.cloud.ibm.com/docs/en/guides/plans-overview |
| Initialize account (API key + CRN) | https://quantum.cloud.ibm.com/docs/guides/initialize-account |
| `QiskitRuntimeService.usage()` | https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/qiskit-runtime-service |
| Job submission rate limit (REST) | https://quantum.cloud.ibm.com/docs/en/api/qiskit-runtime-rest/tags/jobs |
| `QueueInfo` (legacy reference, pre-runtime era) | https://quantum.cloud.ibm.com/docs/en/api/qiskit/0.25/qiskit.providers.ibmq.job.QueueInfo |

***

## 3. API Status Confirmation (June 2026)

### 3.1 `backend.status()` → `BackendStatus` — ✅ Confirmed Present

The `IBMBackend.status()` method is present in the **latest** `qiskit-ibm-runtime`.
Official docs state verbatim:

> "The instance contains the `operational` and `pending_jobs` attributes, which state whether the backend
> is operational and also the number of jobs in the server queue for the backend."

**Fields confirmed in `BackendStatus`:**

| Field | Type | Description |
|---|---|---|
| `backend_name` | `str` | Name of the backend |
| `backend_version` | `str` | Version string `X.Y.Z` |
| `operational` | `bool` | `True` if backend is accepting and processing jobs |
| `pending_jobs` | `int` | **Queue depth** — jobs currently waiting |
| `status_msg` | `str` | Free-form message; value `"internal"` means accepting but not processing |

> ⚠️ **Caveat**: If `operational=True` but `status_msg="internal"`, the backend is paused internally.
> Log `status_msg` explicitly — do not infer from `operational` alone.

### 3.2 `QueueInfo` (per-job queue position) — ⚠️ Deprecated / Legacy Only

`QueueInfo` with `.position`, `.estimated_start_time`, `.estimated_complete_time`,
`.hub_priority`, `.group_priority`, `.project_priority` **was part of the legacy
`qiskit.providers.ibmq` (IBMQ) provider**, which has been fully superseded by
`qiskit_ibm_runtime`.

**The new `RuntimeJobV2` (current) does NOT expose a `.queue_info()` method.**

Instead, per-job queue data must be inferred from:
- `job.status()` — returns a string: `"INITIALIZING"`, `"QUEUED"`, `"RUNNING"`, `"DONE"`, `"ERROR"`, `"CANCELLED"`
- `job.creation_date` — UTC datetime when the job was created (maps to "entered queue" timestamp)
- Polling `job.status()` repeatedly until it transitions from `"QUEUED"` → `"RUNNING"` gives you
  **empirical wait time** without any queue position integer.
- `service.jobs()` with filters — lets you enumerate recent jobs to compute aggregate statistics.

> ✅ **Practical implication**: You **cannot** get a live queue position integer for your own jobs
> with the current `RuntimeJobV2` API. You must derive wait time from status transition timestamps.
> A Stack Overflow answer from Feb 2024 confirms: "there's no current ability to request an estimate
> of queue time from IBM." (https://stackoverflow.com/questions/77932318)

### 3.3 `service.least_busy()` — ✅ Confirmed Present

```python
service.least_busy(operational=True, min_num_qubits=5)
```

Returns the backend with the **lowest `pending_jobs`** matching the filter. Useful as a
derived signal for queue comparison.

### 3.4 Instance usage — ✅ Use `QiskitRuntimeService.usage()` (SDK)

The legacy REST endpoint `GET https://api.quantum-computing.ibm.com/runtime/usage` is **superseded**
on the current IBM Quantum Platform. Use the SDK method instead:

```python
usage = service.usage()
```

**Fields returned** (current platform, `qiskit-ibm-runtime` ≥ 0.42):

| Field | Type | Description |
|---|---|---|
| `usage_consumed_seconds` | `float` | QPU time consumed in the current period |
| `usage_limit_seconds` | `float` | Total quota (when instance uses limit-based billing) |
| `usage_allocation_seconds` | `float` | Total quota (when instance uses allocation-based billing) |
| `usage_remaining_seconds` | `float` | Computed remaining quota |
| `usage_limit_reached` | `bool` | `True` when no more QPU time is available |
| `usage_period` | `str` | Current billing/allocation period identifier |

> ⚠️ **`pending_jobs_instance` is no longer available** via `service.usage()` on the current platform.
> Per-backend `pending_jobs` from `backend.status()` remains the queue-depth signal.

**Authentication for usage calls**: same API key + instance CRN used for `QiskitRuntimeService` init
(see §3.5). No separate `requests` REST call is needed.

Docs: https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/qiskit-runtime-service

### 3.5 Authentication — ✅ API key + CRN (June 2026)

Current IBM Quantum Platform auth (replaces legacy `channel="ibm_quantum"` + `ibm-q/open/main`):

| Credential | Required? | Description |
|---|---|---|
| **API key** | **Yes** | 44-char key from [IBM Quantum dashboard](https://quantum.cloud.ibm.com/). Passed as `token=` to `QiskitRuntimeService`. This **is** the token — there is no separate `api_key` parameter. **Do not** use a bearer/session token (causes `401 Unauthorized`). |
| **Instance CRN** | **Strongly recommended** | Cloud Resource Name from Instances page. Passed as `instance=`. Without it, the SDK auto-selects an instance (extra API calls; may pick wrong plan). |
| **Channel** | Optional | Defaults to `ibm_quantum_platform` (replaces legacy `ibm_quantum` / `ibm_cloud`). |

**SDK-native env vars** (supported as fallbacks):

```dotenv
QISKIT_IBM_TOKEN=<API_KEY>
QISKIT_IBM_INSTANCE=<CRN>
QISKIT_IBM_CHANNEL=ibm_quantum_platform
```

**REST note** (only if calling REST directly): requires `Authorization: Bearer <API_KEY>` **and**
`Service-CRN: <CRN>` headers against `https://quantum.cloud.ibm.com/api/v1/...`. The logger
implementation uses the SDK only.

Docs: https://quantum.cloud.ibm.com/docs/guides/initialize-account

***

## 4. Data Collection Layers

### Layer 1 — Device-Level Poll (Zero QPU Cost)

Runs on every cron tick for all accessible backends.

**Method**: `QiskitRuntimeService.backends()` → iterate → `backend.status()`

**Fields to log per backend per tick:**

```jsonc
{
  "schema_version": "1.0",
  "event_type": "backend_status",
  "ts": "2026-06-12T08:00:00.123Z",           // ISO-8601 UTC timestamp at poll time
  "backend_name": "ibm_brisbane",
  "backend_version": "1.3.0",
  "num_qubits": 127,
  "operational": true,
  "pending_jobs": 43,
  "status_msg": "active",
  "processor_family": "Eagle",                 // from backend.configuration().processor_type["family"]
  "processor_revision": "r3",                 // from backend.configuration().processor_type["revision"]
  "simulator": false,
  "least_busy_rank": 2                         // rank among all online backends by pending_jobs (1=least)
}
```

**Also log instance-level usage via `service.usage()` on every tick:**

```jsonc
{
  "schema_version": "1.0",
  "event_type": "instance_usage",
  "ts": "2026-06-12T08:00:00.123Z",
  "instance": "crn:v1:bluemix:public:quantum-computing:us-east:a/...",
  "quota_seconds": 600,
  "usage_seconds": 42,
  "remaining_seconds": 558,
  "usage_limit_reached": false,
  "usage_period": "2026-06"
}
```

`instance` is the active CRN from `service.active_instance()`. `quota_seconds` maps from
`usage_limit_seconds` or `usage_allocation_seconds`; `usage_seconds` maps from `usage_consumed_seconds`.

### Layer 2 — Job-Level Probe (Small QPU Cost, Optional)

Fires a **minimal probe job** once per poll tick (or at a configurable sub-rate, e.g., 1 in every N
ticks) on the least-busy backend, then polls it to completion to record status transitions.

**Probe circuit**: 1-qubit circuit, 1 gate (Hadamard), 100–256 shots maximum.
This consumes approximately 0.5–2 seconds of QPU time per probe on current Eagle/Heron backends.
At 10 probes/day, total QPU consumption is ~5–20 seconds/day — far inside the 10 free minutes/28-day
window.

**Fields to log per job probe (one record per status-poll of the probe job):**

```jsonc
{
  "schema_version": "1.0",
  "event_type": "job_status_poll",
  "ts": "2026-06-12T08:01:05.000Z",           // time of THIS poll
  "job_id": "cvhm3k8q00j2w8sth2j0",
  "backend_name": "ibm_brisbane",
  "shots": 100,
  "num_qubits": 1,
  "job_creation_date": "2026-06-12T08:00:01.000Z",  // job.creation_date (UTC)
  "status": "QUEUED",                          // job.status() string
  "wall_seconds_since_creation": 64.0,         // float: (ts - job_creation_date).total_seconds()
  "is_terminal": false                         // true when status in {DONE, ERROR, CANCELLED}
}
```

When a job reaches a terminal status, emit a final summary record:

```jsonc
{
  "schema_version": "1.0",
  "event_type": "job_completed",
  "ts": "2026-06-12T08:04:22.000Z",
  "job_id": "cvhm3k8q00j2w8sth2j0",
  "backend_name": "ibm_brisbane",
  "shots": 100,
  "job_creation_date": "2026-06-12T08:00:01.000Z",
  "queued_at": "2026-06-12T08:00:01.000Z",    // first observed QUEUED timestamp
  "running_at": "2026-06-12T08:03:55.000Z",   // first observed RUNNING timestamp (or null)
  "completed_at": "2026-06-12T08:04:22.000Z", // terminal state timestamp
  "queue_wait_seconds": 234.0,                // running_at - queued_at (null if never observed RUNNING)
  "execution_seconds": 27.0,                  // completed_at - running_at
  "total_seconds": 261.0,                     // completed_at - queued_at
  "final_status": "DONE",
  "pending_jobs_at_submission": 43            // snapshot of backend.status().pending_jobs at job submit time
}
```

***

## 5. Schedule Control

### Configuration (`.env` or environment variables)

Implemented in `ibm_queue_logger/config.py`. Copy `.env.example` → `.env`:

```dotenv
# ── AUTHENTICATION ─────────────────────────────────────────────────────────
IBM_QUANTUM_API_KEY=your_44_char_api_key     # Required. Alias: IBM_QUANTUM_TOKEN, QISKIT_IBM_TOKEN
IBM_INSTANCE_CRN=crn:v1:bluemix:...          # Strongly recommended. Alias: IBM_INSTANCE, QISKIT_IBM_INSTANCE
IBM_QUANTUM_CHANNEL=ibm_quantum_platform     # Optional. Alias: QISKIT_IBM_CHANNEL

# ── SCHEDULE CONTROL ───────────────────────────────────────────────────────
RUNS_PER_DAY=48          # Poll ticks per 24-hour UTC day
                         #   1   → once per day  (00:00 UTC)
                         #   24  → once per hour
                         #   48  → every 30 minutes
                         #   144 → every 10 minutes
                         #   288 → every 5 minutes  (practical max for free tier)

ENABLE_JOB_PROBES=true   # Set false to disable Layer 2 (zero QPU cost mode)
PROBE_EVERY_N_TICKS=6    # Submit a probe every N ticks (~8/day at 48 runs/day)
PROBE_SHOTS=100          # 100–256
JOB_POLL_INTERVAL_SECONDS=15

# ── RATE-LIMIT GUARD-RAILS ─────────────────────────────────────────────────
BACKEND_STATUS_DELAY_SECONDS=0.5
API_MAX_RETRIES=3
API_RETRY_BASE_SECONDS=2

LOG_DIR=./logs
```

**CLI testing**: `python queue_logger.py --force-tick` bypasses schedule gating.

### Schedule Calculation Utility

Your cron job calls this script with one argument: the **tick index** for the current day
(0 to RUNS_PER_DAY−1). The simplest approach is to run the script every minute via cron and
let it self-gate:

```python
import datetime, math

def should_run_now(runs_per_day: int) -> tuple[bool, int]:
    """
    Returns (should_run, tick_index).
    Divides the day into runs_per_day equal intervals.
    Tick fires if the current minute falls within the first minute of its interval.
    """
    now = datetime.datetime.utcnow()
    minutes_since_midnight = now.hour * 60 + now.minute
    interval_minutes = 1440 / runs_per_day                     # e.g., 30.0 for 48 runs/day
    tick_index = int(minutes_since_midnight / interval_minutes)
    tick_start_minute = round(tick_index * interval_minutes)
    return (minutes_since_midnight == tick_start_minute), tick_index
```

**Crontab entry** (run every minute, script self-gates):

```cron
* * * * * /path/to/venv/bin/python /path/to/queue_logger.py >> /path/to/logs/cron_stderr.log 2>&1
```

Alternatively, compute all tick times at midnight and write them to cron dynamically, or use
`APScheduler` / `systemd` timers for more precise intervals. The self-gating pattern above works
fine for intervals ≥ 5 minutes.

***

## 6. Output Format

### File Naming

```
logs/
  ibmq_queue_YYYY-MM-DD.ndjson      # one file per UTC day, appended by every tick
```

### NDJSON (Newline-Delimited JSON)

Each log entry is one JSON object per line, no trailing commas, no array wrapper:

```jsonc
{"schema_version":"1.0","event_type":"backend_status","ts":"2026-06-12T00:00:00Z",...}
{"schema_version":"1.0","event_type":"backend_status","ts":"2026-06-12T00:00:00Z",...}
{"schema_version":"1.0","event_type":"instance_usage","ts":"2026-06-12T00:00:00Z",...}
{"schema_version":"1.0","event_type":"job_status_poll","ts":"2026-06-12T00:01:05Z",...}
```

NDJSON is directly loadable with `pandas.read_json(..., lines=True)` or `jq`.

***

## 7. SDK Call Reference

Below are the exact Python calls Cursor should implement. All verified against
the latest `qiskit-ibm-runtime` API docs.

### 7.1 Initialise Service

```python
from qiskit_ibm_runtime import QiskitRuntimeService

service = QiskitRuntimeService(
    token=IBM_QUANTUM_API_KEY,       # IBM Cloud API key (44-char, from dashboard)
    instance=IBM_INSTANCE_CRN,       # CRN from Instances page (strongly recommended)
    # channel defaults to "ibm_quantum_platform"
)

# Confirm active instance after connect:
active_crn = service.active_instance()
```

Docs: https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/qiskit-runtime-service
Guide: https://quantum.cloud.ibm.com/docs/guides/initialize-account

### 7.2 List All Backends

```python
backends = service.backends(simulator=False, operational=True)
# Returns List[IBMBackend]
# Docs: https://qiskit.qotlabs.org/guides/get-qpu-information
```

### 7.3 Get Backend Status (Layer 1)

```python
status = backend.status()
# Returns BackendStatus with fields:
#   .backend_name   str
#   .backend_version str
#   .operational    bool
#   .pending_jobs   int   ← queue depth
#   .status_msg     str
# Docs: https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/models-backend-status
```

### 7.4 Get Backend Configuration (for processor_type)

```python
config = backend.configuration()
processor_family   = config.processor_type.get("family", "unknown")
processor_revision = config.processor_type.get("revision", "unknown")
# Docs: https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/ibm-backend  (configuration() method)
```

### 7.5 Least Busy Helper

```python
least_busy_backend = service.least_busy(
    simulator=False,
    operational=True,
    min_num_qubits=1
)
# Docs: https://qiskit.qotlabs.org/guides/get-qpu-information
```

### 7.6 Instance Usage via SDK (Layer 1 supplement)

```python
usage = service.usage()
# usage_consumed_seconds, usage_limit_seconds (or usage_allocation_seconds),
# usage_remaining_seconds, usage_limit_reached, usage_period

record = {
    "event_type": "instance_usage",
    "instance": service.active_instance(),
    "quota_seconds": usage.get("usage_limit_seconds") or usage.get("usage_allocation_seconds"),
    "usage_seconds": usage.get("usage_consumed_seconds", 0),
    "remaining_seconds": usage.get("usage_remaining_seconds"),
    "usage_limit_reached": usage.get("usage_limit_reached", False),
    "usage_period": usage.get("usage_period"),
}
```

On failure, emit `instance_usage_error` and continue the tick (do not crash).

### 7.7 Submit Probe Job (Layer 2)

```python
from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2 as Sampler

def submit_probe(backend) -> "RuntimeJobV2":
    qc = QuantumCircuit(1, 1)
    qc.h(0)
    qc.measure(0, 0)

    sampler = Sampler(backend)
    job = sampler.run([qc], shots=100)
    # job.job_id()          → str, unique identifier
    # job.creation_date     → datetime UTC (when job was accepted)
    # job.status()          → str: "INITIALIZING" | "QUEUED" | "RUNNING" | "DONE" | "ERROR" | "CANCELLED"
    return job
# RuntimeJobV2 docs: https://qiskit.qotlabs.org/docs/api/qiskit-ibm-runtime/runtime-job-v2
```

### 7.8 Poll an In-Flight Job

```python
import time

def poll_job_to_completion(job, poll_interval_seconds: int = 15) -> list[dict]:
    """
    Polls job.status() until terminal, recording each status transition.
    Returns a list of status-poll log records.
    """
    records = []
    seen_statuses = {}      # status_str → first_seen_datetime
    terminal = {"DONE", "ERROR", "CANCELLED"}

    while True:
        now = datetime.datetime.utcnow()
        current_status = job.status()   # str in current RuntimeJobV2

        if current_status not in seen_statuses:
            seen_statuses[current_status] = now

        records.append({
            "event_type": "job_status_poll",
            "ts": now.isoformat() + "Z",
            "job_id": job.job_id(),
            "status": current_status,
            "wall_seconds_since_creation": (now - job.creation_date.replace(tzinfo=None)).total_seconds(),
            "is_terminal": current_status in terminal,
        })

        if current_status in terminal:
            break
        time.sleep(poll_interval_seconds)

    return records, seen_statuses
```

> ⚠️ **Note on `job.status()` return type**: `RuntimeJobV2.status()` returns a **string**, not a
> `JobStatus` enum (that was the legacy API). Do not compare against `JobStatus.QUEUED`; use
> string literals `"QUEUED"`, `"RUNNING"`, `"DONE"`, etc.

***

## 8. Cost & Rate-Limit Guard-rails

### QPU Cost Budget

| Scenario | Probe jobs/day | Est. QPU time/day | Monthly QPU time |
|---|---|---|---|
| `RUNS_PER_DAY=48`, `PROBE_EVERY_N_TICKS=6` | 8 | ~8–16 s | ~4–8 min |
| `RUNS_PER_DAY=48`, `PROBE_EVERY_N_TICKS=12` | 4 | ~4–8 s | ~2–4 min |
| `RUNS_PER_DAY=144`, `PROBE_EVERY_N_TICKS=18` | 8 | ~8–16 s | ~4–8 min |

All scenarios stay well under the **10 free minutes/28-day** Open Plan quota.

### API Rate Limits (documented + empirical)

| Operation | Limit | Mitigation in logger |
|---|---|---|
| **Job submission** (Layer 2) | **5 jobs/minute/user** ([REST jobs API](https://quantum.cloud.ibm.com/docs/en/api/qiskit-runtime-rest/tags/jobs)) | Max 1 probe per tick; `PROBE_EVERY_N_TICKS` sub-sampling |
| **`backend.status()` sweep** | No published limit | `BACKEND_STATUS_DELAY_SECONDS=0.5` between backends |
| **HTTP 429** | Throttled | `with_retry()` exponential backoff, honor `Retry-After`, max 3 retries |
| **HTTP 409** | Instance quota exceeded | Pre-check `service.usage()` before probes; skip if `usage_limit_reached` |
| **HTTP 401** | Bad credentials | Fail fast: use API key, not bearer token |

Additional recommendations:

- Do NOT call `backend.status()` in a tight loop (< 1 s interval).
- At `RUNS_PER_DAY=288` with ~10 backends, Layer 1 ≈ 2,880 status calls/day — safe when spread across 24 h.
- Probes are skipped when `usage_limit_reached` or `usage_remaining_seconds <= 0` (emits `probe_skipped`).

***

## 9. Derived Signals for Simulation

From the raw logs you can derive:

| Signal | Source | Computation |
|---|---|---|
| Queue depth time series per backend | `event_type=backend_status` | `pending_jobs` vs `ts` |
| Operational availability windows | `event_type=backend_status` | `operational` and `status_msg` transitions |
| Empirical job wait-time distribution | `event_type=job_completed` | `queue_wait_seconds` histogram |
| Queue depth at arrival vs wait time | Join `job_completed.pending_jobs_at_submission` with `queue_wait_seconds` | Scatter plot |
| Intra-day queue load profile | `event_type=backend_status` grouped by hour-of-day | Mean `pending_jobs` by hour |
| Instance saturation proxy | `event_type=instance_usage` | `usage_seconds / quota_seconds` ratio |

***

## 10. Notes on `QueueInfo` Deprecation

The legacy `QueueInfo` object (with `.position`, `.estimated_start_time`, `.estimated_complete_time`,
`.hub_priority`, `.group_priority`, `.project_priority`, `.job_id`) was part of the old
`qiskit.providers.ibmq` stack (retired ~2023). It **does not exist in `qiskit_ibm_runtime`**.

- Do not attempt to call `.queue_info()` on a `RuntimeJobV2` instance — this method does not exist.
- Estimated start/complete times are no longer exposed via the Python SDK as of the current runtime.
- The only confirmed route to queue position/timing is through status transition timestamps as
  described in Section 7.8 above.

Legacy docs (for historical reference only — do not implement against these):
- https://quantum.cloud.ibm.com/docs/en/api/qiskit/0.25/qiskit.providers.ibmq.job.QueueInfo
- https://quantum.cloud.ibm.com/docs/en/api/qiskit/0.29/qiskit.providers.ibmq.job.QueueInfo

***

## 11. Environment Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt`:

```
qiskit-ibm-runtime>=0.42
qiskit>=1.0
python-dotenv>=1.0
```

Minimum Python: 3.10+

`.env` file (see `.env.example`):

```dotenv
IBM_QUANTUM_API_KEY=your_44_char_api_key_here
IBM_INSTANCE_CRN=crn:v1:bluemix:public:quantum-computing:us-east:a/...
LOG_DIR=./logs
RUNS_PER_DAY=48
ENABLE_JOB_PROBES=true
PROBE_EVERY_N_TICKS=6
```

**Run**:

```bash
# Normal (cron self-gates on schedule):
python queue_logger.py

# Force a tick immediately (testing):
python queue_logger.py --force-tick
```

**Crontab**:

```cron
* * * * * /path/to/.venv/bin/python /path/to/queue_logger.py >> /path/to/logs/cron_stderr.log 2>&1
```

***

## 12. Error & Skip Event Types

Emitted alongside primary events; all include `"schema_version": "1.0"`.

| `event_type` | When emitted | Key fields |
|---|---|---|
| `instance_usage_error` | `service.usage()` fails | `error`, `instance` |
| `backend_status_error` | Single backend `status()` / `configuration()` fails | `backend_name`, `error` |
| `probe_skipped` | Quota pre-check blocks probe | `reason` |
| `probe_submit_error` | Backend selection or job submit fails | `error`, `stage`, `backend_name` |

***

## 13. Project Layout (implemented)

```
ibm_queue_simulator/
├── queue_logger.py              # cron entry point
├── ibm_queue_logger/
│   ├── config.py
│   ├── auth.py
│   ├── retry.py
│   ├── schedule.py
│   ├── collectors/
│   │   ├── layer1.py
│   │   └── layer2.py
│   └── logging/
│       └── ndjson_writer.py
├── requirements.txt
├── .env.example
└── ibm_api_spec.md
```

***

*Spec version 1.1 — updated June 2026 — verified against IBM Quantum Platform docs.*

**Changelog v1.0 → v1.1:**
- Auth: API key + CRN, `ibm_quantum_platform` channel (replaces legacy `ibm_quantum` / `ibm-q/open/main`)
- Instance usage: `service.usage()` SDK (replaces legacy REST `/runtime/usage`)
- `instance_usage` schema: added `usage_limit_reached`, `usage_period`; removed `pending_jobs_instance`
- Rate limits: documented 5 jobs/min, 429 retry, quota pre-check
- New error/skip event types (§12)
- Implementation in `ibm_queue_logger/` package (§13)