import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from ixoncdkingress.function.context import FunctionContext

logger = logging.getLogger(__name__)

TIMEOUT = 30
CHUNK_DAYS = 366          # MeterBeheer accepts at most 366 days per request (367 → HTTP 400)
MAX_CHUNKS = 10           # roughly ten years per call
FETCH_WORKERS = 4
QUARTER_MS = 15 * 60 * 1000
MAX_QUARTER_BARS = 4 * 24 * 3  # beyond three days, quarter bars are too thin to read
DEFAULT_ZONE = 'Europe/Amsterdam'
INTERVALS = ('quarter', 'day', 'month', 'year')
FEED_ID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
CHANNEL_CODE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')

HTTP_MESSAGES = {
    400: 'MeterBeheer rejected the request (the range may be too long).',
    401: 'MeterBeheer rejected the API key. Check meterbeheer.apiKey in the configuration.',
    403: 'The API key is not permitted to access this resource.',
    404: 'MeterBeheer could not find this feed or channel.',
    429: 'Too many requests to MeterBeheer. Try again in a moment.',
}


class MeterBeheerError(Exception):
    """Customized MeterBeheer exception."""


def _http_message(status: int) -> str:
    if status in HTTP_MESSAGES:
        return HTTP_MESSAGES[status]
    if status >= 500:
        return f'MeterBeheer is having problems (HTTP {status}). Try again later.'
    return f'MeterBeheer returned HTTP {status}.'


def _config(context: FunctionContext) -> tuple[str, str]:
    """API key and base URL, both required — no defaults, so environments stay explicit."""
    cfg = context.config.get('meterbeheer') or {}
    api_key, base_url = cfg.get('apiKey'), cfg.get('baseUrl')
    if not (api_key and base_url):
        raise MeterBeheerError('Missing config: meterbeheer.apiKey and/or meterbeheer.baseUrl')
    return api_key, base_url.rstrip('/')


def _zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or DEFAULT_ZONE)
    except Exception:
        return ZoneInfo(DEFAULT_ZONE)


def _get_json(url: str, headers: dict | None = None, params: dict | None = None):
    try:
        response = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
    except requests.RequestException as err:
        logger.warning('MeterBeheer request failed: %s', type(err).__name__)
        raise MeterBeheerError('Could not reach MeterBeheer') from err
    if response.status_code != 200:
        logger.warning('MeterBeheer returned HTTP %s', response.status_code)
        raise MeterBeheerError(_http_message(response.status_code))
    try:
        return response.json()
    except ValueError as err:
        raise MeterBeheerError('MeterBeheer returned invalid JSON') from err


# ---------------------------------------------------------------- feeds

def _channel_kind(code: str) -> str:
    c = (code or '').lower()
    if 'prod' in c or c.startswith('2.8'):
        return 'production'
    if 'cons' in c or c.startswith('1.8'):
        return 'consumption'
    return 'unknown'


def _load_feeds(api_key: str, base_url: str) -> list[dict]:
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    feeds = _get_json(f'{base_url}/feed', headers=headers)
    if not isinstance(feeds, list):
        raise MeterBeheerError('MeterBeheer returned an unexpected feed list')
    return feeds


def _public_feed(feed: dict) -> dict:
    """What the browser needs for the pickers: no EAN, address or feed URLs."""
    order = {'consumption': 0, 'unknown': 1, 'production': 2}
    channels = [
        {'code': ch.get('code'), 'kind': _channel_kind(ch.get('code'))}
        for ch in feed.get('channels') or []
        if ch.get('code')
    ]
    channels.sort(key=lambda ch: order[ch['kind']])
    return {
        'id': feed.get('uuid'),
        'name': feed.get('name') or '(unnamed feed)',
        'provider': feed.get('provider'),
        'status': feed.get('status'),
        'meterKind': feed.get('meterKind'),
        'channels': channels,
    }


def _channel_url(base_url: str, feed_id: str, channel_code: str) -> str:
    """Feed URLs live on the same host as the configured API: <origin>/feed/<uuid>/<code>.json"""
    if not FEED_ID.match(str(feed_id or '')):
        raise MeterBeheerError('Invalid feed id')
    if not CHANNEL_CODE.match(str(channel_code or '')):
        raise MeterBeheerError('Invalid channel code')
    parts = urlsplit(base_url)
    return f'{parts.scheme}://{parts.netloc}/feed/{feed_id}/{channel_code}.json'


# ---------------------------------------------------------------- time windows

