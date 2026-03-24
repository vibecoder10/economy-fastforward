# Module 1: Design System + Dashboard + Pipeline View

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the existing StoryEngine frontend to match the dark editorial design spec, rebuild navigation for 6 tabs, redesign the dashboard as an action-first "what needs attention" screen, and upgrade the pipeline view with progress dots and better cards.

**Architecture:** The frontend already has working pages, components, API client, and React Query integration. We're restyling — not rebuilding. Update CSS variables, rework nav components, then upgrade the dashboard and pipeline pages to match the UI/UX spec. No new dependencies needed.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS 4.2, Framer Motion 12.38, Lucide React, Recharts, Geist fonts

**Design Spec:** `docs/superpowers/specs/2026-03-23-storyengine-ui-ux-addendum.md`

**Existing codebase:** `storyengine/frontend/` — 7 pages, 23 components, fully functional

---

## File Map

### Modified Files
| File | Changes |
|------|---------|
| `src/app/globals.css` | Replace CSS variables with new design tokens |
| `src/app/layout.tsx` | Update layout for new nav structure |
| `src/components/nav/sidebar.tsx` | Rebuild: 7 tabs, collapsible, new colors |
| `src/components/nav/bottom-tabs.tsx` | Rebuild: 6 tabs, amber accent, notification badge |
| `src/app/page.tsx` | Redesign: action items first, activity feed, quick stats |
| `src/app/pipeline/page.tsx` | Redesign: progress dot cards, filters, search |
| `src/components/video-card.tsx` | Restyle: match spec card layout |
| `src/components/progress-dots.tsx` | Update: green/amber/red/gray dot colors |
| `src/components/ui/card.tsx` | Restyle: subtle borders, new bg colors |
| `src/components/stat-card.tsx` | Restyle: match spec quick stats |
| `src/lib/constants.ts` | Update stage colors to match new palette |

### New Files
| File | Purpose |
|------|---------|
| `src/components/action-card.tsx` | Dashboard "needs attention" cards with [Review ->] |

### Notes
- `src/components/stat-card.tsx` — kept as-is for other pages; dashboard uses inline `QuickStat`
- `src/components/dashboard/autopilot-card.tsx` — kept for potential future use on dashboard
- Activity feed items are simple enough to inline (3 lines each), no separate component needed
- Notification bell, pull-to-refresh, context menus, desktop table view — deferred to Module 2

---

## Task 1: Update Design Tokens (CSS Variables)

**Files:**
- Modify: `storyengine/frontend/src/app/globals.css`

- [ ] **Step 1: Replace CSS variables with new design tokens**

Replace the existing `:root` / `body` variable block with:

```css
:root {
  /* Base */
  --bg-primary: #0A0A0B;
  --bg-card: #141416;
  --bg-card-hover: #1A1A1E;
  --border: #2A2A2E;

  /* Text */
  --text-primary: #E8E8EA;
  --text-secondary: #8A8A8E;
  --text-muted: #5A5A5E;

  /* Accent */
  --amber: #D4A844;
  --amber-hover: #E0B850;
  --teal: #1A8A7A;
  --red: #C44545;
  --green: #3A9A5A;

  /* Status dots */
  --dot-complete: var(--green);
  --dot-current: var(--amber);
  --dot-pending: var(--text-muted);
  --dot-failed: var(--red);

  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --space-2xl: 48px;

  /* Cards */
  --card-radius: 12px;
  --card-padding: var(--space-lg);

  /* Legacy aliases (for components not yet updated) */
  --background: #0A0A0B;
  --surface: #141416;
  --surface-elevated: #1A1A1E;
  --text-primary-legacy: #E8E8EA;
  --text-secondary-legacy: #8A8A8E;
  --accent: #D4A844;
  --error: #C44545;
  --warning: #D4A844;
  --success: #3A9A5A;
}
```

Keep the existing `@keyframes pulse-dot`, scrollbar styles, and font declarations. Update `body` background:

```css
body {
  background: var(--bg-primary);
  color: var(--text-primary);
}
```

