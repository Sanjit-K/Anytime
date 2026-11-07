import unittest

from engine.models import Scenario, Workload
from engine.robust import make_price_scenarios, robust_optimize


class RobustOptimizerTests(unittest.TestCase):
    def test_generates_three_price_futures(self):
        scenarios = make_price_scenarios([10, 20, 30])
        self.assertEqual([item.name for item in scenarios], ["low-demand", "base", "scarcity"])
        self.assertAlmostEqual(sum(item.probability for item in scenarios), 1.0)

    def test_explains_choice_and_respects_deadline(self):
        scenario = Scenario(
            prices=[10, 100, 20, 90],
            fixed_load_kwh=[1, 1, 1, 1],
            workloads=[Workload("batch", 4, release_slot=0, deadline_slot=3, duration_slots=1, delay_penalty_per_slot=1)],
        )
        result = robust_optimize(scenario)
        self.assertEqual(len(result.assignments["batch"]), 1)
        self.assertTrue(any("batch:" in item for item in result.explanations))
        self.assertIn("scarcity", result.scenario_costs)


if __name__ == "__main__":
    unittest.main()
