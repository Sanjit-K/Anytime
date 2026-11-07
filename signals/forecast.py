"""Transparent short-horizon forecasts for the demo controller."""

from __future__ import annotations

from statistics import mean


def forecast_series(values: list[float], horizon: int, window: int = 4) -> list[float]:
    """Forecast with a bounded recent-level/trend model.

    This is intentionally explainable: the next point starts at the recent
    mean and follows the average recent slope, capped to avoid runaway plans.
    """

    if horizon <= 0:
        return []
    if not values:
        return [0.0] * horizon
    recent = values[-max(1, window):]
    level = mean(recent)
    slope = (recent[-1] - recent[0]) / max(1, len(recent) - 1)
    cap = max(abs(level) * 0.15, 1.0)
    slope = max(-cap, min(cap, slope))
    return [round(max(0.0, level + slope * (step + 1)), 4) for step in range(horizon)]
