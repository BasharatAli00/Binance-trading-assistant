'use client';
import { useEffect, useRef, useState } from 'react';
import { createChart, IChartApi, ISeriesApi, Time, CandlestickSeries, HistogramSeries } from 'lightweight-charts';

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

export default function CandleChart({ symbol }: { symbol: string }) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const [chart, setChart] = useState<IChartApi | null>(null);
  const [candleSeries, setCandleSeries] = useState<ISeriesApi<"Candlestick"> | null>(null);
  const [volumeSeries, setVolumeSeries] = useState<ISeriesApi<"Histogram"> | null>(null);
  const initializedSymbol = useRef<string | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chartInstance = createChart(chartContainerRef.current, {
      autoSize: true,
      layout: {
        background: { type: 'solid' as any, color: '#181A20' },
        textColor: '#848E9C',
      },
      grid: {
        vertLines: { color: '#2B3139' },
        horzLines: { color: '#2B3139' },
      },
      timeScale: {
        borderColor: '#2B3139',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: '#2B3139',
      },
      crosshair: {
        mode: 0, // Normal mode
      }
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
      priceScaleId: '', // overlay
    });

    vSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    setChart(chartInstance);
    setCandleSeries(cSeries);
    setVolumeSeries(vSeries);

    return () => {
      chartInstance.remove();
    };
  }, []);

  useEffect(() => {
    if (!chart || !candleSeries || !volumeSeries) return;

    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/candles?symbol=${symbol}&t=${Date.now()}`);
        const data: CandleData[] = await res.json();
        
        if (data && data.length > 0) {
          const cData = data.map(d => ({
            time: d.time,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close
          }));
          
          const vData: VolumeData[] = data.map(d => ({
            time: d.time,
            value: d.volume || 0,
            color: d.close >= d.open ? 'rgba(14, 203, 129, 0.5)' : 'rgba(246, 70, 93, 0.5)'
          }));

          candleSeries.setData(cData);
          volumeSeries.setData(vData);
          
          // Fit content if we just switched symbols
          if (initializedSymbol.current !== symbol) {
            chart.timeScale().fitContent();
            initializedSymbol.current = symbol;
          }
        }
      } catch (err) {
        console.error("Error fetching candle data", err);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000); // 30s as requested
    return () => clearInterval(interval);
  }, [chart, candleSeries, volumeSeries, symbol]);

  return (
    <div className="bg-[#181a20] border border-[#2b3139] p-4 rounded-lg flex flex-col h-[400px] lg:h-full w-full">
      <div className="text-gray-400 text-sm mb-4 font-medium uppercase tracking-wider flex justify-between shrink-0">
        <span>{symbol.replace('USDT', '/USDT')} 1H Chart</span>
      </div>
      <div className="relative flex-grow w-full rounded overflow-hidden">
        <div ref={chartContainerRef} className="absolute inset-0" />
      </div>
    </div>
  );
}
