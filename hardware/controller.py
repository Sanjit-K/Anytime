"""Read-only discovery and explicitly launched, bounded real compute jobs."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(args: list[str], timeout: float = 5) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def read_mac_battery() -> dict:
    """Read pmset only. No charging, sleep, or power-source settings are changed."""
    try:
        result = _run(["pmset", "-g", "batt"])
        match = re.search(r"(\d+)%;\s*([^;]+);", result.stdout)
        source = re.search(r"Now drawing from '([^']+)'", result.stdout)
        if result.returncode or not match:
            raise ValueError("Battery telemetry is unavailable")
        state = match.group(2).strip()
        return {"available": True, "percent": int(match.group(1)),
                "power_source": source.group(1) if source else None,
                "charging": state == "charging", "state": state,
                "source": "macOS pmset", "observed_at": _now(),
                "power_watts": None, "capacity_wh": None}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"available": False, "percent": None, "power_source": None,
                "charging": None, "state": "unavailable", "reason": str(exc),
                "source": "macOS pmset", "observed_at": _now(),
                "power_watts": None, "capacity_wh": None}


class HardwareController:
    """One real job at a time; never silently substitute a Mac for the Arduino."""

    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._serial = None
        self._last_discovery = 0.0
        self._device = {"available": False, "status": "unchecked", "name": "Arduino UNO Q", "reason": "Discovery pending"}
        self._job = {"status": "idle", "target": None, "completed_units": 0,
                     "progress_pct": 0, "elapsed_seconds": 0, "active_seconds": 0,
                     "cpu_seconds": 0, "duration_seconds": None, "job_id": None}

    def _discover(self, force: bool = False):
        if not force and time.monotonic() - self._last_discovery < 5:
            return
        self._last_discovery = time.monotonic()
        adb = shutil.which("adb")
        self._serial = None
        if not adb:
            self._device = {"available": False, "status": "unavailable", "name": "Arduino UNO Q", "reason": "adb is not installed"}
            return
        try:
            result = _run([adb, "devices"], timeout=8)
            connected = [line.split()[0] for line in result.stdout.splitlines()[1:]
                         if len(line.split()) >= 2 and line.split()[1] == "device"]
            for serial in connected:
                info = _run([adb, "-s", serial, "shell", "cat /proc/device-tree/model; printf '\\n'; command -v python3"], timeout=5)
                details = info.stdout.replace("\x00", "").strip()
                model = details.splitlines()[0] if details else ""
                if "arduino" in model.lower() and "/" in details.splitlines()[-1]:
                    self._serial = serial
                    self._device = {"available": True, "status": "connected", "name": "Arduino UNO Q", "model": model,
                                    "transport": "ADB / USB", "runtime": "Python 3 on board Linux", "reason": None,
                                    "observed_at": _now()}
                    return
            reason = "No accessible Arduino Linux board with Python 3 found"
            if "unauthorized" in result.stdout:
                reason = "ADB device is unauthorized; no connection was attempted"
            self._device = {"available": False, "status": "unavailable", "name": "Arduino UNO Q", "reason": reason, "observed_at": _now()}
        except (OSError, subprocess.SubprocessError) as exc:
            self._device = {"available": False, "status": "unavailable", "name": "Arduino UNO Q", "reason": str(exc), "observed_at": _now()}

    def snapshot(self) -> dict:
        with self._lock:
            self._discover()
            job = dict(self._job)
            device = dict(self._device)
        return {"device": device, "job": job, "mac_battery": read_mac_battery(),
                "observed_at": _now(), "power_control": "simulated",
                "power_measurement": "unavailable", "actual_power_switching": False}

    def start(self, target: str = "auto", duration_seconds: float = 60) -> dict:
        if target not in {"auto", "arduino", "mac"}:
            raise ValueError("target must be auto, arduino, or mac")
        if not math.isfinite(duration_seconds) or not 1 <= duration_seconds <= 300:
            raise ValueError("duration_seconds must be between 1 and 300")
        with self._lock:
            if self._process and self._process.poll() is None:
                raise ValueError("A job is already running; stop it before starting another")
            self._discover(force=True)
            worker = str(Path(__file__).with_name("worker.py"))
            job_id = uuid4().hex
            if target in {"auto", "arduino"}:
                if not self._device["available"]:
                    raise ValueError(self._device.get("reason", "Arduino unavailable"))
                target = "arduino"
                adb = shutil.which("adb")
                remote = f"/tmp/shiftos-worker-{job_id}.py"
                push = _run([adb, "-s", self._serial, "push", worker, remote], timeout=15)
                if push.returncode:
                    raise RuntimeError("Could not copy ShiftOS worker to Arduino")
                # Only task-owned /tmp file is removed; no firmware or service configuration changes.
                shell = f"python3 -u {remote} --duration {duration_seconds}; rm -f {remote}"
                command = [adb, "-s", self._serial, "shell", "-T", shell]
            else:
                command = [sys.executable, "-u", worker, "--duration", str(duration_seconds)]
            self._job = {"status": "starting", "target": target, "job_id": job_id,
                         "completed_units": 0, "progress_pct": 0, "elapsed_seconds": 0,
                         "active_seconds": 0, "cpu_seconds": 0, "duration_seconds": duration_seconds,
                         "started_at": _now(), "telemetry_source": "worker measurement"}
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, bufsize=1)
            self._process = process
            threading.Thread(target=self._read, args=(process, job_id), daemon=True).start()
        return self.snapshot()

    def _read(self, process, job_id):
        try:
            for line in process.stdout:
                try:
                    telemetry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(telemetry, dict) or "status" not in telemetry:
                    continue
                with self._lock:
                    if self._job.get("job_id") == job_id:
                        self._job.update(telemetry)
                        self._job["observed_at"] = _now()
            code = process.wait()
            with self._lock:
                if self._job.get("job_id") == job_id and self._job["status"] not in {"completed", "stopped"}:
                    self._job["status"] = "error"
                    self._job["error"] = f"Worker disconnected or exited (code {code})"
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()

    def _control(self, action: str) -> dict:
        with self._lock:
            if not self._process or self._process.poll() is not None:
                if action == "stop":
                    return self.snapshot()
                raise ValueError("No active worker")
            try:
                self._process.stdin.write(json.dumps({"action": action}) + "\n")
                self._process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise ValueError("Worker connection is unavailable") from exc
        # Wait briefly for the worker's measured acknowledgement, not an optimistic UI state.
        wanted = {"pause": "paused", "resume": "running", "stop": "stopped"}[action]
        until = time.monotonic() + 1.5
        while time.monotonic() < until:
            with self._lock:
                if self._job["status"] in {wanted, "completed", "error"}:
                    break
            time.sleep(0.02)
        return self.snapshot()

    def pause(self) -> dict:
        return self._control("pause")

    def resume(self) -> dict:
        return self._control("resume")

    def stop(self) -> dict:
        return self._control("stop")
