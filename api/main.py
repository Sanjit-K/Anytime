"""Small HTTP API for the ShiftOS scheduling MVP.

The optimizer is intentionally kept behind ``build_schedule`` so the API can
be wired to the richer engine package without changing the request contract.
"""

from __future__ import annotations

from typing import List, Literal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from .spacetime import call_reducer, query_sql
from signals.ercot import fetch_actual_load, fetch_realtime_spp, interval_timestamp, ERCOT_ACTUAL_LOAD_URL
from signals.forecast import forecast_series
from signals.demand import forecast_demand
from signals.news_forecast import fetch_rss, score_with_nemotron, nemotron_status
from simulator.local_demo import demo
from . import demo_runtime
from engine.models import Battery as EngineBattery, Scenario as EngineScenario, Workload as EngineWorkload
from engine.robust import robust_optimize
from engine.models import Scenario as PlanScenario, Battery as PlanBattery, Workload as PlanWorkload
from engine.scheduler import compare_dispatch as engine_compare_dispatch


class FlexibleJob(BaseModel):
    id: str = Field(min_length=1)
    power_kw: float = Field(gt=0)
    duration_slots: int = Field(gt=0)
    deadline_slot: int = Field(gt=0)
    delay_penalty_per_slot: float = Field(default=0, ge=0)


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


class RobustScheduleRequest(ScheduleRequest):
    risk_aversion: float = Field(default=0.35, ge=0, le=2)


class TaskResult(BaseModel):
    workload_id: str = Field(min_length=1)
    actual_energy_kwh: float = Field(ge=0)
    actual_duration_slots: int = Field(gt=0)
    completed_slot: int = Field(ge=0)
    success: bool = True


app = FastAPI(title="ShiftOS API", version="0.2.0", lifespan=demo_runtime.lifespan)


@app.middleware("http")
async def protect_local_controls(request: Request, call_next):
    # The controller operates local USB hardware; browser control is same-origin.
    if request.url.path.startswith("/demo/") and request.method != "GET":
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Hardware controls require the local application origin"}, status_code=403)
    return await call_next(request)


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


def _engine_scenario(s: Scenario) -> EngineScenario:
    slot_hours = s.interval_minutes / 60
    battery = EngineBattery(
        capacity_kwh=s.battery_capacity_kwh,
        max_charge_kw=s.max_charge_kw,
        max_discharge_kw=s.max_discharge_kw,
        charge_efficiency=s.round_trip_efficiency ** 0.5,
        discharge_efficiency=s.round_trip_efficiency ** 0.5,
        initial_soc_kwh=s.initial_soc_kwh,
        reserve_kwh=s.reserve_soc_kwh,
    )
    return EngineScenario(
        prices=list(s.prices),
        fixed_load_kwh=[s.fixed_load_kw * slot_hours] * len(s.prices),
        battery=battery,
        workloads=[EngineWorkload(
            name=job.id,
            energy_kwh=job.power_kw * job.duration_slots * slot_hours,
            duration_slots=job.duration_slots,
            deadline_slot=job.deadline_slot,
            critical=False,
            delay_penalty_per_slot=job.delay_penalty_per_slot,
        ) for job in s.flexible_jobs],
        interval_hours=slot_hours,
    )


@app.get("/health")
def health():
    result = query_sql("SELECT * FROM schedule LIMIT 1")
    connected = result is not None and not (isinstance(result, dict) and "error" in result)
    return {"status": "ok", "service": "shiftos-api", "spacetime": connected}


@app.get("/state")
def state():
    """Return the live public Spacetime state for the operator dashboard."""
    queries = {
        # SpacetimeDB's SQL surface is intentionally kept to portable SELECTs;
        # the dashboard sorts the returned rows client-side.
        "prices": "SELECT * FROM price_signal LIMIT 96",
        "demand": "SELECT * FROM demand_signal LIMIT 96",
        "schedules": "SELECT * FROM schedule LIMIT 10",
        "tasks": "SELECT * FROM task_run LIMIT 20",
    }
    results = {name: query_sql(sql) for name, sql in queries.items()}
    connected = all(value is not None and not (isinstance(value, dict) and "error" in value) for value in results.values())
    return {"connected": connected, "database": __import__('os').getenv("SPACETIME_DATABASE"), "results": results}


