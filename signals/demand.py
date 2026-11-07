"""Small demand-forecast helpers used before an optimization run."""

from __future__ import annotations

from statistics import mean

from .news_forecast import NewsSignal


def forecast_demand(base_load_kw: list[float], news: list[NewsSignal], horizon: int | None = None) -> list[float]:
    """Blend recent load with a transparent news pressure adjustment."""

    if not base_load_kw:
        return []
    horizon = horizon or len(base_load_kw)
    pressure = sum(signal.demand_impact * signal.confidence for signal in news)
    normalized = max(-0.25, min(0.25, pressure / max(1, len(news))))
    recent = mean(base_load_kw[-min(4, len(base_load_kw)):])
    return [round(max(0.0, load * (1 + normalized) if i < len(base_load_kw) else recent * (1 + normalized)), 4) for i, load in enumerate((base_load_kw + [recent] * horizon)[:horizon])]
