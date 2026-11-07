"""Minimal SpacetimeDB HTTP bridge for the Python optimizer service."""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from urllib.parse import quote
from typing import Any


# HTTP reducer calls take an ordered SATS JSON array, not a named object.
# Keep the order synchronized with spacetime/src/index.ts.
REDUCER_FIELDS = {
    "ingest_price": ("region", "slot", "price", "source", "observedAt"),
    "ingest_demand": ("region", "slot", "loadKw", "newsImpact", "confidence", "source"),
    "upsert_workload": ("id", "name", "powerKw", "durationSlots", "deadlineSlot", "critical", "status"),
    "publish_schedule": ("runId", "createdAt", "baselineCost", "optimizedCost", "savings", "status", "planJson"),
    "record_task_run": ("workloadId", "actualEnergyKwh", "actualDurationSlots", "completedSlot", "success", "recordedAt"),
}


def tls_context() -> ssl.SSLContext:
    """Use a verified CA bundle even on Python installs missing system roots."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def is_connected_result(result: Any) -> bool:
    """SQL returns a list on success; an error dictionary is not a connection."""
    return isinstance(result, list)


def call_reducer(name: str, args: dict[str, Any] | list[Any]) -> dict[str, Any] | None:
    """Call a reducer when SPACETIME_URI and SPACETIME_DATABASE are configured.

    The optimizer remains usable without a remote database, which keeps local
    judging and offline development deterministic.
    """

    base = os.getenv("SPACETIME_URI")
    database = os.getenv("SPACETIME_DATABASE")
    if not base or not database:
        return None
    if isinstance(args, dict):
        if name not in REDUCER_FIELDS:
            raise ValueError(f"Unknown reducer argument order: {name}")
        fields = REDUCER_FIELDS[name]
        if set(args) != set(fields):
            raise ValueError(f"Arguments do not match {name}: expected {fields}")
        args = [args[field] for field in fields]
    url = f"{base.rstrip('/')}/v1/database/{quote(database, safe='')}/call/{quote(name, safe='')}"
    headers = {"Content-Type": "application/json"}
    token = os.getenv("SPACETIME_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(args, allow_nan=False).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=8, context=tls_context()) as response:
        body = response.read().decode()
    return json.loads(body) if body else {}


def query_sql(query: str) -> Any:
    """Read a public SpacetimeDB table through its SQL HTTP endpoint."""

    base = os.getenv("SPACETIME_URI")
    database = os.getenv("SPACETIME_DATABASE")
    if not base or not database:
        return None
    url = f"{base.rstrip('/')}/v1/database/{quote(database, safe='')}/sql"
    headers = {"Content-Type": "text/plain"}
    token = os.getenv("SPACETIME_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=query.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=8, context=tls_context()) as response:
            return json.loads(response.read().decode())
    except Exception as exc:  # keep the dashboard available when the backend is offline
        return {"error": str(exc)}
