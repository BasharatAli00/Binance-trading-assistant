"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import API_URL from "@/lib/config";

/* ── Types mirroring backend/rhc_api.py responses ─────────────────────────── */

export type Num = number | null;

export interface WatchRow {
  pool_pk: number;
  pool_id: string;
  kind: string;
  token: string;
  symbol: string | null;
  state: "candidate" | "watch" | "rejected" | "expired";
  discovery: string | null;
  score: Num;
  reject_codes: string | null;
  warn_codes: string | null;
  first_seen_ts: Num;
  last_screened_ts: Num;
  next_screen_ts: Num;
  last_activity_ts: Num;
  screens: Num;
}

export type CheckEvidence = { codes?: string[] } & Record<string, unknown>;

export interface ScreenRow {
  id: number;
  pool_pk: number;
  pool_id: string;
  token: string;
  symbol: string | null;
  ts: number;
  verdict: "pass" | "reject";
  reject_codes: string | null;
  warn_codes: string | null;
  evidence: Record<string, CheckEvidence | boolean> | null;
  duration_ms: Num;
}

export interface Condition {
  value: Num;
  op: string;
  threshold: number;
  ok: boolean;
}

export interface DecisionRow {
  id: number;
  ts: number;
  as_of: number;
  pool_pk: number;
  pool_id: string;
  token: string | null;
  symbol: string | null;
  strategy: string;
  action: "SETUP_DETECTED" | "NOT_CONFIRMED" | "EXPIRED" | "REJECTED_RISK" | "ENTER_INTENT";
  reasons: string | null;
  size_usd: Num;
  entry_ref: Num;
  stop: Num;
  targets: string | null;
  mode: string;
  broker: string | null;
  evidence: {
    features?: Record<string, Num>;
    conditions?: Record<string, Condition>;
    regime?: { label?: string | null; pct?: Num; eth_ret_1h?: Num; no_trade?: string[] };
    risk?: Record<string, unknown>;
    broker_result?: Record<string, unknown> | null;
  } | null;
}

export interface PaperPosition {
  id: number;
  pool_pk: number;
  token: string;
  strategy: string;
  regime: string | null;
  status: "open" | "closed" | "stuck";
  opened_ts: number;
  closed_ts: Num;
  entry_price: Num;
  tokens: Num;
  cost_usd: Num;
  proceeds_usd: Num;
  realized_usd: Num;
  risk_usd: Num;
  stop: Num;
  stop_pct: Num;
  targets: string | null;
  time_stop_ts: Num;
  tp1_done: boolean | null;
  exit_reason: string | null;
}

export interface PaperFill {
  id: number;
  position_id: number | null;
  pool_pk: number;
  ts: number;
  side: string;
  reason: string | null;
  usd: Num;
  gas_usd: Num;
  price_usd: Num;
  ok: boolean | null;
  detail: string | null;
}

export type CI = [Num, Num] | null;

export interface Metrics {
  trades: number;
  tokens: number;
  days: number;
  net_pnl_usd: number;
  win_rate: Num;
  win_rate_ci95: CI;
  avg_win_usd: Num;
  avg_loss_usd: Num;
  payoff_ratio: Num;
  profit_factor: Num;
  profit_factor_ci95: CI;
  expectancy_usd: Num;
  expectancy_usd_ci95: CI;
  expectancy_r: Num;
  expectancy_r_ci95: CI;
  max_drawdown_pct: Num;
  trades_per_day: Num;
  avg_hold_min: Num;
  exit_reasons: Record<string, number>;
  gate: { sufficient: boolean; missing: string[] };
  verdict: string;
}

export interface Performance {
  mode: string;
  overall: Metrics;
  by_strategy: Record<string, Metrics>;
  by_regime: Record<string, Metrics>;
}

export interface BacktestSummary {
  config_hash: string;
  window: [number, number];
  overall: Metrics;
  by_strategy: Record<string, Metrics>;
  by_regime: Record<string, Metrics>;
  walk_forward: {
    folds: { fold: number; start: number; end: number; trades: number; net_pnl_usd: number; expectancy_usd: Num; win_rate: Num }[];
    holdout_start: number;
    holdout: Metrics;
  };
  decisions: Record<string, number>;
  fill_model: string;
  pools: number;
  run_id: number;
}

export interface GateCheck {
  check: string;
  pass: boolean;
  detail: unknown;
}

export interface Gate {
  ready: boolean;
  checks: GateCheck[];
  live_trading: string;
}

