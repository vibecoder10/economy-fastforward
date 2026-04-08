"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/AuthProvider";
import { useQuery } from "@tanstack/react-query";
import { getPendingReview } from "@/lib/api";
import {
  LayoutGrid,
  List,
  BarChart3,
  Settings,
  Palette,
  Key,
  Bot,
  Users,
  Lightbulb,
  Brain,
  CheckSquare,
  CalendarDays,
  ScrollText,
  PanelLeftClose,
  PanelLeft,
  Menu,
  LogOut,
  Lock,
  X,
} from "lucide-react";
import { isPlanAtLeast, PRO_PATHS } from "@/components/auth/AuthenticatedShell";

const navItems = [
  { href: "/", icon: LayoutGrid, label: "Dashboard" },
  { href: "/pipeline", icon: List, label: "Videos" },
  { href: "/review", icon: CheckSquare, label: "Review" },
  { href: "/autopilot", icon: Bot, label: "Autopilot" },
  { href: "/competitors", icon: Users, label: "Competitors" },
  { href: "/discovery", icon: Lightbulb, label: "Discovery" },
  { href: "/learnings", icon: Brain, label: "Learnings" },
  { href: "/profile", icon: Palette, label: "Visual Profile" },
  { href: "/analytics", icon: BarChart3, label: "Analytics" },
  { href: "/calendar", icon: CalendarDays, label: "Calendar" },
  { href: "/system-prompts", icon: ScrollText, label: "System Prompts" },
  { href: "/settings", icon: Settings, label: "Settings" },
  { href: "/settings/keys", icon: Key, label: "API Keys" },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const { data: pendingReview } = useQuery({
    queryKey: ["pending-review-count"],
    queryFn: getPendingReview,
    refetchInterval: 30000,
  });
  const pendingCount = pendingReview
    ? (pendingReview.scripts?.length ?? 0) +
      (pendingReview.storyboards?.length ?? 0) +
      (pendingReview.thumbnails?.length ?? 0) +
      (pendingReview.images?.length ?? 0)
    : 0;

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

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

          const showBadge = href === "/review" && pendingCount > 0;
          const isLocked = PRO_PATHS.some((p) => href.startsWith(p)) && !isPlanAtLeast(user?.plan, "pro");

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
                color: isActive ? "var(--turquoise)" : isLocked ? "var(--text-tertiary)" : "var(--text-secondary)",
                opacity: isLocked ? 0.6 : 1,
              }}
              title={collapsed ? label : undefined}
            >
              <div className="relative shrink-0">
                <Icon size={20} />
                {showBadge && (
                  <span
                    className="absolute -top-1 -right-1 w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold"
                    style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                  >
                    {pendingCount > 9 ? "9+" : pendingCount}
                  </span>
                )}
              </div>
              {!collapsed && (
                <span className="text-sm font-medium font-body flex-1">{label}</span>
              )}
              {!collapsed && isLocked && (
                <Lock size={12} style={{ color: "var(--gold)" }} />
              )}
            </Link>
          );
        })}
      </nav>

      {/* User + Logout */}
      <div className="px-2 pb-2">
        <button
          onClick={handleLogout}
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg w-full transition-colors hover:bg-[var(--bg-surface)] ${
            collapsed ? "justify-center" : ""
          }`}
          style={{ color: "var(--text-tertiary)" }}
        >
          <LogOut size={20} />
          {!collapsed && (
            <span className="text-sm font-body truncate">
              {user?.display_name || user?.email || "Sign out"}
            </span>
          )}
        </button>
      </div>

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
