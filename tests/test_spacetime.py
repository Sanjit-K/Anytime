import json
import os
import unittest
from unittest.mock import MagicMock, patch

from api.spacetime import call_reducer, is_connected_result, query_sql
from api.telemetry import TelemetryRecorder


ENV = {"SPACETIME_URI": "https://example.invalid", "SPACETIME_DATABASE": "test"}


class SpacetimeBridgeTests(unittest.TestCase):
    @patch.dict(os.environ, ENV, clear=True)
    @patch("api.spacetime.urllib.request.urlopen")
    def test_reducer_sends_explicit_order_not_dictionary_order(self, urlopen):
        response = MagicMock()
        response.read.return_value = b""
        urlopen.return_value.__enter__.return_value = response
        call_reducer("ingest_price", {
            "observedAt": "2026-11-07T15:00:00-06:00", "source": "ERCOT",
            "price": -2.5, "slot": 60, "region": "HB_NORTH",
        })
        request = urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data), ["HB_NORTH", 60, -2.5, "ERCOT", "2026-11-07T15:00:00-06:00"])
        self.assertTrue(urlopen.call_args.kwargs["context"].check_hostname)

    @patch.dict(os.environ, ENV, clear=True)
    @patch("api.spacetime.urllib.request.urlopen", side_effect=OSError("offline"))
    def test_sql_failure_is_not_connection(self, urlopen):
        self.assertFalse(is_connected_result(query_sql("SELECT * FROM schedule")))
        self.assertFalse(is_connected_result(None))
        self.assertTrue(is_connected_result([]))

    @patch.dict(os.environ, {}, clear=True)
    def test_unconfigured_does_not_write(self):
        self.assertIsNone(call_reducer("unused", {}))
        self.assertIsNone(query_sql("SELECT * FROM schedule"))


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "costs": {"baseline_usd": 0.000015, "grid_usd": 0.00001,
                      "adjusted_usd": 0.000016, "estimated_savings_usd": -0.000001},
            "hardware": {"device": {"name": "Arduino UNO Q", "serial": "private", "available": True},
                         "job": {"status": "running", "active_seconds": 4, "pid": 12},
                         "mac_battery": {"percent": 57, "power_source": "Battery Power"}},
            "history": list(range(50)),
        }

    @patch.dict(os.environ, ENV, clear=True)
    @patch("api.telemetry.query_sql", return_value=[{"rows": [["saved"]]}])
    @patch("api.telemetry.call_reducer", return_value={})
    def test_real_values_privacy_throttling_and_readback(self, reducer, sql):
        clock = [100]
        recorder = TelemetryRecorder(clock=lambda: clock[0])
        result = recorder.record(self.data)
        self.assertTrue(result["connected"])
        self.assertEqual(result["status"], "saved")
        args = reducer.call_args.args[1]
        self.assertEqual(args["optimizedCost"], 0.000016)
        self.assertEqual(args["savings"], -0.000001)
        persisted = json.loads(args["planJson"])
        self.assertNotIn("serial", persisted["hardware"]["device"])
        self.assertNotIn("pid", persisted["hardware"]["job"])
        self.assertEqual(len(persisted["history"]), 30)
        recorder.record(self.data)
        self.assertEqual(reducer.call_count, 1)
        clock[0] = 131
        recorder.record(self.data)
        self.assertEqual(reducer.call_count, 2)
        self.assertEqual(sql.call_count, 2)

    @patch.dict(os.environ, ENV, clear=True)
    @patch("api.telemetry.call_reducer")
    def test_missing_costs_are_not_fabricated(self, reducer):
        recorder = TelemetryRecorder()
        result = recorder.record({"costs": {"baseline_usd": None}})
        self.assertEqual(result["status"], "waiting_for_priced_sample")
        self.assertFalse(result["connected"])
        reducer.assert_not_called()

    @patch.dict(os.environ, ENV, clear=True)
    @patch("api.telemetry.query_sql", return_value={"error": "offline"})
    @patch("api.telemetry.call_reducer", return_value={})
    def test_failed_readback_is_not_saved(self, reducer, sql):
        result = TelemetryRecorder().record(self.data)
        self.assertFalse(result["connected"])
        self.assertIsNone(result["last_saved_at"])
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
