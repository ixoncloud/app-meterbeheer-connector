<script module>
  // Module scope: survives component remounts, cleared on full page reload.
  const seriesCache = new Map();
  let lastSelection = null; // { feedId, channel }
  let instances = 0;
</script>

<script>
  import { onMount } from 'svelte';

  let { context } = $props();

  const uid = `smm${++instances}`;

  let client;
  let feeds = $state([]);
  let feedId = $state('');
  let channel = $state('');
  let series = $state(null);
  let loading = $state(false);
  let error = $state('');
  let drillStack = $state([]);
  let hover = $state(null);
  let wrapEl = $state();
  let debounceTimer;
  let inFlight = null;

  let title = $state('');
  let capacities = $state([]); // [{ name, kw }] from the Buildings setting
  let colors = $state({ bar: '#7F9DBF', line: '#EE5A10', capacity: '#D62F2F' });
  let rules = $state([]);

  const W = 760;
  const H = 300;
  const PAD = { t: 30, r: 52, b: 34, l: 52 };
  const FINER = { year: 'month', month: 'day', day: 'quarter' };
  const VIEW_NAME = { quarter: 'Quarter-hours', day: 'Days', month: 'Months', year: 'Years' };
  const PER = { quarter: '15 min', day: 'day', month: 'month', year: 'year' };

  const OPS = {
    eq: (v, t) => v === t,
    ne: (v, t) => v !== t,
    lt: (v, t) => v < t,
    le: (v, t) => v <= t,
    gt: (v, t) => v > t,
    ge: (v, t) => v >= t,
  };

  let selectedFeed = $derived(feeds.find((f) => f.id === feedId) ?? null);
  let capacityKw = $derived(capacityFor(selectedFeed));
  let channels = $derived(selectedFeed?.channels ?? []);
  let activeWindow = $derived(drillStack[drillStack.length - 1] ?? null);
  let canDrill = $derived(!!series && !!FINER[series.interval]);

  const zone = () => context?.appData?.timeZone || 'Europe/Amsterdam';
  const locale = () => context?.appData?.locale || 'en-GB';

  // ------------------------------------------------------------ lifecycle

  onMount(async () => {
    try {
      client = context.createBackendComponentClient();
    } catch {
      error = "Could not create backend client. Check the simulator's Cloud Function setting.";
      return;
    }

    const inputs = context.inputs ?? {};
    title = inputs.header?.title || '';
    capacities = (inputs.buildings ?? [])
      .map((b) => b?.building ?? b)
      .filter((b) => b?.name)
      .map((b) => {
        const kw = Number(b.kw);
        return { name: normName(b.name), kw: b.kw !== null && b.kw !== '' && Number.isFinite(kw) && kw > 0 ? kw : null };
      });
    colors = {
      bar: inputs.colors?.bar || colors.bar,
      line: inputs.colors?.line || colors.line,
      capacity: inputs.colors?.capacity || colors.capacity,
    };
    rules = (inputs.rules ?? []).map((r) => r?.rule ?? r).filter(Boolean);

    context.ontimerangechange = (range) => {
      drillStack = [];
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => loadSeries(range.from, range.to), 400);
    };

    try {
      const res = await client.call('functions.ixon_energy_monitor.get_feeds', {});
      const r = res?.data ?? res;
      if (r?.success) feeds = r.data ?? [];
      else error = r?.error ?? 'Could not load feeds.';
    } catch (e) {
      error = e?.message ?? 'Could not load feeds.';
    }

    const remembered = lastSelection && feeds.find((f) => f.id === lastSelection.feedId);
    const only = feeds.length === 1 ? feeds[0] : null;
    const start = remembered ?? only;
    if (start) {
      feedId = start.id;
      channel = start.channels.some((c) => c.code === lastSelection?.channel)
        ? lastSelection.channel
        : defaultChannel(start);
      lastSelection = { feedId, channel };
      const w = effectiveRange();
      await loadSeries(w.from, w.to, false, w.interval);
    }
  });

  // ------------------------------------------------------------ selection

  // Building names are matched case-insensitively, ignoring extra spaces.
  function normName(name) {
    return String(name ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  }

  function capacityFor(feed) {
    if (!feed) return null;
    const name = normName(feed.name);
    return capacities.find((c) => c.name === name && c.kw !== null)?.kw ?? null;
  }

  function defaultChannel(feed) {
    const list = feed?.channels ?? [];
    return (list.find((c) => c.kind === 'consumption') ?? list[0])?.code ?? '';
  }

  function onFeedChange(event) {
    feedId = event.target.value;
    channel = defaultChannel(selectedFeed);
    selectionChanged();
  }

  function onChannelChange(event) {
    channel = event.target.value;
    selectionChanged();
  }

  function selectionChanged() {
    drillStack = [];
    error = '';
    series = null;
    lastSelection = feedId ? { feedId, channel } : null;
    if (!feedId || !channel) return;
    const { from, to } = currentRange();
    loadSeries(from, to);
  }

  function currentRange() {
    const tr = context?.timeRange;
    if (tr?.from && tr?.to) return { from: tr.from, to: tr.to };
    const now = Date.now();
    return { from: now - 86400000, to: now };
  }

  function effectiveRange() {
    return activeWindow ?? currentRange();
  }

  // ------------------------------------------------------------ data

  async function loadSeries(fromMs, toMs, force = false, interval = 'auto') {
    if (!client || !feedId || !channel) return;
    toMs = Math.min(toMs, Date.now());
    const key = [feedId, channel, fromMs, toMs, interval, capacityKw, zone()].join('|');

    if (!force && seriesCache.has(key)) {
      series = seriesCache.get(key);
      return;
    }
    if (inFlight === key) return;

    inFlight = key;
    loading = true;
    error = '';
    hover = null;
    try {
      const res = await client.call('functions.ixon_energy_monitor.get_consumption_series', {
        feed_id: feedId,
        channel_code: channel,
        from_ms: fromMs,
        to_ms: toMs,
        interval,
        tz: zone(),
        capacity_kw: capacityKw,
      });
      const r = res?.data ?? res;
      if (inFlight !== key) return; // a newer request took over
      if (r?.success) {
        series = r;
        seriesCache.set(key, r);
      } else {
        series = null;
        error = r?.error ?? 'Could not load metering data.';
      }
    } catch (e) {
      series = null;
      error = e?.message ?? 'Could not load metering data.';
    } finally {
      if (inFlight === key) {
        loading = false;
        inFlight = null;
      }
    }
  }

  function drillInto(bar) {
    if (!canDrill) return;
    hover = null;
    const next = FINER[series.interval];
    drillStack = [...drillStack, { from: bar.t, to: bar.tTo, interval: next }];
    loadSeries(bar.t, bar.tTo, false, next);
  }

  function goBack() {
    if (!drillStack.length) return;
    hover = null;
    drillStack = drillStack.slice(0, -1);
    const w = effectiveRange();
    loadSeries(w.from, w.to, false, w.interval ?? 'auto');
  }

  function refresh() {
    const w = effectiveRange();
    loadSeries(w.from, w.to, true, w.interval ?? 'auto');
  }

  // ------------------------------------------------------------ chart

  function niceStep(span, target = 5) {
    const raw = span / target;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const norm = raw / mag;
    const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
    return step * mag;
  }

  function ruleApplies(rule, interval) {
    return (rule.appliesTo || 'all') === 'all' || rule.appliesTo === interval;
  }

  function stylesFor(kwh, interval) {
    let fill = colors.bar;
    let labelColor = null;
    let fillSet = false;
    if (kwh === null) return { fill, labelColor };
    for (const rule of rules) {
      const op = OPS[rule.operator];
      const threshold = Number(rule.value);
      if (!op || !Number.isFinite(threshold) || !ruleApplies(rule, interval)) continue;
      if (!op(kwh, threshold)) continue;
      if (rule.colorUsage === 'label') {
        if (labelColor === null) labelColor = rule.color;
      } else if (!fillSet) {
        fill = rule.color;
        fillSet = true;
      }
    }
    return { fill, labelColor };
  }

  function buildChart(s) {
    const pts = s?.points ?? [];
    if (!pts.some((p) => p.kwh !== null)) return null;

    const iv = s.interval;
    const quarter = iv === 'quarter';
    const withPower = quarter && s.isEnergy;
    const cap = withPower ? s.capacityKw : null;
    const labelled = iv === 'month' || iv === 'year';
    const ruleLines = rules
      .filter((r) => r.showLine && ruleApplies(r, iv) && Number.isFinite(Number(r.value)))
      .map((r) => ({ kwh: Number(r.value), color: r.color }));

    // Shared vertical scale: in the quarter view the kW axis is the kWh axis × 4,
    // so the power line runs exactly over the bar tops.
    const tallest = Math.max(
      ...pts.map((p) => p.kwh ?? 0),
      cap ? cap / 4 : 0,
      ...ruleLines.map((l) => l.kwh),
    );
    const anyOver = pts.some((p) => p.over > 0);
    // Headroom for value labels, exceedance markers and the "Limit exceeded" callout.
    const headroom = withPower && cap && anyOver ? 1.32 : labelled ? 1.18 : anyOver ? 1.12 : 1.06;
    const step = niceStep(tallest * headroom || 1);
    const hi = Math.ceil((tallest * headroom || 1) / step) * step;
    const plotW = W - PAD.l - (withPower ? PAD.r : 16);
    const plotH = H - PAD.t - PAD.b;
    const floorY = PAD.t + plotH;
    const yOf = (kwh) => PAD.t + plotH * (1 - kwh / hi);
    const slot = plotW / pts.length;
    const bw = Math.max(slot * (pts.length > 40 ? 0.8 : 0.65), 1);

    const multiYear = new Set(pts.map((p) => part(p.t, { year: 'numeric' }))).size > 1;

    const bars = pts.map((p, i) => {
      const x = PAD.l + i * slot + (slot - bw) / 2;
      const { fill, labelColor } = stylesFor(p.kwh, iv);
      const top = p.kwh === null ? floorY : yOf(p.kwh);
      return {
        ...p,
        i,
        x,
        cx: x + bw / 2,
        y: top,
        w: bw,
        h: floorY - top,
        fill,
        labelColor,
        empty: p.kwh === null,
        missing: p.kwh === null && p.expected > 0, // a real gap
        pending: p.kwh === null && p.expected === 0, // after the newest data: not published yet
        partial: p.kwh !== null && p.received < p.expected,
      };
    });

    const leftTicks = [];
    for (let v = 0; v <= hi + 1e-9; v += step) leftTicks.push({ v, y: yOf(v) });

    const rightTicks = [];
    if (withPower) {
      const kwStep = niceStep(hi * 4);
      for (let v = 0; v <= hi * 4 + 1e-9; v += kwStep) rightTicks.push({ v, y: yOf(v / 4) });
    }

    // Power line, broken wherever a quarter is missing.
    const segments = [];
    if (withPower) {
      let current = [];
      for (const b of bars) {
        if (b.empty) {
          if (current.length) segments.push(current);
          current = [];
        } else {
          current.push(`${b.cx.toFixed(1)},${yOf(b.meanKw / 4).toFixed(1)}`);
        }
      }
      if (current.length) segments.push(current);
    }

    const overBars = bars.filter((b) => b.over > 0);
    let callout = null;
    if (withPower && cap && overBars.length) {
      const worst = overBars.reduce((a, b) => (b.meanKw > a.meanKw ? b : a));
      const py = yOf(worst.meanKw / 4);
      // Box up and to the left of the peak, like the spec; flip right when there is no room.
      const bx = worst.cx - 170 >= PAD.l + 4 ? worst.cx - 170 : Math.min(worst.cx + 20, PAD.l + plotW - 150);
      const by = PAD.t + 2;
      callout = {
        px: worst.cx,
        py,
        x: bx,
        y: by,
        text: `${fmt(worst.meanKw, 2)} kW (> ${fmt(cap, 2)} kW)`,
      };
    }

    return {
      iv,
      quarter,
      withPower,
      labelled,
      bars,
      hi,
      plotW,
      plotH,
      floorY,
      leftTicks,
      rightTicks,
      segments,
      overBars,
      callout,
      capY: cap ? yOf(cap / 4) : null,
      ruleLines: ruleLines.map((l) => ({ ...l, y: yOf(l.kwh) })),
      ticks: pickTicks(bars, iv, multiYear),
      hasMissing: bars.some((b) => b.missing),
      hasPartial: bars.some((b) => b.partial),
    };
  }

  function pickTicks(bars, iv, multiYear) {
    let chosen;
    if (iv === 'quarter') {
      const hhmm = new Intl.DateTimeFormat('en-GB', { timeZone: zone(), hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
      chosen = bars.filter((b) => {
        const [h, m] = hhmm.format(b.t).split(':');
        return m === '00' && Number(h) % 2 === 0;
      });
    } else {
      const every = Math.max(1, Math.ceil(bars.length / 16));
      chosen = bars.filter((_, i) => i % every === 0);
    }
    // On the autumn clock change 02:00 occurs twice, one hour apart: drop a label
    // that would overlap the previous one (positions are in viewBox units).
    const MIN_GAP = 40;
    let lastX = -Infinity;
    chosen = chosen.filter((b) => {
      if (b.cx - lastX < MIN_GAP) return false;
      lastX = b.cx;
      return true;
    });
    return chosen.map((b) => ({ x: b.cx, label: tickLabel(b.t, iv, multiYear) }));
  }

  let chart = $derived(buildChart(series));

  // ------------------------------------------------------------ formatting

  function part(ms, opts) {
    const parts = new Intl.DateTimeFormat('en-GB', { timeZone: zone(), ...opts }).formatToParts(new Date(ms));
    return parts.find((p) => p.type === Object.keys(opts)[0])?.value ?? '';
  }

  function fmtDate(ms, opts) {
    return new Date(ms).toLocaleString(locale(), { timeZone: zone(), ...opts });
  }

  function fmtTime(ms) {
    return fmtDate(ms, { hour: '2-digit', minute: '2-digit' });
  }

  function tickLabel(ms, iv, multiYear) {
    if (iv === 'quarter') return fmtTime(ms);
    if (iv === 'day') return fmtDate(ms, { day: '2-digit', month: 'short' });
    if (iv === 'month') return fmtDate(ms, multiYear ? { month: 'short', year: '2-digit' } : { month: 'short' });
    return fmtDate(ms, { year: 'numeric' });
  }

  function periodLabel(p, iv) {
    if (iv === 'quarter') return `${fmtDate(p.t, { dateStyle: 'medium' })} · ${fmtTime(p.t)} – ${fmtTime(p.tTo)}`;
    if (iv === 'day') return fmtDate(p.t, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' });
    if (iv === 'month') return fmtDate(p.t, { month: 'long', year: 'numeric' });
    return fmtDate(p.t, { year: 'numeric' });
  }

  function windowLabel(w) {
    const end = w.to - 1;
    if (fmtDate(w.from, { dateStyle: 'medium' }) === fmtDate(end, { dateStyle: 'medium' })) {
      return fmtDate(w.from, { dateStyle: 'medium' });
    }
    return `${fmtDate(w.from, { dateStyle: 'medium' })} – ${fmtDate(end, { dateStyle: 'medium' })}`;
  }

  function fmt(v, digits = 3) {
    const n = Number(v);
    // Decimals only help on small numbers; "209.660,568 kWh" just reads as noise.
    return n.toLocaleString(locale(), { maximumFractionDigits: Math.abs(n) >= 1000 ? 0 : digits });
  }

  function fmtAxis(v) {
    return v >= 10000
      ? v.toLocaleString(locale(), { notation: 'compact', maximumFractionDigits: 1 })
      : v.toLocaleString(locale(), { maximumFractionDigits: 2 });
  }

  function completeness(p, iv) {
    if (iv === 'quarter' || iv === 'day') return `${p.received} of ${p.expected} quarter-hours`;
    const days = (n) => Math.round(n / 96);
    return `about ${days(p.received)} of ${days(p.expected)} days`;
  }

  function showTip(event, bar) {
    const box = wrapEl.getBoundingClientRect();
    const x = event.clientX - box.left;
    const y = event.clientY - box.top;
    hover = { bar, x, y, flipX: x > box.width / 2, flipY: y < 120 };
  }

  let windowNow = $derived(series ? effectiveRange() : null);
  let dataLag = $derived(
    series?.stats?.dataUntil && windowNow && series.stats.dataUntil < Math.min(windowNow.to, Date.now()) - 15 * 60000
      ? series.stats.dataUntil
      : null,
  );
</script>

<main>
  {#if title}<h3>{title}</h3>{/if}

  {#if error}<p class="error">{error}</p>{/if}

  <div class="picker">
    <select class="feed" value={feedId} onchange={onFeedChange} aria-label="Feed">
      <option value="">Select a building…</option>
      {#each feeds as feed (feed.id)}
        <option value={feed.id} disabled={!feed.channels?.length}>
          {feed.name}{feed.channels?.length ? '' : ' (no channels)'}
        </option>
      {/each}
    </select>
    {#if channels.length > 1}
      <select class="channel" value={channel} onchange={onChannelChange} aria-label="Channel">
        {#each channels as ch (ch.code)}
          <option value={ch.code}>{ch.code}{ch.kind !== 'unknown' ? ` (${ch.kind})` : ''}</option>
        {/each}
      </select>
    {/if}
    <button onclick={refresh} disabled={!feedId || loading}>
      {loading ? 'Loading…' : 'Refresh'}
    </button>
  </div>

  {#if activeWindow}
    <div class="crumb">
      <button class="back" onclick={goBack}>← Back</button>
      <span>{windowLabel(activeWindow)}</span>
    </div>
  {/if}

  {#if series}
    {#each series.errors ?? [] as err}
      <p class="warn">MeterBeheer: {err.message}{err.requested_date ? ` (${err.requested_date})` : ''}</p>
    {/each}
  {/if}

  {#if series && chart}
    <div class="heading">
      <strong>{VIEW_NAME[series.interval]}</strong>
      <span class="muted">· {windowLabel(windowNow)}{series.channelKind === 'production' ? ' · production channel' : ''}</span>
    </div>

    {#if series.stats?.totalKwh !== undefined}
      <p class="stats">
        Total <strong>{fmt(series.stats.totalKwh)}</strong> {series.unit}
        {#if series.isEnergy && series.stats.peakKw !== null}
          · Peak <strong>{fmt(series.stats.peakKw, 2)}</strong> kW
          <span class="muted">({fmtDate(series.stats.peakAt, { dateStyle: 'short', timeStyle: 'short' })})</span>
        {/if}
        {#if series.capacityKw && series.stats.overCount !== null}
          · {#if series.stats.overCount > 0}
            <strong class="over">{series.stats.overCount}</strong>
            {series.stats.overCount === 1 ? 'quarter-hour' : 'quarter-hours'} above {fmt(series.capacityKw, 2)} kW
          {:else}
            <span>within {fmt(series.capacityKw, 2)} kW</span>
          {/if}
        {/if}
      </p>
    {/if}

    <div class="legend">
      <span><i class="sw bar" style="background: {colors.bar}"></i>{series.channelKind === 'production' ? 'Production' : 'Consumption'} ({series.unit} per {PER[series.interval]})</span>
      {#if chart.withPower}
        <span><i class="sw line" style="background: {colors.line}"></i>Average power (kW)</span>
        {#if series.capacityKw}
          <span><i class="sw dash" style="border-color: {colors.capacity}"></i>Contracted capacity ({fmt(series.capacityKw, 2)} kW = {fmt(series.capacityKw / 4, 3)} kWh per 15 min)</span>
        {/if}
      {:else if series.capacityKw && chart.overBars.length}
        <span><i class="sw tri" style="border-top-color: {colors.capacity}"></i>Contains quarter-hours above {fmt(series.capacityKw, 2)} kW</span>
      {/if}
      {#if !series.capacityKw && series.unit?.toLowerCase() === 'kwh' && series.channelKind !== 'production'}
        <span class="unset">Contracted capacity not set</span>
      {/if}
      {#if chart.hasPartial}<span><i class="sw bar partial" style="background: {colors.bar}"></i>Incomplete period</span>{/if}
      {#if chart.hasMissing}<span><i class="sw hatch"></i>No data</span>{/if}
    </div>

    <div class="chart-wrap" class:busy={loading} bind:this={wrapEl}>
      <svg viewBox={`0 0 ${W} ${H}`} class="chart" role="img" aria-label="Consumption chart">
        <defs>
          <pattern id={`${uid}-hatch`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" class="hatch-line" />
          </pattern>
        </defs>

        {#each chart.leftTicks as tick}
          <line class="grid" x1={PAD.l} x2={PAD.l + chart.plotW} y1={tick.y} y2={tick.y} />
          <text class="axis end" x={PAD.l - 6} y={tick.y + 3}>{fmtAxis(tick.v)}</text>
        {/each}
        <text class="axis unit" x={PAD.l - 6} y={PAD.t - 16} text-anchor="end">{series.unit}</text>

        {#if chart.withPower}
          {#each chart.rightTicks as tick}
            <text class="axis" x={PAD.l + chart.plotW + 6} y={tick.y + 3} style="fill: {colors.line}">{fmtAxis(tick.v)}</text>
          {/each}
          <text class="axis unit" x={PAD.l + chart.plotW + 6} y={PAD.t - 16} style="fill: {colors.line}">kW</text>
        {/if}

        {#each chart.bars as bar (bar.t)}
          {#if bar.missing}
            <rect x={bar.x} y={PAD.t} width={bar.w} height={chart.plotH} fill={`url(#${uid}-hatch)`} />
          {:else if !bar.pending}
            <rect
              x={bar.x} y={bar.y} width={bar.w} height={Math.max(bar.h, 0.5)}
              fill={bar.fill}
              fill-opacity={bar.partial ? 0.45 : 1}
              class="bar"
              class:hot={hover?.bar === bar}
            />
          {/if}
          {#if chart.labelled && !bar.empty}
            <text class="value" x={bar.cx} y={bar.y - 5} fill={bar.labelColor ?? 'currentColor'}>
              {fmt(bar.kwh, 0)} {series.unit}
            </text>
          {/if}
          {#if !chart.quarter && bar.over > 0 && series.capacityKw}
            {@const ty = bar.y - (chart.labelled ? 18 : 4)}
            <path d={`M${bar.cx - 4},${ty - 7} L${bar.cx + 4},${ty - 7} L${bar.cx},${ty} Z`} fill={colors.capacity} />
          {/if}
        {/each}

        <line class="axis-line" x1={PAD.l} y1={chart.floorY} x2={PAD.l + chart.plotW} y2={chart.floorY} />

        {#each chart.ruleLines as line}
          <line x1={PAD.l} x2={PAD.l + chart.plotW} y1={line.y} y2={line.y}
                stroke={line.color} stroke-width="1.2" stroke-dasharray="4 3" />
        {/each}

        {#if chart.capY !== null}
          <line x1={PAD.l} x2={PAD.l + chart.plotW} y1={chart.capY} y2={chart.capY}
                stroke={colors.capacity} stroke-width="2" stroke-dasharray="7 5" />
        {/if}

        {#each chart.segments as seg}
          <polyline points={seg.join(' ')} fill="none" stroke={colors.line} stroke-width="2" stroke-linejoin="round" />
        {/each}

        {#if chart.withPower && series.capacityKw}
          {#each chart.overBars as bar}
            <circle cx={bar.cx} cy={PAD.t + chart.plotH * (1 - bar.meanKw / 4 / chart.hi)} r="3" fill={colors.capacity} />
          {/each}
        {/if}

        {#if chart.callout}
          {@const c = chart.callout}
          <line x1={c.px < c.x ? c.x : c.x + 150} y1={c.y + 30} x2={c.px} y2={c.py - 4} stroke="currentColor" stroke-width="1" />
          <rect x={c.x} y={c.y} width="150" height="34" rx="4" class="callout" stroke={colors.capacity} />
          <text x={c.x + 8} y={c.y + 14} class="callout-text">Limit exceeded!</text>
          <text x={c.x + 8} y={c.y + 27} class="callout-text">{c.text}</text>
        {/if}

        {#each chart.ticks as tick}
          <text class="axis" x={tick.x} y={H - 12} text-anchor="middle">{tick.label}</text>
        {/each}

        {#if hover}
          <line class="guide" x1={hover.bar.cx} y1={PAD.t} x2={hover.bar.cx} y2={chart.floorY} />
        {/if}

        {#each chart.bars as bar (bar.t)}
          <rect
            x={PAD.l + bar.i * (chart.plotW / chart.bars.length)} y={PAD.t}
            width={chart.plotW / chart.bars.length} height={chart.plotH}
            fill="transparent"
            class:drillable={canDrill}
            role="presentation"
            onmousemove={(e) => showTip(e, bar)}
            onmouseleave={() => (hover = null)}
            onclick={() => drillInto(bar)}
          />
        {/each}
      </svg>

      {#if loading}<div class="overlay">Loading…</div>{/if}

      {#if hover}
        {@const b = hover.bar}
        <div class="tip" class:flip-x={hover.flipX} class:flip-y={hover.flipY}
             style="left: {hover.x}px; top: {hover.y}px;">
          <div class="tip-head">{periodLabel(b, series.interval)}</div>
          {#if b.pending}
            <div class="tip-sub">Not available yet</div>
          {:else if b.missing}
            <div class="tip-sub">No data</div>
          {:else}
            <div class="tip-row">
              <span class="swatch" style="background: {b.fill};"></span>
              <strong style={b.labelColor ? `color: ${b.labelColor}` : ''}>{fmt(b.kwh)}</strong>
              <span class="unit">{series.unit}</span>
            </div>
            {#if series.isEnergy}
              {#if chart.quarter}
                <div class="tip-sub">Average power {fmt(b.meanKw, 2)} kW</div>
              {:else}
                <div class="tip-sub">Peak {fmt(b.peakKw, 2)} kW ({fmtDate(b.peakAt, { dateStyle: 'short', timeStyle: 'short' })}) · average {fmt(b.meanKw, 2)} kW</div>
              {/if}
            {/if}
            {#if series.capacityKw && b.over !== null}
              <div class="tip-sub" class:over={b.over > 0}>
                {#if chart.quarter}
                  {b.over > 0 ? `Above capacity (${fmt(series.capacityKw, 2)} kW)` : 'Within capacity'}
                {:else}
                  {b.over > 0 ? `${b.over} quarter-hour${b.over === 1 ? '' : 's'} above capacity` : 'Within capacity'}
                {/if}
              </div>
            {/if}
            {#if b.partial}
              <div class="tip-sub">Incomplete: {completeness(b, series.interval)}</div>
            {/if}
          {/if}
        </div>
      {/if}
    </div>

    <p class="muted foot">
      {[
        dataLag ? `Data available up to ${fmtDate(dataLag, { dateStyle: 'medium', timeStyle: 'short' })}` : '',
        canDrill ? 'Click a bar to zoom in' : '',
      ].filter(Boolean).join(' · ')}
    </p>
  {:else if loading}
    <p class="muted">Loading…</p>
  {:else if series}
    <p class="muted">No metering data for this period.</p>
    {#if windowNow && windowNow.to > Date.now() - 2 * 86400000}
      <p class="muted">MeterBeheer publishes each day's data the following day, so today is not available yet.</p>
    {/if}
    {#if series.masterData?.message}<p class="muted">MeterBeheer: {series.masterData.message}</p>{/if}
  {:else if !feedId && feeds.length}
    <p class="muted">Select a building to see its consumption.</p>
  {/if}
</main>

<style>
  main {
    font-family: Montserrat, Roboto, Helvetica, sans-serif;
    padding: 12px;
    height: 100%;
    box-sizing: border-box;
    overflow: auto;
    color: var(--uic-on-background);
    color-scheme: var(--uic-color-scheme);
  }
  h3 { margin: 0 0 8px; }

  .picker { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 14px; }
  .picker select {
    padding: 6px 8px;
    border-radius: 4px;
    font: inherit;
    color: var(--uic-on-background);
    background: var(--uic-background);
    border: 1px solid color-mix(in srgb, var(--uic-on-background) 25%, transparent);
  }
  .picker .feed { flex: 1 1 200px; min-width: 0; }
  .picker button {
    padding: 6px 12px;
    border: none;
    border-radius: 4px;
    background: var(--uic-primary);
    color: var(--uic-on-primary);
    cursor: pointer;
  }
  .picker button:disabled { opacity: 0.5; cursor: default; }

  .crumb {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 14px;
    font-size: 0.85em;
    color: color-mix(in srgb, var(--uic-on-background) 70%, transparent);
  }
  .crumb .back {
    padding: 4px 10px;
    border-radius: 4px;
    background: none;
    color: var(--uic-on-background);
    border: 1px solid color-mix(in srgb, var(--uic-on-background) 25%, transparent);
    font: inherit;
    cursor: pointer;
    white-space: nowrap;
  }

  .heading { margin-bottom: 6px; }
  .stats {
    margin: 0 0 10px;
    font-size: 0.85em;
    color: color-mix(in srgb, var(--uic-on-background) 70%, transparent);
  }
  .stats strong { color: var(--uic-on-background); }
  .stats strong.over, .tip-sub.over { color: var(--uic-error); }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 18px;
    font-size: 0.8em;
    margin-bottom: 12px;
    color: color-mix(in srgb, var(--uic-on-background) 80%, transparent);
  }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .legend .unset { font-style: italic; opacity: 0.7; }
  .sw { display: inline-block; width: 14px; height: 10px; }
  .sw.line { height: 2px; }
  .sw.partial { opacity: 0.45; }
  .sw.dash { height: 0; border-top: 2px dashed; }
  .sw.tri {
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 7px solid;
  }
  .sw.hatch {
    background: repeating-linear-gradient(45deg,
      color-mix(in srgb, var(--uic-on-background) 30%, transparent) 0 1px, transparent 1px 4px);
    border: 1px solid color-mix(in srgb, var(--uic-on-background) 20%, transparent);
  }

  .chart-wrap { position: relative; }
  .chart { width: 100%; height: auto; display: block; }
  .chart-wrap.busy .chart { opacity: 0.35; }
  .grid { stroke: color-mix(in srgb, var(--uic-on-background) 12%, transparent); stroke-dasharray: 3 3; }
  .axis-line { stroke: color-mix(in srgb, var(--uic-on-background) 40%, transparent); }
  .hatch-line { stroke: color-mix(in srgb, var(--uic-on-background) 22%, transparent); stroke-width: 1.5; }
  .guide {
    stroke: color-mix(in srgb, var(--uic-on-background) 55%, transparent);
    stroke-dasharray: 3 3;
  }
  .bar.hot { opacity: 0.75; }
  .drillable { cursor: zoom-in; }
  .axis { font-size: 10px; fill: color-mix(in srgb, var(--uic-on-background) 65%, transparent); }
  .axis.unit { font-weight: 600; }
  .end { text-anchor: end; }
  .value { font-size: 10px; text-anchor: middle; }
  .callout { fill: var(--uic-background); stroke-width: 1; }
  .callout-text { font-size: 11px; fill: currentColor; }

  .overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    pointer-events: none;
  }

  .tip {
    position: absolute;
    z-index: 2;
    pointer-events: none;
    background: var(--uic-background);
    color: var(--uic-on-background);
    border: 1px solid color-mix(in srgb, var(--uic-on-background) 25%, transparent);
    border-radius: 3px;
    padding: 6px 8px;
    font-size: 12px;
    line-height: 1.4;
    white-space: nowrap;
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.3);
    transform: translate(8px, calc(-100% - 12px));
  }
  .tip.flip-x { transform: translate(calc(-100% - 8px), calc(-100% - 12px)); }
  .tip.flip-y { transform: translate(8px, 12px); }
  .tip.flip-x.flip-y { transform: translate(calc(-100% - 8px), 12px); }
  .tip-head { margin-bottom: 4px; }
  .tip-row { display: flex; align-items: center; gap: 6px; }
  .tip-sub {
    margin-top: 3px;
    font-size: 0.9em;
    color: color-mix(in srgb, var(--uic-on-background) 65%, transparent);
  }
  .swatch { width: 12px; height: 8px; border-radius: 1px; }
  .unit { color: color-mix(in srgb, var(--uic-on-background) 60%, transparent); }

  .muted {
    color: color-mix(in srgb, var(--uic-on-background) 60%, transparent);
    font-size: 0.85em;
  }
  .foot { margin: 6px 0 0; }
  .error { color: var(--uic-error); }
  .warn {
    margin: 0 0 6px;
    font-size: 0.85em;
    color: var(--uic-error);
  }
</style>
