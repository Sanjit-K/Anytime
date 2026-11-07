"""Post-task reconciliation for the ShiftOS optimization loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Scenario
from .scheduler import ScheduleResult, optimize


@dataclass(frozen=True)
class TaskTelemetry:
    """Measured execution data reported after a workload finishes."""

    workload_name: str
    actual_energy_kwh: float
    actual_duration_slots: int
    completed_slot: int
    success: bool = True

    def __post_init__(self) -> None:
        if self.actual_energy_kwh < 0 or self.actual_duration_slots < 1 or self.completed_slot < 0:
            raise ValueError("task telemetry values are invalid")


def reconcile_post_task(
    scenario: Scenario,
    previous: ScheduleResult,
    telemetry: list[TaskTelemetry],
) -> dict[str, Any]:
    """Compare planned and actual execution, then produce a replanned schedule.

    The optimizer remains deterministic and transparent. Actual telemetry is
    used to expose energy variance and to decide whether a fresh plan is needed.
    """

    planned = {name: sum(scenario.workloads[i].energy_kwh for i in range(len(scenario.workloads)) if scenario.workloads[i].name == name) for name in previous.workload_slots}
    actual = {item.workload_name: item.actual_energy_kwh for item in telemetry}
    variance = {
        name: round(actual[name] - planned.get(name, 0.0), 4)
        for name in actual
    }
    failed = [item.workload_name for item in telemetry if not item.success]
    replanned = optimize(scenario)
    return {
        "planned_energy_kwh": planned,
        "actual_energy_kwh": actual,
        "energy_variance_kwh": variance,
        "failed_workloads": failed,
        "replanned_schedule": replanned.as_dict(),
        "requires_replan": bool(failed or any(abs(value) > 0.05 for value in variance.values())),
    }
