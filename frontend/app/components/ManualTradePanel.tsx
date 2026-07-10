'use client';

import { useCallback, useEffect, useState } from 'react';
import { Target, Loader2, CheckCircle2, AlertTriangle, ExternalLink, X, ChevronDown } from 'lucide-react';
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
const fmtPct = (n?: number) => `${(n ?? 0) >= 0 ? '+' : ''}${(n ?? 0).toFixed(2)}%`;
const pnlColor = (n?: number) => ((n ?? 0) >= 0 ? GREEN : RED);
const short = (a: string) => (a ? `${a.slice(0, 4)}…${a.slice(-4)}` : '');

// Solana mint: base58, ~32-44 chars. Loose client-side check; backend is authoritative.
const MINT_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

type StatusResp = { active_count: number; max_positions: number };
type Pos = {
  id: string;
  mint: string;
  symbol: string;
  status: string;
  mode: string;
  amount_usd: number;
  entry_price: number;
  last_price: number;
  entry_mcap: number;
  current_mcap: number;
  tp_mcap: number | null;
  sl_mcap: number | null;
  buy_target_mcap: number | null;
  return_pct: number;
  unrealized_pnl: number;
  auto_sell: boolean;
  // Exit details (closed rows only).
  exit_mcap: number | null;
  realized_pnl: number | null;
  realized_pct: number | null;
  exit_reason: string | null;
  tx_hash_sell: string | null;
  closed_at: string | null;
};
type BuyResult = {
  success: boolean;
  status?: string;
  position_id?: string;
  token_mint?: string;
  symbol?: string;
  entry_price?: number | null;
  tx_signature?: string | null;
  error?: string;
};

// A blank MCap field ("Now"/"Target"/"Stop") means "not set" -> send null, never 0.
const numOrNull = (s: string): number | null => {
  const t = s.trim();
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};

