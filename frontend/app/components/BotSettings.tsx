'use client';
import { useEffect, useState } from 'react';

import API_URL from "@/lib/config";

export default function BotSettings() {
  const [settings, setSettings] = useState({
    auto_trade: false,
    position_size: 20.0,
    stop_loss: 2.0,
    take_profit: 5.0,
  });
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const res = await fetch(`${API_URL}/api/settings`);
        const data = await res.json();
        setSettings({
          auto_trade: data.auto_trade,
          position_size: (data.position_size_pct ?? 0.2) * 100,
          stop_loss: (data.stop_loss_pct ?? 0.02) * 100,
          take_profit: (data.take_profit_pct ?? 0.05) * 100,
        });
      } catch (err) {
        console.error("Error fetching settings", err);
      }
    };
    fetchSettings();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch(`${API_URL}/api/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          auto_trade: settings.auto_trade,
          position_size_pct: settings.position_size,
          stop_loss: settings.stop_loss,
          take_profit: settings.take_profit,
        })
      });
      alert('Settings saved successfully!');
    } catch (err) {
      console.error("Error saving settings", err);
      alert('Failed to save settings.');
    }
    setSaving(false);
  };

  const handleReset = async () => {
    if (!confirm('Reset the demo wallet to 5,000 USDT and clear all trades?')) return;
    setResetting(true);
    try {
      await fetch(`${API_URL}/api/reset`, { method: 'POST' });
      alert('Wallet reset to 5,000 USDT.');
    } catch (err) {
      console.error("Error resetting wallet", err);
      alert('Failed to reset wallet.');
    }
    setResetting(false);
  };

  const numberField = (label: string, key: 'position_size' | 'stop_loss' | 'take_profit') => (
    <div>
      <label className="block text-[color:var(--color-text-secondary)] text-xs uppercase mb-2">{label}</label>
      <input
        type="number"
        className="w-full bg-[var(--color-bg-panel)] border border-[var(--color-border)] text-[color:var(--color-text-primary)] rounded p-2 focus:outline-none focus:border-[#FCD535]"
        value={settings[key]}
        onChange={(e) => setSettings({ ...settings, [key]: parseFloat(e.target.value) || 0 })}
      />
    </div>
  );

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-6 rounded-lg shadow-lg">
      <div className="text-[color:var(--color-text-secondary)] text-sm font-medium uppercase mb-6 border-b border-[var(--color-border)] pb-3">Bot Settings</div>

      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[color:var(--color-text-primary)] font-medium">Auto Trading</div>
            <div className="text-[color:var(--color-text-secondary)] text-xs mt-1">Allow bot to execute trades</div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              className="sr-only peer"
              checked={settings.auto_trade}
              onChange={(e) => setSettings({ ...settings, auto_trade: e.target.checked })}
            />
            <div className="w-11 h-6 bg-[#2b3139] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#0ECB81]"></div>
          </label>
        </div>

        {numberField('Position Size (% of equity)', 'position_size')}
        {numberField('Stop Loss (%)', 'stop_loss')}
        {numberField('Take Profit (%)', 'take_profit')}

        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full bg-[#FCD535] hover:bg-[#FCD535]/90 text-black font-bold py-3 rounded transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>

        <button
          onClick={handleReset}
          disabled={resetting}
          className="w-full bg-transparent border border-[#F6465D]/50 hover:bg-[#F6465D]/10 text-[#F6465D] font-bold py-2.5 rounded transition-colors disabled:opacity-50"
        >
          {resetting ? 'Resetting...' : 'Reset Demo Wallet ($5,000)'}
        </button>
      </div>
    </div>
  );
}
