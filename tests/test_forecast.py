import unittest

from signals.forecast import forecast_series


class ForecastTests(unittest.TestCase):
    def test_forecast_extends_recent_trend_without_negative_values(self):
        result = forecast_series([100, 110, 120, 130], horizon=3)
        self.assertEqual(len(result), 3)
        self.assertGreater(result[0], 120)
        self.assertTrue(all(value >= 0 for value in result))

    def test_empty_series_is_safe(self):
        self.assertEqual(forecast_series([], 2), [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
