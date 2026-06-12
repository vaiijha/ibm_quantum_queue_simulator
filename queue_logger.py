#!/usr/bin/env python3
"""
IBM Quantum Queue Logger — cron entry point.

Crontab (every 5 minutes UTC; requires RUNS_PER_DAY=288 in .env):
  CRON_TZ=UTC
  */5 * * * * cd /path/to/ibm_queue_simulator && .venv/bin/python queue_logger.py >> logs/cron_stderr.log 2>&1

Force a tick without waiting for schedule (testing only):
  python queue_logger.py --force-tick
"""

from __future__ import annotations

import argparse
import logging
import sys

from ibm_queue_logger.auth import create_service
from ibm_queue_logger.collectors import layer1, layer2
from ibm_queue_logger.config import load_settings
from ibm_queue_logger.logging.ndjson_writer import append_records
from ibm_queue_logger.schedule import should_run_now

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("queue_logger")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IBM Quantum queue telemetry logger")
    parser.add_argument(
        "--force-tick",
        action="store_true",
        help="Run immediately, ignoring schedule gating (for testing)",
    )
    args = parser.parse_args(argv)

    try:
        settings = load_settings(force_tick=args.force_tick)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if settings.force_tick:
        should_run = True
        tick_index = 0
        logger.info("Force tick enabled")
    else:
        should_run, tick_index = should_run_now(settings.runs_per_day)
        if not should_run:
            return 0

    logger.info("Running tick %s (runs_per_day=%s)", tick_index, settings.runs_per_day)

    try:
        service = create_service(settings)
    except Exception as exc:
        print(f"Failed to initialize QiskitRuntimeService: {exc}", file=sys.stderr)
        return 1

    records: list[dict] = []
    records.extend(layer1.poll_backends(service, settings))
    records.extend(layer1.fetch_instance_usage(service, settings))

    run_probe = (
        settings.enable_job_probes
        and tick_index % settings.probe_every_n_ticks == 0
    )
    if run_probe:
        logger.info("Submitting probe job (tick %s)", tick_index)
        records.extend(layer2.run_probe(service, settings))
    else:
        logger.info(
            "Skipping probe (enable=%s, tick=%s, every_n=%s)",
            settings.enable_job_probes,
            tick_index,
            settings.probe_every_n_ticks,
        )

    path = append_records(settings.log_dir, records)
    logger.info("Wrote %s records to %s", len(records), path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
