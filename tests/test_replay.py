import unittest
from datetime import datetime, timezone

from signals.ercot import interval_timestamp
from signals.replay import historical_price_replay


class ReplayTests(unittest.TestCase):
    def test_interval_timestamp_local_and_midnight(self):
        self.assertEqual(interval_timestamp("11/07/2026", "1630"), datetime(2026, 11, 7, 22, 30, tzinfo=timezone.utc))
        self.assertEqual(interval_timestamp("11/07/2026", "2400"), datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc))

    def test_fall_back_repeated_interval_uses_later_fold(self):
        first = interval_timestamp("11/01/2026", "0130")
        second = interval_timestamp("11/01/2026", "0130*")
        self.assertEqual((second-first).total_seconds(), 3600)

    def test_replay_is_observed_only_and_reports_coverage(self):
        now = datetime(2026, 11, 7, 23, tzinfo=timezone.utc)
        record = {"observed_at": "2026-11-07T22:45:00+00:00", "price": 61.31}
        result = historical_price_replay(fetcher=lambda **kwargs: {
            "kind":"observed_historical_replay", "records":[record], "forecast":False,
        })
        self.assertFalse(result["forecast"])
        self.assertEqual(result["coverage"]["observations"], 1)
        self.assertEqual(result["coverage"]["maximum_usd_mwh"], 61.31)


if __name__ == "__main__":
    unittest.main()
