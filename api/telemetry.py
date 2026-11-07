"""Persist bounded, non-sensitive experiment snapshots in SpacetimeDB.

The existing schedule table is an audit log here, not a claim that a physical
battery was dispatched. Energy/cost fields remain estimates in plan_json.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import math
import os
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from .spacetime import call_reducer, is_connected_result, query_sql


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Allow experiment values, but never device serials, paths or shell output."""
    result = {
        key: copy.deepcopy(snapshot[key])
        for key in (
            "price", "assumptions", "battery", "flows", "costs", "mode",
            "effective_mode", "reason", "elapsed_seconds", "history",
        ) if key in snapshot
    }
    hardware = snapshot.get("hardware", {})
    fields = {
        "device": ("status", "available", "name"),
        "job": ("status", "target", "completed_units", "progress_pct", "elapsed_seconds", "active_seconds"),
        "mac_battery": ("available", "percent", "power_source", "charging", "state", "observed_at"),
    }
    result["hardware"] = {
        group: {key: hardware.get(group, {})[key] for key in keys if key in hardware.get(group, {})}
        for group, keys in fields.items()
    }
    # History is already bounded by the controller; bound it here too to keep
    # each public audit event small even when called with an external snapshot.
    if isinstance(result.get("history"), list):
        result["history"] = result["history"][-30:]
    result["energy_measurement"] = "estimated from configured watts and measured runtime"
    result["battery_dispatch"] = "simulated; no physical power switching"
    return result


class TelemetryRecorder:
    """30-second audit writer. Run record() in a worker thread, not the UI loop."""

    def __init__(self, interval_seconds: float = 30, clock: Callable[[], float] = time.monotonic):
        self.interval_seconds = max(1.0, interval_seconds)
        self._clock = clock
        self._next_attempt = 0.0
        self._writing = False
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "connected": False, "last_saved_at": None, "last_run_id": None,
            "error": None, "status": "not_started",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            configured = bool(os.getenv("SPACETIME_URI") and os.getenv("SPACETIME_DATABASE"))
            return {
                **self._state,
                "configured": configured,
                "database": os.getenv("SPACETIME_DATABASE"),
                "interval_seconds": self.interval_seconds,
                "status": self._state["status"] if configured else "not_configured",
                "connected": self._state["connected"] if configured else False,
            }

    def record(self, demo_snapshot: dict[str, Any], force: bool = False) -> dict[str, Any]:
        with self._lock:
            if not self.snapshot()["configured"]:
                return self.snapshot()
            now = self._clock()
            if self._writing or (not force and now < self._next_attempt):
                return self.snapshot()
            self._next_attempt = now + self.interval_seconds
            self._writing = True

        # Do not hold the status lock over network I/O: dashboard reads must
        # remain responsive when the remote database is slow or unavailable.
        costs = demo_snapshot.get("costs", {})
        baseline = costs.get("baseline_usd")
        optimized = costs.get("adjusted_usd")
        savings = costs.get("estimated_savings_usd")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) for value in (baseline, optimized, savings)):
            with self._lock:
                self._state.update(status="waiting_for_priced_sample", error=None)
                self._writing = False
            return self.snapshot()

        created_at = datetime.now(timezone.utc).isoformat()
        run_id = f"hardware-{uuid4().hex}"
        try:
            public = _public_snapshot(demo_snapshot)
            public["recorded_at"] = created_at
            result = call_reducer("publish_schedule", {
                "runId": run_id,
                "createdAt": created_at,
                "baselineCost": baseline,
                "optimizedCost": optimized,
                "savings": savings,
                "status": "hardware-demo-simulated-energy",
                "planJson": json.dumps(public, allow_nan=False, separators=(",", ":")),
            })
            if result is None:
                raise RuntimeError("SpacetimeDB configuration unavailable")
            # Verify the row was actually committed, not merely HTTP accepted.
            rows = query_sql(f"SELECT run_id FROM schedule WHERE run_id = '{run_id}'")
            if not is_connected_result(rows) or not any(table.get("rows") for table in rows):
                raise RuntimeError("SpacetimeDB did not confirm the saved experiment row")
            with self._lock:
                self._state.update(connected=True, status="saved", error=None,
                                   last_saved_at=created_at, last_run_id=run_id)
        except Exception as exc:
            with self._lock:
                self._state.update(connected=False, status="error", error=str(exc))
        finally:
            with self._lock:
                self._writing = False
        return self.snapshot()
