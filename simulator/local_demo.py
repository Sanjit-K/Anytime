"""Live ERCOT observations, estimated board demand, and a virtual battery.

No physical power switching. Public reads never advance the simulation.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import threading
import time
from zoneinfo import ZoneInfo

from signals.ercot import ERCOT_REAL_TIME_SPP_URL, fetch_realtime_spp

DEFAULT_ASSUMPTIONS = dict(idle_w=2., active_w=5., capacity_wh=50., reserve_pct=30.,
                           initial_pct=60., efficiency=.9, max_charge_w=10., max_discharge_w=10.)


def observation_time(row, now=None):
    day = datetime.strptime(row['oper_day'], '%m/%d/%Y')
    raw = str(row['interval_ending']).replace(':', '').strip()
    repeated = raw.endswith('*')
    raw = raw.rstrip('*').zfill(4)
    hour, minute = int(raw[:-2]), int(raw[-2:])
    if hour > 24 or minute > 59 or (hour == 24 and minute):
        raise ValueError('Invalid ERCOT interval ending')
    return (day + timedelta(hours=hour, minutes=minute)).replace(
        tzinfo=ZoneInfo('America/Chicago'), fold=int(repeated)).astimezone(timezone.utc)


class LocalDemo:
    def __init__(self, *, clock=time.monotonic, wall_clock=None,
                 price_fetcher=fetch_realtime_spp, **assumptions):
        self._clock = clock
        self._wall = wall_clock or (lambda: datetime.now(timezone.utc))
        self._fetcher = price_fetcher
        self._lock = threading.RLock()
        self._last_fetch = self._fetched_at = self._error = None
        self._observations = []
        self._hardware = {}
        self._mode = 'auto'
        self._assumptions = dict(DEFAULT_ASSUMPTIONS)
        self.configure(**assumptions)

    def configure(self, **settings):
        """Changing assumptions starts a new explicitly simulated accounting session."""
        with self._lock:
            if set(settings) - set(DEFAULT_ASSUMPTIONS):
                raise ValueError('Unknown battery or wattage assumption')
            a = {**self._assumptions, **settings}
            if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in a.values()):
                raise ValueError('Assumptions must be finite numbers')
            if not 0 <= a['reserve_pct'] <= a['initial_pct'] <= 100:
                raise ValueError('Require 0 <= reserve_pct <= initial_pct <= 100')
            if a['capacity_wh'] <= 0 or not 0 < a['efficiency'] <= 1:
                raise ValueError('Capacity must be positive and efficiency in (0, 1]')
            if any(a[k] < 0 for k in ('idle_w', 'active_w', 'max_charge_w', 'max_discharge_w')) or a['active_w'] < a['idle_w']:
                raise ValueError('Power must be nonnegative; active watts include idle watts')
            self._assumptions = a
            self._initial_wh = a['capacity_wh'] * a['initial_pct'] / 100
            self._energy_wh = self._initial_wh
            self._baseline = self._cost = self._load_wh = self._grid_wh = 0.
            self._unpriced = self._loss = self._charged = self._discharged = self._elapsed = 0.
            self._last_tick = self._last_wall = self._last_price = self._last_observed = None
            self._history = deque(maxlen=360)
            self._flows = dict(load_w=0., grid_to_load_w=0., grid_to_battery_w=0., battery_to_load_w=0., grid_w=0.)
            self._effective = 'hold'
            self._reason = 'Waiting for live price and hardware observations'
            return self.snapshot()

    def refresh_prices(self, force=False):
        with self._lock:
            mono = self._clock()
            if not force and self._last_fetch is not None and mono-self._last_fetch < 300:
                return self._price()
            self._last_fetch = mono
        try:
            now = self._wall()
            observations = []
            for row in self._fetcher('HB_NORTH'):
                stamp, value = observation_time(row), float(row['price'])
                if math.isfinite(value) and stamp <= now:
                    observations.append((stamp, value, dict(row)))
            if not observations:
                raise ValueError('ERCOT returned no usable published observations')
            observations.sort(key=lambda r: r[0])
            with self._lock:
                self._observations = observations
                self._fetched_at, self._error = self._wall().isoformat(), None
        except Exception as exc:
            with self._lock:
                self._error = f'{type(exc).__name__}: {exc}'
        with self._lock:
            return self._price()

    def _price(self):
        result = dict(status='unavailable', value_usd_mwh=None, zone='HB_NORTH', observed_at=None,
                      fetched_at=self._fetched_at, age_seconds=None, error=self._error,
                      source='ERCOT real-time settlement point price', source_url=ERCOT_REAL_TIME_SPP_URL,
                      unit='USD/MWh', refresh_seconds=300, interval_minutes=15, stale_after_seconds=2700,
                      notice='Wholesale settlement price; not your household electricity tariff')
        if self._observations:
            stamp, value, row = self._observations[-1]
            age = max(0., (self._wall()-stamp).total_seconds())
            result.update(status='stale' if age > 2700 else 'live', value_usd_mwh=value,
                          observed_at=stamp.isoformat(), age_seconds=age,
                          operating_day=row['oper_day'], interval_ending=row['interval_ending'])
        return result

    def control(self, mode):
        if mode not in {'auto', 'charge', 'discharge', 'hold'}:
            raise ValueError('Mode must be auto, charge, discharge, or hold')
        with self._lock:
            self._mode = mode
            return self.snapshot()

    @staticmethod
    def _connected(hardware):
        d = hardware.get('device', {})
        return bool(d.get('available', d.get('connected', hardware.get('connected', False))))

    def _select_flows(self, price):
        a = self._assumptions
        connected = self._connected(self._hardware)
        job = self._hardware.get('job', {})
        running = job.get('status') == 'running' or job.get('running') is True
        load = (a['active_w'] if running else a['idle_w']) if connected else 0.
        self._flows = dict(load_w=load, grid_to_load_w=load, grid_to_battery_w=0., battery_to_load_w=0., grid_w=load)
        mode, self._reason = self._mode, 'Manual virtual battery command'
        if not connected:
            mode, self._reason = 'hold', 'Device unavailable; no workload energy inferred'
        elif price['status'] != 'live':
            mode, self._reason = 'hold', 'Price unavailable or older than 45 minutes; arbitrage paused'
        elif mode == 'auto':
            prices = sorted(p for _, p, _ in self._observations)
            low, high = prices[len(prices)//4], prices[3*len(prices)//4]
            spread = high > low/(a['efficiency']**2) and high > low
            current = price['value_usd_mwh']
            mode = 'charge' if current < 0 or (spread and current <= low) else ('discharge' if spread and current >= high else 'hold')
            self._reason = 'Auto: observed daily price quartiles and efficiency; no demand forecast'
        reserve = a['capacity_wh']*a['reserve_pct']/100
        if mode == 'charge' and self._energy_wh < a['capacity_wh']:
            self._flows['grid_to_battery_w'] = a['max_charge_w']
            self._flows['grid_w'] += a['max_charge_w']
        elif mode == 'discharge' and self._energy_wh > reserve:
            delivered = min(load, a['max_discharge_w'])
            self._flows.update(battery_to_load_w=delivered, grid_to_load_w=load-delivered, grid_w=load-delivered)
        else:
            mode = 'hold'
        self._effective = mode

    def advance(self, hardware_snapshot):
        """Integrate elapsed monotonic time, then sample next controls. No network I/O."""
        with self._lock:
            mono, now = self._clock(), self._wall()
            dt = 0. if self._last_tick is None else max(0., mono-self._last_tick)
            self._elapsed += dt
            a, f = self._assumptions, self._flows
            priced_seconds = 0.
            if self._last_price is not None and self._last_observed is not None and self._last_wall:
                priced_seconds = min(dt, max(0., 2700-(self._last_wall-self._last_observed).total_seconds()))
            hours = priced_seconds/3600
            load_w = f['load_w']
            # Actual job runtime refines the assumed power profile across pause/completion.
            previous_job, job = self._hardware.get('job', {}), hardware_snapshot.get('job', {})
            if dt and self._connected(self._hardware) and 'active_seconds' in previous_job and 'active_seconds' in job:
                active_delta = float(job['active_seconds']) - float(previous_job['active_seconds'])
                if active_delta >= 0:
                    load_w = a['idle_w'] + (a['active_w']-a['idle_w'])*min(dt, active_delta)/dt
            load_wh = load_w*dt/3600
            charge_wh = min(f['grid_to_battery_w']*hours, max(0., a['capacity_wh']-self._energy_wh)/a['efficiency'])
            reserve = a['capacity_wh']*a['reserve_pct']/100
            discharge_wh = min(f['battery_to_load_w']*hours, load_w*hours,
                               max(0., self._energy_wh-reserve)*a['efficiency'])
            stored, withdrawn = charge_wh*a['efficiency'], discharge_wh/a['efficiency']
            self._energy_wh += stored-withdrawn
            self._charged += charge_wh
            self._discharged += discharge_wh
            self._loss += charge_wh-stored+withdrawn-discharge_wh
            self._load_wh += load_wh
            self._grid_wh += load_wh+charge_wh-discharge_wh
            self._unpriced += load_w*(dt-priced_seconds)/3600
            if self._last_price is not None:
                self._baseline += load_w*hours*self._last_price/1e6
                self._cost += (load_w*hours+charge_wh-discharge_wh)*self._last_price/1e6
            self._hardware = deepcopy(hardware_snapshot)
            price = self._price()
            self._select_flows(price)
            self._last_tick, self._last_wall = mono, now
            self._last_price = price['value_usd_mwh'] if price['status'] == 'live' else None
            self._last_observed = self._observations[-1][0] if self._observations else None
            self._history.append(dict(time=now.isoformat(), elapsed_seconds=self._elapsed,
                                      price_usd_mwh=price['value_usd_mwh'], price_status=price['status'],
                                      energy_wh=self._energy_wh, mode=self._effective, **self._flows))
            return self.snapshot()

    def snapshot(self):
        with self._lock:
            a, price = self._assumptions, self._price()
            replacement = max(0., self._initial_wh-self._energy_wh)/a['efficiency']
            liability = replacement*price['value_usd_mwh']/1e6 if price['status'] == 'live' else None
            complete = self._unpriced < 1e-12 and liability is not None
            adjusted = self._cost+liability if complete else None
            return deepcopy(dict(simulation=True, physical_power_switching=False,
                mode=self._mode, effective_mode=self._effective, reason=self._reason,
                elapsed_seconds=self._elapsed, price=price, assumptions=dict(a),
                assumptions_label='Explicit estimates: board watts and virtual battery are not measured',
                battery=dict(energy_wh=self._energy_wh, capacity_wh=a['capacity_wh'],
                             soc_percent=self._energy_wh/a['capacity_wh']*100, reserve_percent=a['reserve_pct'],
                             initial_energy_wh=self._initial_wh, label='Virtual battery; independent of Mac physical battery'),
                flows=dict(self._flows), hardware=self._hardware, history=list(self._history),
                costs=dict(baseline_usd=self._baseline if complete else None, grid_usd=self._cost if complete else None,
                           replenishment_liability_usd=liability, replacement_energy_wh=replacement,
                           adjusted_usd=adjusted, estimated_savings_usd=self._baseline-adjusted if complete else None,
                           load_energy_wh=self._load_wh, grid_energy_wh=self._grid_wh, unpriced_energy_wh=self._unpriced,
                           loss_energy_wh=self._loss, charge_input_wh=self._charged, discharge_output_wh=self._discharged,
                           complete=complete, label='Modeled wholesale cost for equal estimated work; not realized savings',
                           terminal_valuation='Storage deficit replenished at latest price including charging loss; surplus has no credit')))


DemoController = LocalDemo
demo = LocalDemo()