@app.get("/ercot/prices")
def ercot_prices(zone: str = "HB_NORTH"):
    """Fetch current public ERCOT real-time prices for the requested hub/zone."""
    try:
        records = fetch_realtime_spp(zone)
    except Exception as exc:
        raise HTTPException(502, f"ERCOT price feed unavailable: {exc}") from exc
    return {"source": "ERCOT", "zone": zone, "unit": "USD/MWh", "records": records}


@app.get("/ercot/load")
def ercot_load(zone: str = "TOTAL"):
    """Fetch current public ERCOT hourly actual load."""
    try:
        records = fetch_actual_load(zone)
    except Exception as exc:
        raise HTTPException(502, f"ERCOT load feed unavailable: {exc}") from exc
    return {"source": "ERCOT", "zone": zone, "unit": "MW", "records": records}


@app.get("/forecast")
def forecast(zone: str = "TOTAL", horizon: int = 8, include_news: bool = True):
    """Create a short-horizon load forecast from ERCOT data and news context."""
    if horizon < 1 or horizon > 96:
        raise HTTPException(422, "horizon must be between 1 and 96")
    try:
        records = fetch_actual_load(zone)
    except Exception as exc:
        raise HTTPException(502, f"ERCOT load feed unavailable: {exc}") from exc
    values = [float(record["load_mw"]) for record in records]
    news = []
    if include_news:
        try:
            headlines = fetch_rss(f"ERCOT electricity demand {zone}", limit=6)
            news = score_with_nemotron(headlines)
        except Exception:
            news = []
    baseline = forecast_series(values, horizon)
    adjusted = forecast_demand(baseline, news, horizon=horizon) if news else baseline
    nemotron_scored = any(signal.confidence > 0 for signal in news)
    return {
        "source": "ERCOT actual load + bounded trend + Nemotron news adjustment" if nemotron_scored else ("ERCOT actual load + bounded trend + headlines collected" if news else "ERCOT actual load + bounded trend"),
        "zone": zone,
        "unit": "MW",
        "observed": records,
        "forecast": adjusted,
        "baseline_forecast": baseline,
        "news": [signal.__dict__ for signal in news],
    }


@app.get("/nemotron/status")
def nemotron_connection():
    """Expose configuration state without returning endpoint URLs or secrets."""
    return nemotron_status()


@app.get("/news/signals")
def news_signals(zone: str = "ERCOT", limit: int = 6):
    """Fetch current headlines and score them with the configured Nemotron NIM."""
    if not 1 <= limit <= 10:
        raise HTTPException(422, "limit must be between 1 and 10")
    status=nemotron_status()
    if not status["configured"]:
        raise HTTPException(503, status["endpoint_hint"])
    try:
        headlines=fetch_rss(f"ERCOT electricity demand {zone}",limit=limit)
        if not headlines:
            return {"status":"no_headlines","zone":zone,"signals":[],"model":status["model"]}
        signals=score_with_nemotron(headlines)
        if not signals:
            raise ValueError("Nemotron returned no valid scores")
        return {"status":"scored","zone":zone,"model":status["model"],
            "source":"Google News RSS headlines scored by configured Nemotron endpoint",
            "signals":[signal.__dict__ for signal in signals],
            "interpretation":"Qualitative news context only; these scores are not a numerical ERCOT load or price forecast."}
    except Exception as exc:
        raise HTTPException(502,f"Nemotron news scoring failed: {type(exc).__name__}: {exc}") from exc


@app.get("/demo/state")
def demo_state():
    """Read-only snapshot; the background clock advances the experiment."""
    return demo_runtime.snapshot()


