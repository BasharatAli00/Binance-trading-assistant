'use client';
import { useEffect, useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Indicators({ symbol }: { symbol: string }) {
  const [data, setData] = useState({ rsi: 0, macd: 0, ema20: 0, ema50: 0, signal: 'HOLD' });

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [priceRes, signalRes] = await Promise.all([
          fetch(`${API_URL}/api/price?symbol=${symbol}`),
          fetch(`${API_URL}/api/signal?symbol=${symbol}`)
        ]);
        const priceData = await priceRes.json();
        const signalData = await signalRes.json();
        
        setData({
          rsi: priceData.rsi || 0,
          macd: priceData.macd || 0,
          ema20: priceData.ema20 || 0,
          ema50: priceData.ema50 || 0,
          signal: signalData.signal || 'HOLD'
        });
      } catch (err) {
        console.error("Error fetching indicators", err);
      }
    };
    
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  const getRsiColor = (rsi: number) => {
    if (rsi > 70) return 'text-[#F6465D]'; // Overbought
    if (rsi < 30) return 'text-[#0ECB81]'; // Oversold
    return 'text-white';
  };

  const getSignalStyle = (sig: string) => {
    switch (sig) {
      case 'BUY': return 'bg-[#0ECB81]/20 text-[#0ECB81] border-[#0ECB81]';
      case 'SELL': return 'bg-[#F6465D]/20 text-[#F6465D] border-[#F6465D]';
      default: return 'bg-[#FCD535]/20 text-[#FCD535] border-[#FCD535]';
    }
  };

  return (
    <div className="bg-[#181a20] border border-[#2b3139] p-6 rounded-lg shadow-lg flex flex-col gap-6">
      <div className="flex justify-between items-center pb-4 border-b border-[#2b3139]">
        <span className="text-gray-400 text-sm font-medium uppercase">Current Signal</span>
        <div className={`px-4 py-1.5 rounded text-sm font-bold border ${getSignalStyle(data.signal)}`}>
          {data.signal}
        </div>
      </div>
      
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-[#0b0e14] border border-[#2b3139] p-4 rounded-lg flex flex-col items-center">
          <span className="text-gray-500 text-xs uppercase mb-1">RSI (14)</span>
          <span className={`text-xl font-bold ${getRsiColor(data.rsi)}`}>{data.rsi.toFixed(2)}</span>
        </div>
        <div className="bg-[#0b0e14] border border-[#2b3139] p-4 rounded-lg flex flex-col items-center">
          <span className="text-gray-500 text-xs uppercase mb-1">MACD</span>
          <span className={`text-xl font-bold ${data.macd >= 0 ? 'text-[#0ECB81]' : 'text-[#F6465D]'}`}>{data.macd.toFixed(2)}</span>
        </div>
        <div className="bg-[#0b0e14] border border-[#2b3139] p-4 rounded-lg flex flex-col items-center">
          <span className="text-gray-500 text-xs uppercase mb-1">EMA 20</span>
          <span className="text-xl font-bold text-gray-200">${data.ema20.toFixed(2)}</span>
        </div>
        <div className="bg-[#0b0e14] border border-[#2b3139] p-4 rounded-lg flex flex-col items-center">
          <span className="text-gray-500 text-xs uppercase mb-1">EMA 50</span>
          <span className="text-xl font-bold text-gray-200">${data.ema50.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
}
