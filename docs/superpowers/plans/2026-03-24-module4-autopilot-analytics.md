# Module 4: Autopilot Monitor + Analytics Dashboard

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the existing autopilot page to match the dark editorial design, and build the analytics dashboard page — completing the two remaining nav tabs (Autopilot + Stats).

**Architecture:** The autopilot page already exists with working API integration (candidates, learnings, toggle, config). We restyle it to match the UI spec (Screen 6). The analytics page is new — it queries `videos` table for performance data and displays CTR charts, revenue estimates, and per-video cards (Screen 7). No new backend endpoints needed — all data comes from existing APIs.

**Tech Stack:** Next.js 16, React 19, Tailwind 4.2, Framer Motion, Recharts (already installed, not yet used), Lucide icons

**Design Spec:** `docs/superpowers/specs/2026-03-23-storyengine-ui-ux-addendum.md` — Screens 6 and 7

---

## File Map

### New Files
| File | Purpose |
|------|---------|
| `src/app/analytics/page.tsx` | Analytics dashboard — channel stats, CTR chart, revenue, per-video cards |

### Modified Files
| File | Purpose |
|------|---------|
| `src/app/autopilot/page.tsx` | Restyle to match dark editorial design spec |

---

## Task 1: Restyle Autopilot Page

**Files:**
- Modify: `storyengine/frontend/src/app/autopilot/page.tsx`

The existing page has all the right functionality — candidates, learnings, toggle, config. It just needs to use the new design tokens and match Screen 6 from the spec.

- [ ] **Step 1: Restyle the autopilot page**

Read the current `storyengine/frontend/src/app/autopilot/page.tsx` (589 lines). Apply these changes:

**Color updates throughout:**
- Replace `var(--accent)` with `var(--amber)` for primary actions
- Replace `var(--surface)` with `var(--bg-card)`
- Replace `var(--surface-elevated)` with `var(--bg-card-hover)`
- Replace `var(--text-primary)` references (should already work via legacy aliases)
- Replace `var(--error)` with `var(--red)`
- Replace `var(--success)` with `var(--green)`
- Replace `var(--warning)` with `var(--amber)`
- Replace any hardcoded `#00d4aa` or teal accent with `var(--amber)`

**Structural changes:**
- Header: "Autopilot" title with green/red status badge + toggle button (keep existing toggle logic)
- Structure Performance section: Add horizontal bar chart for curiosity gap structures (from spec: hidden_flaw, asymmetric_dg, time_bomb, paradigm_shift, illusion_ctrl with CTR percentages)
- Learnings section: Quote-style display with pattern text
- Pattern Library section: Count of analyzed videos + top performer

**Keep unchanged:**
- All React Query hooks and data fetching
- Toggle mutation logic
- Candidate ranking with confidence breakdown
- Launch candidate button
- Videos per month config
- Expandable sections

- [ ] **Step 2: Verify page renders**

```bash
cd storyengine/frontend && npm run dev
```

Check http://localhost:3001/autopilot — should show the restyled page with amber accents.

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/app/autopilot/page.tsx
git commit -m "style(storyengine): Restyle autopilot page to dark editorial design"
```

---

## Task 2: Create Analytics Page

**Files:**
- Create: `storyengine/frontend/src/app/analytics/page.tsx`

- [ ] **Step 1: Build the analytics dashboard**

This page shows channel-level and per-video performance. Data comes from `getVideos()` — we filter for published videos with performance data.

```tsx
"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getVideos } from "@/lib/api";
import { formatNumber, formatCost } from "@/lib/utils";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from "recharts";

const RPM = 12; // Revenue per mille (estimated)