export default function ManualTradePanel({ onSuccess }: { onSuccess?: () => void }) {
  const [tokenMint, setTokenMint] = useState('');
  const [amountUsd, setAmountUsd] = useState('1');
  const [buyMcap, setBuyMcap] = useState('');
  const [tpMcap, setTpMcap] = useState('');
  const [slMcap, setSlMcap] = useState('');
  const [autoSell, setAutoSell] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeCount, setActiveCount] = useState(0);
  const [positions, setPositions] = useState<Pos[]>([]);
  const [history, setHistory] = useState<Pos[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [sellingId, setSellingId] = useState<string | null>(null);
  const [tokenInfo, setTokenInfo] = useState<{ symbol: string; mcap: number; price: number } | null>(null);
  const [banner, setBanner] = useState<{ kind: 'ok' | 'err'; msg: string; sig?: string | null } | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/manual/status`);
      const j: StatusResp = await r.json();
      if (typeof j.active_count === 'number') setActiveCount(j.active_count);
    } catch {
      /* badge is best-effort */
    }
  }, []);

  const fetchPositions = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/manual/positions?status=active`);
      const j = await r.json();
      if (Array.isArray(j)) setPositions(j);
    } catch {
      /* table is best-effort */
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/manual/positions?status=closed&limit=50`);
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
    const iv = setInterval(refresh, 8000);
    return () => clearInterval(iv);
  }, [refresh]);

  // Look up the token's live market cap when a valid mint is entered (debounced),
  // so the form can show it and validate that TP is above / SL is below entry.
  const mintTrimmed = tokenMint.trim();
  useEffect(() => {
    if (!MINT_RE.test(mintTrimmed)) {
      setTokenInfo(null);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API_URL}/api/manual/token?mint=${mintTrimmed}`);
        const j = await r.json();
        if (!cancelled && j && !j.error && j.price > 0) {
          setTokenInfo({ symbol: j.symbol, mcap: j.mcap, price: j.price });
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
  }, [mintTrimmed]);

  const sellPosition = async (id: string) => {
    if (!window.confirm('Close this position now at the current market price?')) return;
    setSellingId(id);
    try {
      const r = await fetch(`${API_URL}/api/manual/positions/${id}/sell`, { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) {
        setBanner({ kind: 'err', msg: j.error || `Close failed (${r.status})` });
      } else {
        setBanner({
          kind: 'ok',
          msg: j.status === 'cancelled' ? 'Pending order cancelled.' : 'Position closed.',
          sig: j.tx_signature,
        });
      }
    } catch {
      setBanner({ kind: 'err', msg: 'Network error — try again.' });
    } finally {
      setSellingId(null);
      refresh();
      onSuccess?.();
    }
  };

  // ── Validation ──────────────────────────────────────────────────────────
  const mint = tokenMint.trim();
  const amtNum = Number(amountUsd);
  const buyN = numOrNull(buyMcap);
  const tpN = numOrNull(tpMcap);
  const slN = numOrNull(slMcap);

  const mintError = mint !== '' && !MINT_RE.test(mint) ? 'Not a valid Solana mint address' : '';
  const amtError = amountUsd.trim() !== '' && !(amtNum > 0) ? 'Amount must be a positive number' : '';
  const atCap = activeCount >= MAX_POSITIONS;

  // Reference MCap for TP/SL ordering: the Buy target if set (limit), else the
  // token's current market cap. TP must be ABOVE it and SL BELOW it — otherwise
  // the position would auto-exit the instant it opens. Hard-block when we have a
  // reference (the backend also rejects these).
  const refMcap = buyN != null ? buyN : tokenInfo?.mcap ?? null;
  const refLabel = buyN != null ? 'Buy' : 'current';
  const tpErr =
    tpN != null && refMcap != null && tpN <= refMcap
      ? `TP must be above ${refLabel} MCap (${fmtMcap(refMcap)})`
      : '';
  const slErr =
    slN != null && refMcap != null && slN >= refMcap
      ? `SL must be below ${refLabel} MCap (${fmtMcap(refMcap)})`
      : '';

  const canSubmit =
    !isSubmitting && !atCap && MINT_RE.test(mint) && amtNum > 0 &&
    !mintError && !amtError && !tpErr && !slErr;

  const submit = async () => {
    if (!canSubmit) return;
    setIsSubmitting(true);
    setBanner(null);
    try {
      const r = await fetch(`${API_URL}/api/manual/buy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token_mint: mint,
          amount_usd: amtNum,
          buy_mcap: buyN,
          tp_mcap: tpN,
          sl_mcap: slN,
          auto_sell: autoSell,
        }),
      });
      const j: BuyResult = await r.json().catch(() => ({ success: false, error: 'Bad response' }));
      if (!r.ok || !j.success) {
        // Keep the form intact on failure so the user can retry.
        setBanner({ kind: 'err', msg: j.error || `Request failed (${r.status})` });
      } else {
        const sym = j.symbol || mint.slice(0, 6);
        const msg =
          j.status === 'pending'
            ? `Limit order placed for ${sym} — will fill when it reaches your Buy MCap.`
            : `Bought ${sym} @ $${(j.entry_price ?? 0).toPrecision(4)}`;
        setBanner({ kind: 'ok', msg, sig: j.tx_signature });
        // Clear the form (autoSell persists).
        setTokenMint('');
        setAmountUsd('1');
        setBuyMcap('');
        setTpMcap('');
        setSlMcap('');
        refresh();
        onSuccess?.();
      }
    } catch {
      setBanner({ kind: 'err', msg: 'Network error — try again.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-5">
    <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-[#15241c] border border-[#1f3a2a] flex items-center justify-center">
            <Target className="w-6 h-6 text-[#2ecc71]" />
          </div>
          <div>
            <h2 className="text-lg font-bold tracking-tight">New Manual Trade</h2>
            <p className="text-xs text-[var(--color-text-secondary)]">Up to {MAX_POSITIONS} concurrent positions</p>
          </div>
        </div>
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

      {/* Result banner */}
      {banner && (
        <div
          className={`flex items-start gap-2 rounded-xl px-4 py-3 mb-4 border ${
            banner.kind === 'ok'
              ? 'border-[#1f3a2a] bg-[#15241c] text-[#2ecc71]'
              : 'border-[#3a1f1f] bg-[#241010] text-[#ff4466]'
          }`}
        >
          {banner.kind === 'ok' ? (
            <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
          ) : (
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          )}
          <div className="text-sm">
            {banner.msg}
            {banner.sig && (
              <a
                href={`https://solscan.io/tx/${banner.sig}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-0.5 ml-2 underline"
              >
                view tx <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        </div>
      )}

      {/* Token address (full width) */}
      <div className="mb-4">
        <Label>Token Address</Label>
        <input
          value={tokenMint}
          onChange={(e) => setTokenMint(e.target.value)}
          placeholder="Paste the token mint address"
          spellCheck={false}
          className={`mt-1 w-full font-mono text-sm bg-[var(--color-bg-panel)] border rounded-lg px-3 py-2 text-[var(--color-text-primary)] outline-none focus:border-[#2ecc71] ${
            mintError ? 'border-[#ff4466]' : 'border-[var(--color-border)]'
          }`}
        />
        {mintError && <FieldMsg color={RED}>{mintError}</FieldMsg>}
        {!mintError && tokenInfo && (
          <FieldMsg color={GREEN}>
            {tokenInfo.symbol || 'Token'} · current MCap {fmtMcap(tokenInfo.mcap)} — TP above / SL below this
          </FieldMsg>
        )}
      </div>

      {/* Inputs row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Field label="Amount $">
          <NumInput value={amountUsd} onChange={setAmountUsd} placeholder="1" invalid={!!amtError} />
          {amtError && <FieldMsg color={RED}>{amtError}</FieldMsg>}
        </Field>
        <Field label="Buy MCap $">
          <NumInput value={buyMcap} onChange={setBuyMcap} placeholder="Now" />
        </Field>
        <Field label="TP MCap $" labelColor={GREEN}>
          <NumInput value={tpMcap} onChange={setTpMcap} placeholder="Target" invalid={!!tpErr} />
          {tpErr && <FieldMsg color={RED}>{tpErr}</FieldMsg>}
        </Field>
        <Field label="SL MCap $" labelColor={RED}>
          <NumInput value={slMcap} onChange={setSlMcap} placeholder="Stop" invalid={!!slErr} />
          {slErr && <FieldMsg color={RED}>{slErr}</FieldMsg>}
        </Field>
      </div>

      {/* Auto + Buy */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <label className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoSell}
            onChange={(e) => setAutoSell(e.target.checked)}
            className="w-4 h-4 accent-[#2ecc71]"
          />
          Auto <span className="text-[var(--color-text-secondary)]">(auto-sell on TP/SL)</span>
        </label>

        <div className="flex items-center gap-3">
          {atCap && (
            <span className="text-[11px] text-[#ff4466]">
              Close a position to open another.
            </span>
          )}
          <button
            onClick={submit}
            disabled={!canSubmit}
            title={atCap ? 'Up to 5 concurrent positions — close one to open another.' : undefined}
            className="flex items-center gap-2 text-sm font-semibold px-5 py-2 rounded-lg bg-[#15241c] text-[#2ecc71] border border-[#1f3a2a] hover:bg-[#1a2e22] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Target className="w-4 h-4" />}
            {isSubmitting ? 'Placing…' : 'Buy Now'}
          </button>
        </div>
      </div>

      <p className="mt-4 text-[11px] text-[var(--color-text-secondary)]">
        Targets are Market Cap ($), converted to price assuming a fixed 1B token supply
        (Pump.fun-style). Execution respects the live master + dry-run switches — leave Buy MCap
        blank to buy at the current market cap now.
      </p>
    </div>

    <PositionsTable rows={positions} sellingId={sellingId} onSell={sellPosition} />

    {history.length > 0 && (
      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-5 overflow-x-auto">
        <button
          onClick={() => setShowHistory((s) => !s)}
          className="flex items-center gap-2 text-sm font-semibold mb-1"
        >
          <ChevronDown className={`w-4 h-4 transition-transform ${showHistory ? '' : '-rotate-90'}`} />
          Closed Manual Trades
          <span className="text-[10px] font-normal px-1.5 py-0.5 rounded-full bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]">
            {history.length}
          </span>
        </button>
        {showHistory && <HistoryTable rows={history} />}
      </div>
    )}
    </div>
  );
}

