'use client';
import { useState } from 'react';
import Sidebar, { View } from './components/Sidebar';
import DashboardView from './components/DashboardView';
import PortfolioView from './components/PortfolioView';

const COIN_COLORS: Record<string, string> = {
  'BTCUSDT': '#F7931A',
  'ETHUSDT': '#627EEA',
  'SOLUSDT': '#9945FF',
  'BNBUSDT': '#F3BA2F'
};

const VIEW_TITLES: Record<View, string> = {
  dashboard: 'Dashboard',
  portfolio: 'Portfolio',
};

export default function Home() {
  const [selectedCoin, setSelectedCoin] = useState('BTCUSDT');
  const [view, setView] = useState<View>('dashboard');

  return (
    <div className="flex h-screen bg-[#0f0f0f] text-gray-200 font-sans overflow-hidden">
      <Sidebar active={view} onSelect={setView} />

      <main className="flex-1 flex flex-col overflow-hidden p-6">
        {/* Header: page title + coin selector */}
        <header className="shrink-0 flex justify-between items-center pb-3 mb-4 border-b border-[#2b3139]">
          <h2 className="text-xl font-bold text-white tracking-wide">{VIEW_TITLES[view]}</h2>

          {/* Coin Selector Tabs */}
          <div className="flex gap-2 bg-[#181a20] p-1 rounded-lg border border-[#2b3139]">
            {['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'].map(sym => (
              <button
                key={sym}
                onClick={() => setSelectedCoin(sym)}
                className={`px-4 py-2 rounded-md font-bold transition-colors ${selectedCoin === sym ? 'bg-[#2b3139] text-white' : 'text-gray-400 hover:text-gray-200'}`}
                style={{ color: selectedCoin === sym ? COIN_COLORS[sym] : undefined }}
              >
                {sym.replace('USDT', '')}
              </button>
            ))}
          </div>
        </header>

        {/* Active view */}
        <div className="flex-1 overflow-y-auto custom-scrollbar pr-1">
          {view === 'dashboard'
            ? <DashboardView symbol={selectedCoin} />
            : <PortfolioView symbol={selectedCoin} />}
        </div>
      </main>
    </div>
  );
}
