"use client";

import Link from "next/link";
import {
  LayoutDashboard,
  PieChart,
  Star,
  Activity,
  BarChart2,
  Newspaper,
  Crosshair,
  Users,
  Settings,
  User,
  LogOut,
  X,
} from "lucide-react";
import { useLayout } from "../context/LayoutContext";

const navItems = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Market Analysis", href: "/analysis", icon: BarChart2 },
  { name: "Portfolio", href: "/portfolio", icon: PieChart },
  { name: "Watchlist", href: "/watchlist", icon: Star },
  { name: "AI Signals", href: "/signals", icon: Activity },
  { name: "Sniper", href: "/sniper", icon: Crosshair },
  { name: "Copy Trade", href: "/copytrade", icon: Users },
  { name: "News", href: "/news", icon: Newspaper },
];

const bottomNavItems = [
  { name: "Settings", href: "/settings", icon: Settings },
  { name: "Profile", href: "/profile", icon: User },
];

export default function Sidebar() {
  const { isSidebarCollapsed, isMobileMenuOpen, setMobileMenuOpen } = useLayout();

  const sidebarWidth = isSidebarCollapsed ? "w-20" : "w-64";

  return (
    <>
      {/* Mobile Overlay */}
      {isMobileMenuOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden transition-opacity"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`fixed inset-y-0 left-0 top-16 bg-[var(--color-bg-panel)] border-r border-[var(--color-border)] flex flex-col z-50 transform transition-all duration-300 ease-in-out md:translate-x-0 ${
          isMobileMenuOpen ? "translate-x-0 w-64" : "-translate-x-full md:w-auto"
        } ${sidebarWidth}`}
      >
        <div className="flex-1 py-6 space-y-1 overflow-visible px-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.name}
                href={item.href}
                className="flex items-center gap-4 px-3 py-3 rounded-lg text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors group relative"
                onClick={() => setMobileMenuOpen(false)}
              >
                <Icon className="w-5 h-5 shrink-0 group-hover:text-[var(--color-brand)] transition-colors" />
                {!isSidebarCollapsed && (
                  <span className="font-medium text-sm whitespace-nowrap">{item.name}</span>
                )}
                {isSidebarCollapsed && (
                  <div className="absolute left-full ml-4 px-2.5 py-1.5 bg-[var(--color-bg-panel)] text-[var(--color-text-primary)] text-xs font-semibold rounded-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap border border-[var(--color-border)] shadow-xl z-[100] translate-x-[-10px] group-hover:translate-x-0">
                    {item.name}
                  </div>
                )}
              </Link>
            );
          })}
        </div>

        <div className="p-3 border-t border-[var(--color-border)] space-y-1 overflow-visible">
          {bottomNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.name}
                href={item.href}
                className="flex items-center gap-4 px-3 py-3 rounded-lg text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors group relative"
                onClick={() => setMobileMenuOpen(false)}
              >
                <Icon className="w-5 h-5 shrink-0 group-hover:text-[var(--color-brand)] transition-colors" />
                {!isSidebarCollapsed && (
                  <span className="font-medium text-sm whitespace-nowrap">{item.name}</span>
                )}
                {isSidebarCollapsed && (
                  <div className="absolute left-full ml-4 px-2.5 py-1.5 bg-[var(--color-bg-panel)] text-[var(--color-text-primary)] text-xs font-semibold rounded-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap border border-[var(--color-border)] shadow-xl z-[100] translate-x-[-10px] group-hover:translate-x-0">
                    {item.name}
                  </div>
                )}
              </Link>
            );
          })}
          <button 
            className="w-full flex items-center gap-4 px-3 py-3 rounded-lg text-[var(--color-text-secondary)] hover:text-[var(--color-danger)] hover:bg-[var(--color-bg-hover)] transition-colors group relative"
          >
            <LogOut className="w-5 h-5 shrink-0" />
            {!isSidebarCollapsed && (
              <span className="font-medium text-sm whitespace-nowrap">Logout</span>
            )}
            {isSidebarCollapsed && (
              <div className="absolute left-full ml-4 px-2.5 py-1.5 bg-[var(--color-bg-panel)] text-[var(--color-text-primary)] text-xs font-semibold rounded-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap border border-[var(--color-border)] shadow-xl z-[100] translate-x-[-10px] group-hover:translate-x-0">
                Logout
              </div>
            )}
          </button>
        </div>
      </aside>
    </>
  );
}
