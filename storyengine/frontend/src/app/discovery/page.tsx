"use client";
import { Spinner } from "@/components/ui/spinner";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  Sparkles, RefreshCw, Loader2, TrendingUp, X, ChevronRight, Brain,
  Lightbulb, ExternalLink,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  getDiscoveryIdeas, getDiscoveryStatus, refreshDiscoveryIdeas,
  launchIdea, dismissIdea,
  type DiscoveryIdea, type TitleOption, type DiscoveryStatus,
} from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { Modal } from "@/components/ui/modal";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";
import { timeAgo } from "@/lib/utils";

const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.08 } } };
const item = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0, transition: { duration: 0.5 } } };

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "fresh", label: "Fresh" },
  { value: "launched", label: "Launched" },
  { value: "dismissed", label: "Dismissed" },
];

const APPEAL_KEYS = [
  { key: "timeliness", label: "Timeliness" },
  { key: "audience_fit", label: "Audience" },
  { key: "content_gap", label: "Gap" },
  { key: "virality", label: "Virality" },
  { key: "depth_potential", label: "Depth" },
  { key: "visual_potential", label: "Visual" },
];

export default function DiscoveryPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("fresh");
  const [editIdea, setEditIdea] = useState<DiscoveryIdea | null>(null);
  const [editTitleIndex, setEditTitleIndex] = useState(0);
  const [editLength, setEditLength] = useState(15);

  const { data: ideas, isLoading, error: ideasError } = useQuery({
    queryKey: ["discoveryIdeas", statusFilter],
    queryFn: () => getDiscoveryIdeas(statusFilter || undefined),
  });

  const { data: status } = useQuery({
    queryKey: ["discoveryStatus"],
    queryFn: getDiscoveryStatus,
    refetchInterval: 5000,
  });

  const refreshMutation = useMutation({
    mutationFn: refreshDiscoveryIdeas,
    onSuccess: () => {
      const interval = setInterval(async () => {
        const s = await getDiscoveryStatus();
        if (!s.is_refreshing) {
          clearInterval(interval);
          queryClient.invalidateQueries({ queryKey: ["discoveryIdeas"] });
          queryClient.invalidateQueries({ queryKey: ["discoveryStatus"] });
        }
      }, 3000);
    },
  });

  const launchMutation = useMutation({
    mutationFn: ({ ideaId, titleIndex, length }: { ideaId: string; titleIndex: number; length: number }) =>
      launchIdea(ideaId, titleIndex, length),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["discoveryIdeas"] });
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      setEditIdea(null);
      router.push(`/pipeline/${result.video_id}`);
    },
  });

  const dismissMutation = useMutation({
    mutationFn: dismissIdea,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["discoveryIdeas"] });
    },
  });

  const isRefreshing = status?.is_refreshing || refreshMutation.isPending;

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Lightbulb size={28} style={{ color: "var(--gold)" }} />
          <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
            Discovery
          </h1>
        </div>
        <button
          onClick={() => refreshMutation.mutate()}
          disabled={isRefreshing}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          <RefreshCw size={14} className={isRefreshing ? "animate-spin" : ""} />
          {isRefreshing ? "Generating..." : "Refresh Ideas"}
        </button>
      </motion.div>

      {/* Status Bar */}
      <motion.div variants={item}>
        <GlassCard className="px-5 py-3">
          <div className="flex items-center gap-4 flex-wrap text-xs font-mono">
            {isRefreshing && (
              <span className="flex items-center gap-1.5" style={{ color: "var(--turquoise)" }}>
                <Loader2 size={12} className="animate-spin" />
                Generating ideas...
              </span>
            )}
            {status && (
              <>
                <span style={{ color: "var(--text-secondary)" }}>
                  <span style={{ color: "var(--text-primary)" }}>{status.idea_count}</span> ideas
                </span>
                <span style={{ color: "var(--text-secondary)" }}>
                  <span style={{ color: "var(--green)" }}>{status.fresh_count}</span> fresh
                </span>
                {status.learnings_applied > 0 && (
                  <span className="flex items-center gap-1" style={{ color: "var(--turquoise)" }}>
                    <Brain size={12} />
                    {status.learnings_applied} learnings applied
                  </span>
                )}
                {status.last_batch_date && (
                  <span className="ml-auto" style={{ color: "var(--text-tertiary)" }}>
                    Last batch: {timeAgo(status.last_batch_date)}
                  </span>
                )}
              </>
            )}
          </div>
        </GlassCard>
      </motion.div>

      {/* Filter Tabs */}
      <motion.div variants={item} className="flex gap-2">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setStatusFilter(f.value)}
            className="px-4 py-1.5 rounded-full text-xs font-semibold font-body transition-all"
            style={{
              background: statusFilter === f.value ? "var(--turquoise)" : "var(--bg-elevated)",
              color: statusFilter === f.value ? "var(--bg-void)" : "var(--text-secondary)",
              border: `1px solid ${statusFilter === f.value ? "var(--turquoise)" : "var(--border)"}`,
            }}
          >
            {f.label}
          </button>
        ))}
      </motion.div>

      {/* Idea Grid */}
      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Spinner size="lg" />
        </div>
      )}

      {ideasError && !isLoading && (
        <ErrorCard message={(ideasError as Error).message} onRetry={() => window.location.reload()} />
      )}

      {!isLoading && (!ideas || ideas.length === 0) && (
        <EmptyState
          icon={Sparkles}
          title={statusFilter === "fresh" ? "No fresh ideas" : `No ${statusFilter || ""} ideas`}
          description='Click "Refresh Ideas" to generate ideas from your competitor data.'
          actionLabel="Refresh Ideas"
          onAction={() => refreshMutation.mutate()}
        />
      )}

      {!isLoading && ideas && ideas.length > 0 && (
        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
        >
          {ideas.map((idea) => (
            <motion.div key={idea.id} variants={item}>
              <IdeaCard
                idea={idea}
                onLaunch={() => {
                  setEditIdea(idea);
                  setEditTitleIndex(0);
                  setEditLength(15);
                }}
                onDismiss={() => dismissMutation.mutate(idea.id)}
              />
            </motion.div>
          ))}
        </motion.div>
      )}

      {/* Launch Modal */}
      <Modal
        open={!!editIdea}
        onClose={() => setEditIdea(null)}
        title="Review & Launch"
        size="md"
      >
        {editIdea && (
          <div className="space-y-4">
            {editIdea.competitor_title && (
              <div
                className="p-3 rounded-lg text-xs font-body"
                style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
              >
                <span style={{ color: "var(--text-tertiary)" }}>Inspired by: </span>
                <span style={{ color: "var(--text-secondary)" }}>
                  &quot;{editIdea.competitor_title}&quot;
                </span>
                {editIdea.competitor_channel && (
                  <span style={{ color: "var(--text-tertiary)" }}> by {editIdea.competitor_channel}</span>
                )}
                {editIdea.competitor_url && (
                  <a
                    href={editIdea.competitor_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-0.5 ml-2"
                    style={{ color: "var(--turquoise)" }}
                  >
                    <ExternalLink size={10} />
                  </a>
                )}
              </div>
            )}

            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Our Angle
              </label>
              <p className="text-sm font-body" style={{ color: "var(--text-primary)" }}>
                {editIdea.our_angle}
              </p>
            </div>

            {editIdea.hook && (
              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                  Hook
                </label>
                <p className="text-sm font-body" style={{ color: "var(--text-primary)" }}>
                  {editIdea.hook}
                </p>
              </div>
            )}

            <div>
              <label className="block text-xs font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
                Select Title
              </label>
              <div className="space-y-2">
                {editIdea.title_options.map((opt: TitleOption, idx: number) => (
                  <button
                    key={idx}
                    onClick={() => setEditTitleIndex(idx)}
                    className="w-full text-left p-3 rounded-lg text-sm font-body transition-all"
                    style={{
                      background: editTitleIndex === idx ? "var(--turquoise-bg)" : "var(--bg-elevated)",
                      border: `1px solid ${editTitleIndex === idx ? "var(--turquoise)" : "var(--border)"}`,
                      color: "var(--text-primary)",
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <span>{opt.title}</span>
                      {opt.score > 0 && (
                        <span className="text-[10px] font-mono" style={{ color: "var(--turquoise)" }}>
                          {opt.score}/10
                        </span>
                      )}
                    </div>
                    {opt.thumbnail_text && (
                      <span className="text-[10px] mt-1 block" style={{ color: "var(--text-tertiary)" }}>
                        Thumbnail: {opt.thumbnail_text}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Video Length
              </label>
              <div className="flex gap-2">
                {[5, 10, 15, 20].map((mins) => (
                  <button
                    key={mins}
                    onClick={() => setEditLength(mins)}
                    className="px-4 py-2 rounded-full text-sm font-medium font-body transition-all"
                    style={{
                      background: editLength === mins ? "var(--turquoise)" : "var(--bg-elevated)",
                      color: editLength === mins ? "var(--bg-void)" : "var(--text-secondary)",
                      border: `1px solid ${editLength === mins ? "var(--turquoise)" : "var(--border)"}`,
                    }}
                  >
                    {mins} min
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={() =>
                launchMutation.mutate({
                  ideaId: editIdea.id,
                  titleIndex: editTitleIndex,
                  length: editLength,
                })
              }
              disabled={launchMutation.isPending}
              className="w-full py-2.5 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              {launchMutation.isPending ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 size={14} className="animate-spin" /> Launching...
                </span>
              ) : (
                "Launch Video"
              )}
            </button>
          </div>
        )}
      </Modal>
    </motion.div>
  );
}

/* ─── Idea Card ─── */

function IdeaCard({
  idea,
  onLaunch,
  onDismiss,
}: {
  idea: DiscoveryIdea;
  onLaunch: () => void;
  onDismiss: () => void;
}) {
  const isLaunched = idea.status === "launched";
  const isDismissed = idea.status === "dismissed";

  return (
    <GlassCard className="p-0 overflow-hidden" style={{ opacity: isDismissed ? 0.5 : 1 }}>
      {/* Thumbnail header */}
      <div
        className="relative h-32 flex items-end overflow-hidden"
        style={{ background: "var(--bg-elevated)" }}
      >
        {idea.competitor_thumbnail_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={idea.competitor_thumbnail_url}
            alt=""
            className="absolute inset-0 w-full h-full object-cover opacity-40"
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        )}
        <div className="absolute inset-0" style={{ background: "linear-gradient(transparent 30%, var(--bg-deep) 100%)" }} />

        {idea.competitor_vph != null && idea.competitor_vph > 0 && (
          <div
            className="absolute top-2 right-2 px-2 py-1 rounded-md text-[10px] font-mono font-bold flex items-center gap-1"
            style={{ background: "rgba(0,0,0,0.7)", color: "var(--turquoise)" }}
          >
            <TrendingUp size={10} />
            {idea.competitor_vph >= 1000
              ? `${(idea.competitor_vph / 1000).toFixed(1)}K`
              : Math.round(idea.competitor_vph)}{" "}
            VPH
          </div>
        )}

        {/* Status badge */}
        {isLaunched && (
          <div
            className="absolute top-2 left-2 px-2 py-0.5 rounded-md text-[9px] font-mono font-bold"
            style={{ background: "rgba(0,230,138,0.2)", color: "var(--green)" }}
          >
            LAUNCHED
          </div>
        )}
        {isDismissed && (
          <div
            className="absolute top-2 left-2 px-2 py-0.5 rounded-md text-[9px] font-mono font-bold"
            style={{ background: "rgba(255,255,255,0.1)", color: "var(--text-tertiary)" }}
          >
            DISMISSED
          </div>
        )}

        {/* Dismiss button (only for fresh) */}
        {!isLaunched && !isDismissed && (
          <button
            onClick={(e) => { e.stopPropagation(); onDismiss(); }}
            className="absolute top-2 left-2 p-1 rounded-md transition-all hover:brightness-150"
            style={{ background: "rgba(0,0,0,0.5)", color: "var(--text-tertiary)" }}
            title="Dismiss idea"
          >
            <X size={12} />
          </button>
        )}

        {/* Source info */}
        <div className="relative z-10 px-4 pb-3 w-full">
          {idea.competitor_channel && (
            <p className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
              {idea.competitor_channel}
            </p>
          )}
          {idea.competitor_title && (
            <p className="text-xs font-body line-clamp-1" style={{ color: "var(--text-secondary)" }}>
              {idea.competitor_title}
            </p>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        <p className="text-sm font-body line-clamp-3" style={{ color: "var(--text-primary)" }}>
          {idea.our_angle}
        </p>

        {/* Framework + Appeal */}
        <div className="flex items-center gap-2 flex-wrap">
          {idea.framework && <StatusPill label={idea.framework} color="purple" />}
          {idea.estimated_appeal != null && (
            <span
              className="text-[10px] font-mono px-2 py-0.5 rounded-full"
              style={{
                background: idea.estimated_appeal >= 7
                  ? "rgba(0, 230, 138, 0.12)"
                  : idea.estimated_appeal >= 5
                  ? "rgba(255, 186, 8, 0.12)"
                  : "rgba(255,255,255,0.05)",
                color: idea.estimated_appeal >= 7
                  ? "var(--green)"
                  : idea.estimated_appeal >= 5
                  ? "var(--gold)"
                  : "var(--text-tertiary)",
              }}
            >
              Appeal: {idea.estimated_appeal}/10
            </span>
          )}
        </div>

        {/* Appeal breakdown mini bars */}
        {idea.appeal_breakdown && Object.keys(idea.appeal_breakdown).length > 0 && (
          <div className="grid grid-cols-3 gap-x-3 gap-y-1">
            {APPEAL_KEYS.map(({ key, label }) => {
              const val = idea.appeal_breakdown?.[key];
              if (val == null) return null;
              return (
                <div key={key} className="flex items-center gap-1.5">
                  <span className="text-[9px] font-mono w-14 shrink-0" style={{ color: "var(--text-tertiary)" }}>
                    {label}
                  </span>
                  <div className="flex-1 h-1 rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${(val / 10) * 100}%`,
                        background: val >= 7 ? "var(--green)" : val >= 5 ? "var(--gold)" : "var(--text-tertiary)",
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Title options preview */}
        {idea.title_options.length > 0 && (
          <div className="space-y-1">
            <p className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
              {idea.title_options.length} title option{idea.title_options.length !== 1 ? "s" : ""}
            </p>
            <p className="text-xs font-body line-clamp-1" style={{ color: "var(--text-secondary)" }}>
              {idea.title_options[0].title}
            </p>
          </div>
        )}

        {/* Action */}
        {!isLaunched && !isDismissed && (
          <button
            onClick={onLaunch}
            className="w-full py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 flex items-center justify-center gap-1.5"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            <ChevronRight size={12} />
            Review & Launch
          </button>
        )}

        {isLaunched && (
          <div className="text-center py-1">
            <span className="text-[10px] font-mono" style={{ color: "var(--green)" }}>
              Video created from this idea
            </span>
          </div>
        )}
      </div>
    </GlassCard>
  );
}
