"""Layer 2: optional probe jobs (small QPU cost)."""

from __future__ import annotations

import datetime
import time
from typing import Any

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler

from ibm_queue_logger.config import SCHEMA_VERSION, Settings
from ibm_queue_logger.logging.ndjson_writer import format_ts
from ibm_queue_logger.retry import with_retry

TERMINAL_STATUSES = {"DONE", "ERROR", "CANCELLED"}


def _base_record(event_type: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "ts": format_ts(),
    }


def _to_naive_utc(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def _usage_allows_probe(service: QiskitRuntimeService, settings: Settings) -> tuple[bool, str | None]:
    try:
        usage = with_retry(
            service.usage,
            max_retries=settings.api_max_retries,
            base_delay=settings.api_retry_base_seconds,
        )
    except Exception as exc:
        return False, f"usage_check_failed: {exc}"

    if usage.get("usage_limit_reached"):
        return False, "usage_limit_reached"

    remaining = usage.get("usage_remaining_seconds")
    if remaining is not None and remaining <= 0:
        return False, "usage_remaining_seconds_exhausted"

    return True, None


def _submit_probe(backend, settings: Settings):
    qc = QuantumCircuit(1, 1)
    qc.h(0)
    qc.measure(0, 0)
    sampler = Sampler(backend)

    def _run():
        return sampler.run([qc], shots=settings.probe_shots)

    return with_retry(
        _run,
        max_retries=settings.api_max_retries,
        base_delay=settings.api_retry_base_seconds,
    )


def run_probe(service: QiskitRuntimeService, settings: Settings) -> list[dict]:
    records: list[dict] = []

    allowed, skip_reason = _usage_allows_probe(service, settings)
    if not allowed:
        record = _base_record("probe_skipped")
        record["reason"] = skip_reason
        return [record]

    try:
        backend = with_retry(
            lambda: service.least_busy(simulator=False, operational=True, min_num_qubits=1),
            max_retries=settings.api_max_retries,
            base_delay=settings.api_retry_base_seconds,
        )
        pending_at_submit = with_retry(
            backend.status,
            max_retries=settings.api_max_retries,
            base_delay=settings.api_retry_base_seconds,
        ).pending_jobs
    except Exception as exc:
        record = _base_record("probe_submit_error")
        record["error"] = str(exc)
        record["stage"] = "backend_selection"
        return [record]

    backend_name = backend.name
    num_qubits = 1

    try:
        job = _submit_probe(backend, settings)
    except Exception as exc:
        record = _base_record("probe_submit_error")
        record["error"] = str(exc)
        record["stage"] = "job_submit"
        record["backend_name"] = backend_name
        return [record]

    job_id = job.job_id()
    creation_date = _to_naive_utc(job.creation_date)
    seen_statuses: dict[str, datetime.datetime] = {}

    while True:
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        try:
            current_status = with_retry(
                job.status,
                max_retries=settings.api_max_retries,
                base_delay=settings.api_retry_base_seconds,
            )
        except Exception as exc:
            record = _base_record("job_status_poll")
            record.update(
                {
                    "job_id": job_id,
                    "backend_name": backend_name,
                    "shots": settings.probe_shots,
                    "num_qubits": num_qubits,
                    "job_creation_date": format_ts(creation_date),
                    "status": "POLL_ERROR",
                    "wall_seconds_since_creation": (now - creation_date).total_seconds(),
                    "is_terminal": False,
                    "error": str(exc),
                }
            )
            records.append(record)
            time.sleep(settings.job_poll_interval_seconds)
            continue

        if current_status not in seen_statuses:
            seen_statuses[current_status] = now

        poll_record = _base_record("job_status_poll")
        poll_record.update(
            {
                "job_id": job_id,
                "backend_name": backend_name,
                "shots": settings.probe_shots,
                "num_qubits": num_qubits,
                "job_creation_date": format_ts(creation_date),
                "status": current_status,
                "wall_seconds_since_creation": (now - creation_date).total_seconds(),
                "is_terminal": current_status in TERMINAL_STATUSES,
            }
        )
        records.append(poll_record)

        if current_status in TERMINAL_STATUSES:
            completed_at = now
            queued_at = seen_statuses.get("QUEUED") or seen_statuses.get("INITIALIZING") or creation_date
            running_at = seen_statuses.get("RUNNING")

            queue_wait_seconds = None
            execution_seconds = None
            if running_at is not None:
                queue_wait_seconds = (running_at - queued_at).total_seconds()
                execution_seconds = (completed_at - running_at).total_seconds()
            total_seconds = (completed_at - queued_at).total_seconds()

            completed_record = _base_record("job_completed")
            completed_record.update(
                {
                    "job_id": job_id,
                    "backend_name": backend_name,
                    "shots": settings.probe_shots,
                    "job_creation_date": format_ts(creation_date),
                    "queued_at": format_ts(queued_at),
                    "running_at": format_ts(running_at) if running_at else None,
                    "completed_at": format_ts(completed_at),
                    "queue_wait_seconds": queue_wait_seconds,
                    "execution_seconds": execution_seconds,
                    "total_seconds": total_seconds,
                    "final_status": current_status,
                    "pending_jobs_at_submission": pending_at_submit,
                }
            )
            records.append(completed_record)
            break

        time.sleep(settings.job_poll_interval_seconds)

    return records
