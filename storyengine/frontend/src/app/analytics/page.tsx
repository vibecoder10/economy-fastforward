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

const RPM = 12;

export default function AnalyticsPage() {
  const { data: allVideos, isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  const publishedVideos = useMemo(() => {
    if (!allVideos) return [];
    return allVideos
      .filter((v: any) => v.status === "done" && (v.views > 0 || v.ctr != null))
      .sort((a: any, b: any) => (b.views || 0) - (a.views || 0));
  }, [allVideos]);

  const stats = useMemo(() => {
    if (publishedVideos.length === 0) return null;
    const totalViews = publishedVideos.reduce((s: number, v: any) => s + (v.views || 0), 0);
    const totalCost = publishedVideos.reduce((s: number, v: any) => s + (v.total_cost || 0), 0);
    const ctrs = publishedVideos.filter((v: any) => v.ctr != null).map((v: any) => v.ctr);
    const avgCtr = ctrs.length > 0 ? ctrs.reduce((a: number, b: number) => a + b, 0) / ctrs.length : 0;
    const retentions = publishedVideos.filter((v: any) => v.avg_retention != null).map((v: any) => v.avg_retention);
    const avgRetention = retentions.length > 0 ? retentions.reduce((a: number, b: number) => a + b, 0) / retentions.length : 0;
    const estRevenue = (totalViews / 1000) * RPM;
    return { totalViews, avgCtr, avgRetention, totalCost, estRevenue, netMargin: estRevenue - totalCost, videoCount: publishedVideos.length };
  }, [publishedVideos]);

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
      <div>
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>Analytics</h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>Last 30 days</p>
      </div>

      {stats ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatCard label="Views" value={formatNumber(stats.totalViews)} sub={`${stats.videoCount} videos`} />
          <StatCard label="CTR" value={`${stats.avgCtr.toFixed(1)}%`} alert={stats.avgCtr < 3} />
          <StatCard label="Retention" value={stats.avgRetention > 0 ? `${stats.avgRetention.toFixed(0)}%` : "—"} />
          <StatCard label="Spend" value={formatCost(stats.totalCost)} sub={`${stats.videoCount} vids`} />
        </div>
      ) : (
        <div className="rounded-xl p-8 text-center" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
          <p style={{ color: "var(--text-muted)" }}>No published videos with performance data yet.</p>
        </div>
      )}

      {ctrChartData.length > 0 && (
        <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
          <h2 className="text-sm font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-muted)" }}>CTR by Video</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={ctrChartData} layout="vertical" margin={{ left: 10, right: 20 }}>
                <XAxis type="number" domain={[0, "auto"]} tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickFormatter={(v) => `${v}%`} />
                <YAxis type="category" dataKey="name" width={140} tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-card-hover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-primary)", fontSize: 13 }}
                  formatter={(value: number) => [`${value.toFixed(1)}%`, "CTR"]}
                  labelFormatter={(label: string, payload: any[]) => payload?.[0]?.payload?.fullTitle || label}
                />
                <ReferenceLine x={3} stroke="var(--amber)" strokeDasharray="3 3" label={{ value: "3% threshold", fill: "var(--amber)", fontSize: 11, position: "top" }} />
                <Bar dataKey="ctr" radius={[0, 4, 4, 0]}>
                  {ctrChartData.map((entry: any, index: number) => (
                    <Cell key={index} fill={entry.ctr >= 3 ? "var(--green)" : entry.ctr >= 2 ? "var(--amber)" : "var(--red)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {stats && stats.estRevenue > 0 && (
        <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
          <h2 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>Revenue Estimate</h2>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>Est. Revenue</span>
              <p className="text-lg font-bold" style={{ color: "var(--green)" }}>${stats.estRevenue.toFixed(0)}</p>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>at ${RPM} RPM</span>
            </div>
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>Production Cost</span>
              <p className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>{formatCost(stats.totalCost)}</p>
            </div>
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>Net Margin</span>
              <p className="text-lg font-bold" style={{ color: stats.netMargin >= 0 ? "var(--green)" : "var(--red)" }}>${stats.netMargin.toFixed(0)}</p>
            </div>
          </div>
        </div>
      )}

      {publishedVideos.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>Video Performance</h2>
          <div className="space-y-3">
            {publishedVideos.map((v: any) => (
              <div key={v.id} className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
                <h3 className="text-sm font-semibold mb-2 truncate" style={{ color: "var(--text-primary)" }}>{v.video_title}</h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  <div>
                    <span style={{ color: "var(--text-muted)" }}>Views</span>
                    <p className="font-bold" style={{ color: "var(--text-primary)" }}>{formatNumber(v.views || 0)}</p>
                  </div>
                  <div>
                    <span style={{ color: "var(--text-muted)" }}>CTR</span>
                    <p className="font-bold" style={{ color: v.ctr == null ? "var(--text-muted)" : v.ctr >= 3 ? "var(--green)" : v.ctr >= 2 ? "var(--amber)" : "var(--red)" }}>
                      {v.ctr != null ? `${v.ctr.toFixed(1)}%` : "—"}
                    </p>
                  </div>
                  <div>
                    <span style={{ color: "var(--text-muted)" }}>Retention</span>
                    <p className="font-bold" style={{ color: "var(--text-primary)" }}>{v.avg_retention != null ? `${v.avg_retention.toFixed(0)}%` : "—"}</p>
                  </div>
                  <div>
                    <span style={{ color: "var(--text-muted)" }}>Cost</span>
                    <p className="font-bold" style={{ color: "var(--text-primary)" }}>{formatCost(v.total_cost || 0)}</p>
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

function StatCard({ label, value, sub, alert }: { label: string; value: string; sub?: string; alert?: boolean }) {
  return (
    <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
      <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>{label}</span>
      <p className="text-xl font-bold mt-1" style={{ color: alert ? "var(--red)" : "var(--text-primary)" }}>{value}</p>
      {sub && <span className="text-xs" style={{ color: "var(--text-muted)" }}>{sub}</span>}
    </div>
  );
}
