'use client';
import { useState } from 'react';
import PivotCard from '../components/PivotCard';
import FuturesCard from '../components/FuturesCard';
import OrderBook from '../components/OrderBook';
import FearGreedCard from '../components/FearGreedCard';
import dynamic from 'next/dynamic';

const SkeletonCard = ({ title }: { title: string }) => (
  <div className="h-48 w-full bg-[var(--color-bg-panel)] rounded-lg animate-pulse p-4 border border-[var(--color-border)] flex flex-col gap-4">
    <div className="h-4 w-1/3 bg-[var(--color-bg-hover)] rounded"></div>
    <div className="flex-1 flex items-center justify-center text-[var(--color-text-secondary)]">Loading {title}...</div>
  </div>
);

const Indicators = dynamic(() => import('../components/Indicators'), { ssr: false, loading: () => <SkeletonCard title="Indicators" /> });
const TaapiCard = dynamic(() => import('../components/TaapiCard'), { ssr: false, loading: () => <SkeletonCard title="Taapi Data" /> });
const OnChainCard = dynamic(() => import('../components/OnChainCard'), { ssr: false, loading: () => <SkeletonCard title="On-Chain Data" /> });
const GoogleTrendsCard = dynamic(() => import('../components/GoogleTrendsCard'), { ssr: false, loading: () => <SkeletonCard title="Trends" /> });

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
      <header className="shrink-0 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-3 border-b border-[var(--color-border)]">
        <h2 className="text-2xl font-bold text-[color:var(--color-text-primary)] tracking-wide">Market Analysis</h2>

        <div className="flex gap-2 bg-[var(--color-bg-panel)] p-1 rounded-lg border border-[var(--color-border)]">
          {['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'].map(sym => (
            <button
              key={sym}
              onClick={() => setSelectedCoin(sym)}
              className={`px-4 py-2 rounded-md font-bold transition-all text-sm ${selectedCoin === sym ? 'bg-[var(--color-bg-hover)] shadow-sm' : 'text-[var(--color-text-secondary)] hover:text-[color:var(--color-text-primary)]'}`}
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
