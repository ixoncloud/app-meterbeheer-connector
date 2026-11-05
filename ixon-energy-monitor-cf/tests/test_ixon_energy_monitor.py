"""Unit tests for functions/ixon_energy_monitor.py. Run from the workspace root: python -m unittest -v"""

import sys
import types
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'functions'))

try:
    import ixoncdkingress.function.context  # noqa: F401
except ImportError:  # running outside the Cloud Function venv: a stand-in is enough
    class _FunctionContext:
        @staticmethod
        def expose(function):
            return function

    stub = types.ModuleType('ixoncdkingress.function.context')
    stub.FunctionContext = _FunctionContext
    for name in ('ixoncdkingress', 'ixoncdkingress.function'):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules['ixoncdkingress.function.context'] = stub

import ixon_energy_monitor as mb  # noqa: E402

AMS = ZoneInfo('Europe/Amsterdam')
FEED_UUID = '235b6b58-0000-4dff-a81d-000000000000'
FEED_URL = f'https://hub.meterbeheer.nl/feed/{FEED_UUID}/kwhCons.json'

# Overloon/Zusterbloemstraat-style production day, 2026-09-29, kWh per quarter (00:00 → 23:45).
DAY_0929 = [
    7.679, 7.982, 7.841, 7.597, 7.618, 8.145, 8.205, 7.577, 7.435, 7.962, 8.003, 7.841,
    7.739, 7.942, 8.165, 7.942, 7.861, 7.658, 8.185, 8.104, 7.78, 7.901, 7.719, 8.205,
    3.647, 3.383, 3.586, 5.227, 9.522, 10.819, 10.434, 10.697, 11.629, 11.994, 12.5, 12.825,
    12.825, 15.296, 15.742, 15.62, 14.992, 12.906, 12.784, 13.473, 13.817, 13.615, 13.635, 14.101,
    14.121, 13.797, 13.736, 13.392, 13.696, 13.331, 13.088, 14.81, 15.783, 16.127, 16.269, 16.046,
    16.127, 15.924, 16.998, 18.761, 17.221, 15.479, 14.547, 14.992, 14.81, 14.425, 13.453, 13.554,
    13.088, 12.865, 12.197, 11.832, 12.075, 12.075, 12.399, 12.095, 11.589, 9.846, 9.867, 9.705,
    8.793, 9.117, 9.239, 8.185, 7.375, 7.638, 7.901, 7.354, 7.172, 7.375, 7.841, 7.435,
]


def ms(*args) -> int:
    return int(datetime(*args, tzinfo=AMS).timestamp() * 1000)


def day_rows(day: date, values=None) -> list[dict]:
    """MeterBeheer-style metering_data for one local day, DST-aware."""
    start = datetime(day.year, day.month, day.day, tzinfo=AMS)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), AMS)
    rows, t = [], start.timestamp()
    while t < end.timestamp():
        begins = datetime.fromtimestamp(t, AMS)
        ends = datetime.fromtimestamp(t + 900, AMS)
        value = values[len(rows)] if values else 1.0
        rows.append({'from': begins.isoformat(), 'to': ends.isoformat(), 'value': value})
        t += 900
    return rows


def parsed(rows: list[dict]) -> list[tuple]:
    return sorted(mb._parse_rows({'metering_data': rows}))


