import Link from "next/link";
import {
  LayoutDashboard,
  PieChart,
  Star,
  Activity,
  BarChart2,
  Newspaper,
  Settings,
  User,
  LogOut,
} from "lucide-react";

const navItems = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Portfolio", href: "/portfolio", icon: PieChart },
  { name: "Watchlist", href: "/watchlist", icon: Star },
  { name: "AI Signals", href: "/signals", icon: Activity },
  { name: "Market Analysis", href: "/analysis", icon: BarChart2 },
  { name: "News", href: "/news", icon: Newspaper },
];

const bottomNavItems = [
  { name: "Settings", href: "/settings", icon: Settings },
  { name: "Profile", href: "/profile", icon: User },
];

export default function Sidebar() {
  return (
    <aside className="w-64 h-screen fixed left-0 top-0 bg-[var(--color-bg-panel)] border-r border-[var(--color-border)] flex flex-col pt-16 z-10 hidden md:flex">
      <div className="flex-1 py-6 px-4 space-y-1 overflow-y-auto custom-scrollbar">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.name}
              href={item.href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-[var(--color-text-secondary)] hover:text-white hover:bg-[var(--color-bg-hover)] transition-colors group"
            >
              <Icon className="w-5 h-5 group-hover:text-[var(--color-brand)] transition-colors" />
              <span className="font-medium text-sm">{item.name}</span>
            </Link>
          );
        })}
      </div>

      <div className="p-4 border-t border-[var(--color-border)] space-y-1">
        {bottomNavItems.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.name}
              href={item.href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-[var(--color-text-secondary)] hover:text-white hover:bg-[var(--color-bg-hover)] transition-colors group"
            >
              <Icon className="w-5 h-5 group-hover:text-[var(--color-brand)] transition-colors" />
              <span className="font-medium text-sm">{item.name}</span>
            </Link>
          );
        })}
        <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-[var(--color-text-secondary)] hover:text-[var(--color-danger)] hover:bg-[var(--color-bg-hover)] transition-colors group">
          <LogOut className="w-5 h-5" />
          <span className="font-medium text-sm">Logout</span>
        </button>
      </div>
    </aside>
  );
}