- [ ] **Step 2: Verify the app still renders**

```bash
cd storyengine/frontend && npm run dev
```

Open http://localhost:3001 — colors should shift from teal accent to amber. Existing components may look off (expected — we'll fix them in subsequent tasks).

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/app/globals.css
git commit -m "style(storyengine): Apply dark editorial design tokens

Charcoal #0A0A0B base, amber #D4A844 primary, teal #1A8A7A secondary.
Legacy aliases maintained for gradual migration."
```

---

## Task 2: Update Constants (Stage Colors)

**Files:**
- Modify: `storyengine/frontend/src/lib/constants.ts`

- [ ] **Step 1: Update PIPELINE_STAGES colors only (keep existing keys and dot values)**

CRITICAL: Do NOT change the `key` values — they must match Airtable/Supabase status strings used throughout the app. Only update the `color` field. Keep the `dot` field unchanged.

```typescript
export const PIPELINE_STAGES = [
  { key: "idea_logged", label: "Idea", color: "slate", dot: 1 },
  { key: "ready_for_scripting", label: "Script", color: "teal", dot: 2 },
  { key: "ready_for_voice", label: "Voice", color: "teal", dot: 3 },
  { key: "ready_for_storyboards", label: "Storyboard", color: "teal", dot: 4 },
  { key: "ready_for_images", label: "Images", color: "teal", dot: 5 },
  { key: "ready_for_thumbnail", label: "Thumbnail", color: "teal", dot: 6 },
  { key: "ready_to_render", label: "Render", color: "teal", dot: 7 },
  { key: "rendered", label: "Rendered", color: "teal", dot: 8 },
  { key: "uploaded_draft", label: "Draft", color: "amber", dot: 9 },
  { key: "done", label: "Published", color: "green", dot: 10 },
] as const;
```

Note: Colors remain Tailwind names (not CSS variables) because `ProgressDots` and `VideoCard` use `DOT_COLORS` and `BADGE_COLORS` lookup maps keyed on these names. Tasks 8-9 will update those components to use CSS variables directly, at which point these color values become irrelevant.

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/lib/constants.ts
git commit -m "style(storyengine): Update pipeline stage colors to match design system"
```

---

## Task 3: Restyle UI Primitives (Card)

**Files:**
- Modify: `storyengine/frontend/src/components/ui/card.tsx`

- [ ] **Step 1: Update Card component to use new design tokens**

The Card component should use `--bg-card`, `--border`, and `--card-radius`:

```tsx
// Update the Card root className to use new tokens:
// bg: var(--bg-card)
// border: 1px solid var(--border)
// border-radius: var(--card-radius)
// hover: var(--bg-card-hover)
```

Read the current card.tsx first, then update the Tailwind classes to reference the new CSS variables. Keep the same component API (Card, CardHeader, CardBody).

- [ ] **Step 2: Verify cards render correctly on dashboard**

```bash
cd storyengine/frontend && npm run dev
```

Check that the dashboard stat cards and autopilot card show with the new styling.

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/components/ui/card.tsx
git commit -m "style(storyengine): Restyle Card component with new design tokens"
```

---

## Task 4: Rebuild Navigation — Bottom Tabs (Mobile)

**Files:**
- Modify: `storyengine/frontend/src/components/nav/bottom-tabs.tsx`

- [ ] **Step 1: Update bottom tabs to 6 tabs with amber accent**

The spec calls for 6 tabs: Home, Pipeline, Script, Storyboard, Stats, Settings.

Read the current `bottom-tabs.tsx`, then update:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  LayoutList,
  FileText,
  Clapperboard,
  BarChart3,
  Settings,
} from "lucide-react";

const tabs = [
  { href: "/", icon: Home, label: "Home" },
  { href: "/pipeline", icon: LayoutList, label: "Pipeline" },
  { href: "/review", icon: FileText, label: "Script" },
  { href: "/review?tab=storyboards", icon: Clapperboard, label: "Board" },
  { href: "/analytics", icon: BarChart3, label: "Stats" },
  { href: "/settings", icon: Settings, label: "Settings" },
];

export function BottomTabs() {
  const pathname = usePathname();

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 md:hidden"
         style={{ background: "var(--bg-card)", borderTop: "1px solid var(--border)" }}>
      <div className="flex items-center justify-around h-16 px-2">
        {tabs.map(({ href, icon: Icon, label }) => {
          const isActive = href === "/"
            ? pathname === "/"
            : pathname.startsWith(href.split("?")[0]);

          return (
            <Link
              key={href}
              href={href}
              className="flex flex-col items-center justify-center gap-1 py-2 px-3 rounded-lg transition-colors"
              style={{
                color: isActive ? "var(--amber)" : "var(--text-muted)",
              }}
            >
              <Icon size={20} strokeWidth={isActive ? 2.5 : 1.5} />
              <span className="text-[10px] font-medium">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
```