// ---------- Closed manual trades ----------
function HistoryTable({ rows }: { rows: Pos[] }) {
  return (
    <table className="w-full min-w-[720px] mt-3">
      <thead>
        <tr>
          <Th>Token</Th>
          <Th right>Entry MCap</Th>
          <Th right>Exit MCap</Th>
          <Th right>Return</Th>
          <Th right>Realized P&amp;L</Th>
          <Th>Reason</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const cancelled = r.exit_reason === 'cancelled';
          return (
            <tr key={r.id} className="border-t border-[var(--color-border)]">
              <td className="py-2.5">
                <div className="font-semibold text-sm">{r.symbol || short(r.mint)}</div>
                <div className="text-[10px] text-[var(--color-text-secondary)]">
                  ${(r.amount_usd ?? 0).toFixed(2)} · {short(r.mint)}
                </div>
              </td>
              <td className="text-right tabular-nums text-sm">{cancelled ? '—' : fmtMcap(r.entry_mcap)}</td>
              <td className="text-right tabular-nums text-sm">{cancelled ? '—' : fmtMcap(r.exit_mcap)}</td>
              <td
                className="text-right tabular-nums text-sm font-semibold"
                style={{ color: cancelled ? 'var(--color-text-secondary)' : pnlColor(r.realized_pct ?? 0) }}
              >
                {cancelled ? '—' : fmtPct(r.realized_pct ?? 0)}
              </td>
              <td
                className="text-right tabular-nums text-sm font-semibold"
                style={{ color: cancelled ? 'var(--color-text-secondary)' : pnlColor(r.realized_pnl ?? 0) }}
              >
                {cancelled ? '—' : `${(r.realized_pnl ?? 0) >= 0 ? '+' : '-'}$${Math.abs(r.realized_pnl ?? 0).toFixed(2)}`}
              </td>
              <td className="text-xs text-[var(--color-text-secondary)]">
                {(r.exit_reason || '').replace(/_/g, ' ')}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ---------- Open manual positions ----------
function PositionsTable({
  rows,
  sellingId,
  onSell,
}: {
  rows: Pos[];
  sellingId: string | null;
  onSell: (id: string) => void;
}) {
  if (!rows.length) return null;
  return (
    <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-5 overflow-x-auto">
      <div className="text-sm font-semibold mb-3">Open Manual Positions</div>
      <table className="w-full min-w-[720px]">
        <thead>
          <tr>
            <Th>Token</Th>
            <Th right>Entry MCap</Th>
            <Th right>Current MCap</Th>
            <Th right>P&amp;L</Th>
            <Th right>TP MCap</Th>
            <Th right>SL MCap</Th>
            <Th right></Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const pending = r.status === 'pending';
            return (
              <tr key={r.id} className="border-t border-[var(--color-border)]">
                <td className="py-2.5">
                  <div className="font-semibold text-sm flex items-center gap-2">
                    {r.symbol || short(r.mint)}
                    {pending ? (
                      <span className="text-[9px] font-bold text-yellow-500 bg-[#241f10] border border-[#3a2f1f] px-1.5 py-0.5 rounded">
                        PENDING
                      </span>
                    ) : r.mode === 'dry_run' ? (
                      <span className="text-[9px] font-bold text-[#2ecc71] bg-[#15241c] px-1.5 py-0.5 rounded">
                        DRY
                      </span>
                    ) : (
                      <span className="text-[9px] font-bold text-[#ff4466] bg-[#241010] border border-[#3a1f1f] px-1.5 py-0.5 rounded">
                        REAL
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] text-[var(--color-text-secondary)]">
                    ${(r.amount_usd ?? 0).toFixed(2)} · {short(r.mint)}
                  </div>
                </td>
                <td className="text-right tabular-nums text-sm">
                  {pending ? '—' : fmtMcap(r.entry_mcap)}
                </td>
                <td className="text-right tabular-nums text-sm">
                  {pending ? (
                    <span className="text-[var(--color-text-secondary)]">
                      target {fmtMcap(r.buy_target_mcap)}
                    </span>
                  ) : (
                    fmtMcap(r.current_mcap)
                  )}
                </td>
                <td
                  className="text-right tabular-nums text-sm font-semibold"
                  style={{ color: pending ? 'var(--color-text-secondary)' : pnlColor(r.return_pct) }}
                >
                  {pending ? '—' : fmtPct(r.return_pct)}
                  {!pending && (
                    <div className="text-[10px] font-normal" style={{ color: pnlColor(r.unrealized_pnl) }}>
                      {(r.unrealized_pnl ?? 0) >= 0 ? '+' : '-'}${Math.abs(r.unrealized_pnl ?? 0).toFixed(2)}
                    </div>
                  )}
                </td>
                <td className="text-right tabular-nums text-sm" style={{ color: r.tp_mcap ? GREEN : undefined }}>
                  {fmtMcap(r.tp_mcap)}
                </td>
                <td className="text-right tabular-nums text-sm" style={{ color: r.sl_mcap ? RED : undefined }}>
                  {fmtMcap(r.sl_mcap)}
                </td>
                <td className="text-right">
                  <button
                    onClick={() => onSell(r.id)}
                    disabled={sellingId === r.id}
                    className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-lg border border-[#3a1f1f] text-[#ff4466] hover:bg-[#241010] disabled:opacity-40 transition-colors"
                  >
                    {sellingId === r.id ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <X className="w-3 h-3" />
                    )}
                    {pending ? 'Cancel' : 'Sell'}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children, right }: { children?: React.ReactNode; right?: boolean }) {
  return (
    <th className={`text-[11px] uppercase text-[var(--color-text-secondary)] font-medium pb-2 ${right ? 'text-right' : 'text-left'}`}>
      {children}
    </th>
  );
}

function Label({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <div
      className="text-[11px] uppercase tracking-wide font-medium"
      style={{ color: color || 'var(--color-text-secondary)' }}
    >
      {children}
    </div>
  );
}

function Field({
  label,
  labelColor,
  children,
}: {
  label: string;
  labelColor?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <Label color={labelColor}>{label}</Label>
      {children}
    </div>
  );
}

function NumInput({
  value,
  onChange,
  placeholder,
  invalid,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  invalid?: boolean;
}) {
  return (
    <input
      inputMode="decimal"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={`mt-1 w-full text-sm tabular-nums bg-[var(--color-bg-panel)] border rounded-lg px-3 py-2 text-[var(--color-text-primary)] outline-none focus:border-[#2ecc71] ${
        invalid ? 'border-[#ff4466]' : 'border-[var(--color-border)]'
      }`}
    />
  );
}

function FieldMsg({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <div className="text-[10px] mt-1" style={{ color }}>
      {children}
    </div>
  );
}
