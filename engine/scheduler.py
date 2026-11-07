"""Transparent three-policy dispatch and cost accounting.

Energy arrays are kWh per interval. Prices are USD/MWh. Battery rates are kW.
"""
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
        return {"grid_kwh": self.grid_kwh, "battery_charge_kwh": self.battery_charge_kwh,
                "battery_discharge_kwh": self.battery_discharge_kwh,
                "workload_slots": self.workload_slots, "battery_soc_kwh": self.battery_soc_kwh,
                "total_cost": round(self.total_cost, 6), "peak_grid_kwh": round(self.peak_grid_kwh, 6),
                "sla_violations": self.sla_violations}


def _assign(scenario: Scenario, immediate: bool) -> dict[str, list[int]]:
    assignments: dict[str, list[int]] = {}
    for job in scenario.workloads:
        latest_start = min(job.deadline_slot if job.deadline_slot is not None else scenario.slots-job.duration_slots,
                           scenario.slots-job.duration_slots)
        candidates = list(range(job.release_slot, latest_start + 1))
        if job.critical or immediate:
            selected = job.release_slot if job.release_slot in candidates else -1
        else:
            selected = min(candidates, key=lambda s: sum(
                scenario.prices[s:s+job.duration_slots]), default=-1)
        assignments[job.name] = list(range(selected, selected+job.duration_slots)) if selected >= 0 else []
    return assignments


def _loads(scenario: Scenario, assignments: dict[str, list[int]]) -> tuple[list[float], list[str]]:
    loads = list(scenario.fixed_load_kwh)
    violations = []
    for job in scenario.workloads:
        slots = assignments.get(job.name, [])
        if len(slots) != job.duration_slots:
            violations.append(job.name)
            continue
        each = job.energy_kwh/job.duration_slots
        for slot in slots:
            if 0 <= slot < scenario.slots:
                loads[slot] += each
            else:
                violations.append(job.name)
    return loads, sorted(set(violations))


