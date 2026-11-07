"""A local digital twin for the ShiftOS physical proof of concept."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from signals.ercot import fetch_realtime_spp


@dataclass
class LocalDemo:
    prices: list[float] = field(default_factory=list)
    tick_index: int = 0
    soc_kwh: float = 60.0
    capacity_kwh: float = 100.0
    reserve_kwh: float = 30.0
    charge_kw: float = 25.0
    discharge_kw: float = 25.0

    def _ensure_prices(self) -> None:
        if self.prices:
            return
        try:
            self.prices = [row["price"] for row in fetch_realtime_spp("HB_NORTH")]
        except Exception:
            self.prices = [35, 32, 30, 29, 31, 42, 58, 91, 120, 145, 132, 98]

    def tick(self) -> dict[str, Any]:
        self._ensure_prices()
        price = self.prices[self.tick_index % len(self.prices)]
        low = sorted(self.prices)[max(0, len(self.prices) // 3 - 1)]
        high = sorted(self.prices)[min(len(self.prices) - 1, 2 * len(self.prices) // 3)]
        if price <= low and self.soc_kwh < self.capacity_kwh:
            mode = "charging"
            grid_to_battery = min(self.charge_kw, (self.capacity_kwh - self.soc_kwh) * 0.92)
            self.soc_kwh = min(self.capacity_kwh, self.soc_kwh + grid_to_battery * 0.92)
            battery_to_workload = 0.0
            flexible = "running"
        elif price >= high and self.soc_kwh > self.reserve_kwh:
            mode = "discharging"
            grid_to_battery = 0.0
            battery_to_workload = min(self.discharge_kw, self.soc_kwh - self.reserve_kwh)
            self.soc_kwh = max(self.reserve_kwh, self.soc_kwh - battery_to_workload)
            flexible = "deferred"
        else:
            mode = "steady"
            grid_to_battery = 0.0
            battery_to_workload = 0.0
            flexible = "running"
        self.tick_index += 1
        return {
            "tick": self.tick_index,
            "price_usd_mwh": round(price, 2),
            "mode": mode,
            "grid_to_battery_kw": round(grid_to_battery, 2),
            "battery_to_workload_kw": round(battery_to_workload, 2),
            "battery_soc_percent": round(self.soc_kwh / self.capacity_kwh * 100, 1),
            "reserve_percent": round(self.reserve_kwh / self.capacity_kwh * 100, 1),
            "critical_workload": "running",
            "flexible_workload": flexible,
            "source": "ERCOT HB_NORTH" if self.prices else "synthetic fallback",
        }


demo = LocalDemo()
