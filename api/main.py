"""Small HTTP API for the ShiftOS scheduling MVP.

The optimizer is intentionally kept behind ``build_schedule`` so the API can
be wired to the richer engine package without changing the request contract.
"""

from __future__ import annotations

from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator


class FlexibleJob(BaseModel):
    id: str = Field(min_length=1)
    power_kw: float = Field(gt=0)
    duration_slots: int = Field(gt=0)
    deadline_slot: int = Field(gt=0)


class Scenario(BaseModel):
    prices: List[float] = Field(min_length=1)
    interval_minutes: int = Field(default=15, gt=0)
    fixed_load_kw: float = Field(default=0, ge=0)
    battery_capacity_kwh: float = Field(gt=0)
    max_charge_kw: float = Field(gt=0)
    max_discharge_kw: float = Field(gt=0)
    initial_soc_kwh: float = Field(ge=0)
    reserve_soc_kwh: float = Field(default=0, ge=0)
    round_trip_efficiency: float = Field(default=0.9, gt=0, le=1)
    flexible_jobs: List[FlexibleJob] = Field(default_factory=list)

    @field_validator("initial_soc_kwh")
    @classmethod
    def initial_soc_within_capacity(cls, value: float, info):
        capacity = info.data.get("battery_capacity_kwh")
        if capacity is not None and value > capacity:
            raise ValueError("initial_soc_kwh cannot exceed battery_capacity_kwh")
        return value

    @field_validator("reserve_soc_kwh")
    @classmethod
    def reserve_within_capacity(cls, value: float, info):
        capacity = info.data.get("battery_capacity_kwh")
        if capacity is not None and value > capacity:
            raise ValueError("reserve_soc_kwh cannot exceed battery_capacity_kwh")
        return value


class ScheduleRequest(BaseModel):
    scenario: Scenario


app = FastAPI(title="ShiftOS API", version="0.1.0")


def _job_slots(job: FlexibleJob, prices: List[float]) -> List[int]:
    """Pick the cheapest contiguous window that meets a job deadline."""
    horizon = min(job.deadline_slot, len(prices))
    if horizon < job.duration_slots:
        raise HTTPException(422, f"job {job.id!r} cannot fit before its deadline")
    windows = range(horizon - job.duration_slots + 1)
    return list(min(windows, key=lambda start: sum(prices[start : start + job.duration_slots]))) + list(range(0))


def build_schedule(s: Scenario) -> dict:
    slots = len(s.prices)
    slot_hours = s.interval_minutes / 60
    jobs = {job.id: [False] * slots for job in s.flexible_jobs}
    for job in s.flexible_jobs:
        horizon = min(job.deadline_slot, slots)
        if horizon < job.duration_slots:
            raise HTTPException(422, f"job {job.id!r} cannot fit before its deadline")
        start = min(
            range(horizon - job.duration_slots + 1),
            key=lambda i: sum(s.prices[i : i + job.duration_slots]),
        )
        for i in range(start, start + job.duration_slots):
            jobs[job.id][i] = True

    soc = s.initial_soc_kwh
    charge = []
    discharge = []
    grid = []
    job_load = []
    for i, price in enumerate(s.prices):
        load = sum(job.power_kw for job in s.flexible_jobs if jobs[job.id][i])
        # Cheap hours charge; expensive hours discharge. The reserve is never used.
        if i < slots - 1 and price <= sorted(s.prices)[max(0, slots // 3 - 1)]:
            charge_kw = min(s.max_charge_kw, (s.battery_capacity_kwh - soc) / slot_hours)
        else:
            charge_kw = 0.0
        available = max(0.0, soc - s.reserve_soc_kwh)
        discharge_kw = min(s.max_discharge_kw, available * s.round_trip_efficiency / slot_hours) if price >= sorted(s.prices)[-max(1, slots // 3)] else 0.0
        soc = min(s.battery_capacity_kwh, soc + charge_kw * slot_hours * s.round_trip_efficiency)
        soc = max(s.reserve_soc_kwh, soc - discharge_kw * slot_hours / s.round_trip_efficiency)
        grid_kw = max(0.0, s.fixed_load_kw + load + charge_kw - discharge_kw)
        charge.append(round(charge_kw, 4))
        discharge.append(round(discharge_kw, 4))
        grid.append(round(grid_kw, 4))
        job_load.append(round(load, 4))

    baseline_cost = sum((s.fixed_load_kw + sum(j.power_kw for j in s.flexible_jobs if jobs[j.id][i])) * p * slot_hours for i, p in enumerate(s.prices))
    optimized_cost = sum(g * p * slot_hours for g, p in zip(grid, s.prices))
    return {
        "interval_minutes": s.interval_minutes,
        "charge_kw": charge,
        "discharge_kw": discharge,
        "grid_load_kw": grid,
        "flexible_load_kw": job_load,
        "jobs": {job_id: [i for i, active in enumerate(active_slots) if active] for job_id, active_slots in jobs.items()},
        "metrics": {
            "baseline_cost": round(baseline_cost, 2),
            "optimized_cost": round(optimized_cost, 2),
            "savings": round(baseline_cost - optimized_cost, 2),
            "baseline_peak_kw": round(max((s.fixed_load_kw + load for load in job_load), default=s.fixed_load_kw), 2),
            "optimized_peak_kw": round(max(grid, default=0), 2),
        },
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "shiftos-api"}


@app.post("/schedule")
def schedule(request: ScheduleRequest):
    return build_schedule(request.scenario)

