'use client';

import React, { useEffect, useRef, useState, useMemo } from 'react';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createSeriesMarkers,
  Time,
} from 'lightweight-charts';
import { useTheme } from 'next-themes';
import {
  Droplets,
  ExternalLink,
  RefreshCw,
  Sliders,
  Layers,
  Clock,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Info,
  CheckCircle2,
  Copy,
  Check,
} from 'lucide-react';

import API_URL from '@/lib/config';

interface CandleData {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface VolumeData {
  time: Time;
  value: number;
  color: string;
}

interface LiquidityPool {
  id: string;
  timeframe: '5m' | '1h';
  side: 'buy' | 'sell';
  level: number;
  first_touch_time: number;
  created_at: number;
  touches: number;
  touch_times: number[];
  state: 'untouched' | 'swept' | 'broken';
  end_time: number;
  sweep_time?: number;
  sweep_price?: number;
  broken_time?: number;
}

interface SweepMarker {
  pool_id: string;
  timeframe: '5m' | '1h';
  side: 'buy' | 'sell';
  level: number;
  time: number;
  sweep_price: number;
  candle_index: number;
  direction_hint: 'bearish' | 'bullish';
}

interface LiquidityResponse {
  token: {
    address: string;
    symbol: string;
    name: string;
  };
  pool: {
    address: string;
    name: string;
    liquidity_usd: number;
    volume_24h: number;
    price_usd: number;
    network: string;
  };
  candles: CandleData[];
  candles_1h: CandleData[];
  pools_1h: LiquidityPool[];
  pools_5m: LiquidityPool[];
  sweeps: SweepMarker[];
  meta: {
    history_start: number | null;
    history_end: number | null;
    history_hours: number;
    history_days: number;
    history_summary: string;
    candle_count: number;
    candle_count_1h: number;
    params: {
      swing_n: number;
      tol_mult: number;
      max_pools: number;
      timeframe: string;
      limit: number;
    };
    generated_at: string;
  };
}

const PRESET_TOKENS = [
  {
    label: 'Commander VRAX (Primary Active Pool, $220k+ Liq)',
    tokenAddress: '0x94641b97010608C3827fB058074889f19868FF33',
    poolAddress: '0x435ea42b2792a22de296bee4e8013f4fa102f0cc04983443ff79549f847db577',
  },
  {
    label: 'Commander VRAX (Prompt Address, Low Liq)',
    tokenAddress: '0x56fa3670e19396c4ee8f7775b49ceaede04a84ef',
    poolAddress: '',
  },
];

export default function LiquidityPoolView() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();

  // Selected Token & Pool
  const [selectedPresetIndex, setSelectedPresetIndex] = useState<number>(0);
  const [customToken, setCustomToken] = useState<string>('');
  const [customPool, setCustomPool] = useState<string>('');
  const [useCustom, setUseCustom] = useState<boolean>(false);

  // Filters & Controls
  const [show1hPools, setShow1hPools] = useState<boolean>(true);
  const [show5mPools, setShow5mPools] = useState<boolean>(true);
  const [showSweptBroken, setShowSweptBroken] = useState<boolean>(true);
  const [nearestLimit, setNearestLimit] = useState<number>(10);
  const [swingN, setSwingN] = useState<number>(3);
  const [tolMult, setTolMult] = useState<number>(0.25);

  // API State
  const [data, setData] = useState<LiquidityResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Chart References
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const lineSeriesListRef = useRef<ISeriesApi<'Line'>[]>([]);
  const markersApiRef = useRef<any>(null);

  // Determine current addresses to query
  const currentToken = useCustom
    ? customToken.trim()
    : PRESET_TOKENS[selectedPresetIndex].tokenAddress;
  const currentPool = useCustom
    ? customPool.trim()
    : PRESET_TOKENS[selectedPresetIndex].poolAddress;

