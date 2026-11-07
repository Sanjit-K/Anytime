import unittest

from simulator.local_demo import LocalDemo


class LocalDemoTests(unittest.TestCase):
    def test_tick_reports_control_decision_and_reserve(self):
        demo = LocalDemo(prices=[10, 100], soc_kwh=60)
        first = demo.tick()
        second = demo.tick()
        self.assertIn(first["mode"], {"charging", "steady", "discharging"})
        self.assertIn(second["mode"], {"charging", "steady", "discharging"})
        self.assertGreaterEqual(first["battery_soc_percent"], 30)
        self.assertGreaterEqual(second["battery_soc_percent"], 30)


if __name__ == "__main__":
    unittest.main()
