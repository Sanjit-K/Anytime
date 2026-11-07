#!/usr/bin/env python3
"""A bounded SHA-256 job; JSON-line commands on stdin, telemetry on stdout.

Runs unchanged on the UNO Q Linux processor or macOS. Power is not measured.
Only one CPU thread is used, with a cooperative duty limit and 15-minute wall cap.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import select
import sys
import time


def run(duration_seconds: float, duty_cycle: float = 0.35) -> None:
    duration_seconds = max(1.0, min(float(duration_seconds), 300.0))
    duty_cycle = max(0.05, min(float(duty_cycle), 0.5))
    started = time.monotonic()
    active = 0.0
    cpu = 0.0
    count = 0
    state = "running"
    digest = bytes(4096)
    last_emit = 0.0

    def emit() -> None:
        print(json.dumps({
            "status": state, "completed_units": count,
            "unit": "SHA-256 hashes of 4 KiB blocks",
            "progress_pct": min(100.0, active / duration_seconds * 100),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "active_seconds": round(active, 3), "cpu_seconds": round(cpu, 3),
            "duration_seconds": duration_seconds, "duty_cycle": duty_cycle,
            "hashes_per_second": round(count / active, 1) if active else 0,
            "result_digest": digest[:32].hex() if count else None,
            "telemetry_source": "worker measurement",
        }), flush=True)

    emit()
    while state not in ("completed", "stopped"):
        cycle = time.monotonic()
        if cycle - started >= 900:
            state = "stopped"
            break
        if select.select([sys.stdin], [], [], 0)[0]:
            line = sys.stdin.readline()
            if not line:
                state = "stopped"
                break
            try:
                action = json.loads(line).get("action")
            except (ValueError, AttributeError):
                action = None
            if action == "stop":
                state = "stopped"
                break
            if action == "pause":
                state = "paused"
            elif action == "resume":
                state = "running"
            emit()
        if state == "running":
            cpu_started = time.process_time()
            work_until = cycle + min(0.1, duration_seconds - active) * duty_cycle
            while time.monotonic() < work_until:
                digest = hashlib.sha256(digest).digest() + bytes(4064)
                count += 1
            cpu += time.process_time() - cpu_started
            time.sleep(max(0, min(0.1, duration_seconds - active) - (time.monotonic() - cycle)))
            active = min(duration_seconds, active + time.monotonic() - cycle)
            if active >= duration_seconds:
                state = "completed"
        else:
            time.sleep(0.05)
        if time.monotonic() - last_emit >= 0.5:
            emit()
            last_emit = time.monotonic()
    emit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--duty-cycle", type=float, default=0.35)
    args = parser.parse_args()
    run(args.duration, args.duty_cycle)