- [ ] **Step 2: Verify on mobile viewport**

Open dev tools, set mobile viewport (375px). Confirm 6 tabs visible, amber highlight on active tab.

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/components/nav/bottom-tabs.tsx
git commit -m "style(storyengine): Rebuild bottom tabs — 6 tabs, amber accent, new icons"
```

---

## Task 5: Rebuild Navigation — Sidebar (Desktop)

**Files:**
- Modify: `storyengine/frontend/src/components/nav/sidebar.tsx`

- [ ] **Step 1: Update sidebar with 7 nav items + collapsible**

The spec calls for: Home, Pipeline, Script, Storyboard, Stats, Autopilot, Settings. Plus a Sign Out link at bottom.

Read the current `sidebar.tsx`, then update to include:

```tsx
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
  LogOut,
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
      <div className="flex items-center gap-3 px-4 h-16"
           style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold"
             style={{ background: "var(--amber)", color: "var(--bg-primary)" }}>
          SE
        </div>
        {!collapsed && (
          <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            StoryEngine
          </span>
        )}
      </div>

      {/* Nav items */}
      <nav className="flex-1 py-4 px-2 space-y-1">
        {navItems.map(({ href, icon: Icon, label }) => {
          const isActive = href === "/"
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
              {!collapsed && <span className="text-sm font-medium">{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-2 pb-4 space-y-1">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg w-full transition-colors ${
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
```

- [ ] **Step 2: Update layout.tsx colors and references**

In `layout.tsx`, the `md:ml-60` margin already exists. Update:
- `themeColor` from `#121212` to `#0A0A0B`
- Any `bg-[var(--background)]` references to `bg-[var(--bg-primary)]`
- Any `bg-[var(--surface)]` references to `bg-[var(--bg-card)]`
- Bottom padding for mobile tab bar: keep `pb-16 md:pb-0`

- [ ] **Step 3: Verify desktop and mobile views**

Desktop: sidebar visible with 7 items, amber active state, collapsible.
Mobile: sidebar hidden, bottom tabs visible.

- [ ] **Step 4: Commit**

```bash
git add storyengine/frontend/src/components/nav/sidebar.tsx storyengine/frontend/src/app/layout.tsx
git commit -m "style(storyengine): Rebuild sidebar — 7 tabs, collapsible, amber accent"
```

---

## Task 6: Create Action Card Component

**Files:**
- Create: `storyengine/frontend/src/components/action-card.tsx`

- [ ] **Step 1: Create the action card component**

This is the "needs attention" card shown on the dashboard. From the spec:
```
| Y Hormuz $2K Drone           |
| Storyboard ready for review  |
| [Review ->]                  |
```

```tsx
"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

interface ActionCardProps {
  title: string;
  message: string;
  href: string;
  actionLabel?: string;
  status?: "warning" | "error" | "info";
}

export function ActionCard({
  title,
  message,
  href,
  actionLabel = "Review",
  status = "warning",
}: ActionCardProps) {
  const dotColor = {
    warning: "var(--amber)",
    error: "var(--red)",
    info: "var(--teal)",
  }[status];

  return (
    <Link
      href={href}
      className="block rounded-xl p-4 transition-colors"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-2.5 h-2.5 rounded-full mt-1.5 shrink-0"
          style={{ background: dotColor }}
        />
        <div className="flex-1 min-w-0">
          <h3
            className="text-sm font-semibold truncate"
            style={{ color: "var(--text-primary)" }}
          >
            {title}
          </h3>
          <p
            className="text-sm mt-0.5"
            style={{ color: "var(--text-secondary)" }}
          >
            {message}
          </p>
        </div>
        <div
          className="flex items-center gap-1 text-sm font-medium shrink-0"
          style={{ color: "var(--amber)" }}
        >
          {actionLabel}
          <ArrowRight size={14} />
        </div>
      </div>
    </Link>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/action-card.tsx
git commit -m "feat(storyengine): Add ActionCard component for dashboard alerts"
```

---

## Task 7: Redesign Dashboard Page

**Files:**
- Modify: `storyengine/frontend/src/app/page.tsx`

- [ ] **Step 1: Redesign the dashboard to match spec**

Read the current `page.tsx`. The new layout should be:

**Mobile:** Single column:
1. Greeting + approval count
2. Action cards (videos needing attention)
3. Recent activity feed
4. Quick stats (2x2 grid)

**Desktop:** 3-column grid:
- Left: Action items
- Center: Recent activity
- Right: Quick stats

```tsx
"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getDashboardSummary, getVideos } from "@/lib/api";
import { ActionCard } from "@/components/action-card";
import { formatCost, formatNumber, timeAgo } from "@/lib/utils";
import {
  CheckCircle2,
  XCircle,
  Clock,
  TrendingUp,
  DollarSign,
  Film,
} from "lucide-react";

// Status values that need user attention
const ATTENTION_STATUSES = [
  "ready_for_scripting",
  "ready_for_storyboards",
  "ready_for_thumbnail",
];

function getAttentionMessage(status: string): string {
  const messages: Record<string, string> = {
    ready_for_scripting: "Script ready for review",
    ready_for_storyboards: "Storyboard ready for review",
    ready_for_thumbnail: "Thumbnail ready for review",
  };
  return messages[status] || "Needs attention";
}

export default function DashboardPage() {
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: getDashboardSummary,
  });

  const { data: videos, isLoading: videosLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  // Videos needing attention
  const actionItems = (videos || []).filter((v: any) =>
    ATTENTION_STATUSES.includes(v.status)
  );

  // Recent completed/failed videos for activity feed
  const recentActivity = (videos || [])
    .filter((v: any) => v.status === "done" || v.status === "uploaded_draft" || v.status === "rendered")
    .sort((a: any, b: any) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 5);

  const isLoading = summaryLoading || videosLoading;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          Good morning, Ryan
        </h1>
        <p className="mt-1" style={{ color: "var(--text-secondary)" }}>
          {actionItems.length > 0
            ? `${actionItems.length} video${actionItems.length > 1 ? "s" : ""} need${actionItems.length === 1 ? "s" : ""} approval`
            : "All clear — no approvals pending"}
        </p>
      </div>

      {/* Main grid: mobile stacked, desktop 3-col */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Action items */}
        <div className="space-y-3">
          {isLoading ? (
            <>
              <SkeletonCard />
              <SkeletonCard />
            </>
          ) : actionItems.length > 0 ? (
            actionItems.map((v: any) => (
              <ActionCard
                key={v.id}
                title={v.video_title}
                message={getAttentionMessage(v.status)}
                href={`/pipeline?video=${v.id}`}
              />
            ))
          ) : (
            <div
              className="rounded-xl p-6 text-center"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            >
              <CheckCircle2 size={32} className="mx-auto mb-2" style={{ color: "var(--green)" }} />
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                No approvals needed
              </p>
            </div>
          )}
        </div>

        {/* Center: Recent activity */}
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider mb-3"
              style={{ color: "var(--text-muted)" }}>
            Recent Activity
          </h2>
          <div className="space-y-2">
            {isLoading ? (
              <>
                <SkeletonLine />
                <SkeletonLine />
                <SkeletonLine />
              </>
            ) : recentActivity.length > 0 ? (
              recentActivity.map((v: any) => (
                <Link
                  key={v.id}
                  href={`/pipeline?video=${v.id}`}
                  className="flex items-center gap-3 py-2 rounded-lg px-2 -mx-2 transition-colors hover:bg-[var(--bg-card)]"
                >
                  <div
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{
                      background: v.status === "done" ? "var(--green)" : "var(--teal)",
                    }}
                  />
                  <span className="text-sm truncate flex-1" style={{ color: "var(--text-primary)" }}>
                    {v.video_title}
                  </span>
                  <span className="text-xs shrink-0" style={{ color: "var(--text-muted)" }}>
                    {v.status === "done" ? "published" : v.status.replace(/_/g, " ")}
                  </span>
                </Link>
              ))
            ) : (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>No recent activity</p>
            )}
          </div>
        </div>

        {/* Right: Quick stats */}
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider mb-3"
              style={{ color: "var(--text-muted)" }}>
            Quick Stats
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <QuickStat
              label="Published"
              value={`${summary?.pipeline_distribution?.done || 0} videos`}
              icon={Film}
            />
            <QuickStat
              label="Pending"
              value={`${summary?.pending_review || 0} reviews`}
              icon={TrendingUp}
            />
            <QuickStat
              label="Pipeline"
              value={`${summary?.total_videos || 0} total`}
              icon={Clock}
            />
            <QuickStat
              label="Spend"
              value={summary?.cost_today ? formatCost(summary.cost_today) : "$0"}
              icon={DollarSign}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function QuickStat({ label, value, icon: Icon }: { label: string; value: string; icon: any }) {
  return (
    <div
      className="rounded-xl p-4"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
          {label}
        </span>
        <Icon size={14} style={{ color: "var(--text-muted)" }} />
      </div>
      <p className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
        {value}
      </p>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="rounded-xl p-4 animate-pulse" style={{ background: "var(--bg-card)" }}>
      <div className="h-4 rounded w-3/4 mb-2" style={{ background: "var(--border)" }} />
      <div className="h-3 rounded w-1/2" style={{ background: "var(--border)" }} />
    </div>
  );
}

function SkeletonLine() {
  return (
    <div className="flex items-center gap-3 py-2 animate-pulse">
      <div className="w-2 h-2 rounded-full" style={{ background: "var(--border)" }} />
      <div className="h-3 rounded flex-1" style={{ background: "var(--border)" }} />
    </div>
  );
}
```

- [ ] **Step 2: Verify dashboard renders**

```bash
cd storyengine/frontend && npm run dev
```

Check: greeting, action cards for pending videos, activity feed, quick stats grid.
Mobile: single column stack. Desktop (>1024px): 3-column grid.

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/app/page.tsx
git commit -m "feat(storyengine): Redesign dashboard — action-first with activity feed and stats"
```

---

## Task 8: Update Progress Dots

**Files:**
- Modify: `storyengine/frontend/src/components/progress-dots.tsx`

- [ ] **Step 1: Update dots to use new color system**

Read current `progress-dots.tsx`. Update to use the spec's dot colors:
- Completed: `var(--dot-complete)` (green)
- Current: `var(--dot-current)` (amber) with pulse animation
- Pending: `var(--dot-pending)` (muted gray)
- Failed: `var(--dot-failed)` (red)

Remove per-stage rainbow colors. All completed stages should be the same green, current amber, pending gray.

```tsx
// For each dot:
const dotStyle = {
  background: isComplete
    ? "var(--dot-complete)"
    : isCurrent
    ? "var(--dot-current)"
    : "var(--dot-pending)",
};

// Current stage gets pulse animation class
const dotClass = isCurrent ? "animate-pulse-dot" : "";
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/progress-dots.tsx
git commit -m "style(storyengine): Update progress dots — green/amber/gray system"
```

---

## Task 9: Restyle Video Cards

**Files:**
- Modify: `storyengine/frontend/src/components/video-card.tsx`

- [ ] **Step 1: Restyle video card to match spec**

Read current `video-card.tsx`. The spec card layout is:

```
| Hormuz $2K Drone             |
| * * * * o o o o o o          |
| Y Ready For Storyboards      |
| Created 2d ago  |  $4.20     |
```

Update to:
- Card bg: `var(--bg-card)`, border: `var(--border)`, rounded: `var(--card-radius)`
- Title: `var(--text-primary)`, bold
- Progress dots below title
- Status badge: colored dot + status text
- Bottom row: time ago + cost, `var(--text-muted)`
- Hover: `var(--bg-card-hover)`

Remove the 80x45px thumbnail — the spec doesn't show thumbnails in the pipeline list view.

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/video-card.tsx
git commit -m "style(storyengine): Restyle video cards — progress dots, no thumbnails"
```

---

## Task 10: Redesign Pipeline Page

**Files:**
- Modify: `storyengine/frontend/src/app/pipeline/page.tsx`

- [ ] **Step 1: Update pipeline page layout and filters**

Read the current `pipeline/page.tsx`. Update to match the spec:

**Header:** "Pipeline" title + [+ New] button + search icon
**Filters:** Status dropdown (All, In Progress, Needs Approval, Done, Failed) + Sort dropdown
**List:** VideoCard components in a vertical stack
**Desktop:** Wider cards showing `| Title | Status | Progress | CTR | Views | Cost |` columns

Key changes:
- Replace filter chips with dropdowns (cleaner on mobile)
- Add search input (filter by title text)
- Remove grid view toggle (spec only shows list view)
- Keep the detail panel on video selection (already works)
- Add [+ New] button in header (links to create page or opens modal)
- Add "Load More" pagination button at bottom

Update the filter logic:
```typescript
const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "in_progress", label: "In Progress" },
  { value: "needs_approval", label: "Needs Approval" },
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
];
```

The "In Progress" filter should match any status between `ready_for_scripting` and `rendered`.
The "Needs Approval" filter should match statuses that need human review (ready_for_scripting, ready_for_storyboards, ready_for_thumbnail).

- [ ] **Step 2: Verify pipeline page**

Check: filter dropdowns work, search filters by title, video cards show new styling with progress dots, clicking a card opens detail panel.

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/app/pipeline/page.tsx
git commit -m "feat(storyengine): Redesign pipeline view — dropdowns, search, clean cards"
```

---

## Task 11: Typecheck and Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Run typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

Fix any TypeScript errors.

- [ ] **Step 2: Run build**

```bash
cd storyengine/frontend && npm run build
```

Fix any build errors.

- [ ] **Step 3: Visual check all pages**

Open http://localhost:3001 and verify:
- Dashboard: greeting, action cards, activity, stats
- Pipeline: filters, search, video list with progress dots
- Navigation: 6 bottom tabs (mobile), 7 sidebar items (desktop), amber accent

- [ ] **Step 4: Commit any fixes**

```bash
git add -A storyengine/frontend/
git commit -m "fix(storyengine): Fix typecheck and build errors from Module 1 redesign"
```

---

## Completion Criteria

- [ ] Design tokens applied (charcoal/amber/teal palette)
- [ ] Bottom tabs: 6 tabs with amber accent
- [ ] Sidebar: 7 items, collapsible, amber active state
- [ ] Dashboard: action-first layout with greeting, activity feed, quick stats
- [ ] Pipeline: progress dot cards, status/sort filters, search
- [ ] Progress dots: green (complete), amber (current), gray (pending)
- [ ] Cards: subtle borders, no heavy shadows
- [ ] Skeleton loading states (not spinners)
- [ ] Mobile-first: all views work on 375px viewport
- [ ] TypeScript compiles, Next.js builds

**Total: 11 tasks, ~15 files modified/created**
