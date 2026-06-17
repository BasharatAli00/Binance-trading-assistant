'use client';

export type View = 'dashboard' | 'portfolio';

const NAV: { id: View; label: string; icon: React.ReactNode }[] = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" />
      </svg>
    ),
  },
  {
    id: 'portfolio',
    label: 'Portfolio',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 7h18M3 7l1.5 12a2 2 0 002 1.8h7a2 2 0 002-1.8L21 7M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2" />
      </svg>
    ),
  },
];

export default function Sidebar({ active, onSelect }: { active: View; onSelect: (v: View) => void }) {
  return (
    <aside className="shrink-0 w-16 lg:w-60 bg-[#181a20] border-r border-[#2b3139] flex flex-col py-5">
      {/* Brand */}
      <div className="flex items-center gap-3 px-3 lg:px-5 pb-5 mb-2 border-b border-[#2b3139]">
        <div className="w-10 h-10 shrink-0 bg-[#FCD535] rounded-lg flex items-center justify-center">
          <svg className="w-6 h-6 text-black" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
          </svg>
        </div>
        <div className="hidden lg:block">
          <h1 className="text-base font-bold text-white tracking-wide leading-tight">Binance Trader</h1>
          <span className="text-[#0ECB81] text-[10px] font-medium">Pro</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex flex-col gap-1 px-2 lg:px-3">
        {NAV.map((item) => {
          const isActive = active === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelect(item.id)}
              title={item.label}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-md font-medium transition-colors justify-center lg:justify-start ${
                isActive
                  ? 'bg-[#2b3139] text-[#FCD535]'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-[#2b3139]/50'
              }`}
            >
              {item.icon}
              <span className="hidden lg:inline">{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Status footer */}
      <div className="mt-auto px-3 lg:px-5 pt-4 border-t border-[#2b3139]">
        <div className="text-[#0ECB81] text-xs font-medium flex items-center gap-2 justify-center lg:justify-start">
          <span className="w-2 h-2 rounded-full bg-[#0ECB81]"></span>
          <span className="hidden lg:inline">System Online</span>
        </div>
      </div>
    </aside>
  );
}