class ChannelTests(unittest.TestCase):
    def test_channel_kinds_across_providers(self):
        cases = {
            '1.8.0': 'consumption', '2.8.0': 'production',            # EDSN
            'consumption': 'consumption', 'production': 'production',  # Joulz
            'kwhCons': 'consumption', 'kwhProd': 'production',         # Het Meetbedrijf
            'gasVolume': 'unknown',
        }
        for code, kind in cases.items():
            self.assertEqual(mb._channel_kind(code), kind, code)

    def test_public_feed_keeps_only_what_the_pickers_need(self):
        feed = {
            'uuid': FEED_UUID, 'provider': 'meetbedrijf', 'name': 'Zusterbloemstraat',
            'status': 'verified', 'ean': '871687910000000000', 'postalCode': '1234 DW',
            'houseNumber': '20', 'meterKind': 'electricity',
            'channels': [
                {'code': 'kwhProd', 'url': 'https://hub.meterbeheer.nl/feed/x/kwhProd.json'},
                {'code': 'kwhCons', 'url': FEED_URL},
            ],
        }
        public = mb._public_feed(feed)
        text = repr(public)
        for hidden in ('ean', '871687910000000000', 'postalCode', '1234 DW', 'houseNumber',
                       'url', 'hub.meterbeheer'):
            self.assertNotIn(hidden, text)
        self.assertEqual(public['id'], FEED_UUID)
        self.assertEqual([c['code'] for c in public['channels']], ['kwhCons', 'kwhProd'])


class ChannelUrlTests(unittest.TestCase):
    def test_url_uses_the_host_of_the_configured_base_url(self):
        for base, host in (('https://hub.meterbeheer.nl/api/v1', 'https://hub.meterbeheer.nl'),
                           ('https://hub.meterbeheer.nl/api/test/v1', 'https://hub.meterbeheer.nl'),
                           ('https://other.example/api/v2', 'https://other.example')):
            self.assertEqual(mb._channel_url(base, FEED_UUID, 'kwhCons'),
                             f'{host}/feed/{FEED_UUID}/kwhCons.json')

    def test_channel_codes_of_all_providers_are_accepted(self):
        for code in ('1.8.0', '2.8.0', 'consumption', 'production', 'kwhCons', 'kwhProd'):
            mb._channel_url('https://hub.meterbeheer.nl/api/v1', FEED_UUID, code)

    def test_malformed_ids_and_codes_are_refused(self):
        base = 'https://hub.meterbeheer.nl/api/v1'
        for feed_id in ('', None, 'nope', f'{FEED_UUID}/../x', f'../{FEED_UUID}'):
            with self.assertRaises(mb.MeterBeheerError):
                mb._channel_url(base, feed_id, 'kwhCons')
        for code in ('', None, '../kwhCons', 'kwh/Cons', '.hidden', 'kwhCons?x=1', 'a' * 65):
            with self.assertRaises(mb.MeterBeheerError):
                mb._channel_url(base, FEED_UUID, code)