@app.get("/demo/price-curve")
def demo_price_curve():
    """Return 24 hours of dated published ERCOT settlement prices."""
    from signals.replay import historical_price_replay
    try:
        return historical_price_replay(24, "HB_NORTH")
    except Exception as exc:
        raise HTTPException(502, f"ERCOT historical replay unavailable: {exc}") from exc


@app.get("/demo/demand-curve")
def demo_demand_curve():
    """Return published ERCOT system actual load (not a forecast)."""
    try:
        rows=fetch_actual_load("TOTAL")
        for row in rows:
            row["observed_at"]=interval_timestamp(row["oper_day"],row["hour_ending"]).isoformat()
        if not rows:
            raise ValueError("ERCOT returned no actual system-load observations")
        return {"kind":"observed_actual_load","zone":"TOTAL","unit":"MW",
            "source":"ERCOT actual load","source_url":ERCOT_ACTUAL_LOAD_URL,
            "fetched_at":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
            "records":rows,"forecast":False,
            "note":"ERCOT-wide hourly actual demand, not local data-center load and not a forecast."}
    except Exception as exc:
        raise HTTPException(502,f"ERCOT actual system load unavailable: {exc}") from exc


class CompareRequest(BaseModel):
    prices_usd_mwh: List[float] = Field(min_length=4, max_length=96)
    interval_minutes: int = Field(default=15, ge=1, le=60)
    load_kw: float = Field(gt=0, le=100000)
    battery_kwh: float = Field(gt=0, le=1000000)
    charge_kw: float = Field(gt=0, le=100000)
    discharge_kw: float = Field(gt=0, le=100000)
    initial_soc_pct: float = Field(default=60, ge=0, le=100)
    reserve_pct: float = Field(default=20, ge=0, le=100)
    round_trip_efficiency: float = Field(default=0.9, gt=0.01, le=1)
    degradation_usd_kwh: float = Field(default=0, ge=0, le=10)
    demand_charge_usd_kw: float = Field(default=0, ge=0, le=10000)
    flexible_workload_kwh: float = Field(default=0, ge=0, le=1000000)
    workload_deadline_slot: int = Field(default=95, ge=1, le=95)


