'use client';
import PriceCard from './PriceCard';
import FearGreedCard from './FearGreedCard';
import CandleChart from './CandleChart';
import Indicators from './Indicators';
import MarketStatsRow from './MarketStatsRow';
import PriceChangeTimeline from './PriceChangeTimeline';
import OrderBook from './OrderBook';
import NewsWidget from './NewsWidget';
import OnChainCard from './OnChainCard';
import TaapiCard from './TaapiCard';
import GoogleTrendsCard from './GoogleTrendsCard';
import StrategyCard from './StrategyCard';
import PivotCard from './PivotCard';
import FuturesCard from './FuturesCard';
import PivotStrategyCard from './PivotStrategyCard';

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
        <div className="flex flex-col gap-4">
          <PriceCard symbol={symbol} />
          <StrategyCard symbol={symbol} />
          <PivotStrategyCard symbol={symbol} />
          <PivotCard symbol={symbol} />
          <FuturesCard symbol={symbol} />
          <OrderBook symbol={symbol} />
          <FearGreedCard />
          <NewsWidget />
          <OnChainCard />
          <GoogleTrendsCard />
        </div>

        {/* Right: chart + indicators get 2/3 of the width */}
        <div className="lg:col-span-2 flex flex-col gap-4">
          <div className="h-[460px]">
            <CandleChart symbol={symbol} />
          </div>
          <Indicators symbol={symbol} />
          <TaapiCard symbol={symbol} />
        </div>
      </div>
    </div>
  );
}
