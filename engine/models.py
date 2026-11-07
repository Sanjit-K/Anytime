from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Battery:
    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    charge_efficiency: float = 0.92
    discharge_efficiency: float = 0.92
    initial_soc_kwh: float = 0.0
    reserve_kwh: float = 0.0

    def __post_init__(self) -> None:
        if self.capacity_kwh <= 0 or self.max_charge_kw <= 0 or self.max_discharge_kw <= 0:
            raise ValueError("battery capacity and rates must be positive")
        if not 0 < self.charge_efficiency <= 1 or not 0 < self.discharge_efficiency <= 1:
            raise ValueError("battery efficiencies must be in (0, 1]")
        if not 0 <= self.reserve_kwh <= self.capacity_kwh:
            raise ValueError("reserve must be between zero and capacity")
        if not self.reserve_kwh <= self.initial_soc_kwh <= self.capacity_kwh:
            raise ValueError("initial state of charge must meet reserve and capacity")


@dataclass(frozen=True)
class Workload:
    name: str
    energy_kwh: float
    release_slot: int = 0
    deadline_slot: int | None = None
    duration_slots: int = 1
    critical: bool = False

    def __post_init__(self) -> None:
        if not self.name or self.energy_kwh < 0 or self.duration_slots < 1:
            raise ValueError("workload name, energy, and duration are invalid")
        if self.release_slot < 0:
            raise ValueError("release slot cannot be negative")
        if self.deadline_slot is not None and self.deadline_slot < self.release_slot:
            raise ValueError("deadline must be at or after release")


@dataclass(frozen=True)
class Scenario:
    prices: list[float]
    fixed_load_kwh: list[float]
    workloads: list[Workload] = field(default_factory=list)
    battery: Battery | None = None
    interval_hours: float = 1.0

    def __post_init__(self) -> None:
        if not self.prices or len(self.prices) != len(self.fixed_load_kwh):
            raise ValueError("prices and fixed load must have the same non-zero length")
        if any(p < 0 for p in self.prices) or any(k < 0 for k in self.fixed_load_kwh):
            raise ValueError("prices and loads cannot be negative")
        if self.interval_hours <= 0:
            raise ValueError("interval_hours must be positive")

    @property
    def slots(self) -> int:
        return len(self.prices)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Scenario":
        battery = payload.get("battery")
        return cls(
            prices=list(payload["prices"]),
            fixed_load_kwh=list(payload["fixed_load_kwh"]),
            workloads=[Workload(**w) for w in payload.get("workloads", [])],
            battery=Battery(**battery) if battery else None,
            interval_hours=payload.get("interval_hours", 1.0),
        )