class WindowTests(unittest.TestCase):
    def test_interval_by_range_length(self):
        day = 86_400_000
        start = ms(2026, 9, 29)
        self.assertEqual(mb._pick_interval(start, start + day), 'quarter')
        self.assertEqual(mb._pick_interval(start, start + 25 * 3_600_000), 'quarter')
        self.assertEqual(mb._pick_interval(start, start + 2 * day), 'day')
        self.assertEqual(mb._pick_interval(start, start + 4 * day), 'day')
        self.assertEqual(mb._pick_interval(start, start + 62 * day), 'day')
        self.assertEqual(mb._pick_interval(start, start + 365 * day), 'month')
        self.assertEqual(mb._pick_interval(start, start + 3 * 365 * day), 'year')

    def test_chunks_respect_the_366_day_limit(self):
        self.assertEqual(mb._date_chunks(date(2024, 1, 1), date(2024, 12, 31)),
                         [(date(2024, 1, 1), date(2024, 12, 31))])  # full leap year, one call
        chunks = mb._date_chunks(date(2021, 1, 1), date(2026, 9, 30))
        for first, last in chunks:
            self.assertLessEqual((last - first).days + 1, 366)
        self.assertEqual(chunks[0][0], date(2021, 1, 1))
        self.assertEqual(chunks[-1][1], date(2026, 9, 30))
        for (_, a), (b, _) in zip(chunks, chunks[1:]):
            self.assertEqual(b - a, timedelta(days=1))  # no gaps, no overlaps

    def test_dst_days_have_100_and_92_quarters(self):
        for day, quarters in ((date(2026, 10, 25), 100), (date(2026, 3, 29), 92), (date(2026, 9, 29), 96)):
            nxt = day + timedelta(days=1)
            window = (ms(day.year, day.month, day.day), ms(nxt.year, nxt.month, nxt.day))
            self.assertEqual(len(mb._buckets(*window, 'quarter', AMS)), quarters, day)
            slots = mb._buckets(*window, 'day', AMS)
            self.assertEqual(len(slots), 1)
            self.assertEqual(mb._expected(*slots[0], *window), quarters, day)

    def test_month_and_year_slots_follow_the_calendar(self):
        window = (ms(2025, 11, 15), ms(2026, 2, 10))
        starts = [datetime.fromtimestamp(s / 1000, AMS).date() for s, _ in mb._buckets(*window, 'month', AMS)]
        self.assertEqual(starts, [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)])
        years = mb._buckets(ms(2021, 3, 1), ms(2026, 9, 30), 'year', AMS)
        self.assertEqual(len(years), 6)


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.rows = parsed(day_rows(date(2026, 9, 29), DAY_0929))
        self.window = (ms(2026, 9, 29), ms(2026, 9, 30))
        self.quarters = mb._buckets(*self.window, 'quarter', AMS)

    def aggregate(self, capacity, interval='quarter'):
        slots = mb._buckets(*self.window, interval, AMS)
        return mb._aggregate(self.rows, slots, self.window, capacity, True)

    def test_kw_is_kwh_times_four(self):
        point = self.aggregate(None)[63]  # 15:45
        self.assertEqual(point['t'], ms(2026, 9, 29, 15, 45))
        self.assertEqual(point['kwh'], 18.761)
        self.assertEqual(point['meanKw'], 75.044)
        self.assertEqual(point['peakKw'], 75.044)

    def test_seventy_kw_is_exceeded_once_at_1545(self):
        points = self.aggregate(70)
        over = [p for p in points if p['over']]
        self.assertEqual(len(over), 1)
        self.assertEqual(over[0]['t'], ms(2026, 9, 29, 15, 45))

    def test_forty_eight_kw_is_exceeded_45_times(self):
        points = self.aggregate(48)
        over = [datetime.fromtimestamp(p['t'] / 1000, AMS).strftime('%H:%M') for p in points if p['over']]
        self.assertEqual(len(over), 45)
        self.assertEqual((over[0], over[-1]), ('08:30', '19:45'))
        self.assertNotIn('18:45', over)

    def test_eighty_kw_is_never_exceeded(self):
        self.assertEqual(sum(p['over'] for p in self.aggregate(80)), 0)

    def test_exactly_at_the_limit_is_not_over(self):
        exact = DAY_0929[63] * 4
        self.assertEqual(self.aggregate(exact)[63]['over'], 0)

    def test_day_bar_rolls_up_the_quarters(self):
        [day] = self.aggregate(70, 'day')
        self.assertAlmostEqual(day['kwh'], round(sum(DAY_0929), 3))
        self.assertEqual(day['peakKw'], 75.044)
        self.assertEqual(day['peakAt'], ms(2026, 9, 29, 15, 45))
        self.assertEqual(day['over'], 1)
        self.assertEqual((day['received'], day['expected']), (96, 96))

    def test_no_capacity_means_no_exceedance_count(self):
        self.assertIsNone(self.aggregate(None)[0]['over'])


