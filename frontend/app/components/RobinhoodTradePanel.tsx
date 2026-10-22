'use client';

import { Fragment, useCallback, useEffect, useState } from 'react';
import {
  Target,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
  X,
  ChevronDown,
  Pencil,
  Check,
  ShieldCheck,
  BarChart3,
  TrendingUp,
  TrendingDown,
} from 'lucide-react';
import API_URL from '@/lib/config';

const GREEN = '#2ecc71';
const RED = '#ff4466';
const MAX_POSITIONS = 5;

// Compact Market-Cap formatting ($4.09K / $1.2M / $3.1B).
const fmtMcap = (n?: number | null): string => {
  if (n == null || n <= 0) return '—';
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(2)}K`;
  return `$${n.toFixed(0)}`;
};
const fmtPrice = (p?: number | null): string => {
  if (p == null || p <= 0) return '—';
  if (p < 0.0001) return `$${p.toExponential(2)}`;
  return `$${p.toPrecision(4)}`;
};
const formatPriceTarget = (v?: number | null): string => {
  if (v == null || v <= 0) return '';
  if (v < 0.0001) return v.toExponential(4);
  return Number(v.toPrecision(5)).toString();
};
const fmtPct = (n?: number | null) => `${(n ?? 0) >= 0 ? '+' : ''}${(n ?? 0).toFixed(2)}%`;
const pnlColor = (n?: number | null) => ((n ?? 0) >= 0 ? GREEN : RED);
const shortAddr = (a: string) => (a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '');

// Accepts 20-byte token address (40 hex chars) OR 32-byte pool ID (64 hex chars)
const EVM_INPUT_RE = /^0x[a-fA-F0-9]{40}$|^0x[a-fA-F0-9]{64}$/i;
const EXTRACT_HEX_RE = /0x[a-fA-F0-9]{40,64}/i;
const cleanAddressInput = (raw: string): string => {
  const t = raw.trim();
  const m = t.match(EXTRACT_HEX_RE);
  return m ? m[0] : t;
};

export type DeskStats = {
  total_trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
};

type StatusResp = {
  active_count: number;
  max_positions: number;
  mode: string;
  live_enabled: boolean;
  dry_run: boolean;
  wallet_configured?: boolean;
  address?: string | null;
  eth_balance?: number | null;
  eth_balance_usd?: number | null;
  ready?: boolean;
  total_trades?: number;
  wins?: number;
  losses?: number;
  win_rate?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  total_pnl?: number;
  stats?: DeskStats;
};
type Pos = {
  id: string;
  token_address: string;
  symbol: string;
  status: string;
  mode: string;
  amount_usd: number;
  entry_price: number;
  last_price: number;
  tp_price: number | null;
  sl_price: number | null;
  buy_target_price: number | null;
  return_pct: number;
  unrealized_pnl: number;
  auto_sell: boolean;
  exit_price: number | null;
  realized_pnl: number | null;
  realized_pct: number | null;
  exit_reason: string | null;
  tx_hash_buy: string | null;
  tx_hash_sell: string | null;
  created_at: string | null;
  closed_at: string | null;
  scale_in_enabled?: boolean;
  add_count?: number;
  max_adds?: number;
  initial_amount_usd?: number;
  initial_entry_price?: number;
  tier1_pct?: number;
  tier1_add_usd?: number;
  tier2_pct?: number;
  tier2_add_usd?: number;
};
type BuyResult = {
  success: boolean;
  status?: string;
  position_id?: string;
  token_address?: string;
  symbol?: string;
  entry_price?: number | null;
  tx_hash?: string | null;
  mode?: string;
  error?: string;
};

const numOrNull = (s: string): number | null => {
  const t = s.trim();
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};

export default function RobinhoodTradePanel({ onSuccess }: { onSuccess?: () => void }) {
  const [tokenAddress, setTokenAddress] = useState('');
  const [amountUsd, setAmountUsd] = useState('1');
  const [buyPrice, setBuyPrice] = useState('');
  const [tpPrice, setTpPrice] = useState('');
  const [slPrice, setSlPrice] = useState('');
  const [autoSell, setAutoSell] = useState(true);
  const [scaleInEnabled, setScaleInEnabled] = useState(false);
  const [tier1Pct, setTier1Pct] = useState('5');
  const [tier1AddUsd, setTier1AddUsd] = useState('0.5');
  const [tier2Pct, setTier2Pct] = useState('10');
  const [tier2AddUsd, setTier2AddUsd] = useState('1');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeCount, setActiveCount] = useState(0);
  const [deskMode, setDeskMode] = useState<'paper' | 'dry_run' | 'live'>('paper');
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [ethBalance, setEthBalance] = useState<number | null>(null);
  const [ethBalanceUsd, setEthBalanceUsd] = useState<number | null>(null);
  const [isWalletConfigured, setIsWalletConfigured] = useState(false);
  const [positions, setPositions] = useState<Pos[]>([]);
  const [history, setHistory] = useState<Pos[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [sellingId, setSellingId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTp, setEditTp] = useState('');
  const [editSl, setEditSl] = useState('');
  const [savingTargetsId, setSavingTargetsId] = useState<string | null>(null);
  const [tokenInfo, setTokenInfo] = useState<{
    symbol: string;
    mcap: number;
    price: number;
    liquidity_usd: number;
    address?: string;
    is_pool_resolved?: boolean;
  } | null>(null);
  const [banner, setBanner] = useState<{ kind: 'ok' | 'err'; msg: string; tx?: string | null } | null>(null);

  const [stats, setStats] = useState<DeskStats>({
    total_trades: 0,
    wins: 0,
    losses: 0,
    breakeven: 0,
    win_rate: 0,
    realized_pnl: 0,
    unrealized_pnl: 0,
    total_pnl: 0,
  });

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/robinhood/status`);
      const j: StatusResp = await r.json();
      if (typeof j.active_count === 'number') setActiveCount(j.active_count);
      if (j.mode) setDeskMode(j.mode as any);
      setWalletAddress(j.address ?? null);
      setEthBalance(j.eth_balance ?? null);
      setEthBalanceUsd(j.eth_balance_usd ?? null);
      setIsWalletConfigured(Boolean(j.wallet_configured));
      if (j.stats) {
        setStats(j.stats);
      } else if (typeof j.total_trades === 'number') {
        setStats({
          total_trades: j.total_trades ?? 0,
          wins: j.wins ?? 0,
          losses: j.losses ?? 0,
          breakeven: (j.total_trades ?? 0) - (j.wins ?? 0) - (j.losses ?? 0),
          win_rate: j.win_rate ?? 0,
          realized_pnl: j.realized_pnl ?? 0,
          unrealized_pnl: j.unrealized_pnl ?? 0,
          total_pnl: j.total_pnl ?? 0,
        });
      }
    } catch {
      /* badge is best-effort */
    }
  }, []);

  const fetchPositions = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/robinhood/positions?status=active`);
      const j = await r.json();
      if (Array.isArray(j)) setPositions(j);
    } catch {
      /* table is best-effort */
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/robinhood/positions?status=closed&limit=50`);
      const j = await r.json();
      if (Array.isArray(j)) setHistory(j);
    } catch {
      /* history is best-effort */
    }
  }, []);

  const refresh = useCallback(() => {
    fetchStatus();
    fetchPositions();
    fetchHistory();
  }, [fetchStatus, fetchPositions, fetchHistory]);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 6000);
    return () => clearInterval(iv);
  }, [refresh]);

  // Debounced token market info lookup
  const cleanAddr = cleanAddressInput(tokenAddress);
  useEffect(() => {
    if (!EVM_INPUT_RE.test(cleanAddr)) {
      setTokenInfo(null);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API_URL}/api/robinhood/token?address=${cleanAddr}`);
        const j = await r.json();
        if (!cancelled && j && !j.error && j.price > 0) {
          setTokenInfo({
            symbol: j.symbol,
            mcap: j.mcap,
            price: j.price,
            liquidity_usd: j.liquidity_usd,
            address: j.address,
            is_pool_resolved: j.is_pool_resolved,
          });
          // Auto-calculate standard 1:3 R:R (-7% SL / +21% TP) by default if not set
          setSlPrice((prev) => (prev.trim() === '' ? formatPriceTarget(j.price * 0.93) : prev));
          setTpPrice((prev) => (prev.trim() === '' ? formatPriceTarget(j.price * 1.21) : prev));
        } else if (!cancelled) {
          setTokenInfo(null);
        }
      } catch {
        if (!cancelled) setTokenInfo(null);
      }
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [cleanAddr]);

  const sellPosition = async (id: string) => {
    if (!window.confirm('Close this Robinhood position now at current market price?')) return;
    setSellingId(id);
    try {
      const r = await fetch(`${API_URL}/api/robinhood/positions/${id}/sell`, { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) {
        setBanner({ kind: 'err', msg: j.error || `Close failed (${r.status})` });
      } else {
        setBanner({
          kind: 'ok',
          msg: j.status === 'cancelled' ? 'Pending order cancelled.' : 'Position closed successfully.',
          tx: j.tx_signature,
        });
      }
    } catch {
      setBanner({ kind: 'err', msg: 'Network error — please try again.' });
    } finally {
      setSellingId(null);
      refresh();
      onSuccess?.();
    }
  };

  const startEditTargets = (pos: Pos) => {
    setEditingId(pos.id);
    setEditTp(pos.tp_price != null ? formatPriceTarget(pos.tp_price) : '');
    setEditSl(pos.sl_price != null ? formatPriceTarget(pos.sl_price) : '');
  };

  const saveTargets = async (posId: string) => {
    setSavingTargetsId(posId);
    try {
      const tpVal = numOrNull(editTp);
      const slVal = numOrNull(editSl);
      const r = await fetch(`${API_URL}/api/robinhood/positions/${posId}/targets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tp_price: tpVal,
          sl_price: slVal,
        }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) {
        setBanner({ kind: 'err', msg: j.error || `Failed to update targets (${r.status})` });
      } else {
        setBanner({ kind: 'ok', msg: 'Targets updated successfully!' });
        setEditingId(null);
        refresh();
      }
    } catch {
      setBanner({ kind: 'err', msg: 'Network error — could not update targets.' });
    } finally {
      setSavingTargetsId(null);
    }
  };

  const cleanedAddr = cleanAddressInput(tokenAddress);
  const targetTokenAddr = tokenInfo?.address || cleanedAddr;
  const amtNum = Number(amountUsd);
  const buyN = numOrNull(buyPrice);
  const tpN = numOrNull(tpPrice);
  const slN = numOrNull(slPrice);

  const applyRrPreset = (slPct: number, tpPct: number) => {
    const p = buyN != null ? buyN : tokenInfo?.price ?? null;
    if (!p || p <= 0) return;
    setSlPrice(formatPriceTarget(p * (1 - slPct / 100)));
    setTpPrice(formatPriceTarget(p * (1 + tpPct / 100)));
  };

  const entryForCalc = buyN != null ? buyN : tokenInfo?.price ?? null;
  const slNum = numOrNull(slPrice);
  const tpNum = numOrNull(tpPrice);

  let slPctChange: number | null = null;
  let tpPctChange: number | null = null;
  let riskUsd: number | null = null;
  let rewardUsd: number | null = null;
  let rrRatio: number | null = null;

  if (entryForCalc && entryForCalc > 0) {
    if (slNum && slNum > 0) {
      slPctChange = ((slNum - entryForCalc) / entryForCalc) * 100;
      if (amtNum > 0) {
        riskUsd = Math.abs((slPctChange / 100) * amtNum);
      }
    }
    if (tpNum && tpNum > 0) {
      tpPctChange = ((tpNum - entryForCalc) / entryForCalc) * 100;
      if (amtNum > 0) {
        rewardUsd = (tpPctChange / 100) * amtNum;
      }
    }
    if (riskUsd && riskUsd > 0 && rewardUsd && rewardUsd > 0) {
      rrRatio = rewardUsd / riskUsd;
    }
  }

  const addrError =
    tokenAddress.trim() !== '' && !EVM_INPUT_RE.test(cleanedAddr)
      ? 'Must be a valid 0x EVM contract address, Pool ID, or DexScreener link'
      : '';
  const amtError = amountUsd.trim() !== '' && !(amtNum > 0) ? 'Amount must be greater than 0' : '';
  const atCap = activeCount >= MAX_POSITIONS;

  const refPrice = buyN != null ? buyN : tokenInfo?.price ?? null;
  const refLabel = buyN != null ? 'Buy Target' : 'Current';
  const tpErr = tpN != null && refPrice != null && tpN <= refPrice ? `TP must be above ${refLabel} Price (${fmtPrice(refPrice)})` : '';
  const slErr = slN != null && refPrice != null && slN >= refPrice ? `SL must be below ${refLabel} Price (${fmtPrice(refPrice)})` : '';

  const canSubmit = !isSubmitting && !atCap && EVM_INPUT_RE.test(cleanedAddr) && amtNum > 0 && !addrError && !amtError && !tpErr && !slErr;

  const submit = async () => {
    if (!canSubmit) return;
    setIsSubmitting(true);
    setBanner(null);
    try {
      const r = await fetch(`${API_URL}/api/robinhood/buy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token_address: targetTokenAddr,
          amount_usd: amtNum,
          buy_price: buyN,
          tp_price: tpN,
          sl_price: slN,
          auto_sell: autoSell,
          scale_in_enabled: scaleInEnabled,
          tier1_pct: Number(tier1Pct) || 5.0,
          tier1_add_usd: Number(tier1AddUsd) || 0.5,
          tier2_pct: Number(tier2Pct) || 10.0,
          tier2_add_usd: Number(tier2AddUsd) || 1.0,
        }),
      });
      const j: BuyResult = await r.json().catch(() => ({ success: false, error: 'Bad response' }));
      if (!r.ok || !j.success) {
        setBanner({ kind: 'err', msg: j.error || `Request failed (${r.status})` });
      } else {
        const sym = j.symbol || targetTokenAddr.slice(0, 6);
        const modeLabel = j.mode === 'live' ? 'LIVE' : 'PAPER';
        const msg =
          j.status === 'pending'
            ? `[${modeLabel}] Limit order placed for ${sym} — will fill when target reached.`
            : `[${modeLabel}] Bought ${sym} @ $${(j.entry_price ?? 0).toPrecision(4)}`;
        setBanner({ kind: 'ok', msg, tx: j.tx_hash });
        setTokenAddress('');
        setAmountUsd('1');
        setBuyPrice('');
        setTpPrice('');
        setSlPrice('');
        refresh();
        onSuccess?.();
      }
    } catch {
      setBanner({ kind: 'err', msg: 'Network error — please try again.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Live dynamic stats combining DB aggregates + live ticking open positions
  const liveUnrealizedPnl = positions.reduce((acc, p) => acc + (p.unrealized_pnl || 0), 0);
  const closedHistory = history.filter((h) => h.exit_reason !== 'cancelled');
  const historyWins = closedHistory.filter((h) => (h.realized_pnl || 0) > 0).length;
  const historyLosses = closedHistory.filter((h) => (h.realized_pnl || 0) < 0).length;
  const historyRealized = closedHistory.reduce((acc, h) => acc + (h.realized_pnl || 0), 0);
  const historyTotal = closedHistory.length;
  const historyWinRate = historyTotal > 0 ? (historyWins / historyTotal) * 100 : 0;

  const totalTrades = stats.total_trades > 0 ? stats.total_trades : historyTotal;
  const wins = stats.total_trades > 0 ? stats.wins : historyWins;
  const losses = stats.total_trades > 0 ? stats.losses : historyLosses;
  const winRate = stats.total_trades > 0 ? stats.win_rate : historyWinRate;
  const realizedPnl = stats.total_trades > 0 ? stats.realized_pnl : historyRealized;
  const unrealizedPnl = positions.length > 0 ? liveUnrealizedPnl : stats.unrealized_pnl;
  const totalPnl = realizedPnl + unrealizedPnl;

  return (
    <div className="space-y-5">
      {/* Top Card: Robinhood Chain Desk Header & Controls */}
      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-6">
        <div className="flex items-start justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-[#102a1b] border border-[#1f4a2d] flex items-center justify-center">
              <span className="text-xl font-bold text-[#00c805]">R</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold tracking-tight">Robinhood Chain Desk</h2>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded border border-[#00c805]/30 bg-[#00c805]/10 text-[#00c805]">
                  EVM L2 (Chain 4663)
                </span>
              </div>
              <p className="text-xs text-[var(--color-text-secondary)]">
                Isolated manual trade desk for Robinhood meme tokens (ROBINCAT, MICRODUCK, VRAX, etc.)
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Live Wallet & ETH Balance Pill */}
            {walletAddress && (
              <div className="flex items-center gap-2 px-3 py-1 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-base)] text-xs">
                <span className={`w-2 h-2 rounded-full ${isWalletConfigured ? 'bg-[#00c805] animate-pulse' : 'bg-yellow-400'}`} />
                <span className="font-mono text-[var(--color-text-secondary)]" title={walletAddress}>
                  {shortAddr(walletAddress)}
                </span>
                <span className="text-[var(--color-border)]">|</span>
                <span className="font-mono font-bold text-[var(--color-text-primary)]">
                  {ethBalance != null ? `${ethBalance < 0.0001 ? ethBalance.toExponential(3) : ethBalance.toFixed(5)} ETH` : '0.00 ETH'}
                </span>
                {ethBalanceUsd != null && (
                  <span className="text-[11px] text-[#00c805] font-semibold font-mono">
                    (~${ethBalanceUsd.toFixed(2)})
                  </span>
                )}
              </div>
            )}

            <span
              className={`text-[11px] font-bold px-2.5 py-1 rounded-full border ${
                deskMode === 'live'
                  ? 'text-[#ff4466] border-[#3a1f1f] bg-[#241010]'
                  : 'text-[#00c805] border-[#1f3a24] bg-[#102416]'
              }`}
            >
              {deskMode === 'live' ? '🔴 LIVE (Real Money)' : '🟢 PAPER TRADING ACTIVE'}
            </span>
            <span
              className={`text-[11px] font-bold px-2.5 py-1 rounded-full border ${
                atCap
                  ? 'text-[#ff4466] border-[#3a1f1f] bg-[#241010]'
                  : 'text-[var(--color-text-secondary)] border-[var(--color-border)] bg-[var(--color-bg-hover)]'
              }`}
            >
              {activeCount}/{MAX_POSITIONS} active
            </span>
          </div>
        </div>

        {/* Performance Metric Cards: Total Trades | Win Rate | Total P&L */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6 p-4 rounded-xl bg-[var(--color-bg-base)] border border-[var(--color-border)]">
          {/* Total Trades */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-[#102416] border border-[#1f3a24] flex items-center justify-center shrink-0">
              <BarChart3 className="w-5 h-5 text-[#00c805]" />
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider font-semibold text-[var(--color-text-secondary)]">
                Total Trades
              </div>
              <div className="text-xl font-bold font-mono text-[var(--color-text-primary)]">
                {totalTrades}
              </div>
              <div className="text-[11px] text-[var(--color-text-secondary)]">
                {wins}W · {losses}L {positions.length > 0 ? `· ${positions.length} open` : ''}
              </div>
            </div>
          </div>

          {/* Win Rate */}
          <div className="flex items-center gap-3 sm:border-l sm:border-[var(--color-border)] sm:pl-4">
            <div className="w-10 h-10 rounded-xl bg-[#102416] border border-[#1f3a24] flex items-center justify-center shrink-0">
              <Target className="w-5 h-5 text-[#00c805]" />
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider font-semibold text-[var(--color-text-secondary)]">
                Win Rate
              </div>
              <div
                className="text-xl font-bold font-mono"
                style={{
                  color: totalTrades === 0 ? 'var(--color-text-secondary)' : winRate >= 50 ? GREEN : RED,
                }}
              >
                {totalTrades === 0 ? '—' : `${winRate.toFixed(1)}%`}
              </div>
              <div className="text-[11px] text-[var(--color-text-secondary)]">
                {totalTrades === 0 ? 'No completed trades' : `${wins} of ${totalTrades} won`}
              </div>
            </div>
          </div>

          {/* Total P&L */}
          <div className="flex items-center gap-3 sm:border-l sm:border-[var(--color-border)] sm:pl-4">
            <div className="w-10 h-10 rounded-xl bg-[#102416] border border-[#1f3a24] flex items-center justify-center shrink-0">
              {totalPnl >= 0 ? (
                <TrendingUp className="w-5 h-5 text-[#00c805]" />
              ) : (
                <TrendingDown className="w-5 h-5 text-[#ff4466]" />
              )}
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider font-semibold text-[var(--color-text-secondary)]">
                Total P&L
              </div>
              <div
                className="text-xl font-bold font-mono"
                style={{ color: pnlColor(totalPnl) }}
              >
                {(totalPnl >= 0 ? '+' : '')}${totalPnl.toFixed(2)}
              </div>
              <div className="text-[11px] text-[var(--color-text-secondary)] font-mono flex items-center gap-1.5 flex-wrap">
                <span>Realized: <span style={{ color: pnlColor(realizedPnl) }}>{(realizedPnl >= 0 ? '+' : '')}${realizedPnl.toFixed(2)}</span></span>
                <span>·</span>
                <span>Unrealized: <span style={{ color: pnlColor(unrealizedPnl) }}>{(unrealizedPnl >= 0 ? '+' : '')}${unrealizedPnl.toFixed(2)}</span></span>
              </div>
            </div>
          </div>
        </div>

        {/* Status Alert Banner */}
        {banner && (
          <div
            className={`mb-5 p-3.5 rounded-xl border text-xs flex items-center justify-between ${
              banner.kind === 'ok'
                ? 'bg-[#102416] border-[#1f3a24] text-[#2ecc71]'
                : 'bg-[#241010] border-[#3a1f1f] text-[#ff4466]'
            }`}
          >
            <div className="flex items-center gap-2">
              {banner.kind === 'ok' ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertTriangle className="w-4 h-4 shrink-0" />}
              <span>{banner.msg}</span>
              {banner.tx && (
                <a
                  href={`https://robinhoodchain.blockscout.com/tx/${banner.tx}`}
                  target="_blank"
                  rel="noreferrer"
                  className="underline ml-1 inline-flex items-center gap-0.5"
                >
                  Blockscout <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>
            <button onClick={() => setBanner(null)} className="p-1 hover:opacity-70">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Input Form */}
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)] mb-1.5">
              Token Contract Address (Robinhood Chain EVM)
            </label>
            <input
              type="text"
              placeholder="0x... (Token Address, Uniswap v4 Pool ID, or DexScreener link)"
              value={tokenAddress}
              onChange={(e) => setTokenAddress(e.target.value)}
              className="w-full bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-xl px-3.5 py-2.5 text-sm font-mono focus:outline-none focus:border-[#00c805]"
            />
            {addrError && <p className="text-xs text-[#ff4466] mt-1">{addrError}</p>}
          </div>

          {/* Live Token Details Preview */}
          {tokenInfo && (
            <div className="p-3 rounded-xl bg-[var(--color-bg-hover)] border border-[var(--color-border)] flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-[#00c805]">{tokenInfo.symbol}</span>
                  {tokenInfo.is_pool_resolved && (
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-[#102416] border border-[#1f3a24] text-[#00c805]">
                      Pool Auto-Resolved
                    </span>
                  )}
                </div>
                <div className="text-xs text-[var(--color-text-secondary)] mt-0.5 flex items-center gap-2 flex-wrap">
                  <span>Market Cap: {fmtMcap(tokenInfo.mcap)}</span>
                  {tokenInfo.address && (
                    <span className="font-mono text-[10px] text-[var(--color-text-secondary)]">
                      Contract: {shortAddr(tokenInfo.address)}
                    </span>
                  )}
                </div>
              </div>
              <div className="text-right">
                <span className="text-xs font-mono font-semibold">${tokenInfo.price < 0.0001 ? tokenInfo.price.toExponential(2) : tokenInfo.price.toPrecision(4)}</span>
                <span className="text-[11px] text-[var(--color-text-secondary)] block">
                  Liq: ${Math.round(tokenInfo.liquidity_usd).toLocaleString()}
                </span>
              </div>
            </div>
          )}

          {/* Targets Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <div>
              <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">
                Amount ($ USD)
              </label>
              <input
                type="number"
                step="0.5"
                min="0.1"
                value={amountUsd}
                onChange={(e) => setAmountUsd(e.target.value)}
                className="w-full bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-[#00c805]"
              />
              {amtError && <p className="text-[11px] text-[#ff4466] mt-0.5">{amtError}</p>}
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">
                Buy Price (Optional Limit)
              </label>
              <input
                type="number"
                step="any"
                placeholder="Market Now"
                value={buyPrice}
                onChange={(e) => setBuyPrice(e.target.value)}
                className="w-full bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-xl px-3 py-2 text-sm font-mono focus:outline-none focus:border-[#00c805]"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">
                Take-Profit Price ($)
              </label>
              <input
                type="number"
                step="any"
                placeholder="Optional (e.g. 0.0025)"
                value={tpPrice}
                onChange={(e) => setTpPrice(e.target.value)}
                className="w-full bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-xl px-3 py-2 text-sm font-mono focus:outline-none focus:border-[#00c805]"
              />
              {tpErr && <p className="text-[11px] text-[#ff4466] mt-0.5">{tpErr}</p>}
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--color-text-secondary)] mb-1">
                Stop-Loss Price ($)
              </label>
              <input
                type="number"
                step="any"
                placeholder="Optional (e.g. 0.0012)"
                value={slPrice}
                onChange={(e) => setSlPrice(e.target.value)}
                className="w-full bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-xl px-3 py-2 text-sm font-mono focus:outline-none focus:border-[#00c805]"
              />
              {slErr && <p className="text-[11px] text-[#ff4466] mt-0.5">{slErr}</p>}
            </div>
          </div>

          {/* Smart Risk:Reward Assistant */}
          {tokenInfo && (tokenInfo.price > 0 || (buyN != null && buyN > 0)) && (
            <div className="p-3 rounded-xl bg-[var(--color-bg-hover)] border border-[var(--color-border)] text-xs space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1.5 font-semibold text-[11px] text-[var(--color-text-primary)]">
                  <span>⚖️ Risk:Reward:</span>
                  <button
                    type="button"
                    onClick={() => applyRrPreset(5, 10)}
                    className="px-2 py-0.5 rounded bg-[var(--color-bg-input)] border border-[var(--color-border)] hover:border-[#00c805] text-[10px] text-[var(--color-text-secondary)] hover:text-white transition-colors cursor-pointer"
                  >
                    1:2 (-5% / +10%)
                  </button>
                  <button
                    type="button"
                    onClick={() => applyRrPreset(7, 21)}
                    className="px-2 py-0.5 rounded bg-[#102416] border border-[#1f3a24] text-[#00c805] text-[10px] font-bold hover:bg-[#152e1c] transition-colors cursor-pointer"
                  >
                    1:3 Standard (-7% / +21%)
                  </button>
                  <button
                    type="button"
                    onClick={() => applyRrPreset(10, 40)}
                    className="px-2 py-0.5 rounded bg-[var(--color-bg-input)] border border-[var(--color-border)] hover:border-[#00c805] text-[10px] text-[var(--color-text-secondary)] hover:text-white transition-colors cursor-pointer"
                  >
                    1:4 Runner (-10% / +40%)
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setTpPrice('');
                      setSlPrice('');
                    }}
                    className="px-2 py-0.5 rounded bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[10px] text-[var(--color-text-secondary)] hover:text-red-400 transition-colors cursor-pointer"
                  >
                    Clear
                  </button>
                </div>

                {/* Live Dollar Risk vs Potential Profit */}
                <div className="flex items-center gap-3 font-mono text-[11px] ml-auto">
                  {riskUsd != null && (
                    <span className="text-[#ff4466]">
                      Risk: -${riskUsd.toFixed(2)} ({slPctChange ? slPctChange.toFixed(1) : ''}%)
                    </span>
                  )}
                  {rewardUsd != null && (
                    <span className="text-[#2ecc71]">
                      Target: +${rewardUsd.toFixed(2)} ({tpPctChange ? `+${tpPctChange.toFixed(1)}` : ''}%)
                    </span>
                  )}
                  {rrRatio != null && (
                    <span className="px-1.5 py-0.5 rounded bg-[#102416] text-[#00c805] font-bold text-[10px]">
                      1:{rrRatio.toFixed(1)} R:R
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Smart Momentum Pyramiding Toggle */}
          <div className="pt-2 border-t border-[var(--color-border)]">
            <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-[var(--color-text-primary)]">
              <input
                type="checkbox"
                checked={scaleInEnabled}
                onChange={(e) => setScaleInEnabled(e.target.checked)}
                className="rounded accent-[#00c805] w-4 h-4 cursor-pointer"
              />
              Enable Smart Momentum Pyramiding (Scale into winners)
            </label>
            {scaleInEnabled && (
              <div className="mt-2.5 p-3 rounded-xl bg-[#102416] border border-[#1f3a24] text-xs space-y-1.5">
                <div className="flex items-center justify-between text-[11px] font-semibold text-[#00c805]">
                  <span>Stage 1: +{tier1Pct}% Gain &rarr; Add +${tier1AddUsd}</span>
                  <span className="text-[var(--color-text-secondary)] font-normal">&bull; Auto-moves SL to Break-Even (Risk-Free)</span>
                </div>
                <div className="flex items-center justify-between text-[11px] font-semibold text-[#00c805]">
                  <span>Stage 2: +{tier2Pct}% Gain &rarr; Add +${tier2AddUsd}</span>
                  <span className="text-[var(--color-text-secondary)] font-normal">&bull; Auto-moves SL to +4% Profit Lock</span>
                </div>
                <p className="text-[10px] text-[var(--color-text-secondary)] pt-1 border-t border-[#1f3a24]/50">
                  Recalculates weighted average entry price on each add. Max 2 adds enforced.
                </p>
              </div>
            )}
          </div>

          {/* Auto Sell Toggle & Submit Button */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-2">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-[var(--color-text-secondary)]">
              <input
                type="checkbox"
                checked={autoSell}
                onChange={(e) => setAutoSell(e.target.checked)}
                className="rounded accent-[#00c805] w-4 h-4 cursor-pointer"
              />
              Auto-Sell when TP or SL target is reached
            </label>

            <button
              onClick={submit}
              disabled={!canSubmit}
              className={`w-full sm:w-auto px-6 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all flex items-center justify-center gap-2 ${
                canSubmit
                  ? 'bg-[#00c805] text-black hover:bg-[#00b004] cursor-pointer'
                  : 'bg-[var(--color-border)] text-[var(--color-text-secondary)] cursor-not-allowed opacity-50'
              }`}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Placing Order...
                </>
              ) : buyN ? (
                `Place Limit Buy ($${amtNum})`
              ) : (
                `Buy ${tokenInfo?.symbol || 'Token'} ($${amtNum})`
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Active Positions Table */}
      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--color-text-primary)]">
            Open & Pending Positions ({positions.length})
          </h3>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="text-xs text-[#00c805] hover:underline cursor-pointer"
          >
            {showHistory ? 'Hide History' : `View Trade History (${history.length})`}
          </button>
        </div>

        {positions.length === 0 ? (
          <div className="py-8 text-center text-xs text-[var(--color-text-secondary)]">
            No active positions right now. Paste a Robinhood token address above to open a paper trade.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-[var(--color-text-secondary)] uppercase">
                  <th className="pb-2.5 font-semibold">Token</th>
                  <th className="pb-2.5 font-semibold">Mode</th>
                  <th className="pb-2.5 font-semibold">Status</th>
                  <th className="pb-2.5 font-semibold text-right">Size ($)</th>
                  <th className="pb-2.5 font-semibold text-right">Entry Price</th>
                  <th className="pb-2.5 font-semibold text-right">Current Price</th>
                  <th className="pb-2.5 font-semibold text-right">P&L ($ / %)</th>
                  <th className="pb-2.5 font-semibold text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {positions.map((p) => {
                  const isPending = p.status === 'pending';
                  const isEditing = editingId === p.id;
                  return (
                    <Fragment key={p.id}>
                      <tr className={`hover:bg-[var(--color-bg-hover)] ${isEditing ? 'bg-[var(--color-bg-hover)]/60' : ''}`}>
                        <td className="py-3 font-semibold">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[#00c805]">{p.symbol || 'TOKEN'}</span>
                            <a
                              href={`https://robinhoodchain.blockscout.com/token/${p.token_address}`}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[var(--color-text-secondary)] hover:text-white"
                            >
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          </div>
                          <span className="text-[10px] text-[var(--color-text-secondary)] font-mono">
                            {shortAddr(p.token_address)}
                          </span>
                          {p.scale_in_enabled && (
                            <div className="text-[9px] mt-0.5">
                              <span className={`px-1.5 py-0.2 rounded font-bold ${
                                (p.add_count ?? 0) === 2
                                  ? 'bg-[#102a1b] text-[#2ecc71] border border-[#1f4a2d]'
                                  : (p.add_count ?? 0) === 1
                                  ? 'bg-[#3a2f10] text-[#f1c40f] border border-[#4a3f1a]'
                                  : 'bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)] border border-[var(--color-border)]'
                              }`}>
                                Adds: {p.add_count ?? 0}/2 { (p.add_count ?? 0) === 1 ? '(SL Break-Even)' : (p.add_count ?? 0) === 2 ? '(SL +4% Profit)' : '' }
                              </span>
                            </div>
                          )}
                        </td>

                        <td className="py-3">
                          <span
                            className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                              p.mode === 'live'
                                ? 'text-[#ff4466] border-[#3a1f1f] bg-[#241010]'
                                : 'text-[#00c805] border-[#1f3a24] bg-[#102416]'
                            }`}
                          >
                            {p.mode.toUpperCase()}
                          </span>
                        </td>

                        <td className="py-3">
                          <span
                            className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                              isPending
                                ? 'bg-[#3a2f10] text-[#f1c40f]'
                                : 'bg-[#102a1b] text-[#2ecc71]'
                            }`}
                          >
                            {p.status.toUpperCase()}
                          </span>
                        </td>

                        <td className="py-3 text-right font-mono">${p.amount_usd.toFixed(2)}</td>
                        <td className="py-3 text-right font-mono">
                          <div>{isPending ? 'Pending' : `$${p.entry_price < 0.0001 ? p.entry_price.toExponential(2) : p.entry_price.toPrecision(4)}`}</div>
                          {(p.tp_price || p.sl_price) && (
                            <div className="text-[10px] text-[var(--color-text-secondary)] space-x-1">
                              {p.tp_price && <span className="text-[#2ecc71]">TP: ${p.tp_price < 0.0001 ? p.tp_price.toExponential(2) : p.tp_price.toPrecision(3)}</span>}
                              {p.sl_price && <span className="text-[#ff4466]">SL: ${p.sl_price < 0.0001 ? p.sl_price.toExponential(2) : p.sl_price.toPrecision(3)}</span>}
                            </div>
                          )}
                        </td>
                        <td className="py-3 text-right font-mono">
                          ${p.last_price < 0.0001 ? p.last_price.toExponential(2) : p.last_price.toPrecision(4)}
                        </td>

                        <td className="py-3 text-right font-mono" style={{ color: pnlColor(p.unrealized_pnl) }}>
                          {isPending ? '—' : `${(p.unrealized_pnl >= 0 ? '+' : '')}$${p.unrealized_pnl.toFixed(2)} (${fmtPct(p.return_pct)})`}
                        </td>

                        <td className="py-3 text-center whitespace-nowrap">
                          <div className="flex items-center justify-center gap-1.5">
                            {!isPending && (
                              <button
                                onClick={() => isEditing ? setEditingId(null) : startEditTargets(p)}
                                className={`px-2 py-1 rounded-lg text-[11px] font-semibold border transition-colors cursor-pointer flex items-center gap-1 ${
                                  isEditing
                                    ? 'bg-[#102416] border-[#1f3a24] text-[#00c805]'
                                    : 'border-[var(--color-border)] text-[var(--color-text-secondary)] hover:text-white hover:border-[#00c805]/50'
                                }`}
                              >
                                <Pencil className="w-3 h-3" />
                                {isEditing ? 'Close' : 'Edit'}
                              </button>
                            )}
                            <button
                              onClick={() => sellPosition(p.id)}
                              disabled={sellingId === p.id}
                              className="px-2.5 py-1 rounded-lg text-[11px] font-bold border border-[#ff4466]/40 text-[#ff4466] hover:bg-[#ff4466]/10 transition-colors cursor-pointer"
                            >
                              {sellingId === p.id ? 'Exiting...' : isPending ? 'Cancel' : 'Sell Market'}
                            </button>
                          </div>
                        </td>
                      </tr>

                      {/* Inline Target Editor Sub-row */}
                      {isEditing && (
                        <tr className="bg-[var(--color-bg-base)] border-t border-[var(--color-border)]">
                          <td colSpan={8} className="py-3.5 px-4">
                            <div className="flex flex-wrap items-end gap-3 text-xs">
                              <div>
                                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#2ecc71] mb-1">
                                  Take-Profit Price ($)
                                </label>
                                <input
                                  type="number"
                                  step="any"
                                  placeholder="Clear TP"
                                  value={editTp}
                                  onChange={(e) => setEditTp(e.target.value)}
                                  className="w-36 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#2ecc71]"
                                />
                              </div>

                              <div>
                                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#ff4466] mb-1">
                                  Stop-Loss Price ($)
                                </label>
                                <input
                                  type="number"
                                  step="any"
                                  placeholder="Clear SL"
                                  value={editSl}
                                  onChange={(e) => setEditSl(e.target.value)}
                                  className="w-36 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#ff4466]"
                                />
                              </div>

                              {/* Quick Presets for Target Editing */}
                              <div className="flex flex-wrap items-center gap-1.5 pb-0.5">
                                <button
                                  type="button"
                                  onClick={() => {
                                    const base = p.entry_price || p.last_price;
                                    if (base > 0) {
                                      setEditSl(formatPriceTarget(base * 0.93));
                                      setEditTp(formatPriceTarget(base * 1.21));
                                    }
                                  }}
                                  className="px-2 py-1 rounded bg-[var(--color-bg-hover)] border border-[var(--color-border)] hover:border-[#00c805] text-[10px] font-semibold text-[var(--color-text-secondary)] hover:text-white transition-colors cursor-pointer"
                                >
                                  1:3 R:R (-7% / +21%)
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (p.entry_price > 0) {
                                      setEditSl(formatPriceTarget(p.entry_price));
                                    }
                                  }}
                                  className="px-2 py-1 rounded bg-[var(--color-bg-hover)] border border-[var(--color-border)] hover:border-[#00c805] text-[10px] font-semibold text-[var(--color-text-secondary)] hover:text-white transition-colors cursor-pointer"
                                >
                                  Break-Even SL
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setEditTp('');
                                    setEditSl('');
                                  }}
                                  className="px-2 py-1 rounded bg-[var(--color-bg-hover)] border border-[var(--color-border)] hover:border-red-500/50 text-[10px] text-[var(--color-text-secondary)] hover:text-red-400 transition-colors cursor-pointer"
                                >
                                  Clear
                                </button>
                              </div>

                              {/* Action Buttons */}
                              <div className="flex items-center gap-2 pb-0.5 ml-auto">
                                <button
                                  onClick={() => saveTargets(p.id)}
                                  disabled={savingTargetsId === p.id}
                                  className="px-3.5 py-1.5 rounded-lg bg-[#00c805] text-black font-bold text-xs hover:bg-[#00b004] transition-colors flex items-center gap-1 cursor-pointer disabled:opacity-50"
                                >
                                  {savingTargetsId === p.id ? (
                                    <>
                                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                      Saving...
                                    </>
                                  ) : (
                                    <>
                                      <Check className="w-3.5 h-3.5" />
                                      Save Targets
                                    </>
                                  )}
                                </button>
                                <button
                                  onClick={() => setEditingId(null)}
                                  className="px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:text-white text-xs font-semibold transition-colors cursor-pointer"
                                >
                                  Cancel
                                </button>
                              </div>
                            </div>
                            <div className="text-[10px] text-[var(--color-text-secondary)] mt-1.5 font-mono">
                              Entry: ${p.entry_price < 0.0001 ? p.entry_price.toExponential(3) : p.entry_price.toPrecision(5)} · Last: ${p.last_price < 0.0001 ? p.last_price.toExponential(3) : p.last_price.toPrecision(5)} · Targets auto-trigger on live price monitor.
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* History Table (Collapsible) */}
      {showHistory && (
        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-6">
          <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--color-text-primary)] mb-4">
            Completed Trades History
          </h3>
          {history.length === 0 ? (
            <div className="py-6 text-center text-xs text-[var(--color-text-secondary)]">No completed trades yet.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[var(--color-border)] text-[var(--color-text-secondary)] uppercase">
                    <th className="pb-2.5 font-semibold">Token</th>
                    <th className="pb-2.5 font-semibold">Exit Reason</th>
                    <th className="pb-2.5 font-semibold text-right">Entry Price</th>
                    <th className="pb-2.5 font-semibold text-right">Exit Price</th>
                    <th className="pb-2.5 font-semibold text-right">Realized P&L</th>
                    <th className="pb-2.5 font-semibold text-center">Closed At</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]">
                  {history.map((h) => (
                    <tr key={h.id} className="hover:bg-[var(--color-bg-hover)]">
                      <td className="py-2.5 font-semibold text-[#00c805]">{h.symbol || 'TOKEN'}</td>
                      <td className="py-2.5 capitalize">{h.exit_reason || 'Manual'}</td>
                      <td className="py-2.5 text-right font-mono">${(h.entry_price || 0).toPrecision(4)}</td>
                      <td className="py-2.5 text-right font-mono">${(h.exit_price || 0).toPrecision(4)}</td>
                      <td className="py-2.5 text-right font-mono font-bold" style={{ color: pnlColor(h.realized_pnl) }}>
                        {(h.realized_pnl ?? 0) >= 0 ? '+' : ''}${(h.realized_pnl ?? 0).toFixed(2)} ({fmtPct(h.realized_pct)})
                      </td>
                      <td className="py-2.5 text-center text-[var(--color-text-secondary)]">
                        {h.closed_at ? new Date(h.closed_at).toLocaleTimeString() : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