def _pick_interval(from_ms: int, to_ms: int) -> str:
    hours = (to_ms - from_ms) / 3_600_000
    if hours <= 26:            # one day, with room for a 25-hour DST day
        return 'quarter'
    if hours <= 24 * 62:
        return 'day'
    if hours <= 24 * 731:
        return 'month'
    return 'year'


def _date_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split an inclusive date range into MeterBeheer-sized pieces."""
    chunks = []
    while start <= end:
        stop = min(start + timedelta(days=CHUNK_DAYS - 1), end)
        chunks.append((start, stop))
        start = stop + timedelta(days=1)
    return chunks


def _local(ms: int, zone: ZoneInfo) -> datetime:
    return datetime.fromtimestamp(ms / 1000, zone)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _period_start(moment: datetime, interval: str, zone: ZoneInfo) -> datetime:
    if interval == 'day':
        naive = datetime(moment.year, moment.month, moment.day)
    elif interval == 'month':
        naive = datetime(moment.year, moment.month, 1)
    else:
        naive = datetime(moment.year, 1, 1)
    return naive.replace(tzinfo=zone)


def _next_period(start: datetime, interval: str, zone: ZoneInfo) -> datetime:
    if interval == 'day':
        naive = datetime(start.year, start.month, start.day) + timedelta(days=1)
    elif interval == 'month':
        naive = datetime(start.year + start.month // 12, start.month % 12 + 1, 1)
    else:
        naive = datetime(start.year + 1, 1, 1)
    return naive.replace(tzinfo=zone)


def _buckets(from_ms: int, to_ms: int, interval: str, zone: ZoneInfo) -> list[tuple[int, int]]:
    """Every slot in the window, including ones with no data, as (start_ms, end_ms)."""
    if interval == 'quarter':
        first = from_ms - from_ms % QUARTER_MS
        return [(t, t + QUARTER_MS) for t in range(first, to_ms, QUARTER_MS)]

    slots = []
    start = _period_start(_local(from_ms, zone), interval, zone)
    while _ms(start) < to_ms:
        end = _next_period(start, interval, zone)
        slots.append((_ms(start), _ms(end)))
        start = end
    return slots


# ---------------------------------------------------------------- data

def _parse_rows(payload: dict) -> list[tuple[int, int, float]]:
    rows = []
    for entry in payload.get('metering_data') or []:
        try:
            rows.append((
                _ms(datetime.fromisoformat(entry['from'])),
                _ms(datetime.fromisoformat(entry['to'])),
                float(entry['value']),
            ))
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows rather than failing the whole call
    return rows


def _fetch_rows(url: str, from_ms: int, to_ms: int, zone: ZoneInfo) -> tuple[list, dict]:
    """All quarters in the window plus the metadata of the newest chunk."""
    # One day of slack on both sides: MeterBeheer counts in Dutch days, the viewer may not.
    start = _local(from_ms, zone).date() - timedelta(days=1)
    end = _local(to_ms - 1, zone).date() + timedelta(days=1)
    chunks = _date_chunks(start, end)
    if len(chunks) > MAX_CHUNKS:
        raise MeterBeheerError(f'The time range is too long; at most {MAX_CHUNKS} years at once')

    def fetch(chunk):
        params = {'from': chunk[0].isoformat(), 'to': chunk[1].isoformat()}
        return _get_json(url, params=params)  # feed URLs are public; no API key needed

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        payloads = list(pool.map(fetch, chunks))

    rows: dict[int, tuple] = {}
    errors, seen = [], set()
    for payload in payloads:
        for row in _parse_rows(payload):
            rows[row[0]] = row
        for err in (payload.get('meter_data') or {}).get('errors') or []:
            key = (err.get('type'), err.get('code'), err.get('requested_date'))
            if key not in seen:
                seen.add(key)
                errors.append(err)

    meta = dict(payloads[-1].get('meter_data') or {}) if payloads else {}
    meta['errors'] = errors
    window = [r for r in rows.values() if r[1] > from_ms and r[0] < to_ms]
    return sorted(window), meta


def _expected(start: int, end: int, from_ms: int, to_ms: int) -> int:
    """Quarters of this slot that fall inside the window (92, 96 or 100 for a whole DST-aware day)."""
    lo = max(start, from_ms - from_ms % QUARTER_MS)
    hi = min(end, to_ms)
    return max(0, -(-(hi - lo) // QUARTER_MS))


def _aggregate(rows, slots, window, capacity_kw: float | None, is_energy: bool) -> list[dict]:
    points = []
    i = 0
    for start, end in slots:
        kwh, received, peak_kw, peak_at, over = 0.0, 0, None, None, 0
        while i < len(rows) and rows[i][0] < start:
            i += 1
        j = i
        while j < len(rows) and rows[j][0] < end:
            begins, ends, value = rows[j]
            kwh += value
            received += 1
            if is_energy:
                kw = value / max((ends - begins) / 3_600_000, 1e-9)
                if peak_kw is None or kw > peak_kw:
                    peak_kw, peak_at = kw, begins
                if capacity_kw is not None and kw > capacity_kw:
                    over += 1
            j += 1
        i = j

        hours = received * 0.25
        points.append({
            't': start,
            'tTo': end,
            'kwh': round(kwh, 3) if received else None,
            'meanKw': round(kwh / hours, 3) if received and is_energy else None,
            'peakKw': round(peak_kw, 3) if peak_kw is not None else None,
            'peakAt': peak_at,
            'over': over if capacity_kw is not None and is_energy else None,
            'received': received,
            'expected': _expected(start, end, *window),
        })
    return points


def _summarise(points: list[dict], rows: list) -> dict:
    with_data = [p for p in points if p['received']]
    if not with_data:
        return {}
    peak = max((p for p in with_data if p['peakKw'] is not None),
               key=lambda p: p['peakKw'], default=None)
    overs = [p['over'] for p in with_data if p['over'] is not None]
    return {
        'totalKwh': round(sum(p['kwh'] for p in with_data), 3),
        'peakKw': peak['peakKw'] if peak else None,
        'peakAt': peak['peakAt'] if peak else None,
        'overCount': sum(overs) if overs else None,
        'received': sum(p['received'] for p in points),
        'expected': sum(p['expected'] for p in points),
        'dataUntil': rows[-1][1] if rows else None,
    }


def _capacity(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# ---------------------------------------------------------------- exposed

@FunctionContext.expose
def get_feeds(context: FunctionContext) -> dict:
    """Return the feeds of this MeterBeheer account for the feed and channel pickers."""
    try:
        api_key, base_url = _config(context)
        feeds = _load_feeds(api_key, base_url)
    except MeterBeheerError as err:
        return {'success': False, 'error': str(err)}
    return {'success': True, 'data': [_public_feed(f) for f in feeds]}


@FunctionContext.expose
def get_consumption_series(
    context: FunctionContext,
    feed_id: str,
    channel_code: str,
    from_ms: int,
    to_ms: int,
    interval: str = 'auto',
    tz: str = DEFAULT_ZONE,
    capacity_kw: float | None = None,
) -> dict:
    """One channel of one feed over a time window, grouped per quarter, day, month or year."""
    try:
        _, base_url = _config(context)
        url = _channel_url(base_url, feed_id, channel_code)
        zone = _zone(tz)
        from_ms, to_ms = int(from_ms), int(to_ms)
        if to_ms <= from_ms:
            raise MeterBeheerError('The end of the time range is before its start')
        now_ms = int(time.time() * 1000)
        if from_ms >= now_ms:
            raise MeterBeheerError('This time range lies in the future; there is no data yet')
        to_ms = min(to_ms, now_ms)
        if interval not in INTERVALS or (
            interval == 'quarter' and (to_ms - from_ms) / QUARTER_MS > MAX_QUARTER_BARS
        ):
            interval = _pick_interval(from_ms, to_ms)

        rows, meta = _fetch_rows(url, from_ms, to_ms, zone)
    except MeterBeheerError as err:
        return {'success': False, 'error': str(err)}

    unit = meta.get('unit') or ''
    is_energy = unit.lower() == 'kwh'
    capacity = _capacity(capacity_kw) if is_energy else None
    slots = _buckets(from_ms, to_ms, interval, zone)
    # Feeds are published a day late: time after the newest quarter is "not yet available",
    # not missing, so it does not make the current day, month or year look incomplete.
    available_to = min(to_ms, rows[-1][1]) if rows else to_ms
    points = _aggregate(rows, slots, (from_ms, available_to), capacity, is_energy)

    return {
        'success': True,
        'channel': channel_code,
        'channelKind': _channel_kind(channel_code),
        'unit': unit,
        'isEnergy': is_energy,
        'interval': interval,
        'capacityKw': capacity,
        'points': points,
        'stats': _summarise(points, rows),
        'errors': meta.get('errors', []),
        'masterData': meta.get('master_data') if isinstance(meta.get('master_data'), dict) else None,
    }
