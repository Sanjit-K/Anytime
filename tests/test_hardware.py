"""Verify measured worker controls and unavailable hardware behavior."""
import subprocess
import time
from unittest.mock import patch

import pytest

from hardware import HardwareController
from hardware.controller import read_mac_battery


def wait_for(controller, status, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = controller.snapshot()
        if result["job"]["status"] == status:
            return result["job"]
        time.sleep(0.025)
    raise AssertionError(f"Worker did not reach {status}: {controller.snapshot()}")


def test_mac_battery_reports_real_power_source_without_assuming_ac():
    output = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t57%; discharging; 3:55 remaining present: true\n"
    with patch("hardware.controller._run", return_value=subprocess.CompletedProcess([], 0, output, "")):
        battery = read_mac_battery()
    assert battery["percent"] == 57
    assert battery["power_source"] == "Battery Power"
    assert battery["charging"] is False
    assert battery["power_watts"] is None


def test_battery_unavailable_is_not_a_fake_percentage():
    with patch("hardware.controller._run", side_effect=FileNotFoundError("pmset unavailable")):
        battery = read_mac_battery()
    assert not battery["available"]
    assert battery["percent"] is None


def test_unavailable_board_never_falls_back_to_mac():
    controller = HardwareController()
    with patch("hardware.controller.shutil.which", return_value=None):
        with pytest.raises(ValueError, match="adb is not installed"):
            controller.start()
    assert controller._process is None
    assert controller._job["target"] is None


def test_real_worker_pause_resume_completion():
    controller = HardwareController()
    with patch.object(controller, "_discover"), patch("hardware.controller.read_mac_battery", return_value={"available": False}):
        try:
            controller.start(target="mac", duration_seconds=1)
            wait_for(controller, "running")
            time.sleep(0.2)
            paused = controller.pause()["job"]
            assert paused["status"] == "paused"
            assert paused["completed_units"] > 0
            time.sleep(0.6)
            still_paused = controller.snapshot()["job"]
            assert still_paused["completed_units"] == paused["completed_units"]
            assert still_paused["active_seconds"] == paused["active_seconds"]
            controller.resume()
            completed = wait_for(controller, "completed")
            assert completed["progress_pct"] == 100
            assert completed["active_seconds"] == 1
            assert completed["elapsed_seconds"] > 1.5
            assert completed["cpu_seconds"] > 0
            assert completed["completed_units"] > paused["completed_units"]
        finally:
            controller.stop()


def test_real_worker_stop_is_acknowledged():
    controller = HardwareController()
    with patch.object(controller, "_discover"), patch("hardware.controller.read_mac_battery", return_value={"available": False}):
        controller.start(target="mac", duration_seconds=5)
        wait_for(controller, "running")
        stopped = controller.stop()["job"]
        assert stopped["status"] == "stopped"
        assert stopped["progress_pct"] < 100
        assert controller._process.wait(timeout=2) == 0