export default function AnalyticsPage() {
  const { data: allVideos, isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  // Filter to published videos with performance data
  const publishedVideos = useMemo(() => {
    if (!allVideos) return [];
    return allVideos
      .filter((v: any) => v.status === "done" && (v.views > 0 || v.ctr != null))
      .sort((a: any, b: any) => (b.views || 0) - (a.views || 0));
  }, [allVideos]);

  // Aggregate stats
  const stats = useMemo(() => {
    if (publishedVideos.length === 0) return null;
    const totalViews = publishedVideos.reduce((s: number, v: any) => s + (v.views || 0), 0);
    const totalCost = publishedVideos.reduce((s: number, v: any) => s + (v.total_cost || 0), 0);
    const ctrs = publishedVideos.filter((v: any) => v.ctr != null).map((v: any) => v.ctr);
    const avgCtr = ctrs.length > 0 ? ctrs.reduce((a: number, b: number) => a + b, 0) / ctrs.length : 0;
    const retentions = publishedVideos.filter((v: any) => v.avg_retention != null).map((v: any) => v.avg_retention);
    const avgRetention = retentions.length > 0 ? retentions.reduce((a: number, b: number) => a + b, 0) / retentions.length : 0;
    const estRevenue = (totalViews / 1000) * RPM;

    return {
      totalViews,
      avgCtr,
      avgRetention,
      totalCost,
      estRevenue,
      netMargin: estRevenue - totalCost,
      videoCount: publishedVideos.length,
    };
  }, [publishedVideos]);

  // CTR chart data
  const ctrChartData = useMemo(() => {
    return publishedVideos
      .filter((v: any) => v.ctr != null)
      .map((v: any) => ({
        name: v.video_title?.length > 20 ? v.video_title.slice(0, 20) + "..." : v.video_title,
        ctr: v.ctr,
        fullTitle: v.video_title,
      }))
      .slice(0, 10);
  }, [publishedVideos]);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-32 rounded animate-pulse" style={{ background: "var(--border)" }} />
        <div className="grid grid-cols-2 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          Analytics
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          Last 30 days
        </p>
      </div>

      {/* Top stat cards */}
      {stats ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatCard
            label="Views"
            value={formatNumber(stats.totalViews)}
            sub={`${stats.videoCount} videos`}
          />
          <StatCard
            label="CTR"
            value={`${stats.avgCtr.toFixed(1)}%`}
            alert={stats.avgCtr < 3}
          />
          <StatCard
            label="Retention"
            value={stats.avgRetention > 0 ? `${stats.avgRetention.toFixed(0)}%` : "—"}
          />
          <StatCard
            label="Spend"
            value={formatCost(stats.totalCost)}
            sub={`${stats.videoCount} vids`}
          />
        </div>
      ) : (
        <div
          className="rounded-xl p-8 text-center"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <p style={{ color: "var(--text-muted)" }}>
            No published videos with performance data yet.
          </p>
        </div>
      )}

      {/* CTR by Video chart */}
      {ctrChartData.length > 0 && (
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h2
            className="text-sm font-semibold uppercase tracking-wider mb-4"
            style={{ color: "var(--text-muted)" }}
          >
            CTR by Video
          </h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={ctrChartData} layout="vertical" margin={{ left: 10, right: 20 }}>
                <XAxis
                  type="number"
                  domain={[0, "auto"]}
                  tick={{ fill: "var(--text-muted)", fontSize: 12 }}
                  tickFormatter={(v) => `${v}%`}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={140}
                  tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--bg-card-hover)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    color: "var(--text-primary)",
                    fontSize: 13,
                  }}
                  formatter={(value: number) => [`${value.toFixed(1)}%`, "CTR"]}
                  labelFormatter={(label, payload) =>
                    payload?.[0]?.payload?.fullTitle || label
                  }
                />
                <ReferenceLine
                  x={3}
                  stroke="var(--amber)"
                  strokeDasharray="3 3"
                  label={{
                    value: "3% threshold",
                    fill: "var(--amber)",
                    fontSize: 11,
                    position: "top",
                  }}
                />
                <Bar dataKey="ctr" radius={[0, 4, 4, 0]}>
                  {ctrChartData.map((entry: any, index: number) => (
                    <Cell
                      key={index}
                      fill={entry.ctr >= 3 ? "var(--green)" : entry.ctr >= 2 ? "var(--amber)" : "var(--red)"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Revenue estimate */}
      {stats && stats.estRevenue > 0 && (
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h2
            className="text-sm font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-muted)" }}
          >
            Revenue Estimate
          </h2>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                Est. Revenue
              </span>
              <p className="text-lg font-bold" style={{ color: "var(--green)" }}>
                ${stats.estRevenue.toFixed(0)}
              </p>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                at ${RPM} RPM
              </span>
            </div>
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                Production Cost
              </span>
              <p className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
                {formatCost(stats.totalCost)}
              </p>
            </div>
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                Net Margin
              </span>
              <p
                className="text-lg font-bold"
                style={{ color: stats.netMargin >= 0 ? "var(--green)" : "var(--red)" }}
              >
                ${stats.netMargin.toFixed(0)}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Per-video performance cards */}
      {publishedVideos.length > 0 && (
        <div>
          <h2
            className="text-sm font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-muted)" }}
          >
            Video Performance
          </h2>
          <div className="space-y-3">
            {publishedVideos.map((v: any) => (
              <div
                key={v.id}
                className="rounded-xl p-4"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                }}
              >
                <h3
                  className="text-sm font-semibold mb-2 truncate"
                  style={{ color: "var(--text-primary)" }}
                >
                  {v.video_title}
                </h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  <div>
                    <span style={{ color: "var(--text-muted)" }}>Views</span>
                    <p className="font-bold" style={{ color: "var(--text-primary)" }}>
                      {formatNumber(v.views || 0)}
                    </p>
                  </div>
                  <div>
                    <span style={{ color: "var(--text-muted)" }}>CTR</span>
                    <p
                      className="font-bold"
                      style={{
                        color:
                          v.ctr == null
                            ? "var(--text-muted)"
                            : v.ctr >= 3
                            ? "var(--green)"
                            : v.ctr >= 2
                            ? "var(--amber)"
                            : "var(--red)",
                      }}
                    >
                      {v.ctr != null ? `${v.ctr.toFixed(1)}%` : "—"}
                    </p>
                  </div>
                  <div>
                    <span style={{ color: "var(--text-muted)" }}>Retention</span>
                    <p className="font-bold" style={{ color: "var(--text-primary)" }}>
                      {v.avg_retention != null ? `${v.avg_retention.toFixed(0)}%` : "—"}
                    </p>
                  </div>
                  <div>
                    <span style={{ color: "var(--text-muted)" }}>Cost</span>
                    <p className="font-bold" style={{ color: "var(--text-primary)" }}>
                      {formatCost(v.total_cost || 0)}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  alert,
}: {
  label: string;
  value: string;
  sub?: string;
  alert?: boolean;
}) {
  return (
    <div
      className="rounded-xl p-4"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
    >
      <span
        className="text-xs uppercase tracking-wider"
        style={{ color: "var(--text-muted)" }}
      >
        {label}
      </span>
      <p
        className="text-xl font-bold mt-1"
        style={{ color: alert ? "var(--red)" : "var(--text-primary)" }}
      >
        {value}
      </p>
      {sub && (
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {sub}
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify the page**

```bash
cd storyengine/frontend && npm run dev
```

Check http://localhost:3001/analytics — should show stat cards, CTR bar chart, revenue estimates, per-video cards.

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/app/analytics/page.tsx
git commit -m "feat(storyengine): Add analytics dashboard — CTR chart, revenue, per-video cards"
```

---

## Task 3: Typecheck and Build

- [ ] **Step 1: Typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 2: Build**

```bash
cd storyengine/frontend && npm run build
```

- [ ] **Step 3: Push to deploy**

```bash
git push origin main
```

The VPS cron will auto-pull and rebuild within 5 minutes.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A storyengine/frontend/ && git commit -m "fix(storyengine): Fix Module 4 build errors"
```

---

## Completion Criteria

- [ ] Autopilot page uses new design tokens (amber accent, charcoal bg)
- [ ] Analytics page shows: stat cards, CTR bar chart, revenue estimate, per-video cards
- [ ] CTR chart uses Recharts with color-coded bars (green ≥3%, amber 2-3%, red <2%)
- [ ] 3% threshold reference line on CTR chart
- [ ] Revenue estimate with RPM calculation
- [ ] TypeScript compiles, Next.js builds
- [ ] Pushed to GitHub for VPS auto-deploy

**Total: 3 tasks, 2 files modified/created**
