"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  LayoutList,
  FileText,
  Clapperboard,
  BarChart3,
  Bot,
  Settings,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";

const navItems = [
  { href: "/", icon: Home, label: "Home" },
  { href: "/pipeline", icon: LayoutList, label: "Pipeline" },
  { href: "/review", icon: FileText, label: "Scripts" },
  { href: "/review?tab=storyboards", icon: Clapperboard, label: "Storyboards" },
  { href: "/analytics", icon: BarChart3, label: "Analytics" },
  { href: "/autopilot", icon: Bot, label: "Autopilot" },
  { href: "/settings", icon: Settings, label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={`hidden md:flex flex-col fixed left-0 top-0 bottom-0 z-40 transition-all duration-200 ${
        collapsed ? "w-16" : "w-60"
      }`}
      style={{
        background: "var(--bg-card)",
        borderRight: "1px solid var(--border)",
      }}
    >
      {/* Logo */}
      <div
        className="flex items-center gap-3 px-4 h-16"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold shrink-0"
          style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
        >
          SE
        </div>
        {!collapsed && (
          <span
            className="text-sm font-semibold"
            style={{ color: "var(--text-primary)" }}
          >
            StoryEngine
          </span>
        )}
      </div>

      {/* Nav items */}
      <nav className="flex-1 py-4 px-2 space-y-1">
        {navItems.map(({ href, icon: Icon, label }) => {
          const isActive =
            href === "/"
              ? pathname === "/"
              : pathname.startsWith(href.split("?")[0]);

          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
                collapsed ? "justify-center" : ""
              }`}
              style={{
                background: isActive ? "rgba(212, 168, 68, 0.1)" : "transparent",
                color: isActive ? "var(--amber)" : "var(--text-secondary)",
              }}
              title={collapsed ? label : undefined}
            >
              <Icon size={20} />
              {!collapsed && (
                <span className="text-sm font-medium">{label}</span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Collapse toggle */}
      <div className="px-2 pb-4">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg w-full transition-colors hover:bg-[var(--bg-card-hover)] ${
            collapsed ? "justify-center" : ""
          }`}
          style={{ color: "var(--text-muted)" }}
        >
          {collapsed ? <PanelLeft size={20} /> : <PanelLeftClose size={20} />}
          {!collapsed && <span className="text-sm">Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
