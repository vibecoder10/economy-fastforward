"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/AuthProvider";
import { useQuery } from "@tanstack/react-query";
import { getPendingReview, getSubscription } from "@/lib/api";
import { useHealthCheck } from "@/hooks/use-health-check";
import {
  LayoutGrid,
  List,
  BarChart3,
  Settings,
  Bot,
  Users,
  CheckSquare,
  CalendarDays,
  ScrollText,
  PanelLeftClose,
  PanelLeft,
  Menu,
  LogOut,
  Lock,
  X,
  BookOpen,
  MessageSquare,
  Lightbulb,
} from "lucide-react";
import { isPlanAtLeast, PRO_PATHS } from "@/components/auth/AuthenticatedShell";
import { WorkspaceSwitcher } from "@/components/nav/workspace-switcher";

// Chat is the primary surface; Dashboard is now secondary. Everything else lives
// under "Advanced" so the chat-first experience stays uncluttered.
const primaryNav = [
  { href: "/", icon: MessageSquare, label: "Chat" },
  { href: "/dashboard", icon: LayoutGrid, label: "Dashboard" },
];
// API Keys, Billing, and Visual Styles now live as tabs under Profile; Learnings
// lives as a tab under Autopilot (see components/nav/hub-tabs). `match` keeps the
// hub entry highlighted while you're on one of its sub-route tabs.
const advancedNav = [
  { href: "/pipeline", icon: List, label: "Videos" },
  { href: "/review", icon: CheckSquare, label: "Review" },
  { href: "/autopilot", icon: Bot, label: "Autopilot", match: ["/learnings"] },
  { href: "/discovery", icon: Users, label: "Competitor Modeling" },
  { href: "/analytics", icon: BarChart3, label: "Analytics" },
  { href: "/calendar", icon: CalendarDays, label: "Calendar" },
  { href: "/system-prompts", icon: ScrollText, label: "System Prompts" },
  { href: "/settings", icon: Settings, label: "Profile", match: ["/settings/keys", "/billing", "/profile"] },
  { href: "/docs", icon: BookOpen, label: "Getting Started" },
  { href: "/ideas", icon: Lightbulb, label: "Ideas" },
];

export function Sidebar({
  collapsed,
  onCollapsedChange,
}: {
  /** Controlled from AuthenticatedShell so <main>'s margin can react too — see hooks/use-sidebar-collapsed.ts */
  collapsed: boolean;
  onCollapsedChange: (next: boolean) => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);

  const { data: health } = useHealthCheck();

  const { data: pendingReview } = useQuery({
    queryKey: ["pending-review-count"],
    queryFn: getPendingReview,
    refetchInterval: 30000,
  });
  const { data: subscription } = useQuery({
    queryKey: ["subscription"],
    queryFn: getSubscription,
    refetchInterval: 60000,
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

  const renderNavItem = ({ href, icon: Icon, label, match }: { href: string; icon: typeof LayoutGrid; label: string; match?: string[] }) => {
    const base = href.split("?")[0];
    const isActive =
      href === "/"
        ? pathname === "/"
        : pathname.startsWith(base) || (match?.some((m) => pathname.startsWith(m)) ?? false);
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
        {!collapsed && <span className="text-sm font-medium font-body flex-1">{label}</span>}
        {!collapsed && isLocked && <Lock size={12} style={{ color: "var(--gold)" }} />}
      </Link>
    );
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

      {/* Workspace switcher (command center) — operators only; hidden otherwise */}
      <WorkspaceSwitcher collapsed={collapsed} />

      {/* Nav items */}
      <nav className="flex-1 py-4 px-2 space-y-1 overflow-y-auto">
        {primaryNav.map(renderNavItem)}

        {!collapsed && (
          <div
            className="px-3 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-tertiary)" }}
          >
            Advanced
          </div>
        )}
        {collapsed && <div className="my-2 mx-3 h-px" style={{ background: "var(--border-subtle)" }} />}

        {advancedNav.map(renderNavItem)}
      </nav>

      {/* Trial badge */}
      {!collapsed && subscription?.trial_active && (
        <div className="px-3 pb-2">
          <Link
            href="/pricing"
            className="block px-3 py-2 rounded-lg text-center text-xs font-semibold font-body transition-colors hover:brightness-110"
            style={{
              background: subscription.trial_days_remaining <= 3
                ? "rgba(212, 168, 82, 0.15)"
                : "rgba(0, 212, 170, 0.1)",
              color: subscription.trial_days_remaining <= 3
                ? "var(--gold)"
                : "var(--turquoise)",
              border: `1px solid ${subscription.trial_days_remaining <= 3 ? "rgba(212, 168, 82, 0.3)" : "rgba(0, 212, 170, 0.2)"}`,
            }}
          >
            Pro Trial — {subscription.trial_days_remaining}d left
          </Link>
        </div>
      )}
      {!collapsed && subscription && !subscription.trial_active && (subscription.plan || "free") === "free" && (
        <div className="px-3 pb-2">
          <Link
            href="/pricing"
            className="block px-3 py-2 rounded-lg text-center text-xs font-semibold font-body transition-colors hover:brightness-110"
            style={{
              background: "rgba(255, 77, 106, 0.1)",
              color: "var(--red)",
              border: "1px solid rgba(255, 77, 106, 0.2)",
            }}
          >
            Trial ended
          </Link>
        </div>
      )}

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

      {/* System health indicator */}
      <div className={`px-3 pb-2 ${collapsed ? "flex justify-center" : ""}`}>
        <div
          className={`flex items-center gap-2 ${collapsed ? "" : "px-3 py-1.5"}`}
          title={
            health
              ? `System: ${health.status}\nDB: ${health.database ? "OK" : "DOWN"}\nActive tasks: ${health.active_tasks}\nStorage: ${health.storage ? "OK" : "DOWN"}`
              : "Checking system status..."
          }
        >
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{
              background: !health
                ? "var(--text-tertiary)"
                : health.status === "healthy"
                  ? "#22c55e"
                  : health.status === "degraded"
                    ? "#eab308"
                    : "#ef4444",
            }}
          />
          {!collapsed && (
            <span className="text-[11px] font-body" style={{ color: "var(--text-tertiary)" }}>
              {!health ? "..." : health.status === "healthy" ? "All systems OK" : health.status === "degraded" ? "Degraded" : "System issues"}
            </span>
          )}
        </div>
      </div>

      {/* Unhealthy banner */}
      {health && health.status === "unhealthy" && !collapsed && (
        <div
          className="mx-3 mb-2 px-3 py-2 rounded-lg text-[11px] font-body"
          style={{
            background: "rgba(239, 68, 68, 0.1)",
            color: "#ef4444",
            border: "1px solid rgba(239, 68, 68, 0.2)",
          }}
        >
          System experiencing issues. Some features may be slow.
        </div>
      )}

      {/* Collapse toggle (desktop only) */}
      <div className="px-2 pb-4 hidden md:block">
        <button
          onClick={() => onCollapsedChange(!collapsed)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
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
