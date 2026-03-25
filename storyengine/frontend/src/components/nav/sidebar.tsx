"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutGrid,
  List,
  FolderOpen,
  BarChart3,
  Settings,
  Palette,
  Key,
  PanelLeftClose,
  PanelLeft,
  Menu,
  X,
} from "lucide-react";

const navItems = [
  { href: "/", icon: LayoutGrid, label: "Dashboard" },
  { href: "/pipeline", icon: List, label: "Queue" },
  { href: "/profile", icon: Palette, label: "Visual Profile" },
  { href: "/analytics", icon: BarChart3, label: "Analytics" },
  { href: "/settings", icon: Settings, label: "Settings" },
  { href: "/settings/keys", icon: Key, label: "API Keys" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const sidebarContent = (
    <>
      {/* Logo */}
      <div
        className="flex items-center gap-3 px-4 h-16"
        style={{ borderBottom: "1px solid var(--border-subtle)" }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold shrink-0"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          S
        </div>
        {!collapsed && (
          <span className="text-sm font-semibold font-body" style={{ color: "var(--text-primary)" }}>
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
              onClick={() => setMobileOpen(false)}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all ${
                collapsed ? "justify-center" : ""
              }`}
              style={{
                background: isActive ? "var(--turquoise-dim)" : "transparent",
                color: isActive ? "var(--turquoise)" : "var(--text-secondary)",
              }}
              title={collapsed ? label : undefined}
            >
              <Icon size={20} />
              {!collapsed && (
                <span className="text-sm font-medium font-body">{label}</span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Collapse toggle (desktop only) */}
      <div className="px-2 pb-4 hidden md:block">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg w-full transition-colors hover:bg-[var(--bg-surface)] ${
            collapsed ? "justify-center" : ""
          }`}
          style={{ color: "var(--text-tertiary)" }}
        >
          {collapsed ? <PanelLeft size={20} /> : <PanelLeftClose size={20} />}
          {!collapsed && <span className="text-sm font-body">Collapse</span>}
        </button>
      </div>
    </>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        className="fixed top-4 left-4 z-50 md:hidden p-2 rounded-lg"
        style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
        onClick={() => setMobileOpen(true)}
      >
        <Menu size={20} style={{ color: "var(--text-primary)" }} />
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-50 md:hidden"
          onClick={() => setMobileOpen(false)}
          style={{ background: "rgba(0,0,0,0.6)" }}
        >
          <aside
            className="flex flex-col w-60 h-full"
            style={{
              background: "var(--bg-deep)",
              borderRight: "1px solid var(--border)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="absolute top-4 right-4"
              onClick={() => setMobileOpen(false)}
              style={{ color: "var(--text-secondary)" }}
            >
              <X size={20} />
            </button>
            {sidebarContent}
          </aside>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside
        className={`hidden md:flex flex-col fixed left-0 top-0 bottom-0 z-40 transition-all duration-200 ${
          collapsed ? "w-16" : "w-60"
        }`}
        style={{
          background: "var(--bg-deep)",
          borderRight: "1px solid var(--border-subtle)",
        }}
      >
        {sidebarContent}
      </aside>
    </>
  );
}