  const copyToClipboard = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  // 1. Data Fetching
  const fetchData = async () => {
    try {
      setError(null);
      let url = `${API_URL}/api/liquidity?timeframe=5m&limit=1000&swing_n=${swingN}&tol_mult=${tolMult}`;
      if (currentToken) url += `&token_address=${currentToken}`;
      if (currentPool) url += `&pool_address=${currentPool}`;

      const res = await fetch(url);
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP ${res.status}: Failed to fetch liquidity data`);
      }

      const json: LiquidityResponse = await res.json();
      setData(json);
      setLastUpdated(new Date());
    } catch (err: any) {
      console.error('Liquidity data fetch error:', err);
      setError(err.message || 'Error fetching liquidity data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchData();
    const interval = setInterval(fetchData, 30000); // 30s auto-refresh
    return () => clearInterval(interval);
  }, [currentToken, currentPool, swingN, tolMult]);

  // 2. Chart Initialization
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const isDark = theme !== 'light';
    const bgColor = isDark ? '#181A20' : '#ffffff';
    const textColor = isDark ? '#848E9C' : '#474d57';
    const gridColor = isDark ? '#2B3139' : '#e2e8f0';

    const chartInstance = createChart(chartContainerRef.current, {
      autoSize: true,
      layout: {
        background: { type: 'solid' as any, color: bgColor },
        textColor: textColor,
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
      },
      timeScale: {
        borderColor: gridColor,
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: gridColor,
        autoScale: true,
      },
      crosshair: {
        mode: 0,
      },
    });

    const cSeries = chartInstance.addSeries(CandlestickSeries, {
      upColor: '#0ECB81',
      downColor: '#F6465D',
      borderDownColor: '#F6465D',
      borderUpColor: '#0ECB81',
      wickDownColor: '#F6465D',
      wickUpColor: '#0ECB81',
    });

    const vSeries = chartInstance.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });

    vSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.82,
        bottom: 0,
      },
    });

    chartRef.current = chartInstance;
    candleSeriesRef.current = cSeries;
    volumeSeriesRef.current = vSeries;

    return () => {
      chartInstance.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      lineSeriesListRef.current = [];
      markersApiRef.current = null;
    };
  }, [theme]);

  // 3. Render Chart Data (Candles, Pools, Sweeps)
  useEffect(() => {
    const chart = chartRef.current;
    const cSeries = candleSeriesRef.current;
    const vSeries = volumeSeriesRef.current;
    if (!chart || !cSeries || !vSeries || !data) return;

    // Set Candlestick & Volume Data
    if (data.candles && data.candles.length > 0) {
      const cData = data.candles.map((d) => ({
        time: d.time,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }));

      const vData: VolumeData[] = data.candles.map((d) => ({
        time: d.time,
        value: d.volume || 0,
        color: d.close >= d.open ? 'rgba(14, 203, 129, 0.45)' : 'rgba(246, 70, 93, 0.45)',
      }));

      cSeries.setData(cData);
      vSeries.setData(vData);
    }

    // Clear previous pool lines
    lineSeriesListRef.current.forEach((s) => {
      try {
        chart.removeSeries(s);
      } catch (e) {
        // Ignored
      }
    });
    lineSeriesListRef.current = [];

    // Filter pools
    const currentPrice = data.pool.price_usd || (data.candles.length ? data.candles[data.candles.length - 1].close : 0);
    let poolsToRender: LiquidityPool[] = [];

    if (show1hPools) poolsToRender.push(...data.pools_1h);
    if (show5mPools) poolsToRender.push(...data.pools_5m);

    if (!showSweptBroken) {
      poolsToRender = poolsToRender.filter((p) => p.state === 'untouched');
    }

    // Sort by distance to current price if nearestLimit is active
    if (nearestLimit > 0 && currentPrice > 0) {
      poolsToRender.sort((a, b) => Math.abs(a.level - currentPrice) - Math.abs(b.level - currentPrice));
      poolsToRender = poolsToRender.slice(0, nearestLimit);
    }

    // Render each pool line
    poolsToRender.forEach((pool) => {
      const is1h = pool.timeframe === '1h';
      const isSweptOrBroken = pool.state !== 'untouched';

      // Color coding:
      // 1H Pools: Thick Orange/Amber (Buy: #f59e0b, Sell: #fbbf24)
      // 5M Pools: Thin Cyan/Blue (Buy: #06b6d4, Sell: #38bdf8)
      let lineColor = is1h ? '#f59e0b' : '#06b6d4';
      if (isSweptOrBroken) {
        lineColor = is1h ? 'rgba(245, 158, 11, 0.4)' : 'rgba(6, 182, 212, 0.4)';
      }

      const lSeries = chart.addSeries(LineSeries, {
        color: lineColor,
        lineWidth: is1h ? 3 : 1,
        lineStyle: isSweptOrBroken ? LineStyle.Dashed : LineStyle.Solid,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });

      const startTime = pool.created_at as Time;
      // Ensure end_time > startTime so lightweight-charts accepts the 2 points
      const rawEndTime = pool.end_time || pool.created_at + 300;
      const endTime = (rawEndTime > pool.created_at ? rawEndTime : pool.created_at + 300) as Time;

      lSeries.setData([
        { time: startTime, value: pool.level },
        { time: endTime, value: pool.level },
      ]);

      lineSeriesListRef.current.push(lSeries);
    });

    // Render Sweeps Markers
    const markers: any[] = [];
    if (data.sweeps && data.sweeps.length > 0) {
      data.sweeps.forEach((sweep) => {
        const isBuy = sweep.side === 'buy';
        markers.push({
          time: sweep.time as Time,
          position: isBuy ? 'aboveBar' : 'belowBar',
          color: isBuy ? '#f43f5e' : '#10b981',
          shape: isBuy ? 'arrowDown' : 'arrowUp',
          text: `${sweep.timeframe.toUpperCase()} ${isBuy ? 'Buy' : 'Sell'} Sweep (${sweep.direction_hint})`,
        });
      });
    }

    // Sort markers by time ascending (strictly required by lightweight-charts)
    markers.sort((a, b) => (Number(a.time) - Number(b.time)));

    if (markersApiRef.current) {
      try {
        markersApiRef.current.setMarkers(markers);
      } catch (e) {
        // Ignored
      }
    } else {
      try {
        markersApiRef.current = createSeriesMarkers(cSeries, markers);
      } catch (e) {
        console.warn('Failed to set markers:', e);
      }
    }

    // Fit content
    chart.timeScale().fitContent();
  }, [data, show1hPools, show5mPools, showSweptBroken, nearestLimit]);

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6 w-full max-w-7xl mx-auto">
      {/* ── Top Header ──────────────────────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[var(--color-border)] pb-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-orange-500/10 text-orange-500 border border-orange-500/20">
              <Droplets className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl md:text-2xl font-bold tracking-tight text-[var(--color-text-primary)] flex items-center gap-2">
                Commander VRAX Liquidity Pools
                <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 font-medium">
                  Robinhood Chain L2
                </span>
              </h1>
              <p className="text-xs md:text-sm text-[var(--color-text-secondary)] mt-0.5">
                5-minute candlestick chart with automated 1h &amp; 5m liquidity clusters and sweep detection.
              </p>
            </div>
          </div>
        </div>

        {/* Refresh & Last Updated */}
        <div className="flex items-center gap-3">
          <div className="text-xs text-[var(--color-text-secondary)] text-right hidden sm:block">
            <div>Last Updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : 'Loading...'}</div>
            <div className="text-[10px] text-emerald-400 flex items-center justify-end gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Auto-refresh 30s
            </div>
          </div>
          <button
            onClick={() => {
              setLoading(true);
              fetchData();
            }}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-lg bg-[var(--color-bg-panel)] border border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] text-[var(--color-text-primary)] transition-all cursor-pointer disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* ── Token / Pool Selector Bar ───────────────────────────────────────── */}
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-4 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 flex-1">
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)] shrink-0">
            Pool Target:
          </span>
          <div className="flex items-center gap-2 flex-wrap">
            {PRESET_TOKENS.map((preset, idx) => (
              <button
                key={idx}
                onClick={() => {
                  setUseCustom(false);
                  setSelectedPresetIndex(idx);
                }}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-all cursor-pointer ${
                  !useCustom && selectedPresetIndex === idx
                    ? 'bg-orange-500/10 text-orange-400 border-orange-500/30'
                    : 'bg-[var(--color-bg-base)] text-[var(--color-text-secondary)] border-[var(--color-border)] hover:text-[var(--color-text-primary)]'
                }`}
              >
                {preset.label}
              </button>
            ))}
            <button
              onClick={() => setUseCustom(!useCustom)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-all cursor-pointer ${
                useCustom
                  ? 'bg-blue-500/10 text-blue-400 border-blue-500/30'
                  : 'bg-[var(--color-bg-base)] text-[var(--color-text-secondary)] border-[var(--color-border)] hover:text-[var(--color-text-primary)]'
              }`}
            >
              Custom Address
            </button>
          </div>
        </div>

        {useCustom && (
          <div className="flex flex-col sm:flex-row gap-2 w-full md:w-auto">
            <input
              type="text"
              placeholder="Token Address (0x...)"
              value={customToken}
              onChange={(e) => setCustomToken(e.target.value)}
              className="px-3 py-1.5 text-xs bg-[var(--color-bg-base)] border border-[var(--color-border)] rounded-lg text-[var(--color-text-primary)] focus:outline-none focus:border-blue-500 w-full sm:w-56"
            />
            <input
              type="text"
              placeholder="Pool Address (optional)"
              value={customPool}
              onChange={(e) => setCustomPool(e.target.value)}
              className="px-3 py-1.5 text-xs bg-[var(--color-bg-base)] border border-[var(--color-border)] rounded-lg text-[var(--color-text-primary)] focus:outline-none focus:border-blue-500 w-full sm:w-56"
            />
          </div>
        )}
      </div>

      {/* ── Info Panel (Token, Pool, Liquidity, DexScreener verification) ───── */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          {/* Token Address */}
          <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-3 rounded-xl flex flex-col justify-between">
            <span className="text-[11px] text-[var(--color-text-secondary)] font-medium">Token Address</span>
            <div className="flex items-center justify-between gap-1 mt-1">
              <span className="font-mono text-xs font-medium text-[var(--color-text-primary)] truncate" title={data.token.address}>
                {data.token.address ? `${data.token.address.slice(0, 6)}...${data.token.address.slice(-4)}` : 'N/A'}
              </span>
              <button
                onClick={() => copyToClipboard(data.token.address, 'token')}
                className="text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] transition-colors p-1"
                title="Copy Token Address"
              >
                {copiedKey === 'token' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>

          {/* Pool Address & DexScreener Link */}
          <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-3 rounded-xl flex flex-col justify-between">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-[var(--color-text-secondary)] font-medium">Pool Address</span>
              <a
                href={`https://dexscreener.com/robinhood/${data.pool.address}`}
                target="_blank"
                rel="noreferrer"
                className="text-[10px] text-blue-400 hover:text-blue-300 flex items-center gap-0.5"
                title="Verify on DexScreener"
              >
                DexScreener <ExternalLink className="w-2.5 h-2.5" />
              </a>
            </div>
            <div className="flex items-center justify-between gap-1 mt-1">
              <span className="font-mono text-xs font-medium text-[var(--color-text-primary)] truncate" title={data.pool.address}>
                {data.pool.address ? `${data.pool.address.slice(0, 6)}...${data.pool.address.slice(-4)}` : 'N/A'}
              </span>
              <button
                onClick={() => copyToClipboard(data.pool.address, 'pool')}
                className="text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] transition-colors p-1"
                title="Copy Pool Address"
              >
                {copiedKey === 'pool' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>

          {/* Liquidity USD */}
          <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-3 rounded-xl flex flex-col justify-between">
            <span className="text-[11px] text-[var(--color-text-secondary)] font-medium">Pool Liquidity</span>
            <div className="text-base font-bold text-emerald-400 mt-1">
              ${data.pool.liquidity_usd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* 24h Volume USD */}
          <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-3 rounded-xl flex flex-col justify-between">
            <span className="text-[11px] text-[var(--color-text-secondary)] font-medium">24h Volume</span>
            <div className="text-base font-bold text-[var(--color-text-primary)] mt-1">
              ${data.pool.volume_24h.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* History Available */}
          <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-3 rounded-xl flex flex-col justify-between col-span-2 sm:col-span-1">
            <span className="text-[11px] text-[var(--color-text-secondary)] font-medium">Available History</span>
            <div className="flex items-center gap-1.5 mt-1 text-xs font-semibold text-[var(--color-text-primary)]">
              <Clock className="w-3.5 h-3.5 text-orange-400" />
              <span>{data.meta.history_summary}</span>
              <span className="text-[10px] text-[var(--color-text-secondary)] font-normal">
                ({data.meta.candle_count} 5m)
              </span>
            </div>
          </div>
        </div>
      )}

      {/* ── Error Banner ────────────────────────────────────────────────────── */}
      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-center gap-3 text-sm">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <div className="flex-1">
            <div className="font-semibold">Unable to load liquidity data</div>
            <div className="text-xs opacity-90">{error}</div>
          </div>
        </div>
      )}

      {/* ── Low History Warning ─────────────────────────────────────────────── */}
      {data && data.meta.candle_count < 30 && (
        <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 flex items-center gap-3 text-xs">
          <Info className="w-4 h-4 shrink-0 text-amber-400" />
          <span>
            This pool has only <strong>{data.meta.candle_count} 5-minute candles</strong> available.
            Liquidity pool clustering and sweep detection require sufficient price history. Try selecting the Primary Active Pool above.
          </span>
        </div>
      )}

      {/* ── Chart Controls Bar ──────────────────────────────────────────────── */}
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-3 rounded-xl flex flex-wrap items-center justify-between gap-4">
        {/* Visibility Toggles */}
        <div className="flex items-center gap-4 flex-wrap">
          {/* 1h Pools Toggle */}
          <label className="flex items-center gap-2 cursor-pointer text-xs font-medium select-none">
            <input
              type="checkbox"
              checked={show1hPools}
              onChange={(e) => setShow1hPools(e.target.checked)}
              className="accent-orange-500 rounded"
            />
            <span className="flex items-center gap-1.5 text-orange-400">
              <span className="w-2.5 h-0.5 bg-orange-500 inline-block" />
              1H Pools ({data?.pools_1h.length || 0})
            </span>
          </label>

          {/* 5m Pools Toggle */}
          <label className="flex items-center gap-2 cursor-pointer text-xs font-medium select-none">
            <input
              type="checkbox"
              checked={show5mPools}
              onChange={(e) => setShow5mPools(e.target.checked)}
              className="accent-cyan-500 rounded"
            />
            <span className="flex items-center gap-1.5 text-cyan-400">
              <span className="w-2.5 h-0.5 bg-cyan-400 inline-block" />
              5M Pools ({data?.pools_5m.length || 0})
            </span>
          </label>

          {/* Swept/Broken Toggle */}
          <label className="flex items-center gap-2 cursor-pointer text-xs font-medium text-[var(--color-text-secondary)] select-none">
            <input
              type="checkbox"
              checked={showSweptBroken}
              onChange={(e) => setShowSweptBroken(e.target.checked)}
              className="accent-slate-500 rounded"
            />
            <span>Show Swept / Broken</span>
          </label>
        </div>

        {/* Nearest Pools Limit & Sensitivity */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)]">
            <span>Show Nearest:</span>
            <select
              value={nearestLimit}
              onChange={(e) => setNearestLimit(Number(e.target.value))}
              className="bg-[var(--color-bg-base)] border border-[var(--color-border)] rounded-md px-2 py-1 text-xs text-[var(--color-text-primary)] focus:outline-none"
            >
              <option value={5}>5 Nearest</option>
              <option value={10}>10 Nearest</option>
              <option value={20}>20 Nearest</option>
              <option value={0}>All Pools</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)]">
            <span>Tolerance (ATR×):</span>
            <select
              value={tolMult}
              onChange={(e) => setTolMult(Number(e.target.value))}
              className="bg-[var(--color-bg-base)] border border-[var(--color-border)] rounded-md px-2 py-1 text-xs text-[var(--color-text-primary)] focus:outline-none"
            >
              <option value={0.15}>0.15 (Strict)</option>
              <option value={0.25}>0.25 (Default)</option>
              <option value={0.4}>0.40 (Wide)</option>
            </select>
          </div>
        </div>
      </div>

      {/* ── Candlestick Chart Container ─────────────────────────────────────── */}
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl p-4 flex flex-col h-[520px] w-full relative">
        <div className="flex items-center justify-between text-xs text-[var(--color-text-secondary)] font-medium mb-2 shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-[var(--color-text-primary)] font-semibold">VRAX / USD 5m Chart</span>
            <span className="text-[10px] text-[var(--color-text-secondary)]">
              (Current Price: ${data?.pool.price_usd?.toFixed(8) || '0.00'})
            </span>
          </div>

          <div className="flex items-center gap-3 text-[11px]">
            <span className="flex items-center gap-1 text-orange-400">
              <span className="w-3 h-1 bg-orange-400 rounded-sm" /> 1H Pool (Thick)
            </span>
            <span className="flex items-center gap-1 text-cyan-400">
              <span className="w-3 h-0.5 bg-cyan-400 rounded-sm" /> 5M Pool (Thin)
            </span>
            <span className="flex items-center gap-1 text-rose-400">
              ▼ Buy Sweep (Bearish)
            </span>
            <span className="flex items-center gap-1 text-emerald-400">
              ▲ Sell Sweep (Bullish)
            </span>
          </div>
        </div>

        <div className="relative flex-grow w-full rounded-lg overflow-hidden">
          <div ref={chartContainerRef} className="absolute inset-0" />
          {loading && !data && (
            <div className="absolute inset-0 flex items-center justify-center bg-[var(--color-bg-panel)]/70 backdrop-blur-sm z-10">
              <div className="flex items-center gap-2 text-sm text-[var(--color-text-primary)]">
                <RefreshCw className="w-4 h-4 animate-spin text-orange-400" />
                Loading candlestick and pool data...
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Sweeps & Pools Summary Tables ───────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sweeps Table */}
        <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl p-4 flex flex-col">
          <div className="flex items-center justify-between pb-3 border-b border-[var(--color-border)] mb-3">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-orange-400" />
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
                Detected Liquidity Sweeps ({data?.sweeps.length || 0})
              </h3>
            </div>
            <span className="text-[10px] text-[var(--color-text-secondary)]">Context markers only</span>
          </div>

          <div className="overflow-x-auto max-h-72 overflow-y-auto">
            {data && data.sweeps.length > 0 ? (
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="text-[var(--color-text-secondary)] border-b border-[var(--color-border)]">
                    <th className="pb-2 font-medium">Time (UTC)</th>
                    <th className="pb-2 font-medium">TF</th>
                    <th className="pb-2 font-medium">Pool Level</th>
                    <th className="pb-2 font-medium">Sweep Price</th>
                    <th className="pb-2 font-medium">Context Hint</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]">
                  {data.sweeps.map((sweep, idx) => {
                    const isBearish = sweep.direction_hint === 'bearish';
                    return (
                      <tr key={idx} className="hover:bg-[var(--color-bg-hover)] transition-colors">
                        <td className="py-2 font-mono text-[11px] text-[var(--color-text-secondary)]">
                          {new Date(sweep.time * 1000).toISOString().slice(5, 16).replace('T', ' ')}
                        </td>
                        <td className="py-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                              sweep.timeframe === '1h'
                                ? 'bg-orange-500/10 text-orange-400 border border-orange-500/20'
                                : 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                            }`}
                          >
                            {sweep.timeframe.toUpperCase()}
                          </span>
                        </td>
                        <td className="py-2 font-mono text-[var(--color-text-primary)]">
                          ${sweep.level < 0.0001 ? sweep.level.toExponential(4) : sweep.level.toFixed(6)}
                        </td>
                        <td className="py-2 font-mono text-[var(--color-text-primary)]">
                          ${sweep.sweep_price < 0.0001 ? sweep.sweep_price.toExponential(4) : sweep.sweep_price.toFixed(6)}
                        </td>
                        <td className="py-2">
                          <span
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                              isBearish
                                ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                                : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            }`}
                          >
                            {isBearish ? <TrendingDown className="w-3 h-3" /> : <TrendingUp className="w-3 h-3" />}
                            {isBearish ? 'Bearish Context' : 'Bullish Context'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="py-8 text-center text-xs text-[var(--color-text-secondary)]">
                No liquidity sweeps detected in current window.
              </div>
            )}
          </div>
        </div>

        {/* Active Pools Table */}
        <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl p-4 flex flex-col">
          <div className="flex items-center justify-between pb-3 border-b border-[var(--color-border)] mb-3">
            <div className="flex items-center gap-2">
              <Droplets className="w-4 h-4 text-cyan-400" />
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
                Liquidity Pool Clusters ({((data?.pools_1h.length || 0) + (data?.pools_5m.length || 0))})
              </h3>
            </div>
            <span className="text-[10px] text-[var(--color-text-secondary)]">Equal Highs / Lows</span>
          </div>

          <div className="overflow-x-auto max-h-72 overflow-y-auto">
            {data && (data.pools_1h.length > 0 || data.pools_5m.length > 0) ? (
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="text-[var(--color-text-secondary)] border-b border-[var(--color-border)]">
                    <th className="pb-2 font-medium">TF</th>
                    <th className="pb-2 font-medium">Side</th>
                    <th className="pb-2 font-medium">Level</th>
                    <th className="pb-2 font-medium">Touches</th>
                    <th className="pb-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]">
                  {[...(data.pools_1h || []), ...(data.pools_5m || [])]
                    .sort((a, b) => b.created_at - a.created_at)
                    .map((pool, idx) => (
                      <tr key={idx} className="hover:bg-[var(--color-bg-hover)] transition-colors">
                        <td className="py-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                              pool.timeframe === '1h'
                                ? 'bg-orange-500/10 text-orange-400 border border-orange-500/20'
                                : 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                            }`}
                          >
                            {pool.timeframe.toUpperCase()}
                          </span>
                        </td>
                        <td className="py-2 font-medium">
                          <span className={pool.side === 'buy' ? 'text-amber-400' : 'text-blue-400'}>
                            {pool.side === 'buy' ? 'Buy-side (Highs)' : 'Sell-side (Lows)'}
                          </span>
                        </td>
                        <td className="py-2 font-mono text-[var(--color-text-primary)]">
                          ${pool.level < 0.0001 ? pool.level.toExponential(4) : pool.level.toFixed(6)}
                        </td>
                        <td className="py-2 font-mono text-[var(--color-text-secondary)]">
                          {pool.touches} touches
                        </td>
                        <td className="py-2">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                              pool.state === 'untouched'
                                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                : pool.state === 'swept'
                                ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                                : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
                            }`}
                          >
                            {pool.state}
                          </span>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            ) : (
              <div className="py-8 text-center text-xs text-[var(--color-text-secondary)]">
                No liquidity clusters found.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
