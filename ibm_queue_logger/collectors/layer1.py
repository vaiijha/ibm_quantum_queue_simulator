"""Layer 1: device-level polling (zero QPU cost)."""

from __future__ import annotations

import time
from typing import Any

from qiskit_ibm_runtime import QiskitRuntimeService

from ibm_queue_logger.config import SCHEMA_VERSION, Settings
from ibm_queue_logger.logging.ndjson_writer import format_ts
from ibm_queue_logger.retry import with_retry


def _base_record(event_type: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "ts": format_ts(),
    }


def poll_backends(service: QiskitRuntimeService, settings: Settings) -> list[dict]:
    records: list[dict] = []

    backends = with_retry(
        lambda: service.backends(simulator=False, operational=True),
        max_retries=settings.api_max_retries,
        base_delay=settings.api_retry_base_seconds,
    )

    status_snapshots: list[tuple[Any, Any]] = []
    for backend in backends:
        try:
            status = with_retry(
                backend.status,
                max_retries=settings.api_max_retries,
                base_delay=settings.api_retry_base_seconds,
            )
            status_snapshots.append((backend, status))
        except Exception as exc:
            record = _base_record("backend_status_error")
            record["backend_name"] = getattr(backend, "name", "unknown")
            record["error"] = str(exc)
            records.append(record)
        time.sleep(settings.backend_status_delay_seconds)

    ranked = sorted(status_snapshots, key=lambda item: item[1].pending_jobs)
    rank_by_name = {backend.name: idx + 1 for idx, (backend, _) in enumerate(ranked)}

    poll_ts = format_ts()
    for backend, status in status_snapshots:
        try:
            config = backend.configuration()
            processor_type = getattr(config, "processor_type", None) or {}
            if not isinstance(processor_type, dict):
                processor_type = {}

            record = _base_record("backend_status")
            record["ts"] = poll_ts
            record.update(
                {
                    "backend_name": status.backend_name,
                    "backend_version": status.backend_version,
                    "num_qubits": config.num_qubits,
                    "operational": status.operational,
                    "pending_jobs": status.pending_jobs,
                    "status_msg": status.status_msg,
                    "processor_family": processor_type.get("family", "unknown"),
                    "processor_revision": processor_type.get("revision", "unknown"),
                    "simulator": config.simulator,
                    "least_busy_rank": rank_by_name.get(backend.name),
                }
            )
            records.append(record)
        except Exception as exc:
            record = _base_record("backend_status_error")
            record["backend_name"] = getattr(backend, "name", status.backend_name)
            record["error"] = str(exc)
            records.append(record)

    return records


def fetch_instance_usage(service: QiskitRuntimeService, settings: Settings) -> list[dict]:
    try:
        usage = with_retry(
            service.usage,
            max_retries=settings.api_max_retries,
            base_delay=settings.api_retry_base_seconds,
        )
        instance = service.active_instance()
        quota = usage.get("usage_limit_seconds") or usage.get("usage_allocation_seconds")
        consumed = usage.get("usage_consumed_seconds", 0)
        remaining = usage.get("usage_remaining_seconds")
        if remaining is None and quota is not None:
            remaining = max(quota - consumed, 0)

        record = _base_record("instance_usage")
        record.update(
            {
                "instance": instance,
                "quota_seconds": quota,
                "usage_seconds": consumed,
                "remaining_seconds": remaining,
                "usage_limit_reached": usage.get("usage_limit_reached", False),
                "usage_period": usage.get("usage_period"),
            }
        )
        return [record]
    except Exception as exc:
        record = _base_record("instance_usage_error")
        record["error"] = str(exc)
        try:
            record["instance"] = service.active_instance()
        except Exception:
            record["instance"] = settings.instance_crn
        return [record]
