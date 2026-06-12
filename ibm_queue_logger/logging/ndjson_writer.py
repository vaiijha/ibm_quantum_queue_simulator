"""Append-only NDJSON log writer."""

from __future__ import annotations

import datetime
import json
from pathlib import Path


def format_ts(dt: datetime.datetime | None = None) -> str:
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


def log_path(log_dir: str, when: datetime.datetime | None = None) -> Path:
    if when is None:
        when = datetime.datetime.now(datetime.timezone.utc)
    if when.tzinfo is not None:
        when = when.astimezone(datetime.timezone.utc)
    date_str = when.strftime("%Y-%m-%d")
    return Path(log_dir) / f"ibmq_queue_{date_str}.ndjson"


def append_records(log_dir: str, records: list[dict]) -> Path:
    if not records:
        path = log_path(log_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    path = log_path(log_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":"), default=str))
            handle.write("\n")
    return path
