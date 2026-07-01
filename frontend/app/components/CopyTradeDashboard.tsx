'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Users, RefreshCw, Wallet, ShieldCheck, BarChart3, Target,
  Radio, Clock, Eye, Pause, Play, SlidersHorizontal, RotateCcw,
  Zap, AlertTriangle,
} from 'lucide-react';
import API_URL from '@/lib/config';

// ---------- types ----------
type CB = { enabled: boolean; max_daily_loss: number; current_drawdown: number; tripped: boolean };
type Summary = {
  id: number; name: string; mode: string; is_active: boolean;
  cash_balance: number; initial_balance: number; position_size: number;
  max_open_positions: number; open_positions: number; open_exposure: number;
  positions_value: number; total_value: number; unrealized_pnl: number;
  realized_pnl: number; total_pnl: number; total_pnl_pct: number;
  closed_trades: number; wins: number; win_rate: number; circuit_breaker: CB;
};
type Loop = {
  running: boolean; last_tick: string | null; watched_wallets: number;
  open_positions: number; webhook_id: string | null;
};
type Cfg = {
  enabled: boolean; has_helius_key: boolean; webhook_configured: boolean;
  min_wallets: number; consensus_window_min: number; position_size: number;
};
type Position = {
  id: string; mint: string; symbol: string; entry_price: number; qty: number;
  position_usd: number; last_price: number; status: string; return_pct: number;
  realized_pnl: number; exit_reason: string; unrealized_pnl: number;
  hold_minutes: number; entry_time: string; trigger_wallets: string[];
  exited_wallets: string[]; scaled_out: boolean;
};
type Signal = {
  mint: string; symbol: string; wallet_count: number; wallets: string[];
  status: string; reason: string; fired_at: string | null;
};
type Watched = { wallet: string; window: string; rank: number; score: number };
type Trade = {
  timestamp: string; mint: string; symbol: string; side: string; price: number;
  quantity: number; usd_value: number; realized_pnl: number; reason: string;
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
const ago = (iso: string | null) => {
  if (!iso) return '—';
  const s = Math.max(0, (Date.now() - new Date(iso + 'Z').getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
};

// ---------- main ----------
const TABS = ['Overview', 'Positions', 'Signals', 'Wallets', 'History'] as const;
type Tab = typeof TABS[number];

export default function CopyTradeDashboard() {
  const [sel, setSel] = useState<Summary | null>(null);
  const [loop, setLoop] = useState<Loop | null>(null);
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [tab, setTab] = useState<Tab>('Overview');
  const [positions, setPositions] = useState<Position[]>([]);
  const [history, setHistory] = useState<Position[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [watched, setWatched] = useState<Watched[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [showSettings, setShowSettings] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/copytrade/status`);
      const j = await r.json();
      setSel(j.portfolio ?? null);
      setLoop(j.loop ?? null);
      setCfg(j.config ?? null);
    } catch (e) {
      console.error('copytrade status error', e);
    }
  }, []);

  const fetchDetail = useCallback(async (which: Tab) => {
    try {
      if (which === 'Positions') {
        setPositions(await (await fetch(`${API_URL}/api/copytrade/positions?status=open`)).json());
      } else if (which === 'History') {
        setHistory(await (await fetch(`${API_URL}/api/copytrade/positions?status=closed&limit=300`)).json());
      } else if (which === 'Signals') {
        setSignals(await (await fetch(`${API_URL}/api/copytrade/signals?limit=60`)).json());
      } else if (which === 'Wallets') {
        setWatched(await (await fetch(`${API_URL}/api/copytrade/watched`)).json());
      }
    } catch (e) {
      console.error('copytrade detail error', e);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 8000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  useEffect(() => {
    fetchDetail(tab);
    const iv = setInterval(() => fetchDetail(tab), 8000);
    return () => clearInterval(iv);
  }, [tab, fetchDetail]);

  const toggleTrading = async () => {
    if (!sel) return;
    await fetch(`${API_URL}/api/copytrade/config`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !sel.is_active }),
    });
    fetchStatus();
  };

  const resetWallet = async () => {
    if (!sel) return;
    const ok = window.confirm(
      `Reset the copy-trade wallet?\n\nThis deletes all positions, trades and signals and ` +
      `restores the balance to ${usd(sel.initial_balance, 0)}. This cannot be undone.`,
    );
    if (!ok) return;
    await fetch(`${API_URL}/api/copytrade/reset`, { method: 'POST' });
    fetchStatus();
    fetchDetail(tab);
  };

  const syncWallets = async () => {
    await fetch(`${API_URL}/api/copytrade/sync`, { method: 'POST' });
    fetchStatus();
  };

  const saveConfig = async (patch: Record<string, number | boolean>) => {
    await fetch(`${API_URL}/api/copytrade/config`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    fetchStatus();
  };

  const notConnected = cfg && (!cfg.has_helius_key || !cfg.webhook_configured);

  return (
    <div className="max-w-6xl mx-auto font-sans text-[var(--color-text-primary)]">
      {/* ---------- Header ---------- */}
      <div className="flex items-start justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-[#15241c] border border-[#1f3a2a] flex items-center justify-center">
            <Users className="w-6 h-6 text-[#2ecc71]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight">Smart-Money Copy Trade</h1>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${loop?.running ? 'text-[#2ecc71] border-[#1f3a2a] bg-[#15241c]' : 'text-[var(--color-text-secondary)] border-[var(--color-border)] bg-[var(--color-bg-hover)]'}`}>
                ● {loop?.running ? 'Live' : 'Idle'}
              </span>
            </div>
            <p className="text-sm text-[var(--color-text-secondary)]">
              Copies top-gainer wallets on {cfg?.min_wallets ?? 2}+ wallet consensus (simulated)
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] px-3 py-2">
            <Eye className="w-4 h-4 text-[#2ecc71]" />
            <div className="leading-none">
              <div className="text-base font-bold tabular-nums">{loop?.watched_wallets ?? 0}</div>
              <div className="text-[9px] text-[var(--color-text-secondary)] uppercase">wallets</div>
            </div>
            <button onClick={syncWallets} title="Re-sync watched wallets + Helius webhook"
              className="text-[var(--color-text-secondary)] hover:text-[#2ecc71] transition-colors">
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* ---------- Connection warning ---------- */}
      {notConnected && (
        <div className="flex items-start gap-3 rounded-xl border border-[#3a2f1f] bg-[#241f10] px-4 py-3 mb-4">
          <AlertTriangle className="w-5 h-5 text-yellow-500 shrink-0 mt-0.5" />
          <div className="text-sm text-[var(--color-text-secondary)]">
            <span className="text-yellow-500 font-semibold">Wallet watching not connected. </span>
            {!cfg?.has_helius_key
              ? 'Set HELIUS_API_KEY (and the webhook URL + secret) in the backend environment.'
              : 'Helius webhook URL is not configured — set HELIUS_WEBHOOK_URL to your public backend address.'}
            {' '}Until then no live buy/sell events arrive and no trades fire.
          </div>
        </div>
      )}

      {/* ---------- Sub-tabs ---------- */}
      <div className="flex items-center gap-6 mb-5 border-b border-[var(--color-border)] pb-2">
        {TABS.map((t) => {
          const Icon = { Overview: BarChart3, Positions: Target, Signals: Radio, Wallets: Eye, History: Clock }[t];
          const badge = t === 'Positions' ? sel?.open_positions
            : t === 'Wallets' ? (loop?.watched_wallets ?? watched.length)
            : t === 'History' ? sel?.closed_trades : null;
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
        <div className="text-[var(--color-text-secondary)] text-sm py-20 text-center">Loading copy-trade wallet…</div>
      ) : tab === 'Overview' ? (
        <Overview sel={sel} cfg={cfg} loop={loop} onToggle={toggleTrading} onReset={resetWallet}
          onOpenSettings={() => setShowSettings((s) => !s)} showSettings={showSettings} onSave={saveConfig} />
      ) : tab === 'Positions' ? (
        <PositionsTable rows={positions} />
      ) : tab === 'Signals' ? (
        <SignalsTable rows={signals} />
      ) : tab === 'Wallets' ? (
        <WatchedTable rows={watched} />
      ) : (
        <HistoryTable rows={history} />
      )}
    </div>
  );
}

// ---------- Overview ----------
function Overview({ sel, cfg, loop, onToggle, onReset, onOpenSettings, showSettings, onSave }: {
  sel: Summary; cfg: Cfg | null; loop: Loop | null; onToggle: () => void; onReset: () => void;
  onOpenSettings: () => void; showSettings: boolean; onSave: (p: Record<string, number | boolean>) => void;
}) {
  const cb = sel.circuit_breaker;
  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-6">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-xl bg-[#15241c] border border-[#1f3a2a] flex items-center justify-center">
              <Wallet className="w-6 h-6 text-[#2ecc71]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-3xl font-bold tabular-nums">{usd(sel.cash_balance)}</span>
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded text-yellow-500 bg-[#241f10]">
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
              <div className="text-[11px] text-[var(--color-text-secondary)] uppercase">Realized</div>
              <div className="text-lg font-bold" style={{ color: pnlColor(sel.realized_pnl) }}>{signedUsd(sel.realized_pnl)}</div>
              <div className="text-[11px] text-[var(--color-text-secondary)]">{sel.closed_trades} trades · {sel.wins}W</div>
            </div>
            <div className="text-right">
              <div className="text-[11px] text-[var(--color-text-secondary)] uppercase">Total Value</div>
              <div className="text-lg font-bold" style={{ color: pnlColor(sel.total_pnl) }}>{usd(sel.total_value)}</div>
              <div className="text-[11px] text-[var(--color-text-secondary)]">{pct(sel.total_pnl_pct)}</div>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between mt-5 pt-4">
          <div className="flex items-center gap-2 text-sm">
            <span className={`w-2 h-2 rounded-full ${sel.is_active ? 'bg-[#2ecc71]' : 'bg-yellow-500'}`} />
            <span className="text-[var(--color-text-secondary)]">
              {sel.is_active
                ? `Active — waiting for ${cfg?.min_wallets ?? 2}+ wallets to buy the same token within ${cfg?.consensus_window_min ?? 10} min`
                : 'Trading Paused'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onToggle}
              className="flex items-center gap-2 text-sm font-medium px-3 py-1.5 rounded-lg border border-[var(--color-border)] hover:border-gray-500 transition-colors">
              {sel.is_active ? <><Pause className="w-4 h-4" /> Pause</> : <><Play className="w-4 h-4" /> Resume</>}
            </button>
            <button onClick={onReset}
              className="flex items-center gap-2 text-sm font-medium px-3 py-1.5 rounded-lg border border-[#3a1f1f] text-[#ff4466] hover:bg-[#241010] transition-colors">
              <RotateCcw className="w-4 h-4" /> Reset
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5 pt-5 border-t border-[var(--color-border)]">
          <Stat label="Open Positions" value={`${sel.open_positions}/${sel.max_open_positions}`} />
          <Stat label="Open Exposure" value={usd(sel.open_exposure)} />
          <Stat label="Win Rate" value={`${(sel.win_rate ?? 0).toFixed(0)}%`} />
          <Stat label="Unrealized" value={signedUsd(sel.unrealized_pnl)} valueColor={pnlColor(sel.unrealized_pnl)} />
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-4 text-xs text-[var(--color-text-secondary)]">
          <span className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-[#2ecc71]" />
            Daily loss breaker: <span className="text-[var(--color-text-primary)]">{cb.max_daily_loss}%</span>
            · drawdown {cb.current_drawdown.toFixed(1)}%
            {cb.tripped && <span className="text-[#ff4466] font-bold">· TRIPPED</span>}
          </span>
          <span className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-[#2ecc71]" />
            Webhook: <span className={cfg?.webhook_configured && loop?.webhook_id ? 'text-[#2ecc71]' : 'text-yellow-500'}>
              {loop?.webhook_id ? 'connected' : cfg?.webhook_configured ? 'configured' : 'not set'}
            </span>
            · last event tick {ago(loop?.last_tick ?? null)}
          </span>
        </div>

        <button onClick={onOpenSettings}
          className="flex items-center gap-1.5 text-xs text-[#2ecc71] mt-4 hover:underline">
          <SlidersHorizontal className="w-3.5 h-3.5" /> Wallet Settings
        </button>
        {showSettings && <SettingsPanel sel={sel} onSave={onSave} />}
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
const FIELDS: { key: string; label: string }[] = [
  { key: 'initial_balance', label: 'Initial balance ($)' },
  { key: 'position_size', label: 'Position size ($)' },
  { key: 'max_open_positions', label: 'Max open positions' },
];

function SettingsPanel({ sel, onSave }: { sel: Summary; onSave: (p: Record<string, number | boolean>) => void }) {
  const init = useMemo(() => ({
    initial_balance: String(sel.initial_balance ?? ''),
    position_size: String(sel.position_size ?? ''),
    max_open_positions: String(sel.max_open_positions ?? ''),
  }), [sel]);
  const [form, setForm] = useState<Record<string, string>>(init);

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
        Most strategy rules (consensus size, stops, exits) live in the backend env — the tuning
        comments in your .env list them. Click <span className="text-[#ff4466]">Reset</span> after
        changing Initial balance to re-fund the wallet.
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

function WalletsBadge({ wallets, exited }: { wallets: string[]; exited?: string[] }) {
  const ex = new Set(exited || []);
  return (
    <span className="inline-flex items-center gap-1" title={(wallets || []).join('\n')}>
      <Users className="w-3.5 h-3.5 text-[#2ecc71]" />
      <span className="text-sm font-semibold">{wallets?.length ?? 0}</span>
      {ex.size > 0 && <span className="text-[10px] text-[#ff4466]">({ex.size} sold)</span>}
    </span>
  );
}

function PositionsTable({ rows }: { rows: Position[] }) {
  if (!rows.length) return <Empty text="No open positions — waiting for a consensus signal" />;
  return (
    <TableShell head={<><Th>Token</Th><Th right>Entry</Th><Th right>Mark</Th><Th right>Size</Th><Th>Wallets</Th><Th right>Unreal. P&amp;L</Th><Th right>Held</Th></>}>
      {rows.map((r) => (
        <tr key={r.id} className="border-t border-[var(--color-border)]">
          <td className="py-2.5">
            <div className="font-semibold text-sm flex items-center gap-2">{r.symbol || short(r.mint)}
              {r.scaled_out && <span className="text-[9px] text-[#2ecc71] bg-[#15241c] px-1 rounded">RUNNER</span>}
            </div>
            <div className="text-[10px] text-[var(--color-text-secondary)]">{short(r.mint)}</div>
          </td>
          <td className="text-right tabular-nums text-sm">{tokenPrice(r.entry_price)}</td>
          <td className="text-right tabular-nums text-sm">{tokenPrice(r.last_price)}</td>
          <td className="text-right tabular-nums text-sm">{usd(r.position_usd, 0)}</td>
          <td><WalletsBadge wallets={r.trigger_wallets} exited={r.exited_wallets} /></td>
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
    <TableShell head={<><Th>Token</Th><Th right>Entry</Th><Th right>Exit</Th><Th right>Return</Th><Th right>P&amp;L</Th><Th>Reason</Th></>}>
      {rows.map((r, i) => (
        <tr key={`${r.id}-${i}`} className="border-t border-[var(--color-border)]">
          <td className="py-2.5"><div className="font-semibold text-sm">{r.symbol || short(r.mint)}</div><div className="text-[10px] text-[var(--color-text-secondary)]">{short(r.mint)}</div></td>
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

function SignalsTable({ rows }: { rows: Signal[] }) {
  if (!rows.length) return <Empty text="No consensus signals yet — they fire when 2+ watched wallets buy the same token" />;
  return (
    <TableShell head={<><Th>Time</Th><Th>Token</Th><Th right>Wallets</Th><Th>Result</Th><Th>Detail</Th></>}>
      {rows.map((r, i) => {
        const entered = r.status === 'entered';
        return (
          <tr key={`${r.mint}-${i}`} className="border-t border-[var(--color-border)]">
            <td className="py-2.5 text-xs text-[var(--color-text-secondary)]">{ago(r.fired_at)}</td>
            <td><div className="font-semibold text-sm">{r.symbol || short(r.mint)}</div><div className="text-[10px] text-[var(--color-text-secondary)]">{short(r.mint)}</div></td>
            <td className="text-right"><WalletsBadge wallets={r.wallets} /></td>
            <td>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${entered ? 'text-[#2ecc71] bg-[#15241c]' : 'text-[var(--color-text-secondary)] bg-[var(--color-bg-hover)]'}`}>
                {entered ? 'ENTERED' : 'SKIPPED'}
              </span>
            </td>
            <td className="text-xs text-[var(--color-text-secondary)]">{(r.reason || '').replace(/_/g, ' ')}</td>
          </tr>
        );
      })}
    </TableShell>
  );
}

function WatchedTable({ rows }: { rows: Watched[] }) {
  if (!rows.length) return <Empty text="No watched wallets yet — they sync from the top-gainer leaderboard" />;
  return (
    <TableShell head={<><Th>Wallet</Th><Th>Qualified in</Th><Th right>Rank</Th><Th right>Score</Th></>}>
      {rows.map((r) => (
        <tr key={r.wallet} className="border-t border-[var(--color-border)]">
          <td className="py-2.5">
            <a href={`https://solscan.io/account/${r.wallet}`} target="_blank" rel="noreferrer"
              className="font-mono text-sm text-[#2ecc71] hover:underline">{short(r.wallet)}</a>
          </td>
          <td className="text-xs text-[var(--color-text-secondary)]">{r.window}</td>
          <td className="text-right tabular-nums text-sm">#{r.rank}</td>
          <td className="text-right tabular-nums text-sm font-semibold">{(r.score ?? 0).toFixed(3)}</td>
        </tr>
      ))}
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
