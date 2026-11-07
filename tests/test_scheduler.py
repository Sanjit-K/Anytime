import unittest

from engine.models import Battery, Scenario, Workload
from engine.scheduler import baseline, optimize


class SchedulerTests(unittest.TestCase):
    def scenario(self):
        return Scenario(
            prices=[1, 1, 10, 10],
            fixed_load_kwh=[5, 5, 5, 5],
            workloads=[Workload("batch", 4, release_slot=0, deadline_slot=3, duration_slots=2)],
            battery=Battery(10, 5, 5, initial_soc_kwh=5, reserve_kwh=1),
        )

    def test_optimizer_moves_flexible_workload_to_cheap_slots(self):
        result = optimize(self.scenario())
        self.assertEqual(result.workload_slots["batch"], [0, 1])

    def test_optimizer_cost_is_below_immediate_baseline(self):
        self.assertLess(optimize(self.scenario()).total_cost, baseline(self.scenario()).total_cost)

    def test_invalid_deadline_is_reported(self):
        with self.assertRaises(ValueError):
            Scenario(prices=[1, 2], fixed_load_kwh=[1, 1], workloads=[Workload("late", 1, release_slot=1, deadline_slot=0)])


if __name__ == "__main__":
    unittest.main()
