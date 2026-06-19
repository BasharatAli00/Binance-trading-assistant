'use client';
import { useState } from 'react';
import PivotCard from '../components/PivotCard';
import Indicators from '../components/Indicators';
import FuturesCard from '../components/FuturesCard';
import OrderBook from '../components/OrderBook';
import TaapiCard from '../components/TaapiCard';
import FearGreedCard from '../components/FearGreedCard';
import OnChainCard from '../components/OnChainCard';
import GoogleTrendsCard from '../components/GoogleTrendsCard';

const COIN_COLORS: Record<string, string> = {
  'BTCUSDT': '#f0b90b', // Binance Yellow
  'ETHUSDT': '#627EEA',
  'SOLUSDT': '#14F195',
  'BNBUSDT': '#F3BA2F'
};

export default function MarketAnalysisPage() {
  const [selectedCoin, setSelectedCoin] = useState('BTCUSDT');

  return (
    <div className="flex flex-col gap-6">
      <header className="shrink-0 flex justify-between items-center pb-3 border-b border-[var(--color-border)]">
        <h2 className="text-2xl font-bold text-white tracking-wide">Market Analysis</h2>

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

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
        <div className="flex flex-col gap-6 lg:col-span-2 xl:col-span-1">
          <Indicators symbol={selectedCoin} />
        </div>
        <div className="flex flex-col gap-6">
          <PivotCard symbol={selectedCoin} />

        </div>

        <div className="flex flex-col gap-6">
          <OrderBook symbol={selectedCoin} />
          <TaapiCard symbol={selectedCoin} />
        </div>


        <div className="flex flex-col gap-6">
          <FuturesCard symbol={selectedCoin} />

          <OnChainCard />
        </div>
        <div className='flex flex-col'>
          <FearGreedCard />

        </div>
        <div className='flex flex-col'>
          <GoogleTrendsCard />
        </div>
      </div>
    </div>
  );
}