class GapTests(unittest.TestCase):
    def test_missing_day_is_empty_not_zero(self):
        # Production case: 27 and 29 September present, 28 September absent.
        rows = parsed(day_rows(date(2026, 9, 27)) + day_rows(date(2026, 9, 29)))
        window = (ms(2026, 9, 27), ms(2026, 9, 30))
        points = mb._aggregate(rows, mb._buckets(*window, 'day', AMS), window, 70, True)
        self.assertEqual([p['received'] for p in points], [96, 0, 96])
        self.assertIsNone(points[1]['kwh'])
        self.assertIsNone(points[1]['peakKw'])
        stats = mb._summarise(points, rows)
        self.assertEqual((stats['received'], stats['expected']), (192, 288))

    def test_month_with_missing_day_is_incomplete(self):
        rows = parsed(day_rows(date(2026, 9, 27)) + day_rows(date(2026, 9, 29)))
        window = (ms(2026, 9, 1), ms(2026, 10, 1))
        [month] = mb._aggregate(rows, mb._buckets(*window, 'month', AMS), window, None, True)
        self.assertEqual(month['received'], 192)
        self.assertEqual(month['expected'], 30 * 96)


def fake_payload(days, errors=None, unit='kWh'):
    rows = []
    for day in days:
        rows += day_rows(day, DAY_0929 if day == date(2026, 9, 29) else None)
    return {
        'meter_data': {
            'unit': unit, 'supplier_channel': 'kwhCons', 'errors': errors or [],
            'master_data': {'message': 'Request a Smart Meter Check to view the master data for this meter.'},
        },
        'metering_data': rows,
    }


