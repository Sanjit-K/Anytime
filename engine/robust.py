"""Uncertainty-aware workload dispatch for ShiftOS.

This is deliberately small enough for a hackathon demo, but it models a real
decision problem: a job has an energy cost, a deadline, and a cost of delay;
the optimizer evaluates several plausible price futures rather than taking a
single threshold branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from .models import Scenario, Workload
from .scheduler import _evaluate


@dataclass(frozen=True)
class ScenarioWeight:
    prices: list[float]
    probability: float
    name: str


@dataclass
class RobustScheduleResult:
    assignments: dict[str, list[int]]
    schedule: dict[str, Any]
    scenario_costs: dict[str, float]
    explanations: list[str]
    risk_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "assignments": self.assignments,
            "schedule": self.schedule,
            "scenario_costs": {k: round(v, 4) for k, v in self.scenario_costs.items()},
            "explanations": self.explanations,
            "risk_score": round(self.risk_score, 4),
        }


def make_price_scenarios(prices: list[float], uncertainty: float = 0.20) -> list[ScenarioWeight]:
    """Create low/base/high price futures around the observed curve."""

    if not prices:
        return []
    center = mean(prices)
    low = [max(0.0, p - uncertainty * center) for p in prices]
    high = [p + uncertainty * center for p in prices]
    return [
        ScenarioWeight(low, 0.25, "low-demand"),
        ScenarioWeight(list(prices), 0.50, "base"),
        ScenarioWeight(high, 0.25, "scarcity"),
    ]


def _window_cost(job: Workload, start: int, scenario: ScenarioWeight) -> float:
    return sum(scenario.prices[start:start + job.duration_slots]) * job.energy_kwh / job.duration_slots


def robust_optimize(
    scenario: Scenario,
    price_scenarios: list[ScenarioWeight] | None = None,
    risk_aversion: float = 0.35,
) -> RobustScheduleResult:
    """Optimize flexible jobs against expected cost plus downside risk."""

    scenarios = price_scenarios or make_price_scenarios(scenario.prices)
    if not scenarios:
        raise ValueError("at least one price scenario is required")
    assignments: dict[str, list[int]] = {}
    explanations: list[str] = []
    for job in scenario.workloads:
        last = job.deadline_slot if job.deadline_slot is not None else scenario.slots - job.duration_slots
        candidates = list(range(job.release_slot, min(last, scenario.slots - job.duration_slots) + 1))
        if not candidates:
            assignments[job.name] = []
            explanations.append(f"{job.name}: cannot fit before deadline")
            continue
        if job.critical:
            selected = candidates[0]
            reason = "critical workload starts immediately"
        else:
            scores: list[tuple[float, int, float, float]] = []
            for start in candidates:
                costs = [_window_cost(job, start, item) for item in scenarios]
                expected = sum(cost * item.probability for cost, item in zip(costs, scenarios))
                downside = max(costs) - min(costs)
                delay = max(0, start - job.release_slot) * getattr(job, "delay_penalty_per_slot", 0.0)
                score = expected + risk_aversion * downside + delay
                scores.append((score, start, expected, downside))
            score, selected, expected, downside = min(scores)
            reason = f"expected ${expected:.2f} + risk ${risk_aversion * downside:.2f} + delay penalty"
        assignments[job.name] = list(range(selected, selected + job.duration_slots))
        explanations.append(f"{job.name}: slots {assignments[job.name]} because {reason}")

    # Evaluate the chosen dispatch against every price future for a useful
    # counterfactual readout. The live battery schedule remains reserve-aware.
    result = _evaluate(scenario, assignments, battery_mode=True)
    scenario_costs = {
        item.name: sum(grid * price for grid, price in zip(result.grid_kwh, item.prices))
        for item in scenarios
    }
    risk_score = max(scenario_costs.values()) - min(scenario_costs.values())
    return RobustScheduleResult(assignments, result.as_dict(), scenario_costs, explanations, risk_score)
