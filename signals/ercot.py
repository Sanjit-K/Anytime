"""Public ERCOT real-time settlement point price reader.

ERCOT publishes the current-day RT settlement point table publicly at
``real_time_spp.html``. The reader deliberately uses the public display rather
than requiring an API credential, which makes the hackathon demo reproducible.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
import urllib.request


ERCOT_REAL_TIME_SPP_URL = "https://www.ercot.com/content/cdr/html/real_time_spp.html"


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


def fetch_realtime_spp(zone: str = "HB_NORTH", timeout: int = 15) -> list[dict[str, Any]]:
    """Return current-day 15-minute ERCOT prices in $/MWh for one hub/zone."""

    request = urllib.request.Request(ERCOT_REAL_TIME_SPP_URL, headers={"User-Agent": "ShiftOS/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
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
            })
        except ValueError:
            continue
    return records
