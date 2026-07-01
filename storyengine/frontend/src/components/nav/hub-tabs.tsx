"use client";

// Sub-navigation for consolidated hubs. The Profile hub groups Profile / API Keys
// / Billing / Visual Styles; the Autopilot hub groups Autopilot / Learnings. Each
// tab is its own route (fast client-side nav), so deep links keep working — the
// sidebar just shows the one hub entry instead of four separate items.

import Link from "next/link";
import { usePathname } from "next/navigation";

export type HubTab = { label: string; href: string };

export const PROFILE_TABS: HubTab[] = [
  { label: "Profile", href: "/settings" },
  { label: "API Keys", href: "/settings/keys" },
  { label: "Billing", href: "/billing" },
  { label: "Visual Styles", href: "/profile" },
];

export const AUTOPILOT_TABS: HubTab[] = [
  { label: "Autopilot", href: "/autopilot" },
  { label: "Learnings", href: "/learnings" },
];

export function HubTabs({ tabs }: { tabs: HubTab[] }) {
  const pathname = usePathname();
  return (
    <div
      className="flex flex-wrap gap-1 mb-8"
      style={{ borderBottom: "1px solid var(--border-subtle)" }}
    >
      {tabs.map((t) => {
        const active = pathname === t.href;
        return (
          <Link
            key={t.href}
            href={t.href}
            className="px-4 py-2.5 text-sm font-medium font-body transition-colors -mb-px"
            style={{
              color: active ? "var(--turquoise)" : "var(--text-secondary)",
              borderBottom: `2px solid ${active ? "var(--turquoise)" : "transparent"}`,
            }}
          >
            {t.label}
          </Link>
        );
      })}
    </div>
  );
}
