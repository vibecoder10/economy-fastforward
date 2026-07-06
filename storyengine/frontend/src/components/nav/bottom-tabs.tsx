"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { getPendingReview } from "@/lib/api";
import { AnimatePresence, motion } from "framer-motion";
import {
  LayoutGrid,
  List,
  CheckSquare,
  Lightbulb,
  MoreHorizontal,
  X,
  Bot,
  Brain,
  Palette,
  BarChart3,
  CalendarDays,
  ScrollText,
  Settings,
  Key,
  CreditCard,
} from "lucide-react";

const primaryTabs = [
  { href: "/", icon: LayoutGrid, label: "Home" },
  { href: "/pipeline", icon: List, label: "Videos" },
  { href: "/review", icon: CheckSquare, label: "Review", badge: true },
  { href: "/discovery", icon: Lightbulb, label: "Modeling" },
];

const moreTabs = [
  { href: "/autopilot", icon: Bot, label: "Autopilot" },
  { href: "/learnings", icon: Brain, label: "Learnings" },
  { href: "/profile", icon: Palette, label: "Visual Styles" },
  { href: "/analytics", icon: BarChart3, label: "Analytics" },
  { href: "/calendar", icon: CalendarDays, label: "Calendar" },
  { href: "/system-prompts", icon: ScrollText, label: "System Prompts" },
  { href: "/settings", icon: Settings, label: "Profile" },
  { href: "/billing", icon: CreditCard, label: "Billing" },
  { href: "/settings/keys", icon: Key, label: "API Keys" },
];

export function BottomTabs() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);

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

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href.split("?")[0]);

  const moreIsActive = moreTabs.some((t) => isActive(t.href));

  return (
    <>
      {/* More menu overlay */}
      <AnimatePresence>
        {moreOpen && (
          <>
            <motion.div
              className="fixed inset-0 z-50 md:hidden"
              style={{ background: "rgba(0,0,0,0.5)" }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMoreOpen(false)}
            />
            <motion.div
              className="fixed bottom-0 left-0 right-0 z-50 md:hidden rounded-t-2xl"
              style={{
                background: "var(--bg-deep)",
                borderTop: "1px solid var(--border)",
              }}
              initial={{ y: "100%" }}
              animate={{ y: 0 }}
              exit={{ y: "100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
            >
              <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                <span className="text-sm font-semibold font-body" style={{ color: "var(--text-primary)" }}>
                  More
                </span>
                <button onClick={() => setMoreOpen(false)} style={{ color: "var(--text-tertiary)" }}>
                  <X size={20} />
                </button>
              </div>
              <nav className="grid grid-cols-3 gap-1 p-4">
                {moreTabs.map(({ href, icon: Icon, label }) => {
                  const active = isActive(href);
                  return (
                    <Link
                      key={href}
                      href={href}
                      onClick={() => setMoreOpen(false)}
                      className="flex flex-col items-center justify-center gap-1.5 py-3 rounded-xl transition-colors"
                      style={{
                        background: active ? "var(--turquoise-dim)" : "transparent",
                        color: active ? "var(--turquoise)" : "var(--text-secondary)",
                      }}
                    >
                      <Icon size={22} strokeWidth={active ? 2.5 : 1.5} />
                      <span className="text-[11px] font-medium font-body">{label}</span>
                    </Link>
                  );
                })}
              </nav>
              {/* Safe area padding for phones with home indicator */}
              <div className="h-6" />
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Bottom tab bar */}
      <nav
        className="fixed bottom-0 left-0 right-0 z-40 md:hidden"
        style={{
          background: "var(--bg-deep)",
          borderTop: "1px solid var(--border-subtle)",
          backdropFilter: "blur(12px)",
        }}
      >
        <div className="flex items-center justify-around h-16 px-2">
          {primaryTabs.map(({ href, icon: Icon, label, badge }) => {
            const active = isActive(href);
            const showBadge = badge && pendingCount > 0;

            return (
              <Link
                key={href}
                href={href}
                className="flex flex-col items-center justify-center gap-1 py-2 px-3 rounded-lg transition-colors"
                style={{
                  color: active ? "var(--turquoise)" : "var(--text-tertiary)",
                }}
              >
                <div className="relative">
                  <Icon size={20} strokeWidth={active ? 2.5 : 1.5} />
                  {showBadge && (
                    <span
                      className="absolute -top-1 -right-2 w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold"
                      style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                    >
                      {pendingCount > 9 ? "9+" : pendingCount}
                    </span>
                  )}
                </div>
                <span className="text-[10px] font-medium font-body">{label}</span>
              </Link>
            );
          })}

          {/* More button */}
          <button
            onClick={() => setMoreOpen(true)}
            className="flex flex-col items-center justify-center gap-1 py-2 px-3 rounded-lg transition-colors"
            style={{
              color: moreIsActive ? "var(--turquoise)" : "var(--text-tertiary)",
            }}
          >
            <MoreHorizontal size={20} strokeWidth={moreIsActive ? 2.5 : 1.5} />
            <span className="text-[10px] font-medium font-body">More</span>
          </button>
        </div>
      </nav>
    </>
  );
}
