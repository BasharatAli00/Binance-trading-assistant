'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Crosshair, RefreshCw, Wallet, ShieldCheck, BarChart3, Target,
  Eye, Clock, Pause, Play, SlidersHorizontal, RotateCcw, BrainCircuit,
} from 'lucide-react';
import API_URL from '@/lib/config';

// ---------- types ----------
type Stat = { trades: number; wins: number; losses: number; pnl: number; win_rate: number };
type CB = {
  enabled: boolean; max_drawdown: number; current_drawdown: number;
  headroom_pct: number | null; headroom_usd: number | null; tripped: boolean;
};
type Summary = {
  id: number; name: string; mode: string; is_active: boolean;
  cash_balance: number; initial_balance: number; position_size: number;
  max_open_positions: number; open_positions: number; open_exposure: number;
  positions_value: number; total_value: number; unrealized_pnl: number;
  realized_pnl: number; total_pnl: number; total_pnl_pct: number; win_rate: number;
  today: Stat; overall: Stat; circuit_breaker: CB; config: Record<string, number | boolean>;
};
type Loop = {
  running: boolean; last_tick: string | null; last_tick_seconds: number;
  tracked_tokens: number; candidates: number;
};
type Position = {
  token_address: string; symbol: string; entry_price: number; qty: number;
  position_usd: number; last_price: number; conviction_score: number;
  rug_risk_score: number; status: string; return_pct: number; realized_pnl: number;
  exit_reason: string; unrealized_pnl: number; hold_minutes: number; entry_time: string;
};
type WatchRow = {
  token_address: string; symbol: string; name: string; dex_id: string;
  liquidity_usd: number; volume_h1: number; price_usd: number; market_cap: number;
  discovery_source: string; conviction_score: number | null; rug_risk_score: number | null;
};
type ChartPoint = { ts: string | null; cum_pnl: number };
type ModelInfo = {
  ready: boolean; val_auc: number | null; n_samples: number | null;
  n_pos: number | null; suggested_prob_floor: number | null; trained_at: string | null;
  training: boolean; last_train: { ok: boolean; error?: string } | null;
};

// ---------- helpers ----------
const GREEN = '#2ecc71';
const RED = '#ff4466';
const usd = (n?: number, d = 2) =>
  `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })}`;
const signedUsd = (n?: number) => `${(n ?? 0) >= 0 ? '+' : '-'}$${Math.abs(n ?? 0).toFixed(2)}`;
const pct = (n?: number) => `${(n ?? 0) >= 0 ? '+' : ''}${(n ?? 0).toFixed(2)}%`;
const pnlColor = (n?: number) => ((n ?? 0) >= 0 ? GREEN : RED);
const tokenPrice = (n?: number) => {
  const v = n ?? 0;
  if (v === 0) return '$0';
  if (v < 0.0001) return `$${v.toExponential(2)}`;
  return `$${v.toPrecision(4)}`;
};
const short = (a: string) => (a ? `${a.slice(0, 4)}…${a.slice(-4)}` : '');

