"""Fetch ERCOT real-time prices and persist them to SpacetimeDB.

Usage:
    python scripts/ingest_ercot.py --database shiftos --zone HB_NORTH

The Spacetime CLI currently provides the most reliable cross-platform reducer
argument encoding, so this script uses ``spacetime call`` rather than relying
on the unstable raw HTTP call endpoint.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone

from signals.ercot import fetch_realtime_spp


def persist_prices(database: str, zone: str) -> int:
    records = fetch_realtime_spp(zone)
    observed_at = datetime.now(timezone.utc).isoformat()
    for slot, record in enumerate(records):
        args = [
            "spacetime", "call", database, "ingest_price",
            zone, str(slot), str(record["price"]), record["source"], observed_at, "-y",
        ]
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=os.getenv("SPACETIME_DATABASE", "shiftos"))
    parser.add_argument("--zone", default="HB_NORTH")
    args = parser.parse_args()
    count = persist_prices(args.database, args.zone)
    print(f"Persisted {count} ERCOT {args.zone} price intervals to {args.database}.")


if __name__ == "__main__":
    main()
