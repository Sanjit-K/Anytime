"""Local hardware experiment. Polling the browser never advances the simulation."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from hardware import HardwareController
from simulator.local_demo import demo
from .telemetry import TelemetryRecorder

hardware = HardwareController()
recorder = TelemetryRecorder()
runtime = {"last_tick_at": None, "error": None}
log = logging.getLogger(__name__)


async def control_loop():
    while True:
        try:
            state = await asyncio.to_thread(hardware.snapshot)
            await asyncio.to_thread(demo.advance, state)
            runtime.update(last_tick_at=datetime.now(timezone.utc).isoformat(), error=None)
        except Exception as exc:
            runtime["error"] = str(exc)
            log.exception("Hardware experiment update failed")
        await asyncio.sleep(1)


async def market_loop():
    while True:
        try:
            await asyncio.to_thread(demo.refresh_prices)
        except Exception:
            log.exception("ERCOT refresh failed")
        await asyncio.sleep(60)


async def persistence_loop():
    while True:
        try:
            await asyncio.to_thread(recorder.record, demo.snapshot())
        except Exception:
            log.exception("SpacetimeDB persistence failed")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app):
    # Fetch once before integration begins so the sample can be priced from its
    # first second, when ERCOT is available.
    await asyncio.to_thread(demo.refresh_prices)
    tasks = [asyncio.create_task(fn()) for fn in (control_loop, market_loop, persistence_loop)]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.to_thread(hardware.stop)


def snapshot():
    result = demo.snapshot()
    result["persistence"] = recorder.snapshot()
    result["runtime"] = dict(runtime)
    return result
