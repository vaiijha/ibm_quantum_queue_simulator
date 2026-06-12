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
| `RUNS_PER_DAY` | `288` (every 5 minutes) |
| `ENABLE_JOB_PROBES` | `false` (no QPU-consuming probe jobs) |

## Cron (every 5 minutes UTC)

```bash
mkdir -p logs
crontab -e
```

```cron
# IBM Quantum queue logger — every 5 minutes UTC, Layer 1 only
CRON_TZ=UTC
*/5 * * * * cd /absolute/path/to/ibm_quantum_queue_simulator && .venv/bin/python queue_logger.py >> logs/cron_stderr.log 2>&1
```

Replace `/absolute/path/to/ibm_quantum_queue_simulator` with your real path.

`CRON_TZ=UTC` must match the logger's UTC schedule gate (`should_run_now`). **Do not** use `--force-tick` in cron.

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
| Cron runs but no new log lines | Confirm `RUNS_PER_DAY=288` and `CRON_TZ=UTC`; check `cron_stderr.log` |
| Logger exits silently | Normal between ticks — cron only collects at `:00`, `:05`, `:10`, … UTC |