// Tiny dependency-free area sparkline for the cumulative P&L curve.
function PnlChart({ data }: { data: ChartPoint[] }) {
  const W = 900, H = 180, P = 8;
  if (!data || data.length < 2) {
    return <div className="h-[180px] flex items-center justify-center text-[var(--color-text-secondary)] text-sm">No closed trades yet</div>;
  }
  const ys = data.map((d) => d.cum_pnl);
  const min = Math.min(...ys, 0);
  const max = Math.max(...ys, 0);
  const span = max - min || 1;
  const x = (i: number) => P + (i / (data.length - 1)) * (W - 2 * P);
  const y = (v: number) => P + (1 - (v - min) / span) * (H - 2 * P);
  const line = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(d.cum_pnl).toFixed(1)}`).join(' ');
  const area = `${line} L${x(data.length - 1).toFixed(1)},${y(min)} L${x(0).toFixed(1)},${y(min)} Z`;
  const last = ys[ys.length - 1];
  const stroke = last >= 0 ? GREEN : RED;
  const zeroY = y(0);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[180px]" preserveAspectRatio="none">
      <defs>
        <linearGradient id="pnlgrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.30" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <line x1={P} y1={zeroY} x2={W - P} y2={zeroY} stroke="#333" strokeDasharray="3 3" strokeWidth="1" />
      <path d={area} fill="url(#pnlgrad)" />
      <path d={line} fill="none" stroke={stroke} strokeWidth="2" />
    </svg>
  );
}

// ---------- main ----------
const TABS = ['Overview', 'Positions', 'Watchlist', 'History'] as const;
type Tab = typeof TABS[number];

export default function SniperDashboard() {
  const [portfolios, setPortfolios] = useState<Summary[]>([]);
  const [loop, setLoop] = useState<Loop | null>(null);
  const [selId, setSelId] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>('Overview');
  const [positions, setPositions] = useState<Position[]>([]);
  const [history, setHistory] = useState<Position[]>([]);
  const [watch, setWatch] = useState<WatchRow[]>([]);
  const [chart, setChart] = useState<ChartPoint[]>([]);
  const [countdown, setCountdown] = useState(60);
  const [showSettings, setShowSettings] = useState(false);
  const [model, setModel] = useState<ModelInfo | null>(null);
  const lastTickRef = useRef<string | null>(null);

  const sel = useMemo(
    () => portfolios.find((p) => p.id === selId) ?? portfolios[0],
    [portfolios, selId],
  );

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/sniper/status`);
      const j = await r.json();
      if (Array.isArray(j.portfolios)) {
        setPortfolios(j.portfolios);
        setSelId((cur) => (cur == null && j.portfolios.length ? j.portfolios[0].id : cur));
      }
      setLoop(j.loop ?? null);
      // Reset the countdown whenever the bot completes a fresh tick.
      if (j.loop?.last_tick && j.loop.last_tick !== lastTickRef.current) {
        lastTickRef.current = j.loop.last_tick;
        setCountdown(60);
      }
    } catch (e) {
      console.error('sniper status error', e);
    }
  }, []);

  const fetchDetail = useCallback(async (id: number, which: Tab) => {
    try {
      if (which === 'Positions') {
        const r = await fetch(`${API_URL}/api/sniper/positions?portfolio_id=${id}&status=open`);
        setPositions(await r.json());
      } else if (which === 'History') {
        const r = await fetch(`${API_URL}/api/sniper/positions?portfolio_id=${id}&status=closed&limit=300`);
        setHistory(await r.json());
      } else if (which === 'Watchlist') {
        const r = await fetch(`${API_URL}/api/sniper/watchlist`);
        setWatch(await r.json());
      } else if (which === 'Overview') {
        const r = await fetch(`${API_URL}/api/sniper/chart-pnl?portfolio_id=${id}`);
        setChart(await r.json());
      }
    } catch (e) {
      console.error('sniper detail error', e);
    }
  }, []);

  const fetchModel = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/sniper/model`);
      setModel(await r.json());
    } catch {
      /* model endpoint optional */
    }
  }, []);

  const trainModel = useCallback(async () => {
    if (model?.training) return;
    if (!window.confirm('Retrain the ML brain from snapshot history? This runs in the background (~1 min).')) return;
    await fetch(`${API_URL}/api/sniper/train`, { method: 'POST' });
    setModel((m) => (m ? { ...m, training: true } : m));
    setTimeout(fetchModel, 3000);
  }, [model, fetchModel]);

  useEffect(() => {
    fetchStatus();
    fetchModel();
    const iv = setInterval(() => { fetchStatus(); fetchModel(); }, 8000);
    return () => clearInterval(iv);
  }, [fetchStatus, fetchModel]);

  useEffect(() => {
    if (sel) fetchDetail(sel.id, tab);
    const iv = setInterval(() => sel && fetchDetail(sel.id, tab), 8000);
    return () => clearInterval(iv);
  }, [sel, tab, fetchDetail]);

  useEffect(() => {
    const iv = setInterval(() => setCountdown((c) => (c <= 1 ? 60 : c - 1)), 1000);
    return () => clearInterval(iv);
  }, []);

  const toggleTrading = async () => {
    if (!sel) return;
    await fetch(`${API_URL}/api/sniper/toggle/${sel.id}`, { method: 'POST' });
    fetchStatus();
  };

  const resetPortfolio = async () => {
    if (!sel) return;
    const ok = window.confirm(
      `Reset "${sel.name}" wallet?\n\nThis deletes all positions and trade history and ` +
      `restores the balance to its initial ${usd(sel.initial_balance, 0)}. This cannot be undone.`,
    );
    if (!ok) return;
    await fetch(`${API_URL}/api/sniper/reset/${sel.id}`, { method: 'POST' });
    fetchStatus();
    if (sel) fetchDetail(sel.id, tab);
  };

  const saveConfig = async (patch: Record<string, number | boolean>) => {
    if (!sel) return;
    await fetch(`${API_URL}/api/sniper/config/${sel.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    fetchStatus();
  };

  const historyCount = sel?.overall.trades ?? 0;

  return (
    <div className="max-w-6xl mx-auto font-sans text-[var(--color-text-primary)]">
      {/* ---------- Header ---------- */}
      <div className="flex items-start justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-[#15241c] border border-[#1f3a2a] flex items-center justify-center">
            <Crosshair className="w-6 h-6 text-[#2ecc71]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight">Intelligent Sniper</h1>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${loop?.running ? 'text-[#2ecc71] border-[#1f3a2a] bg-[#15241c]' : 'text-[var(--color-text-secondary)] border-[var(--color-border)] bg-[var(--color-bg-hover)]'}`}>
                ● {loop?.running ? 'Live' : 'Idle'}
              </span>
            </div>
            <p className="text-sm text-[var(--color-text-secondary)]">ML-powered pump.fun token trading bot</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Brain (ML model) status + retrain */}
          <div className="flex items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] px-3 py-2">
            <BrainCircuit className={`w-4 h-4 ${model?.ready ? 'text-[#2ecc71]' : 'text-yellow-500'}`} />
            <div className="leading-none">
              <div className="text-xs font-semibold">
                {model?.ready ? `ML brain · AUC ${(model.val_auc ?? 0).toFixed(2)}` : 'Rule-based brain'}
              </div>
              <div className="text-[9px] text-[var(--color-text-secondary)] uppercase">
                {model?.training ? 'training…'
                  : model?.ready ? `${(model.n_samples ?? 0).toLocaleString()} samples`
                  : 'no model yet'}
              </div>
            </div>
            <button onClick={trainModel} disabled={model?.training}
              title="Retrain the LightGBM brain from snapshot history"
              className="text-[var(--color-text-secondary)] hover:text-[#2ecc71] disabled:opacity-40 transition-colors">
              <RefreshCw className={`w-3.5 h-3.5 ${model?.training ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <div className="flex items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] px-3 py-2">
            <div className="text-right leading-none">
              <div className="text-base font-bold tabular-nums">{countdown}</div>
              <div className="text-[9px] text-[var(--color-text-secondary)] uppercase">sec</div>
            </div>
            <button onClick={fetchStatus} className="text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] transition-colors">
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* ---------- Wallet selector ---------- */}
      <div className="flex items-center gap-6 border-b border-[var(--color-border)] mb-4">
        {portfolios.map((p) => {
          const active = sel?.id === p.id;
          return (
            <button
              key={p.id}
              onClick={() => setSelId(p.id)}
              className={`flex items-center gap-2 pb-2 -mb-px border-b-2 transition-colors ${active ? 'border-[#2ecc71]' : 'border-transparent'}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${p.mode === 'live' ? 'bg-[#2ecc71]' : 'bg-yellow-500'}`} />
              <span className={`text-sm font-semibold ${active ? 'text-[var(--color-text-primary)]' : 'text-[var(--color-text-secondary)]'}`}>{p.name}</span>
              <span className="text-xs text-[var(--color-text-secondary)]">{usd(p.cash_balance)}</span>
              {!p.is_active && <span className="text-[9px] font-bold text-yellow-500 bg-[#241f10] border border-[#3a2f1f] px-1.5 py-0.5 rounded">PAUSED</span>}
            </button>
          );
        })}
      </div>

      {/* ---------- Sub-tabs ---------- */}
      <div className="flex items-center gap-6 mb-5">
        {TABS.map((t) => {
          const Icon = { Overview: BarChart3, Positions: Target, Watchlist: Eye, History: Clock }[t];
          const badge = t === 'Positions' ? sel?.open_positions
            : t === 'Watchlist' ? (loop?.tracked_tokens ?? watch.length)
            : t === 'History' ? historyCount : null;
          const active = tab === t;
          return (
            <button key={t} onClick={() => setTab(t)}
              className={`flex items-center gap-2 text-sm font-medium transition-colors ${active ? 'text-[#2ecc71]' : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}`}>
              <Icon className="w-4 h-4" />
              {t}
              {badge != null && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${active ? 'bg-[#15241c] text-[#2ecc71]' : 'bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]'}`}>{badge}</span>
              )}
            </button>
          );
        })}
      </div>

      {!sel ? (
        <div className="text-[var(--color-text-secondary)] text-sm py-20 text-center">Loading sniper…</div>
      ) : tab === 'Overview' ? (
        <Overview sel={sel} chart={chart} onToggle={toggleTrading} onReset={resetPortfolio}
          onOpenSettings={() => setShowSettings((s) => !s)} showSettings={showSettings}
          onSave={saveConfig} />
      ) : tab === 'Positions' ? (
        <PositionsTable rows={positions} />
      ) : tab === 'Watchlist' ? (
        <WatchlistTable rows={watch} rugVeto={Number(sel.config.rug_veto_threshold ?? 45)} floor={Number(sel.config.conviction_floor ?? 20)} />
      ) : (
        <HistoryTable rows={history} />
      )}
    </div>
  );
}

// ---------- Overview ----------
function Overview({ sel, chart, onToggle, onReset, onOpenSettings, showSettings, onSave }: {
  sel: Summary; chart: ChartPoint[]; onToggle: () => void; onReset: () => void;
  onOpenSettings: () => void; showSettings: boolean;
  onSave: (p: Record<string, number | boolean>) => void;
}) {
  const cb = sel.circuit_breaker;
  return (
    <div className="space-y-5">
      {/* Wallet / P&L card */}
      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-6">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-xl bg-[#15241c] border border-[#1f3a2a] flex items-center justify-center">
              <Wallet className="w-6 h-6 text-[#2ecc71]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-3xl font-bold tabular-nums">{usd(sel.cash_balance)}</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${sel.mode === 'live' ? 'text-[#2ecc71] bg-[#15241c]' : 'text-yellow-500 bg-[#241f10]'}`}>
                  {sel.mode.toUpperCase()}
                </span>
              </div>
              <div className="text-xs text-[var(--color-text-secondary)] mt-1">
                Cash Balance · Initial: {usd(sel.initial_balance, 0)} · Per trade: {usd(sel.position_size, 0)}
              </div>
            </div>
          </div>
          <div className="flex gap-8">
            <div className="text-right">
              <div className="text-[11px] text-[var(--color-text-secondary)] uppercase">Today</div>
              <div className="text-lg font-bold" style={{ color: pnlColor(sel.today.pnl) }}>{signedUsd(sel.today.pnl)}</div>
              <div className="text-[11px] text-[var(--color-text-secondary)]">{sel.today.trades} trades · {sel.today.wins}W / {sel.today.losses}L</div>
            </div>
            <div className="text-right">
              <div className="text-[11px] text-[var(--color-text-secondary)] uppercase">Overall</div>
              <div className="text-lg font-bold" style={{ color: pnlColor(sel.realized_pnl) }}>{signedUsd(sel.realized_pnl)}</div>
              <div className="text-[11px] text-[var(--color-text-secondary)]">{sel.overall.trades} trades · {sel.overall.wins}W / {sel.overall.losses}L</div>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between mt-5 pt-4">
          <div className="flex items-center gap-2 text-sm">
            <span className={`w-2 h-2 rounded-full ${sel.is_active ? 'bg-[#2ecc71]' : 'bg-yellow-500'}`} />
            <span className="text-[var(--color-text-secondary)]">
              {sel.is_active
                ? `Trading Active — Bot is scanning for entries every ${60}s`
                : 'Trading Paused'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onToggle}
              className="flex items-center gap-2 text-sm font-medium px-3 py-1.5 rounded-lg border border-[var(--color-border)] hover:border-gray-500 transition-colors">
              {sel.is_active ? <><Pause className="w-4 h-4" /> Pause Trading</> : <><Play className="w-4 h-4" /> Resume Trading</>}
            </button>
            <button onClick={onReset}
              title={`Reset wallet to ${usd(sel.initial_balance, 0)} and clear history`}
              className="flex items-center gap-2 text-sm font-medium px-3 py-1.5 rounded-lg border border-[#3a1f1f] text-[#ff4466] hover:bg-[#241010] transition-colors">
              <RotateCcw className="w-4 h-4" /> Reset
            </button>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5 pt-5 border-t border-[var(--color-border)]">
          <Stat label="Open Positions" value={`${sel.open_positions}/${sel.max_open_positions}`} />
          <Stat label="Open Exposure" value={usd(sel.open_exposure)} />
          <Stat label="Win Rate" value={`${(sel.win_rate ?? 0).toFixed(0)}%`} />
          <Stat label="Total Value" value={usd(sel.total_value)} valueColor={pnlColor(sel.total_pnl)} />
        </div>

        {/* Circuit breaker */}
        <div className="flex items-center gap-2 mt-4 text-xs text-[var(--color-text-secondary)]">
          <ShieldCheck className="w-4 h-4 text-[#2ecc71]" />
          Circuit Breaker: <span className={cb.enabled ? 'text-[#2ecc71]' : 'text-[var(--color-text-secondary)]'}>{cb.enabled ? 'Active' : 'Off'}</span>
          {cb.enabled && (
            <>
              <span>· Max drawdown {cb.max_drawdown}%</span>
              {cb.headroom_pct != null && (
                <span>· Headroom: {cb.headroom_pct.toFixed(1)}%{cb.headroom_usd != null ? ` (${usd(cb.headroom_usd)} left before pause)` : ''}</span>
              )}
              {cb.tripped && <span className="text-[#ff4466] font-bold">· TRIPPED</span>}
            </>
          )}
        </div>

        <button onClick={onOpenSettings}
          className="flex items-center gap-1.5 text-xs text-[#2ecc71] mt-4 hover:underline">
          <SlidersHorizontal className="w-3.5 h-3.5" /> Portfolio Settings
        </button>
        {showSettings && <SettingsPanel sel={sel} onSave={onSave} />}
      </div>

      {/* P&L chart */}
      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-5">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-[var(--color-text-secondary)] font-semibold">Cumulative P&L</span>
          <span className="text-sm font-bold" style={{ color: pnlColor(sel.realized_pnl) }}>
            {signedUsd(sel.realized_pnl)} <span className="text-[var(--color-text-secondary)] font-normal text-xs">{sel.overall.trades} trades</span>
          </span>
        </div>
        <PnlChart data={chart} />
      </div>
    </div>
  );
}

function Stat({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div>
      <div className="text-[11px] text-[var(--color-text-secondary)] uppercase tracking-wide">{label}</div>
      <div className="text-xl font-bold mt-0.5" style={valueColor ? { color: valueColor } : undefined}>{value}</div>
    </div>
  );
}

// ---------- Settings ----------
const FIELDS: { key: string; label: string; step?: number }[] = [
  { key: 'initial_balance', label: 'Initial balance ($)' },
  { key: 'position_size', label: 'Position size ($)' },
  { key: 'max_open_positions', label: 'Max open positions' },
  { key: 'stop_loss_pct', label: 'Stop loss (%)' },
  { key: 'take_profit_pct', label: 'Take profit (%)' },
  { key: 'time_exit_minutes', label: 'Time exit (min)' },
  { key: 'scale_out_pct', label: 'Scale-out at (%)' },
  { key: 'scale_out_fraction', label: 'Scale-out fraction (0-1)', step: 0.05 },
  { key: 'runner_trail_pct', label: 'Runner trail (%)' },
  { key: 'trail_start_pct', label: 'Trail start (%)' },
  { key: 'trail_end_pct', label: 'Trail end (%)' },
  { key: 'no_progress_minutes', label: 'No-progress cull (min)' },
  { key: 'no_progress_pct', label: 'No-progress gain (%)' },
  { key: 'conviction_floor', label: 'Conviction floor' },
  { key: 'rug_veto_threshold', label: 'Rug veto threshold' },
  { key: 'cb_max_drawdown', label: 'Circuit breaker DD (%)' },
];

function SettingsPanel({ sel, onSave }: { sel: Summary; onSave: (p: Record<string, number | boolean>) => void }) {
  const [form, setForm] = useState<Record<string, string>>(() =>
    Object.fromEntries(FIELDS.map((f) => [f.key, String(sel.config[f.key] ?? '')])));

  const submit = () => {
    const patch: Record<string, number> = {};
    for (const f of FIELDS) {
      const v = Number(form[f.key]);
      if (!Number.isNaN(v)) patch[f.key] = v;
    }
    onSave(patch);
  };

  return (
    <div className="mt-4 p-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-panel)]">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {FIELDS.map((f) => (
          <label key={f.key} className="text-xs text-[var(--color-text-secondary)]">
            {f.label}
            <input
              value={form[f.key]}
              onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
              className="mt-1 w-full bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded px-2 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[#2ecc71] outline-none"
            />
          </label>
        ))}
      </div>
      <p className="mt-3 text-[11px] text-[var(--color-text-secondary)]">
        Changing <span className="text-[var(--color-text-primary)]">Initial balance</span> sets the new
        starting amount and P&amp;L baseline — click <span className="text-[#ff4466]">Reset</span> afterwards
        to fund the wallet with it and clear history.
      </p>
      <button onClick={submit}
        className="mt-3 text-sm font-medium px-4 py-1.5 rounded-lg bg-[#15241c] text-[#2ecc71] border border-[#1f3a2a] hover:bg-[#1a2e22]">
        Save settings
      </button>
    </div>
  );
}

// ---------- Tables ----------
function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`text-[11px] uppercase text-[var(--color-text-secondary)] font-medium pb-2 ${right ? 'text-right' : 'text-left'}`}>{children}</th>;
}
function rugColor(n: number | null) {
  if (n == null) return '#9ca3af';
  if (n >= 45) return RED;
  if (n >= 25) return '#f5a623';
  return GREEN;
}

function PositionsTable({ rows }: { rows: Position[] }) {
  if (!rows.length) return <Empty text="No open positions" />;
  return (
    <TableShell head={<><Th>Token</Th><Th right>Entry</Th><Th right>Mark</Th><Th right>Size</Th><Th right>Conv</Th><Th right>Rug</Th><Th right>Unreal. P&L</Th><Th right>Held</Th></>}>
      {rows.map((r) => (
        <tr key={r.token_address} className="border-t border-[var(--color-border)]">
          <td className="py-2.5"><div className="font-semibold text-sm">{r.symbol || short(r.token_address)}</div><div className="text-[10px] text-[var(--color-text-secondary)]">{short(r.token_address)}</div></td>
          <td className="text-right tabular-nums text-sm">{tokenPrice(r.entry_price)}</td>
          <td className="text-right tabular-nums text-sm">{tokenPrice(r.last_price)}</td>
          <td className="text-right tabular-nums text-sm">{usd(r.position_usd, 0)}</td>
          <td className="text-right text-sm font-semibold text-[#2ecc71]">{Math.round(r.conviction_score)}</td>
          <td className="text-right text-sm font-semibold" style={{ color: rugColor(r.rug_risk_score) }}>{Math.round(r.rug_risk_score)}</td>
          <td className="text-right tabular-nums text-sm font-semibold" style={{ color: pnlColor(r.unrealized_pnl) }}>{signedUsd(r.unrealized_pnl)}</td>
          <td className="text-right tabular-nums text-sm text-[var(--color-text-secondary)]">{Math.round(r.hold_minutes)}m</td>
        </tr>
      ))}
    </TableShell>
  );
}

function HistoryTable({ rows }: { rows: Position[] }) {
  if (!rows.length) return <Empty text="No closed trades yet" />;
  return (
    <TableShell head={<><Th>Token</Th><Th right>Entry</Th><Th right>Exit</Th><Th right>Return</Th><Th right>P&L</Th><Th>Reason</Th></>}>
      {rows.map((r, i) => (
        <tr key={`${r.token_address}-${i}`} className="border-t border-[var(--color-border)]">
          <td className="py-2.5"><div className="font-semibold text-sm">{r.symbol || short(r.token_address)}</div><div className="text-[10px] text-[var(--color-text-secondary)]">{short(r.token_address)}</div></td>
          <td className="text-right tabular-nums text-sm">{tokenPrice(r.entry_price)}</td>
          <td className="text-right tabular-nums text-sm">{tokenPrice(r.last_price)}</td>
          <td className="text-right tabular-nums text-sm font-semibold" style={{ color: pnlColor(r.return_pct) }}>{pct(r.return_pct)}</td>
          <td className="text-right tabular-nums text-sm font-semibold" style={{ color: pnlColor(r.realized_pnl) }}>{signedUsd(r.realized_pnl)}</td>
          <td className="text-xs text-[var(--color-text-secondary)]">{(r.exit_reason || '').replace(/_/g, ' ')}</td>
        </tr>
      ))}
    </TableShell>
  );
}

function WatchlistTable({ rows, rugVeto, floor }: { rows: WatchRow[]; rugVeto: number; floor: number }) {
  if (!rows.length) return <Empty text="Discovering tokens… (first watchlist builds within ~5 min)" />;
  return (
    <TableShell head={<><Th>Token</Th><Th>Source</Th><Th right>Price</Th><Th right>Liq</Th><Th right>Vol 1h</Th><Th right>Conviction</Th><Th right>Rug</Th></>}>
      {rows.map((r) => {
        const tradeable = (r.conviction_score ?? 0) >= floor && (r.rug_risk_score ?? 100) < rugVeto;
        return (
          <tr key={r.token_address} className="border-t border-[var(--color-border)]">
            <td className="py-2.5">
              <div className="flex items-center gap-2">
                {tradeable && <span className="w-1.5 h-1.5 rounded-full bg-[#2ecc71]" title="passes gates" />}
                <div>
                  <div className="font-semibold text-sm">{r.symbol || short(r.token_address)}</div>
                  <div className="text-[10px] text-[var(--color-text-secondary)]">{short(r.token_address)}</div>
                </div>
              </div>
            </td>
            <td className="text-xs text-[var(--color-text-secondary)]">{r.discovery_source}</td>
            <td className="text-right tabular-nums text-sm">{tokenPrice(r.price_usd)}</td>
            <td className="text-right tabular-nums text-sm">{usd(r.liquidity_usd, 0)}</td>
            <td className="text-right tabular-nums text-sm">{usd(r.volume_h1, 0)}</td>
            <td className="text-right text-sm font-semibold text-[#2ecc71]">{r.conviction_score != null ? Math.round(r.conviction_score) : '—'}</td>
            <td className="text-right text-sm font-semibold" style={{ color: rugColor(r.rug_risk_score) }}>{r.rug_risk_score != null ? Math.round(r.rug_risk_score) : '—'}</td>
          </tr>
        );
      })}
    </TableShell>
  );
}

function TableShell({ head, children }: { head: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-5 overflow-x-auto">
      <table className="w-full min-w-[640px]">
        <thead><tr>{head}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-12 text-center text-[var(--color-text-secondary)] text-sm">{text}</div>;
}
