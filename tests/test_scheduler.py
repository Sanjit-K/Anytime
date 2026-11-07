import unittest

from engine.models import Battery, Scenario, Workload
from engine.scheduler import baseline, optimize, compare_dispatch
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

    def test_cost_uses_usd_per_mwh_and_kwh_once(self):
        scenario = Scenario(prices=[1000], fixed_load_kwh=[2])
        self.assertEqual(baseline(scenario).total_cost, 2.0)

    def test_comparison_keeps_full_jobs_and_applies_economic_charges(self):
        result = compare_dispatch(self.scenario(), degradation_usd_per_kwh=.1,
                                  demand_charge_usd_per_kw=2)
        self.assertEqual(set(result) - {"assumptions"}, {"grid_only", "threshold", "optimized"})
        self.assertEqual(result["grid_only"]["workload_slots"]["batch"], [0, 1])
        self.assertEqual(len(result["optimized"]["workload_slots"]["batch"]), 2)
        self.assertGreater(result["grid_only"]["demand_charge_usd"], 0)
        self.assertGreaterEqual(result["threshold"]["battery_soc_kwh"][-1], 1)
        for strategy in ("grid_only", "threshold", "optimized"):
            row = result[strategy]
            self.assertAlmostEqual(row["total_cost_usd"], sum(row[k] for k in (
                "energy_cost_usd", "demand_charge_usd", "degradation_usd", "terminal_energy_cost_usd")))

    def test_terminal_soc_deficit_is_valued_and_reserve_is_kept(self):
        scenario = Scenario(prices=[1, 100], fixed_load_kwh=[1, 10],
            battery=Battery(10, 5, 5, initial_soc_kwh=8, reserve_kwh=3), interval_hours=1)
        result=compare_dispatch(scenario)
        threshold=result["threshold"]
        self.assertGreater(threshold["terminal_energy_cost_usd"],0)
        self.assertTrue(all(soc>=3 for soc in threshold["battery_soc_kwh"]))


if __name__ == "__main__":
    unittest.main()
