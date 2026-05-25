'use client';
import { useEffect, useState } from 'react';

import API_URL from "@/lib/config";

export default function BotSettings() {
  const [settings, setSettings] = useState({ auto_trade: false, max_amount: 20.0, stop_loss: 2.0 });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const res = await fetch(`${API_URL}/api/settings`);
        const data = await res.json();
        setSettings({
          auto_trade: data.auto_trade,
          max_amount: data.max_trade_amount,
          stop_loss: data.stop_loss_pct * 100 // Convert back to percentage for UI
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
          max_amount: settings.max_amount,
          stop_loss: settings.stop_loss / 100 // Convert back to decimal for backend
        })
      });
      alert('Settings saved successfully!');
    } catch (err) {
      console.error("Error saving settings", err);
      alert('Failed to save settings.');
    }
    setSaving(false);
  };

  return (
    <div className="bg-[#181a20] border border-[#2b3139] p-6 rounded-lg shadow-lg">
      <div className="text-gray-400 text-sm font-medium uppercase mb-6 border-b border-[#2b3139] pb-3">Bot Settings</div>
      
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-gray-200 font-medium">Auto Trading</div>
            <div className="text-gray-500 text-xs mt-1">Allow bot to execute trades</div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input 
              type="checkbox" 
              className="sr-only peer" 
              checked={settings.auto_trade}
              onChange={(e) => setSettings({...settings, auto_trade: e.target.checked})}
            />
            <div className="w-11 h-6 bg-[#2b3139] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#0ECB81]"></div>
          </label>
        </div>

        <div>
          <label className="block text-gray-400 text-xs uppercase mb-2">Max Trade Amount (USDT)</label>
          <input 
            type="number" 
            className="w-full bg-[#0b0e14] border border-[#2b3139] text-gray-200 rounded p-2 focus:outline-none focus:border-[#FCD535]"
            value={settings.max_amount}
            onChange={(e) => setSettings({...settings, max_amount: parseFloat(e.target.value) || 0})}
          />
        </div>

        <div>
          <label className="block text-gray-400 text-xs uppercase mb-2">Stop Loss (%)</label>
          <input 
            type="number" 
            className="w-full bg-[#0b0e14] border border-[#2b3139] text-gray-200 rounded p-2 focus:outline-none focus:border-[#FCD535]"
            value={settings.stop_loss}
            onChange={(e) => setSettings({...settings, stop_loss: parseFloat(e.target.value) || 0})}
          />
        </div>

        <button 
          onClick={handleSave}
          disabled={saving}
          className="w-full bg-[#FCD535] hover:bg-[#FCD535]/90 text-black font-bold py-3 rounded transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>
    </div>
  );
}
