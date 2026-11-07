"""Observed ERCOT price data for replay. No future prices are generated here."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .ercot import fetch_spp_replay


def historical_price_replay(hours: int = 24, zone: str = "HB_NORTH", *,
                            now: datetime | None = None,
                            fetcher: Callable[..., dict[str, Any]] = fetch_spp_replay) -> dict[str, Any]:
    """Return dated observed intervals and data coverage for a replay plot."""
    response = fetcher(hours=hours, zone=zone, now=now)
    records = response.get("records", [])
    values = [float(row["price"]) for row in records]
    if not values:
        raise ValueError("Replay requires at least one published ERCOT price")
    times = [datetime.fromisoformat(row["observed_at"]) for row in records]
    expected = hours * 4
    return {
        **response,
        "coverage": {
            "observations": len(records),
            "expected_15m_intervals": expected,
            "fraction": min(1., len(records) / expected),
            "first_observation": min(times).isoformat(),
            "last_observation": max(times).isoformat(),
            "minimum_usd_mwh": min(values),
            "maximum_usd_mwh": max(values),
        },
        "note": "Every point is a published historical ERCOT settlement-point price. Missing intervals are omitted; this is not a forecast.",
    }
