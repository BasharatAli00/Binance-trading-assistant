'use client';
import { useState } from 'react';
import Portfolio from './Portfolio';
import TradeHistory from './TradeHistory';
import BotSettings from './BotSettings';
import PivotPortfolio from './PivotPortfolio';
import PivotTradeHistory from './PivotTradeHistory';

type Tab = 'one' | 'two';

const TABS: { id: Tab; label: string; sub: string }[] = [
  { id: 'one', label: 'Strategy One', sub: 'Trend-Follow' },
  { id: 'two', label: 'Strategy Two', sub: 'Pivot Bracket' },
];

export default function PortfolioView({ symbol }: { symbol: string }) {
  const [tab, setTab] = useState<Tab>('one');  // Strategy One is the default

  return (
    <div className="flex flex-col gap-6 pb-6">
      {/* Strategy tabs */}
      <div className="flex gap-2 bg-[var(--color-bg-panel)] p-1 rounded-lg border border-[var(--color-border)] w-fit">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 rounded-md font-bold transition-all text-sm ${
              tab === t.id ? 'bg-[var(--color-bg-hover)] text-[color:var(--color-text-primary)] shadow-sm' : 'text-[var(--color-text-secondary)] hover:text-[color:var(--color-text-primary)]'
            }`}
          >
            {t.label}
            <span className="ml-2 text-[10px] font-normal text-[var(--color-text-secondary)] uppercase">{t.sub}</span>
          </button>
        ))}
      </div>

      {/* Active strategy */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {tab === 'one' ? (
          <>
            <div className="flex flex-col gap-6">
              <Portfolio />
              <BotSettings />
            </div>
            <div className="lg:col-span-2 flex flex-col">
              <TradeHistory symbol={symbol} />
            </div>
          </>
        ) : (
          <>
            <div className="flex flex-col gap-6">
              <PivotPortfolio />
            </div>
            <div className="lg:col-span-2 flex flex-col">
              <PivotTradeHistory symbol={symbol} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
