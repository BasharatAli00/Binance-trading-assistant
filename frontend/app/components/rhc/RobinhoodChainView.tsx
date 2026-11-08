"use client";

import { useEffect, useState } from "react";
import { Activity, BarChart3, Gauge, HeartPulse, LayoutGrid, ListChecks, Wallet } from "lucide-react";
import { fmtNum, fmtPct, rhcGet, usePoll, type Health, type Reason } from "./api";
import DecisionsPanel from "./DecisionsPanel";
import HealthPanel, { HealthSummary } from "./HealthPanel";
import PaperPanel from "./PaperPanel";
import PerformancePanel from "./PerformancePanel";
import RiskPanel from "./RiskPanel";
import TokenReport from "./TokenReport";
import WatchlistPanel from "./WatchlistPanel";
import { Card, Chips, PaperBanner, ReasonsContext, Stat } from "./ui";

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutGrid },
  { id: "watchlist", label: "Discovery & Watchlist", icon: ListChecks },
  { id: "signals", label: "Signals & Decisions", icon: Activity },
  { id: "paper", label: "Paper Trading", icon: Wallet },
  { id: "performance", label: "Performance & Validation", icon: BarChart3 },
  { id: "risk", label: "Risk", icon: Gauge },
  { id: "system", label: "System Health", icon: HeartPulse },
] as const;

type TabId = (typeof TABS)[number]["id"];

function RegimeCard() {
  const { data } = usePoll<Health>("/health", 30000);
  const r = data?.regime;
  return (
    <Card title="Market conditions & regime">
      <div className="grid grid-cols-2 gap-4">
        <Stat label="Regime" value={r?.label ?? "—"} sub={r?.pct !== undefined && r?.pct !== null ? `volume pct ${fmtNum(r.pct, 2)}` : "needs ≥ 2 h history"}
          tone={r?.label === "cold" ? "bad" : r?.label === "hot" ? "good" : undefined} />
        <Stat label="ETH 1h" value={fmtPct(r?.eth_ret_1h ?? null)} tone={(r?.eth_ret_1h ?? 0) < 0 ? "bad" : "good"} />
        <Stat label="Market volume 1h" value={r?.market_vol_1h ? `$${fmtNum(r.market_vol_1h, 0)}` : "—"} sub="tracked pools" />
        <div>
          <div className="text-[11px] uppercase tracking-wider text-[var(--color-text-secondary)] mb-1">No-trade conditions</div>
          <Chips list={r?.no_trade ?? []} />
        </div>
      </div>
    </Card>
  );
}

export default function RobinhoodChainView() {
  const [tab, setTab] = useState<TabId>("overview");
  const [pool, setPool] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, Reason>>({});

  useEffect(() => {
    let live = true;
    rhcGet<Reason[]>("/reasons")
      .then((rs) => { if (live) setReasons(Object.fromEntries(rs.map((r) => [r.code, r]))); })
      .catch(() => undefined);
    return () => { live = false; };
  }, []);

  return (
    <ReasonsContext.Provider value={reasons}>
      <div className="p-4 md:p-6 space-y-4 max-w-[1600px] mx-auto">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold">Robinhood Chain</h1>
            <p className="text-sm text-[var(--color-text-secondary)]">
              Autonomous token discovery, safety screening, signals and paper trading on chain 4663.
            </p>
          </div>
          <HealthSummary />
        </div>
        <PaperBanner />

        <nav className="flex gap-1 overflow-x-auto custom-scrollbar border-b border-[var(--color-border)]">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setTab(id)}
              className={`flex items-center gap-2 px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px ${tab === id
                ? "border-[var(--color-brand)] text-[var(--color-text-primary)] font-semibold"
                : "border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"}`}>
              <Icon className="w-4 h-4" /> {label}
            </button>
          ))}
        </nav>

        {tab === "overview" && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 space-y-4">
              <WatchlistPanel onSelect={setPool} compact fixedState="watch" />
              <DecisionsPanel compact />
              <PaperPanel compact />
            </div>
            <div className="space-y-4">
              <RegimeCard />
              <RiskPanel compact />
            </div>
          </div>
        )}
        {tab === "watchlist" && <WatchlistPanel onSelect={setPool} />}
        {tab === "signals" && <DecisionsPanel />}
        {tab === "paper" && <PaperPanel />}
        {tab === "performance" && <PerformancePanel />}
        {tab === "risk" && <RiskPanel />}
        {tab === "system" && <HealthPanel />}

        {pool && <TokenReport poolId={pool} onClose={() => setPool(null)} />}
      </div>
    </ReasonsContext.Provider>
  );
}
