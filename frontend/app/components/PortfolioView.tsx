'use client';
import Portfolio from './Portfolio';
import TradeHistory from './TradeHistory';
import BotSettings from './BotSettings';

export default function PortfolioView({ symbol }: { symbol: string }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start pb-6">
      {/* Left: balance / open positions / P&L + bot settings */}
      <div className="flex flex-col gap-6">
        <Portfolio />
        <BotSettings />
      </div>

      {/* Right (wide): trade history */}
      <div className="lg:col-span-2 flex flex-col">
        <TradeHistory symbol={symbol} />
      </div>
    </div>
  );
}