@app.post("/compare-dispatch")
def compare_dispatch(request: CompareRequest):
    """Replay identical prices/load against grid, threshold, and optimizer."""
    from engine.models import Scenario as EngineScenario, Battery as EngineBattery, Workload as EngineWorkload
    prices = request.prices_usd_mwh
    n = len(prices); hours = request.interval_minutes / 60
    if any(p < 0 for p in prices):
        raise HTTPException(422, "Negative price values are not supported in this comparison")
    reserve = request.battery_kwh * request.reserve_pct / 100
    initial = request.battery_kwh * request.initial_soc_pct / 100
    if reserve > initial:
        raise HTTPException(422, "Initial state of charge must be at or above the reserve")
    efficiency = request.round_trip_efficiency ** .5
    battery = EngineBattery(request.battery_kwh, request.charge_kw, request.discharge_kw,
        charge_efficiency=efficiency, discharge_efficiency=efficiency,
        initial_soc_kwh=initial, reserve_kwh=reserve)
    fixed = [request.load_kw * hours] * n
    workloads = []
    if request.flexible_workload_kwh:
        workloads.append(EngineWorkload("flexible_batch", request.flexible_workload_kwh,
            release_slot=0, deadline_slot=min(request.workload_deadline_slot, n-1),
            duration_slots=1, critical=False))
    scenario = EngineScenario(prices, fixed, workloads, battery, hours)
    try:
        result = engine_compare_dispatch(scenario,
            degradation_usd_per_kwh=request.degradation_usd_kwh,
            demand_charge_usd_per_kw=request.demand_charge_usd_kw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    normalized={}
    for key, name in (("grid_only","Grid only"),("threshold","Threshold control"),("optimized","ShiftOS optimizer")):
        row=result[key]
        normalized[key]={"name":name,"energy_cost_usd":row["energy_cost_usd"],
            "demand_charge_usd":row["demand_charge_usd"],"degradation_usd":row["degradation_usd"],
            "terminal_energy_cost_usd":row["terminal_energy_cost_usd"],"total_usd":row["total_cost_usd"],
            "peak_grid_kw":row["peak_grid_kw"],"grid_kwh":row["grid_kwh"],
            "battery_soc_kwh":row["battery_soc_kwh"],"workload_slots":row["workload_slots"],
            "battery_discharge_kwh":row["battery_discharge_kwh"]}
    normalized["assumptions"]=result["assumptions"]
    return {"kind":"historical_replay", "slots":n,"interval_minutes":request.interval_minutes,
        "unit_price":"USD/MWh","cost_unit":"USD", **normalized,
        "assumptions":{"load_kw":request.load_kw,"battery_kwh":request.battery_kwh,
        "initial_soc_pct":request.initial_soc_pct,"reserve_pct":request.reserve_pct,
        "round_trip_efficiency":request.round_trip_efficiency,
        "degradation_usd_kwh":request.degradation_usd_kwh,
        "demand_charge_usd_kw":request.demand_charge_usd_kw},
        "note":"Historical replay, not a forecast. All three strategies run the same workload and begin at the same state of charge. Demand charges use horizon peak kW; degradation uses battery discharge throughput. Cost = USD/MWh × kWh / 1000; terminal energy deficit is replenished at the final interval price."}


class JobCommand(BaseModel):
    action: Literal["start", "pause", "resume", "stop"]
    target: Literal["auto", "arduino", "mac"] = "auto"
    duration_seconds: int = Field(default=60, ge=5, le=300)


@app.post("/demo/job")
def demo_job(command: JobCommand):
    try:
        if command.action == "start":
            demo_runtime.hardware.start(target=command.target, duration_seconds=command.duration_seconds)
        else:
            getattr(demo_runtime.hardware, command.action)()
        demo.advance(demo_runtime.hardware.snapshot())
        return demo_runtime.snapshot()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


class DispatchCommand(BaseModel):
    mode: Literal["auto", "charge", "discharge", "hold"]


@app.post("/demo/dispatch")
def demo_dispatch(command: DispatchCommand):
    demo.advance(demo_runtime.hardware.snapshot())
    demo.control(command.mode)
    return demo_runtime.snapshot()


@app.post("/demo/configure")
def demo_configure(assumptions: dict):
    try:
        demo.configure(**assumptions)
        demo.advance(demo_runtime.hardware.snapshot())
        return demo_runtime.snapshot()
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/robust-schedule")
def robust_schedule(request: RobustScheduleRequest):
    """Plan against low/base/scarcity price futures with explanations."""
    result = robust_optimize(_engine_scenario(request.scenario), risk_aversion=request.risk_aversion)
    return result.as_dict()


@app.post("/schedule")
def schedule(request: ScheduleRequest):
    result = build_schedule(request.scenario)
    call_reducer("publish_schedule", {
        "runId": f"api-{int(__import__('time').time() * 1000)}",
        "createdAt": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        "baselineCost": result["metrics"]["baseline_cost"],
        "optimizedCost": result["metrics"]["optimized_cost"],
        "savings": result["metrics"]["savings"],
        "status": "planned",
        "planJson": __import__('json').dumps(result),
    })
    return result


@app.post("/task-result")
def task_result(result: TaskResult):
    """Record post-task telemetry and make it available for replanning."""
    call_reducer("record_task_run", {
        "workloadId": result.workload_id,
        "actualEnergyKwh": result.actual_energy_kwh,
        "actualDurationSlots": result.actual_duration_slots,
        "completedSlot": result.completed_slot,
        "success": result.success,
        "recordedAt": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
    })
    return {"accepted": True, "requires_replan": not result.success}


@app.get("/", include_in_schema=False)
def dashboard():
    # Serve only the dashboard, never the repository or local environment files.
    return FileResponse(Path(__file__).resolve().parents[1] / "index.html", headers={"Cache-Control": "no-store"})

