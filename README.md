# IBM Quantum Queue Logger

Polls IBM Quantum backend queue depth and instance usage on a schedule, writing append-only NDJSON logs for downstream simulation and analysis.

- **Layer 1** (default): `backend.status()` + `service.usage()` — zero QPU cost
- **Layer 2** (optional): minimal probe jobs to measure queue wait times

Full API and schema details: [`ibm_api_spec.md`](ibm_api_spec.md).

## Quick start (server)

```bash
git clone https://github.com/vaiijha/ibm_quantum_queue_simulator.git
cd ibm_quantum_queue_simulator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set IBM_QUANTUM_API_KEY + IBM_INSTANCE_CRN
python queue_logger.py --force-tick
```

## Security

- **Never commit `.env`** — it is gitignored. Create it only on the server.
- **Never commit `logs/`** — NDJSON files contain your instance CRN.
- Rotate your IBM API key if it was ever exposed; use a fresh key in the server `.env` only.

## Configure `.env`

| Variable | Value |
|---|---|
| `IBM_QUANTUM_API_KEY` | 44-char API key from [IBM Quantum dashboard](https://quantum.cloud.ibm.com/) |
| `IBM_INSTANCE_CRN` | CRN from Instances page (must match the account that owns the API key) |
| `RUNS_PER_DAY` | `288` (every 5 minutes) — see [Cron vs `RUNS_PER_DAY`](#cron-vs-runs_per_day) |
| `ENABLE_JOB_PROBES` | `false` (no QPU-consuming probe jobs) |

## Cron vs `RUNS_PER_DAY`

There are **two** scheduling layers in this project:

| Layer | What it does |
|---|---|
| **Cron** (`*/5 * * * *`) | Starts `queue_logger.py` every 5 minutes |
| **`RUNS_PER_DAY`** (in `.env`) | Inside the script, `should_run_now()` decides whether this invocation should collect data |

`RUNS_PER_DAY=288` means 1440 ÷ 288 = **5 minutes** between ticks — the same interval as `*/5` cron.

### Why both exist

The original design used **cron every minute** (`* * * * *`) plus `RUNS_PER_DAY` as a single knob: change `.env` to switch between hourly, 30-minute, or 5-minute polling without editing crontab.

If you already use **`*/5` cron**, that internal gate is **redundant** — cron is the real scheduler on your server.

### What can go wrong with both

The gate checks **UTC hour + minute** (seconds are ignored), so a few seconds of startup delay is fine. It **skips silently** when cron and the script disagree on the minute:

| Mismatch | Result |
|---|---|
| Cron `*/5` in local time, script uses UTC (no `CRON_TZ=UTC`) | Wrong UTC minute → no data collected |
| Cron `*/5` but `RUNS_PER_DAY=24` | Cron fires every 5 min, script only accepts hourly → mostly skips |

### Recommended for server deploy

Let **cron** be the only scheduler — use `--force-tick` so the script always runs when cron wakes it:

```cron
CRON_TZ=UTC
*/5 * * * * cd /path/to/ibm_quantum_queue_simulator && .venv/bin/python queue_logger.py --force-tick >> logs/cron_stderr.log 2>&1
```

`RUNS_PER_DAY` still matters if you enable probe jobs (`PROBE_EVERY_N_TICKS`); for Layer 1 only it is unused when `--force-tick` is set.

**Alternative:** omit `--force-tick` and keep cron + `RUNS_PER_DAY=288` + `CRON_TZ=UTC` aligned. Works, but two knobs must stay in sync.

## Cron (every 5 minutes UTC)

### What is cron?

**Cron** is Linux’s built-in job scheduler. It runs commands automatically on a repeating timetable — like an alarm clock for shell commands. You don’t need to keep a terminal open or a Python process running; the system starts your script at the times you specify.

- **`crontab -e`** — edit *your* user’s cron table (the list of scheduled jobs).
- **First time?** You’ll be asked to pick a text editor (`1` = nano is easiest).
- **`no crontab for quantum - using an empty one`** — normal on first setup; you’re creating a new schedule from scratch.
- The cron daemon (`cron` service) reads this file and launches your command at the right times, even after reboot (as long as cron is enabled).

### Cron schedule format

Each job line has **five time fields** plus the **command**:

```text
┌──────── minute (0–59)
│ ┌────── hour (0–23)
│ │ ┌──── day of month (1–31)
│ │ │ ┌── month (1–12)
│ │ │ │ ┌ day of week (0–7, 0 and 7 = Sunday)
│ │ │ │ │
* * * * *  command to run
```

Examples:

| Expression | Meaning |
|---|---|
| `*/5 * * * *` | Every 5 minutes |
| `0 * * * *` | Every hour, at minute 0 |
| `0 0 * * *` | Every day at midnight |

### Install the logger job

```bash
mkdir -p logs
crontab -e
```

At the editor prompt, type **`1`** and press Enter (nano). Paste:

```cron
# IBM Quantum queue logger — every 5 minutes UTC, Layer 1 only
CRON_TZ=UTC
*/5 * * * * cd /home/quantum/vaibhav/ibm_quantum_queue_simulator && .venv/bin/python queue_logger.py --force-tick >> logs/cron_stderr.log 2>&1
```

Save in nano: `Ctrl+O`, Enter, then exit: `Ctrl+X`.

Replace the `cd` path with your real project path (`pwd` in the repo directory).

**What each part does:**

| Piece | Purpose |
|---|---|
| `CRON_TZ=UTC` | Fire at `:00`, `:05`, `:10`, … UTC regardless of server local timezone |
| `*/5 * * * *` | Every 5 minutes |
| `cd ... &&` | Run from the project directory so `.env` and `logs/` resolve correctly |
| `queue_logger.py --force-tick` | Run immediately; cron controls timing (see [Cron vs `RUNS_PER_DAY`](#cron-vs-runs_per_day)) |
| `>> logs/cron_stderr.log 2>&1` | Append stdout and stderr to a log file for debugging |

### Useful cron commands

```bash
crontab -l          # list your current jobs
crontab -r          # remove all your jobs (careful)
grep CRON /var/log/syslog   # see if cron ran (path may vary by distro)
```

With `--force-tick` in cron, each cron firing should produce new NDJSON lines. If you omit `--force-tick`, the logger may exit silently when the internal `RUNS_PER_DAY` gate does not match the current UTC minute.

## Verify

```bash
tail -5 logs/ibmq_queue_$(date -u +%Y-%m-%d).ndjson
tail logs/cron_stderr.log
```

## Update code

```bash
cd /absolute/path/to/ibm_quantum_queue_simulator
git pull
# .env is never overwritten by git pull
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401 Unauthorized` | Use API key, not a bearer token |
| Token has no access to instance | Copy CRN from the same account that created the API key |
| Cron runs but no new log lines | Use `--force-tick` in crontab, or align `RUNS_PER_DAY=288` + `CRON_TZ=UTC`; check `cron_stderr.log` |
| Logger exits silently | With `--force-tick`: check errors in `cron_stderr.log`. Without it: cron minute may not match `RUNS_PER_DAY` gate |
