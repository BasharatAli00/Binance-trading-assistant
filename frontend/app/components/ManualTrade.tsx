'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

interface ManualOrder {
  id: string;
  symbol: string;
  status: string;              // 'pending' | 'open'
  amount_usdt: number;
  limit_price: number | null;
  quantity: number;
  avg_entry_price: number;
  take_profit: number | null;
  stop_price: number | null;
  created_at: string;
}

const MAX_POSITIONS = 5;

const fmtUsd = (n: number | null | undefined) =>
  n == null ? '—' : `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function ManualTrade({ symbol = 'BTCUSDT' }: { symbol?: string }) {
  const [orders, setOrders] = useState<ManualOrder[]>([]);
  const [btcPrice, setBtcPrice] = useState<number>(0);

  // Form state
  const [amount, setAmount] = useState<string>('100');   // default $100
  const [buyPrice, setBuyPrice] = useState<string>('');   // empty => market
  const [takeProfit, setTakeProfit] = useState<string>('');
  const [stopPrice, setStopPrice] = useState<string>('');
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string>('');
  const [busyId, setBusyId] = useState<string>('');

  const fetchOrders = async () => {
    try {
      const [oRes, pRes] = await Promise.all([
        fetch(`${API_URL}/api/manual-orders?symbol=${symbol}`),
        fetch(`${API_URL}/api/manual-portfolio`),
      ]);
      const oData = await oRes.json();
      const pData = await pRes.json();
      if (Array.isArray(oData)) setOrders(oData);
      if (!pData.error) setBtcPrice(pData.btc_price || 0);
    } catch (err) {
      console.error("Error fetching manual orders", err);
    }
  };

  useEffect(() => {
    fetchOrders();
    const interval = setInterval(fetchOrders, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  const activeCount = orders.length;
  const atMax = activeCount >= MAX_POSITIONS;

  const placeOrder = async () => {
    setNotice('');
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) { setNotice('Enter an amount greater than 0'); return; }
    setSubmitting(true);
    try {
      const res = await fetch(`${API_URL}/api/manual-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          amount_usdt: amt,
          limit_price: buyPrice ? parseFloat(buyPrice) : null,
          take_profit: takeProfit ? parseFloat(takeProfit) : null,
          stop_price: stopPrice ? parseFloat(stopPrice) : null,
        }),
      });
      const d = await res.json();
      if (d.error) {
        setNotice(d.error);
      } else {
        setNotice(d.status === 'filled'
          ? `Bought at ${fmtUsd(d.avg_entry_price)}`
          : `Limit order placed at ${fmtUsd(d.limit_price)} — waiting to fill`);
        setBuyPrice(''); setTakeProfit(''); setStopPrice('');
        fetchOrders();
      }
    } catch (err) {
      console.error("Error placing manual order", err);
      setNotice('Failed to place order');
    } finally {
      setSubmitting(false);
    }
  };

  const cancelOrder = async (id: string) => {
    setBusyId(id);
    try {
      await fetch(`${API_URL}/api/manual-cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, symbol }),
      });
      fetchOrders();
    } catch (err) {
      console.error("Error cancelling order", err);
    } finally {
      setBusyId('');
    }
  };

  const closePosition = async (id: string) => {
    setBusyId(id);
    try {
      await fetch(`${API_URL}/api/manual-close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, symbol }),
      });
      fetchOrders();
    } catch (err) {
      console.error("Error closing position", err);
    } finally {
      setBusyId('');
    }
  };

  const inputCls =
    "w-full bg-[var(--color-bg-base)] border border-[var(--color-border)] rounded-md px-3 py-2 " +
    "text-sm text-[color:var(--color-text-primary)] placeholder:text-[color:var(--color-text-secondary)] " +
    "focus:outline-none focus:border-[#f0b90b] transition-colors";

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg shadow-lg overflow-hidden">
      {/* Header */}
      <div className="flex justify-between items-center p-6 pb-4 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full flex items-center justify-center"
               style={{ backgroundColor: '#0ea5e922', color: '#0ea5e9' }}>◎</div>
          <div>
            <div className="text-[color:var(--color-text-primary)] font-bold">New Manual Trade</div>
            <div className="text-[11px] text-[color:var(--color-text-secondary)]">Up to {MAX_POSITIONS} concurrent positions</div>
          </div>
        </div>
        <div className="text-xs font-bold px-3 py-1 rounded-full bg-[var(--color-bg-base)] border border-[var(--color-border)] text-[color:var(--color-text-secondary)]">
          {activeCount}/{MAX_POSITIONS} active
        </div>
      </div>

      {/* Form row */}
      <div className="p-6 pt-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 items-end">
          <div>
            <label className="block text-[11px] text-[color:var(--color-text-secondary)] mb-1">Amount $</label>
            <input type="number" min="0" value={amount} onChange={e => setAmount(e.target.value)}
                   placeholder="100" className={inputCls} />
          </div>
          <div>
            <label className="block text-[11px] text-[color:var(--color-text-secondary)] mb-1">Buy Price $</label>
            <input type="number" min="0" value={buyPrice} onChange={e => setBuyPrice(e.target.value)}
                   placeholder="Now" className={inputCls} />
          </div>
          <div>
            <label className="block text-[11px] text-[#0ECB81] mb-1">TP Price $</label>
            <input type="number" min="0" value={takeProfit} onChange={e => setTakeProfit(e.target.value)}
                   placeholder="Target" className={inputCls} />
          </div>
          <div>
            <label className="block text-[11px] text-[#F6465D] mb-1">SL Price $</label>
            <input type="number" min="0" value={stopPrice} onChange={e => setStopPrice(e.target.value)}
                   placeholder="Stop" className={inputCls} />
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 mt-4">
          <div className="text-[11px] text-[color:var(--color-text-secondary)]">
            {buyPrice
              ? `Limit buy — fills when BTC touches ${fmtUsd(parseFloat(buyPrice))}`
              : `Market buy at current price (${fmtUsd(btcPrice)})`}
            {notice && <span className="ml-2 text-[color:var(--color-text-primary)]">· {notice}</span>}
          </div>
          <button
            onClick={placeOrder}
            disabled={submitting || atMax}
            className="px-6 py-2 rounded-md font-bold text-sm bg-[#0ea5e9] text-white hover:bg-[#0284c7] disabled:opacity-40 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
          >
            {atMax ? 'Max positions' : submitting ? 'Placing…' : 'Buy Now'}
          </button>
        </div>
      </div>

      {/* Active positions / pending orders */}
      <div className="px-6 pb-6">
        <div className="text-[color:var(--color-text-secondary)] text-[11px] uppercase font-medium mb-2">
          Active Positions
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-[color:var(--color-text-secondary)] uppercase text-[10px] border-b border-[var(--color-border)]">
              <tr>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium">Amount</th>
                <th className="pb-2 font-medium">Entry</th>
                <th className="pb-2 font-medium text-[#0ECB81]">TP</th>
                <th className="pb-2 font-medium text-[#F6465D]">SL</th>
                <th className="pb-2 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]/50">
              {orders.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-[color:var(--color-text-secondary)]">
                    No active positions — place a trade above
                  </td>
                </tr>
              ) : (
                orders.map((o) => {
                  const pending = o.status === 'pending';
                  return (
                    <tr key={o.id} className="hover:bg-[var(--color-bg-hover)]/20 transition-colors">
                      <td className="py-3">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                          pending ? 'text-[#f0b90b] bg-[#f0b90b22]' : 'text-[#0ECB81] bg-[#0ECB8122]'
                        }`}>
                          {pending ? 'PENDING' : 'OPEN'}
                        </span>
                      </td>
                      <td className="py-3 text-[color:var(--color-text-primary)]">{fmtUsd(o.amount_usdt)}</td>
                      <td className="py-3 text-[color:var(--color-text-primary)]">
                        {pending ? `limit ${fmtUsd(o.limit_price)}` : fmtUsd(o.avg_entry_price)}
                      </td>
                      <td className="py-3 text-[#0ECB81]">{fmtUsd(o.take_profit)}</td>
                      <td className="py-3 text-[#F6465D]">{fmtUsd(o.stop_price)}</td>
                      <td className="py-3 text-right">
                        <button
                          onClick={() => pending ? cancelOrder(o.id) : closePosition(o.id)}
                          disabled={busyId === o.id}
                          className="px-3 py-1 rounded text-xs font-bold border border-[var(--color-border)] text-[color:var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] disabled:opacity-40 transition-colors"
                        >
                          {busyId === o.id ? '…' : pending ? 'Cancel' : 'Close'}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
