from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Scenario, Workload


@dataclass
class ScheduleResult:
    grid_kwh: list[float]
    battery_charge_kwh: list[float]
    battery_discharge_kwh: list[float]
    workload_slots: dict[str, list[int]]
    battery_soc_kwh: list[float]
    total_cost: float
    peak_grid_kwh: float
    sla_violations: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "grid_kwh": self.grid_kwh,
            "battery_charge_kwh": self.battery_charge_kwh,
            "battery_discharge_kwh": self.battery_discharge_kwh,
            "workload_slots": self.workload_slots,
            "battery_soc_kwh": self.battery_soc_kwh,
            "total_cost": round(self.total_cost, 4),
            "peak_grid_kwh": round(self.peak_grid_kwh, 4),
            "sla_violations": self.sla_violations,
        }


def _evaluate(scenario: Scenario, assignments: dict[str, list[int]], battery_mode: bool) -> ScheduleResult:
    n = scenario.slots
    workload_load = [0.0] * n
    violations: list[str] = []
    for workload in scenario.workloads:
        slots = assignments.get(workload.name, [])
        if not slots:
            violations.append(workload.name)
            continue
        for slot in slots:
            if slot < 0 or slot >= n:
                violations.append(workload.name)
            else:
                workload_load[slot] += workload.energy_kwh / workload.duration_slots

    charge = [0.0] * n
    discharge = [0.0] * n
    soc = []
    current_soc = scenario.battery.initial_soc_kwh if scenario.battery else 0.0
    if battery_mode and scenario.battery:
        prices = scenario.prices
        low = sorted(prices)[max(0, len(prices) // 3 - 1)]
        high = sorted(prices)[min(len(prices) - 1, (2 * len(prices)) // 3)]
        for i, price in enumerate(prices):
            b = scenario.battery
            if price <= low and current_soc < b.capacity_kwh:
                amount = min(b.max_charge_kw * scenario.interval_hours, b.capacity_kwh - current_soc)
                charge[i] = amount
                current_soc += amount * b.charge_efficiency
            elif price >= high and current_soc > b.reserve_kwh:
                amount = min(b.max_discharge_kw * scenario.interval_hours, current_soc - b.reserve_kwh)
                discharge[i] = amount * b.discharge_efficiency
                current_soc -= amount
            soc.append(current_soc)
    else:
        soc = [current_soc] * n

    grid = [max(0.0, scenario.fixed_load_kwh[i] + workload_load[i] + charge[i] - discharge[i]) for i in range(n)]
    cost = sum(grid[i] * scenario.prices[i] * scenario.interval_hours for i in range(n))
    return ScheduleResult(grid, charge, discharge, assignments, soc, cost, max(grid), sorted(set(violations)))


def _assign(scenario: Scenario, immediate: bool) -> dict[str, list[int]]:
    assignments: dict[str, list[int]] = {}
    for workload in scenario.workloads:
        if workload.critical or immediate:
            start = workload.release_slot
        else:
            last = workload.deadline_slot if workload.deadline_slot is not None else scenario.slots - workload.duration_slots
            candidates = range(workload.release_slot, min(last, scenario.slots - workload.duration_slots) + 1)
            start = min(candidates, key=lambda s: sum(scenario.prices[s:s + workload.duration_slots]), default=-1)
        if start < 0 or start + workload.duration_slots > scenario.slots:
            assignments[workload.name] = []
        else:
            assignments[workload.name] = list(range(start, start + workload.duration_slots))
    return assignments


def baseline(scenario: Scenario) -> ScheduleResult:
    """Run every workload at release time and do not use the battery."""
    return _evaluate(scenario, _assign(scenario, immediate=True), battery_mode=False)


def optimize(scenario: Scenario) -> ScheduleResult:
    """Greedy cost-aware schedule for a hackathon-sized replay simulator."""
    return _evaluate(scenario, _assign(scenario, immediate=False), battery_mode=True)
