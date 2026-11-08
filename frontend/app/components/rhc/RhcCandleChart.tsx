"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, HistogramSeries, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useTheme } from "next-themes";
import { rhcGet, type Candle } from "./api";

interface CandleResponse {
  pool_id: string;
  pool_pk: number;
  tf: number;
  candles: Candle[];
}

/** USD candles for one pool (execution-price OHLC; quote OHLC scaled by the close's USD rate). */
export default function RhcCandleChart({ poolId, height = 300 }: { poolId: string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const [tf, setTf] = useState<60 | 300>(60);
  const [note, setNote] = useState<string | null>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    if (!ref.current) return;
    const dark = resolvedTheme !== "light";
    const grid = dark ? "#2B3139" : "#e2e8f0";
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { color: dark ? "#1e2329" : "#ffffff" }, textColor: dark ? "#848E9C" : "#474d57" },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale: { borderColor: grid, timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: grid },
      localization: { priceFormatter: (p: number) => (p >= 1 ? p.toFixed(4) : p.toPrecision(4)) },
    });
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "#0ECB81", downColor: "#F6465D", borderUpColor: "#0ECB81", borderDownColor: "#F6465D",
      wickUpColor: "#0ECB81", wickDownColor: "#F6465D",
    });
    volRef.current = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "" });
    volRef.current.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [resolvedTheme]);

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const r = await rhcGet<CandleResponse>(`/candles?pool_id=${poolId}&tf=${tf}&limit=500`);
        if (!live || !candleRef.current || !volRef.current) return;
        const rows = r.candles.filter((c) => c.c && c.c_usd && c.o && c.h && c.l);
        const k = (c: Candle) => (c.c_usd as number) / (c.c as number);
        candleRef.current.setData(rows.map((c) => ({
          time: c.bucket as UTCTimestamp,
          open: (c.o as number) * k(c), high: (c.h as number) * k(c), low: (c.l as number) * k(c), close: c.c_usd as number,
        })));
        volRef.current.setData(rows.map((c) => ({
          time: c.bucket as UTCTimestamp, value: c.vol_usd || 0,
          color: (c.c as number) >= (c.o as number) ? "rgba(14,203,129,0.45)" : "rgba(246,70,93,0.45)",
        })));
        chartRef.current?.timeScale().fitContent();
        setNote(rows.length ? null : "No stored candles for this pool yet (it may not be tracked).");
      } catch (e) {
        if (live) setNote(e instanceof Error ? e.message : String(e));
      }
    };
    load();
    const iv = setInterval(load, 30000);
    return () => {
      live = false;
      clearInterval(iv);
    };
  }, [poolId, tf, resolvedTheme]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-xs">
        {([60, 300] as const).map((t) => (
          <button key={t} onClick={() => setTf(t)}
            className={`px-2 py-1 rounded border ${tf === t ? "border-[var(--color-brand)] text-[var(--color-brand)]" : "border-[var(--color-border)] text-[var(--color-text-secondary)]"}`}>
            {t === 60 ? "1m" : "5m"}
          </button>
        ))}
        <span className="text-[var(--color-text-secondary)]">USD, execution-price candles from our own index</span>
      </div>
      <div className="relative w-full rounded overflow-hidden" style={{ height }}>
        <div ref={ref} className="absolute inset-0" />
      </div>
      {note && <div className="text-xs text-[var(--color-text-secondary)]">{note}</div>}
    </div>
  );
}
