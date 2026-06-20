'use client';
import PriceCard from './PriceCard';
import MarketStatsRow from './MarketStatsRow';
import PriceChangeTimeline from './PriceChangeTimeline';
import StrategyCard from './StrategyCard';
import dynamic from 'next/dynamic';

const CandleChart = dynamic(() => import('./CandleChart'), {
  ssr: false,
  loading: () => <div className="h-full w-full bg-[var(--color-bg-panel)] rounded-lg animate-pulse flex items-center justify-center text-[var(--color-text-secondary)] border border-[var(--color-border)]">Loading Chart...</div>
});
import Strategy2Card from './Strategy2Card';

export default function DashboardView({ symbol }: { symbol: string }) {
  return (
    <div className="flex flex-col gap-4 pb-6">
      {/* Stats strip + 24h timeline */}
      <div className="flex flex-col xl:flex-row gap-4">
        <div className="flex-1">
          <MarketStatsRow symbol={symbol} />
        </div>
        <div className="w-full xl:w-1/3">
          <PriceChangeTimeline symbol={symbol} />
        </div>
      </div>

      {/* Main area: left rail (cards) + right (chart on top, indicators below) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        {/* Left rail */}
        <div className="order-2 lg:order-1 flex flex-col gap-4">
          <PriceCard symbol={symbol} />
          <StrategyCard symbol={symbol} />
          <Strategy2Card symbol={symbol} />
        </div>

        {/* Right: chart + indicators get 2/3 of the width */}
        <div className="order-1 lg:order-2 lg:col-span-2 flex flex-col gap-4">
          <div className="h-[460px]">
            <CandleChart symbol={symbol} />
          </div>
        </div>
      </div>
    </div>
  );
}
