'use client';

import { useCallback, useEffect, useState } from 'react';
import { Target, Loader2, CheckCircle2, AlertTriangle, ExternalLink } from 'lucide-react';
import API_URL from '@/lib/config';

const GREEN = '#2ecc71';
const RED = '#ff4466';
const MAX_POSITIONS = 5;

// Solana mint: base58, ~32-44 chars. Loose client-side check; backend is authoritative.
const MINT_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

type StatusResp = { active_count: number; max_positions: number };
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

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 8000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  // ── Validation ──────────────────────────────────────────────────────────
  const mint = tokenMint.trim();
  const amtNum = Number(amountUsd);
  const buyN = numOrNull(buyMcap);
  const tpN = numOrNull(tpMcap);
  const slN = numOrNull(slMcap);

  const mintError = mint !== '' && !MINT_RE.test(mint) ? 'Not a valid Solana mint address' : '';
  const amtError = amountUsd.trim() !== '' && !(amtNum > 0) ? 'Amount must be a positive number' : '';
  const atCap = activeCount >= MAX_POSITIONS;

  // Soft warnings (backend re-validates; these never hard-block).
  const tpWarn = tpN != null && buyN != null && tpN <= buyN ? 'TP should be above Buy' : '';
  const slWarn = slN != null && buyN != null && slN >= buyN ? 'SL should be below Buy' : '';

  const canSubmit =
    !isSubmitting && !atCap && MINT_RE.test(mint) && amtNum > 0 && !mintError && !amtError;

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
        fetchStatus();
        onSuccess?.();
      }
    } catch {
      setBanner({ kind: 'err', msg: 'Network error — try again.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
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
          <NumInput value={tpMcap} onChange={setTpMcap} placeholder="Target" />
          {tpWarn && <FieldMsg color="#f5a623">{tpWarn}</FieldMsg>}
        </Field>
        <Field label="SL MCap $" labelColor={RED}>
          <NumInput value={slMcap} onChange={setSlMcap} placeholder="Stop" />
          {slWarn && <FieldMsg color="#f5a623">{slWarn}</FieldMsg>}
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
