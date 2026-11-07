import unittest
from datetime import datetime, timedelta, timezone
from simulator.local_demo import LocalDemo, observation_time


class Clock:
    seconds = 0.
    start = datetime(2026, 11, 7, 18, tzinfo=timezone.utc)
    def mono(self):
        return self.seconds
    def wall(self):
        return self.start+timedelta(seconds=self.seconds)


class LocalDemoTests(unittest.TestCase):
    hardware = {'device': {'available': True}, 'job': {'status': 'running'}}

    def make_demo(self, price=100, **settings):
        self.clock, self.calls = Clock(), 0
        def fetch(zone):
            self.calls += 1
            return [dict(oper_day='11/07/2026', interval_ending='1200', price=price)]
        demo = LocalDemo(clock=self.clock.mono, wall_clock=self.clock.wall, price_fetcher=fetch, **settings)
        demo.refresh_prices()
        return demo

    def test_reads_are_read_only_and_prices_cached(self):
        demo = self.make_demo()
        demo.control('charge')
        before = demo.advance(self.hardware)
        self.clock.seconds = 100
        for _ in range(10):
            state = demo.snapshot()
            self.assertEqual(state['battery'], before['battery'])
            self.assertEqual(state['history'], before['history'])
        demo.refresh_prices()
        self.assertEqual(self.calls, 1)

    def test_elapsed_time_energy_conservation_units(self):
        demo = self.make_demo()
        demo.control('charge')
        demo.advance(self.hardware)
        self.clock.seconds = 1800
        s = demo.advance(self.hardware)
        c = s['costs']
        self.assertAlmostEqual(c['load_energy_wh'], 2.5)
        self.assertAlmostEqual(s['battery']['energy_wh'], 34.5)
        self.assertAlmostEqual(c['grid_energy_wh'], 7.5)
        self.assertAlmostEqual(c['grid_energy_wh'], c['load_energy_wh']+4.5+c['loss_energy_wh'])
        self.assertAlmostEqual(c['grid_usd'], 7.5*100/1e6)

    def test_initial_battery_is_not_free_savings(self):
        demo = self.make_demo()
        demo.control('discharge')
        demo.advance(self.hardware)
        self.clock.seconds = 1800
        c = demo.advance(self.hardware)['costs']
        self.assertEqual(c['grid_usd'], 0)
        self.assertGreater(c['replenishment_liability_usd'], c['baseline_usd'])
        self.assertLess(c['estimated_savings_usd'], 0)

    def test_negative_price(self):
        demo = self.make_demo(-20)
        self.assertEqual(demo.advance(self.hardware)['effective_mode'], 'charge')
        self.clock.seconds = 600
        state = demo.advance(self.hardware)
        self.assertEqual(state['price']['value_usd_mwh'], -20)
        self.assertLess(state['costs']['grid_usd'], 0)

    def test_stale_price_splits_accounting_and_stops_arbitrage(self):
        demo = self.make_demo()
        demo.control('charge')
        demo.advance(self.hardware)
        self.clock.seconds = 3600
        state = demo.advance(self.hardware)
        self.assertEqual(state['price']['status'], 'stale')
        self.assertEqual(state['effective_mode'], 'hold')
        self.assertAlmostEqual(state['battery']['energy_wh'], 30+10*.75*.9)
        self.assertAlmostEqual(state['costs']['unpriced_energy_wh'], 1.25)
        self.assertIsNone(state['costs']['estimated_savings_usd'])

    def test_feed_failure_never_fabricates_prices(self):
        demo = self.make_demo()
        def failed(zone):
            raise OSError('offline')
        demo._fetcher = failed
        demo.refresh_prices(force=True)
        self.assertIn('offline', demo.snapshot()['price']['error'])
        empty = LocalDemo(price_fetcher=failed)
        empty.refresh_prices()
        state = empty.advance(self.hardware)
        self.assertEqual(state['price']['status'], 'unavailable')
        self.assertIsNone(state['price']['value_usd_mwh'])
        self.assertIsNone(state['costs']['grid_usd'])

    def test_capacity_reserve(self):
        demo = self.make_demo(capacity_wh=1)
        demo.control('charge')
        demo.advance(self.hardware)
        self.clock.seconds = 600
        self.assertAlmostEqual(demo.advance(self.hardware)['battery']['energy_wh'], 1)
        demo.control('discharge')
        demo.advance(self.hardware)
        self.clock.seconds = 1200
        s = demo.advance(self.hardware)
        self.assertAlmostEqual(s['battery']['energy_wh'], .3)
        self.assertAlmostEqual(s['costs']['discharge_output_wh'], .7*.9)

    def test_disconnected_device_does_not_invent_workload(self):
        demo = self.make_demo()
        demo.control('charge')
        demo.advance({'device': {'available': False}})
        self.clock.seconds = 30
        state = demo.advance({'device': {'available': False}})
        self.assertEqual(state['costs']['load_energy_wh'], 0)
        self.assertEqual(state['battery']['energy_wh'], 30)

    def test_runtime_delta_accounts_for_completion(self):
        demo = self.make_demo()
        demo.advance({'device': {'available': True}, 'job': {'status': 'running', 'active_seconds': 0}})
        self.clock.seconds = 60
        s = demo.advance({'device': {'available': True}, 'job': {'status': 'completed', 'active_seconds': 30}})
        self.assertAlmostEqual(s['costs']['load_energy_wh'], (5*30+2*30)/3600)
        self.assertEqual(s['flows']['load_w'], 2)

    def test_invalid_settings_and_midnight(self):
        demo = self.make_demo()
        for setting in ({'efficiency': 0}, {'initial_pct': 10}, {'capacity_wh': float('nan')}, {'active_w': -1}):
            with self.assertRaises(ValueError):
                demo.configure(**setting)
        self.assertEqual(observation_time(dict(oper_day='11/07/2026', interval_ending='2400')),
                         datetime(2026, 11, 8, 6, tzinfo=timezone.utc))


if __name__ == '__main__':
    unittest.main()