export interface Risk {
  mode: string;
  live_trading: string;
  equity_usd: number;
  open_positions: number;
  max_open: number;
  exposure_usd: number;
  max_exposure_usd: number;
  realized_today_usd: number;
  unrealized_usd: number;
  daily_pnl_usd: number;
  daily_loss_limit_usd: number;
  daily_limit_hit: boolean;
  kill_switch: { db: { enabled: boolean; reason?: string; ts?: number }; env: boolean };
  no_trade: string[];
  regime: string | null;
}

export interface Reason {
  code: string;
  category: string;
  severity: "reject" | "warn" | "info";
  permanent: boolean;
  description: string;
}

export interface Candle {
  bucket: number;
  o: Num;
  h: Num;
  l: Num;
  c: Num;
  c_usd: Num;
  vol_usd: Num;
  buys: Num;
  sells: Num;
  traders: Num;
}

export interface Health {
  mode: string;
  live_trading: string;
  enabled: boolean;
  database_configured: boolean;
  service: { status: string; error: string | null; started_at: Num; lock_held: boolean };
  indexer?: Record<string, unknown>;
  registry?: { cached_pools: number; cached_tokens: number; unrecognized_factories: Record<string, number> };
  rpc?: { active_url_index: number; urls: number; per_url: Record<string, unknown>[] };
  sources?: Record<string, Record<string, unknown>>;
  cross_check?: { ts?: number; rows?: number; flagged?: { pool_pk: number; source: string; dev_pct: number }[] };
  chain_context?: Record<string, unknown>;
  storage?: { size_mb?: number; budget_mb?: number; pct?: number; level?: string; paused?: boolean };
  screener?: Record<string, unknown>;
  decisions?: Record<string, unknown>;
  paper?: Record<string, unknown>;
  regime?: { label?: string | null; pct?: Num; eth_ret_1h?: Num; no_trade?: string[]; market_vol_1h?: Num };
  counts?: Record<string, number>;
}

/* ── Fetching ─────────────────────────────────────────────────────────────── */

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function rhcGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}/api/rhc${path}`, { cache: "no-store" });
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const msg = body && typeof body === "object" && "error" in body ? String((body as { error: unknown }).error) : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

export async function rhcPost<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(`${API_URL}/api/rhc${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, String(res.statusText));
  return body as T;
}

/** Poll an RHC endpoint. Pass path = null to pause. */
export function usePoll<T>(path: string | null, intervalMs = 20000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    if (path === null) return;
    try {
      const d = await rhcGet<T>(path);
      if (!alive.current) return;
      setData(d);
      setError(null);
    } catch (e) {
      if (!alive.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    if (path === null) return;
    const first = setTimeout(load, 0);
    const iv = setInterval(load, intervalMs);
    return () => {
      alive.current = false;
      clearTimeout(first);
      clearInterval(iv);
    };
  }, [path, intervalMs, load]);

  return { data, error, loading, refresh: load };
}

/* ── Formatting ───────────────────────────────────────────────────────────── */

export function fmtUsd(v: Num | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v < 0 ? "-" : "";
  const a = Math.abs(v);
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)}k`;
  return `${sign}$${a.toFixed(digits)}`;
}

export function fmtPrice(v: Num | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (v === 0) return "$0";
  if (Math.abs(v) >= 1) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 4 })}`;
  return `$${v.toPrecision(4)}`;
}

export function fmtPct(v: Num | undefined, digits = 2, fromFraction = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const p = fromFraction ? v * 100 : v;
  return `${p > 0 ? "+" : ""}${p.toFixed(digits)}%`;
}

export function fmtNum(v: unknown, digits = 3): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return v > 0 ? "∞" : "—";
    if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
    // Keep significant digits for small values (e.g. a 0.0002 round-trip cost must not show as 0).
    if (v !== 0 && Math.abs(v) < 0.01) return String(Number(v.toPrecision(3)));
    return String(Number(v.toFixed(digits)));
  }
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.map((x) => fmtNum(x, digits)).join(", ");
  return String(v);
}

export function fmtCI(ci: CI | undefined, usd = false): string {
  if (!ci || ci[0] === null || ci[1] === null) return "—";
  return usd ? `${fmtUsd(ci[0])} … ${fmtUsd(ci[1])}` : `${fmtNum(ci[0])} … ${fmtNum(ci[1])}`;
}

export function ago(ts: Num | undefined): string {
  if (!ts) return "—";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function clock(ts: Num | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function shortAddr(a: string | null | undefined): string {
  if (!a) return "—";
  return a.length > 14 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a;
}

export function codes(s: string | null | undefined): string[] {
  return (s || "").split(",").map((x) => x.trim()).filter(Boolean);
}

export const EXPLORER = "https://robinhoodchain.blockscout.com";
