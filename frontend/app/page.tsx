'use client';
import { useState } from 'react';
import DashboardView from './components/DashboardView';

const COIN_COLORS: Record<string, string> = {
  'BTCUSDT': '#f0b90b', // Binance Yellow
  'ETHUSDT': '#627EEA',
  'SOLUSDT': '#14F195',
  'BNBUSDT': '#F3BA2F'
};

export default function Home() {
  const [selectedCoin, setSelectedCoin] = useState('BTCUSDT');

  return (
    <div className="flex flex-col gap-6">
      {/* Header: page title + coin selector */}
      <header className="shrink-0 flex justify-between items-center pb-3 border-b border-[var(--color-border)]">
        <h2 className="text-2xl font-bold text-white tracking-wide">Market Overview</h2>

        {/* Coin Selector Tabs */}
        <div className="flex gap-2 bg-[var(--color-bg-panel)] p-1 rounded-lg border border-[var(--color-border)]">
          {['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'].map(sym => (
            <button
              key={sym}
              onClick={() => setSelectedCoin(sym)}
              className={`px-4 py-2 rounded-md font-bold transition-all text-sm ${selectedCoin === sym ? 'bg-[var(--color-bg-hover)] shadow-sm' : 'text-[var(--color-text-secondary)] hover:text-white'}`}
              style={{ color: selectedCoin === sym ? COIN_COLORS[sym] : undefined }}
            >
              {sym.replace('USDT', '')}
            </button>
          ))}
        </div>
      </header>

      {/* Active view */}
      <DashboardView symbol={selectedCoin} />
    </div>
  );
}
