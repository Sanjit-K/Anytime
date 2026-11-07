import unittest

from engine.models import Battery, Scenario, Workload
from engine.scheduler import baseline, optimize
from engine.post_task import TaskTelemetry, reconcile_post_task


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

    def test_post_task_reconciliation_flags_energy_drift(self):
        scenario = Scenario(
            prices=[10, 100],
            fixed_load_kwh=[1, 1],
            workloads=[Workload("batch", energy_kwh=2, release_slot=0, deadline_slot=1)],
        )
        result = reconcile_post_task(
            scenario,
            optimize(scenario),
            [TaskTelemetry("batch", actual_energy_kwh=2.2, actual_duration_slots=1, completed_slot=0)],
        )
        self.assertTrue(result["requires_replan"])
        self.assertAlmostEqual(result["energy_variance_kwh"]["batch"], 0.2)


if __name__ == "__main__":
    unittest.main()