def _dispatch(scenario: Scenario, loads: list[float], policy: str) -> tuple[list[float],list[float],list[float],list[float]]:
    n, interval = scenario.slots, scenario.interval_hours
    battery = scenario.battery
    soc = battery.initial_soc_kwh if battery else 0.
    grid, charge, discharge, soc_trace = [], [], [], []
    ordered = sorted(scenario.prices)
    low = ordered[max(0, n//3-1)]
    high = ordered[min(n-1, 2*n//3)]
    for i, price in enumerate(scenario.prices):
        purchased = delivered = 0.
        if policy != "grid_only" and battery:
            do_charge = (price <= low and (policy == "optimized" or i < n-1))
            do_discharge = price >= high
            # For the economic optimizer require the observed spread to cover
            # round-trip loss. Threshold retains the intuitive quartile rule.
            if policy == "optimized" and high <= low/(battery.charge_efficiency*battery.discharge_efficiency):
                do_charge = do_discharge = False
            if do_charge and soc < battery.capacity_kwh:
                purchased = min(battery.max_charge_kw*interval,
                                (battery.capacity_kwh-soc)/battery.charge_efficiency)
                soc += purchased*battery.charge_efficiency
            elif do_discharge and soc > battery.reserve_kwh:
                delivered = min(battery.max_discharge_kw*interval,
                                (soc-battery.reserve_kwh)*battery.discharge_efficiency,
                                loads[i])
                soc -= delivered/battery.discharge_efficiency
        charge.append(purchased)
        discharge.append(delivered)
        grid.append(max(0., loads[i]+purchased-delivered))
        soc_trace.append(soc)
    return grid, charge, discharge, soc_trace


def _evaluate(scenario: Scenario, assignments: dict[str, list[int]], battery_mode: bool) -> ScheduleResult:
    loads, violations = _loads(scenario, assignments)
    policy = "threshold" if battery_mode else "grid_only"
    grid, charge, discharge, soc = _dispatch(scenario, loads, policy)
    cost = sum(kwh*price/1000 for kwh, price in zip(grid, scenario.prices))
    return ScheduleResult(grid, charge, discharge, assignments, soc, cost, max(grid), violations)


def baseline(scenario: Scenario) -> ScheduleResult:
    """Immediate workloads, grid supplied, no battery."""
    return _evaluate(scenario, _assign(scenario, immediate=True), battery_mode=False)


def optimize(scenario: Scenario) -> ScheduleResult:
    """Move eligible jobs to their cheapest contiguous price window; threshold dispatch."""
    assignments = _assign(scenario, immediate=False)
    loads, violations = _loads(scenario, assignments)
    grid, charge, discharge, soc = _dispatch(scenario, loads, "optimized")
    cost = sum(kwh*price/1000 for kwh, price in zip(grid, scenario.prices))
    return ScheduleResult(grid, charge, discharge, assignments, soc, cost, max(grid), violations)


def compare_dispatch(scenario: Scenario, degradation_usd_per_kwh: float = 0.0,
                     demand_charge_usd_per_kw: float = 0.0) -> dict[str, Any]:
    """Compare grid-only, quartile threshold, and workload optimizer policies.

    Every strategy executes the same workloads. Non-optimized policies run at
    release; optimized jobs may move within their deadlines. Terminal battery
    deficit is valued as replacement energy at the final observed price.
    Demand charges apply uniformly to each strategy's horizon peak.
    """
    if degradation_usd_per_kwh < 0 or demand_charge_usd_per_kw < 0:
        raise ValueError("degradation and demand charge rates must be nonnegative")
    immediate = _assign(scenario, immediate=True)
    optimized_assignments = _assign(scenario, immediate=False)
    results = {
        "grid_only": _evaluate(scenario, immediate, False),
        "threshold": _evaluate(scenario, immediate, True),
    }
    loads, violations = _loads(scenario, optimized_assignments)
    grid, charge, discharge, soc = _dispatch(scenario, loads, "optimized")
    opt_cost = sum(kwh*p/1000 for kwh,p in zip(grid,scenario.prices))
    results["optimized"] = ScheduleResult(grid,charge,discharge,optimized_assignments,soc,opt_cost,max(grid),violations)

    b = scenario.battery
    terminal_price = scenario.prices[-1]
    output = {}
    for name, result in results.items():
        peak_kw = result.peak_grid_kwh/scenario.interval_hours
        throughput = sum(result.battery_discharge_kwh)
        deficit = max(0., (b.initial_soc_kwh-result.battery_soc_kwh[-1])) if b and result.battery_soc_kwh else 0.
        terminal_kwh = deficit/b.charge_efficiency if b and deficit else 0.
        terminal_cost = terminal_kwh*terminal_price/1000
        degradation = throughput*degradation_usd_per_kwh
        demand = peak_kw*demand_charge_usd_per_kw
        output[name] = {
            "energy_cost_usd": result.total_cost,
            "demand_charge_usd": demand,
            "degradation_usd": degradation,
            "terminal_energy_cost_usd": terminal_cost,
            "total_cost_usd": result.total_cost+demand+degradation+terminal_cost,
            "grid_kwh": result.grid_kwh,
            "peak_grid_kw": peak_kw,
            "battery_soc_kwh": result.battery_soc_kwh,
            "battery_charge_kwh": result.battery_charge_kwh,
            "battery_discharge_kwh": result.battery_discharge_kwh,
            "workload_slots": result.workload_slots,
            "sla_violations": result.sla_violations,
            "terminal_soc_replacement_kwh": terminal_kwh,
        }
    return {**output, "assumptions": {
        "price_unit":"USD/MWh", "energy_unit":"kWh per interval", "interval_hours":scenario.interval_hours,
        "degradation_usd_per_kwh_discharged":degradation_usd_per_kwh,
        "demand_charge_usd_per_kw_peak":demand_charge_usd_per_kw,
        "demand_charge_basis":"horizon maximum grid kW",
        "terminal_energy_valuation":"SOC deficit from initial replenished at last price / charge efficiency; no surplus credit",
    }}
