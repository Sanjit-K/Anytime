"""Public ERCOT real-time settlement point price reader.

ERCOT publishes the current-day RT settlement point table publicly at
``real_time_spp.html``. The reader deliberately uses the public display rather
than requiring an API credential, which makes the hackathon demo reproducible.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
import ssl
import certifi
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


ERCOT_REAL_TIME_SPP_URL = "https://www.ercot.com/content/cdr/html/real_time_spp.html"
ERCOT_ACTUAL_LOAD_URL = "https://www.ercot.com/content/cdr/html/actual_loads_of_forecast_zones"
ERCOT_MARKET_PRICES_URL = "https://www.ercot.com/mktinfo/prices"


def interval_timestamp(oper_day: str, interval_ending: str) -> datetime:
    """Interpret an ERCOT interval ending in ERCOT local time (DST aware).

    Ambiguous repeated fall-back intervals are marked with ``*`` by the
    published report and map to the second occurrence. 24:00 belongs to the
    end of the stated operating day.
    """
    day = datetime.strptime(oper_day.strip(), "%m/%d/%Y").date()
    raw = interval_ending.strip().replace(":", "")
    repeated = raw.endswith("*")
    raw = raw.rstrip("*").zfill(4)
    if not raw.isdigit() or len(raw) != 4:
        raise ValueError(f"invalid ERCOT interval ending: {interval_ending!r}")
    hour, minute = int(raw[:2]), int(raw[2:])
    if hour > 24 or minute > 59 or (hour == 24 and minute != 0):
        raise ValueError(f"invalid ERCOT interval ending: {interval_ending!r}")
    local = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=minute)
    return local.replace(tzinfo=ZoneInfo("America/Chicago"), fold=int(repeated)).astimezone(timezone.utc)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = None


def _fetch_spp_url(url: str, zone: str, timeout: int) -> list[dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": "ShiftOS/0.1"})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())) as response:
        parser = _TableParser()
        parser.feed(response.read().decode("utf-8", "ignore"))
    if not parser.rows:
        return []
    header = parser.rows[0]
    if zone not in header:
        raise ValueError(f"unknown ERCOT settlement point: {zone}")
    price_index = header.index(zone)
    records: list[dict[str, Any]] = []
    for row in parser.rows[1:]:
        if len(row) <= price_index or len(row) < 2:
            continue
        try:
            records.append({
                "oper_day": row[0],
                "interval_ending": row[1],
                "region": zone,
                "price": float(row[price_index]),
                "source": "ERCOT real-time SPP",
                "source_url": url,
            })
        except ValueError:
            continue
    return records


def fetch_realtime_spp(zone: str = "HB_NORTH", timeout: int = 15) -> list[dict[str, Any]]:
    """Return current-day 15-minute ERCOT prices in $/MWh for one hub/zone."""
    return _fetch_spp_url(ERCOT_REAL_TIME_SPP_URL, zone, timeout)


def fetch_spp_replay(hours: int = 24, zone: str = "HB_NORTH", *, now: datetime | None = None,
                     timeout: int = 15) -> dict[str, Any]:
    """Fetch actual ERCOT daily display archives for an observed-time replay.

    The date-specific report is an ERCOT-hosted historical current-day display
    (also exposed via the official market prices page). This is replay data,
    not a forecast. The unauthenticated HTML view only supports current and
    recently archived dates reliably; no synthetic values are inserted.
    """
    if not isinstance(hours, int) or not 1 <= hours <= 48:
        raise ValueError("hours must be an integer between 1 and 48")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    start = now - timedelta(hours=hours)
    local_start = start.astimezone(ZoneInfo("America/Chicago")).date()
    local_end = now.astimezone(ZoneInfo("America/Chicago")).date()
    records = []
    errors = []
    day = local_start
    while day <= local_end:
        url = f"https://www.ercot.com/content/cdr/html/{day:%Y%m%d}_real_time_spp.html"
        try:
            for row in _fetch_spp_url(url, zone, timeout):
                row["observed_at"] = interval_timestamp(row["oper_day"], row["interval_ending"]).isoformat()
                stamp = datetime.fromisoformat(row["observed_at"])
                if start < stamp <= now:
                    records.append(row)
        except Exception as exc:
            errors.append({"operating_day": day.isoformat(), "error": str(exc)})
        day += timedelta(days=1)
    records.sort(key=lambda row: row["observed_at"])
    if not records:
        raise RuntimeError("ERCOT did not return published prices for the requested replay window" +
                           (f": {errors}" if errors else ""))
    return {
        "kind": "observed_historical_replay", "source": "ERCOT date-specific Real-Time SPP display",
        "source_url": ERCOT_MARKET_PRICES_URL, "zone": zone, "unit": "USD/MWh",
        "interval_minutes": 15, "requested_hours": hours, "start": start.isoformat(),
        "end": now.isoformat(), "records": records, "errors": errors,
        "forecast": False,
    }


def fetch_actual_load(zone: str = "TOTAL", timeout: int = 15) -> list[dict[str, Any]]:
    """Return current-day hourly ERCOT actual load in MW for a forecast zone."""

    request = urllib.request.Request(ERCOT_ACTUAL_LOAD_URL, headers={"User-Agent": "ShiftOS/0.1"})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())) as response:
        parser = _TableParser()
        parser.feed(response.read().decode("utf-8", "ignore"))
    if not parser.rows:
        return []
    header = parser.rows[0]
    if zone not in header:
        raise ValueError(f"unknown ERCOT forecast zone: {zone}")
    load_index = header.index(zone)
    records: list[dict[str, Any]] = []
    for row in parser.rows[1:]:
        if len(row) <= load_index or len(row) < 2:
            continue
        try:
            records.append({
                "oper_day": row[0],
                "hour_ending": row[1],
                "region": zone,
                "load_mw": float(row[load_index]),
                "source": "ERCOT actual load",
            })
        except ValueError:
            continue
    return records