class SeriesTests(unittest.TestCase):
    """get_consumption_series end to end, with MeterBeheer replaced by a stand-in."""

    FEEDS = [{
        'uuid': FEED_UUID, 'name': 'Zusterbloemstraat', 'provider': 'meetbedrijf',
        'meterKind': 'electricity',
        'channels': [{'code': 'kwhCons', 'url': FEED_URL}, {'code': 'kwhProd', 'url': FEED_URL}],
    }]

    def setUp(self):
        self.context = types.SimpleNamespace(config={'meterbeheer': {
            'apiKey': 'test-key', 'baseUrl': 'https://hub.meterbeheer.nl/api/v1/'}})
        self.calls = []
        self.available = {date(2026, 9, 27), date(2026, 9, 29)}  # 28 September missing
        self.unit = 'kWh'

    def fake_get_json(self, url, headers=None, params=None):
        self.calls.append((url, headers, params))
        if url.endswith('/feed'):
            return self.FEEDS
        first, last = date.fromisoformat(params['from']), date.fromisoformat(params['to'])
        self.assertLessEqual((last - first).days + 1, 366)
        days = [d for d in self.available if first <= d <= last]
        return fake_payload(sorted(days), unit=self.unit)

    def series(self, from_ms, to_ms, **kwargs):
        now = ms(2026, 9, 30, 17, 0)
        with mock.patch.object(mb, '_get_json', self.fake_get_json), \
                mock.patch.object(mb.time, 'time', return_value=now / 1000):
            return mb.get_consumption_series(
                self.context, FEED_UUID, 'kwhCons', from_ms, to_ms, **kwargs)

    def test_quarter_view_of_one_day(self):
        result = self.series(ms(2026, 9, 29), ms(2026, 9, 30), capacity_kw='70')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['interval'], 'quarter')
        self.assertEqual(len(result['points']), 96)
        self.assertEqual(result['capacityKw'], 70.0)
        self.assertEqual(result['stats']['overCount'], 1)
        self.assertEqual(result['stats']['peakKw'], 75.044)
        self.assertEqual(result['stats']['dataUntil'], ms(2026, 9, 30))
        self.assertEqual(result['masterData']['message'][:7], 'Request')

    def test_chart_calls_only_the_feed_url_without_the_api_key(self):
        self.series(ms(2026, 9, 29), ms(2026, 9, 30))
        self.assertTrue(self.calls)
        self.assertTrue(all(url == FEED_URL for url, _, _ in self.calls))
        self.assertTrue(all(headers is None for _, headers, _ in self.calls))

    def test_feed_list_uses_the_configured_base_url_and_key(self):
        with mock.patch.object(mb, '_get_json', self.fake_get_json):
            result = mb.get_feeds(self.context)
        self.assertEqual(result['data'][0]['id'], FEED_UUID)
        [(url, headers, _)] = self.calls
        self.assertEqual(url, 'https://hub.meterbeheer.nl/api/v1/feed')
        self.assertEqual(headers['Authorization'], 'Bearer test-key')

    def test_three_days_with_a_gap_become_three_day_bars(self):
        result = self.series(ms(2026, 9, 27), ms(2026, 9, 30))
        self.assertEqual(result['interval'], 'day')
        self.assertEqual([p['received'] for p in result['points']], [96, 0, 96])

    def test_explicit_quarter_on_a_long_range_falls_back(self):
        result = self.series(ms(2026, 9, 1), ms(2026, 9, 30), interval='quarter')
        self.assertEqual(result['interval'], 'day')

    def test_multi_year_range_is_fetched_in_chunks(self):
        result = self.series(ms(2021, 1, 1), ms(2026, 9, 30))
        self.assertTrue(result['success'], result)
        self.assertEqual(result['interval'], 'year')
        self.assertEqual(len(result['points']), 6)
        chunk_calls = [c for c in self.calls if c[0] == FEED_URL]
        self.assertGreaterEqual(len(chunk_calls), 6)
        self.assertEqual(result['points'][-1]['received'], 192)

    def test_todays_lag_does_not_make_the_month_incomplete(self):
        # Now is 30 Sep 17:00 and data runs up to 30 Sep 00:00: only real gaps count.
        self.available = {date(2026, 9, d) for d in range(1, 30)}
        result = self.series(ms(2026, 9, 1), ms(2026, 10, 1), interval='month')
        [month] = result['points']
        self.assertEqual((month['received'], month['expected']), (29 * 96, 29 * 96))
        self.assertEqual(result['stats']['dataUntil'], ms(2026, 9, 30))

    def test_real_gap_before_the_lag_still_counts(self):
        self.available = {date(2026, 9, d) for d in range(1, 30)} - {date(2026, 9, 28)}
        [month] = self.series(ms(2026, 9, 1), ms(2026, 10, 1), interval='month')['points']
        self.assertEqual((month['received'], month['expected']), (28 * 96, 29 * 96))

    def test_quarters_after_the_newest_data_expect_nothing(self):
        result = self.series(ms(2026, 9, 29, 12), ms(2026, 9, 30, 12))
        after = [p for p in result['points'] if p['t'] >= ms(2026, 9, 30)]
        self.assertTrue(after)
        self.assertTrue(all(p['expected'] == 0 and p['received'] == 0 for p in after))

    def test_window_is_capped_at_now(self):
        result = self.series(ms(2026, 9, 30), ms(2026, 10, 1))
        self.assertEqual(len(result['points']), 68)  # 00:00 → 17:00 on 30 September
        self.assertEqual(result['stats'], {})          # today has no data yet

    def test_future_window_is_refused(self):
        result = self.series(ms(2026, 10, 2), ms(2026, 10, 3))
        self.assertFalse(result['success'])

    def test_malformed_feed_id_is_refused_before_any_request(self):
        with mock.patch.object(mb, '_get_json', self.fake_get_json):
            result = mb.get_consumption_series(self.context, 'nope', 'kwhCons', 0, 1)
        self.assertFalse(result['success'])
        self.assertEqual(self.calls, [])

    def test_gas_meter_has_no_power_figures(self):
        self.unit = 'm3'
        result = self.series(ms(2026, 9, 29), ms(2026, 9, 30), capacity_kw=70)
        self.assertFalse(result['isEnergy'])
        self.assertIsNone(result['capacityKw'])
        self.assertIsNone(result['points'][0]['meanKw'])
        self.assertIsNone(result['points'][0]['over'])

    def test_missing_config_is_reported(self):
        self.context.config = {}
        result = mb.get_feeds(self.context)
        self.assertFalse(result['success'])
        self.assertIn('meterbeheer.apiKey', result['error'])


if __name__ == '__main__':
    unittest.main()
