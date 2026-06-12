"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

SCHEMA_VERSION = "1.0"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    return float(raw)


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


@dataclass(frozen=True)
class Settings:
    api_key: str
    instance_crn: str | None
    channel: str
    log_dir: str
    runs_per_day: int
    enable_job_probes: bool
    probe_every_n_ticks: int
    probe_shots: int
    job_poll_interval_seconds: int
    backend_status_delay_seconds: float
    api_max_retries: int
    api_retry_base_seconds: float
    force_tick: bool


def load_settings(*, force_tick: bool = False) -> Settings:
    api_key = _first_env("IBM_QUANTUM_API_KEY", "IBM_QUANTUM_TOKEN", "QISKIT_IBM_TOKEN")
    if not api_key:
        raise ValueError(
            "Missing IBM Quantum API key. Set IBM_QUANTUM_API_KEY "
            "(or IBM_QUANTUM_TOKEN / QISKIT_IBM_TOKEN)."
        )

    instance_crn = _first_env("IBM_INSTANCE_CRN", "IBM_INSTANCE", "QISKIT_IBM_INSTANCE")
    channel = _first_env("IBM_QUANTUM_CHANNEL", "QISKIT_IBM_CHANNEL") or "ibm_quantum_platform"

    runs_per_day = _env_int("RUNS_PER_DAY", 48)
    if runs_per_day < 1:
        raise ValueError("RUNS_PER_DAY must be >= 1")

    probe_shots = _env_int("PROBE_SHOTS", 100)
    if not 100 <= probe_shots <= 256:
        raise ValueError("PROBE_SHOTS must be between 100 and 256")

    return Settings(
        api_key=api_key,
        instance_crn=instance_crn,
        channel=channel,
        log_dir=os.getenv("LOG_DIR", "./logs"),
        runs_per_day=runs_per_day,
        enable_job_probes=_env_bool("ENABLE_JOB_PROBES", True),
        probe_every_n_ticks=max(1, _env_int("PROBE_EVERY_N_TICKS", 6)),
        probe_shots=probe_shots,
        job_poll_interval_seconds=max(1, _env_int("JOB_POLL_INTERVAL_SECONDS", 15)),
        backend_status_delay_seconds=max(0.0, _env_float("BACKEND_STATUS_DELAY_SECONDS", 0.5)),
        api_max_retries=max(0, _env_int("API_MAX_RETRIES", 3)),
        api_retry_base_seconds=max(0.1, _env_float("API_RETRY_BASE_SECONDS", 2.0)),
        force_tick=force_tick,
    )
