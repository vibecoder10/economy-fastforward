"use client";

import { HubTabs, AUTOPILOT_TABS } from "@/components/nav/hub-tabs";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Brain,
  Power,
  TrendingUp,
  BarChart3,
  Lightbulb,
  ChevronRight,
  Check,
  X,
  Rocket,
  Loader2,
  Sliders,
  Shield,
  RefreshCw,
  Clock,
  AlertCircle,
} from "lucide-react";
import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { StatCard } from "@/components/ui/StatCard";
import { Spinner } from "@/components/ui/spinner";
import { ErrorCard } from "@/components/ui/ErrorCard";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  getAutopilotSummary,
  toggleAutopilot,
  updateAutopilotConfig,
  launchCandidate,
  syncYouTubeMetrics,
  getYouTubeSyncStatus,
  getAutopilotTasks,
  getAutopilotScorecards,
  type AutopilotSummary,
  type AutopilotTasks,
  type VideoScorecard,
} from "@/lib/api";
import { timeAgo } from "@/lib/utils";

const DEFAULT_WEIGHTS = {
  competitor_vph: 0.55,
  timing_freshness: 0.45,
};

const WEIGHT_LABELS: Record<string, string> = {
  competitor_vph: "Competitor VPH",
  topic_channel_fit: "Topic Channel Fit",
  timing_freshness: "Timing Freshness",
  channel_momentum: "Channel Momentum",
  retention_patterns: "Retention Patterns",
  title_formula: "Title Formula",
};

const THRESHOLD_LABELS: Record<string, { label: string; suffix: string; min: number; max: number; step: number }> = {
  min_confidence_score: { label: "Min Confidence Score", suffix: "", min: 0, max: 100, step: 5 },
  min_competitor_vph: { label: "Min Competitor VPH", suffix: "", min: 0, max: 500, step: 10 },
  max_idea_age_days: { label: "Max Idea Age", suffix: " days", min: 1, max: 30, step: 1 },
  ctr_success_threshold: { label: "CTR Success", suffix: "%", min: 0, max: 15, step: 0.5 },
  ctr_failure_threshold: { label: "CTR Failure", suffix: "%", min: 0, max: 15, step: 0.5 },
};

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const CATEGORY_COLORS: Record<string, string> = {
  title: "turquoise",
  hook: "orange",
  thumbnail: "purple",
  retention: "green",
  framework: "gold",
};

export default function AutopilotPage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [isToggling, setIsToggling] = useState(false);
  const [editingTarget, setEditingTarget] = useState(false);
  const [targetValue, setTargetValue] = useState(15);
  const [savingTarget, setSavingTarget] = useState(false);
  const [editingScrapeLimit, setEditingScrapeLimit] = useState(false);
  const [scrapeLimitValue, setScrapeLimitValue] = useState(10);
  const [savingScrapeLimit, setSavingScrapeLimit] = useState(false);
  const [launchingId, setLaunchingId] = useState<string | null>(null);
  const [editingWeights, setEditingWeights] = useState(false);
  const [draftWeights, setDraftWeights] = useState<Record<string, number>>({});
  const [savingWeights, setSavingWeights] = useState(false);
  const [editingThresholds, setEditingThresholds] = useState(false);
  const [draftThresholds, setDraftThresholds] = useState<Record<string, number>>({});
  const [savingThresholds, setSavingThresholds] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);

  const launchMutation = useMutation({
    mutationFn: launchCandidate,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
      router.push(`/pipeline/${data.video_id}`);
    },
    onError: () => {
      setLaunchingId(null);
    },
  });

  const { data, isLoading, error } = useQuery({
    queryKey: ["autopilot-summary"],
    queryFn: getAutopilotSummary,
  });

  const { data: syncStatus } = useQuery({
    queryKey: ["youtube-sync-status"],
    queryFn: getYouTubeSyncStatus,
    refetchInterval: isSyncing ? 3000 : false,
  });

  const { data: bgTasks } = useQuery({
    queryKey: ["autopilot-tasks"],
    queryFn: getAutopilotTasks,
  });

  // Live-updating per-video scorecards (refresh so post-publish lessons appear as
  // analytics sync). 60s keeps it feeling live without hammering the API.
  const { data: scorecards } = useQuery({
    queryKey: ["autopilot-scorecards"],
    queryFn: () => getAutopilotScorecards(12),
    refetchInterval: 60000,
  });

  const handleSync = async () => {
    setIsSyncing(true);
    try {
      await syncYouTubeMetrics();
    } catch (err) {
      console.error("Error triggering sync:", err);
      setIsSyncing(false);
      return;
    }
    // Poll will handle detecting completion
  };

  // Stop polling when sync completes
  useEffect(() => {
    if (isSyncing && syncStatus && !syncStatus.is_running) {
      setIsSyncing(false);
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    }
  }, [isSyncing, syncStatus, queryClient]);

  const isEnabled = data?.state.enabled ?? true;

  const handleToggle = async () => {
    if (!data) return;
    setIsToggling(true);
    try {
      await toggleAutopilot(!isEnabled);
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    } catch (err) {
      console.error("Error toggling autopilot:", err);
    } finally {
      setIsToggling(false);
    }
  };

  const handleSaveTarget = async () => {
    setSavingTarget(true);
    try {
      await updateAutopilotConfig({ videos_per_month: targetValue });
      setEditingTarget(false);
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    } catch (err) {
      console.error("Error saving target:", err);
    } finally {
      setSavingTarget(false);
    }
  };

  const handleSaveScrapeLimit = async () => {
    setSavingScrapeLimit(true);
    try {
      await updateAutopilotConfig({ videos_per_scrape: scrapeLimitValue });
      setEditingScrapeLimit(false);
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    } catch (err) {
      console.error("Error saving scrape limit:", err);
    } finally {
      setSavingScrapeLimit(false);
    }
  };

  const handleSaveWeights = async () => {
    setSavingWeights(true);
    try {
      await updateAutopilotConfig({ weights: draftWeights });
      setEditingWeights(false);
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    } catch (err) {
      console.error("Error saving weights:", err);
    } finally {
      setSavingWeights(false);
    }
  };

  const handleSaveThresholds = async () => {
    setSavingThresholds(true);
    try {
      await updateAutopilotConfig({ thresholds: draftThresholds });
      setEditingThresholds(false);
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    } catch (err) {
      console.error("Error saving thresholds:", err);
    } finally {
      setSavingThresholds(false);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Autopilot
        </h1>
        <div className="flex items-center justify-center h-48">
          <Spinner size="lg" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="space-y-6">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Autopilot
        </h1>
        <ErrorCard message={(error as Error)?.message || "Failed to load autopilot data"} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  const { state, config, candidates, learnings } = data;
  const weights =
    Object.keys(config.weights).length > 0 ? config.weights : DEFAULT_WEIGHTS;

  // Initialize target value from config on first load
  if (!editingTarget && targetValue !== config.videos_per_month) {
    // We use a ref-like pattern here: only set if not currently editing
    // This is a controlled one-time sync
  }

  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      <HubTabs tabs={AUTOPILOT_TABS} />
      {/* Header with toggle */}
      <motion.div variants={item} className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
            Autopilot
          </h1>
          {isEnabled && <StatusPill label="Active" color="turquoise" pulse size="md" />}
        </div>
        <button
          onClick={handleToggle}
          disabled={isToggling}
          className="relative flex items-center gap-2.5 rounded-full px-6 py-2.5 text-sm font-semibold transition-all duration-300 disabled:opacity-50"
          style={{
            background: isEnabled
              ? "linear-gradient(135deg, rgba(0, 212, 170, 0.25), rgba(0, 212, 170, 0.1))"
              : "linear-gradient(135deg, rgba(255, 77, 106, 0.25), rgba(255, 77, 106, 0.1))",
            color: isEnabled ? "var(--turquoise)" : "var(--red)",
            border: isEnabled
              ? "1px solid rgba(0, 212, 170, 0.3)"
              : "1px solid rgba(255, 77, 106, 0.3)",
            boxShadow: isEnabled
              ? "0 0 20px rgba(0, 212, 170, 0.15)"
              : "0 0 20px rgba(255, 77, 106, 0.15)",
          }}
        >
          <Power size={16} />
          {isEnabled ? "ON" : "OFF"}
        </button>
      </motion.div>

      {/* Production Cycle Status */}
      {(state.last_cycle || state.days_until_next > 0) && (
        <motion.div
          variants={item}
          className="flex items-center gap-6 px-1"
        >
          {state.last_cycle && (
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              <span className="font-mono" style={{ color: "var(--text-tertiary)" }}>Last cycle:</span>{" "}
              <span style={{ color: "var(--text-primary)" }}>{timeAgo(state.last_cycle)}</span>
            </p>
          )}
          {state.days_until_next > 0 && (
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              <span className="font-mono" style={{ color: "var(--text-tertiary)" }}>Next production:</span>{" "}
              <span style={{ color: "var(--turquoise)" }}>
                {state.days_until_next === 1 ? "tomorrow" : `in ${state.days_until_next} days`}
              </span>
            </p>
          )}
          {state.next_production_date && (
            <p className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
              {new Date(state.next_production_date).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
              })}
            </p>
          )}
        </motion.div>
      )}

      {/* Disabled banner */}
      {!isEnabled && (
        <motion.div variants={item}>
          <GlassCard
            style={{
              borderColor: "rgba(255, 77, 106, 0.2)",
              background: "rgba(255, 77, 106, 0.05)",
            }}
          >
            <div className="flex items-center gap-3">
              <Brain size={20} style={{ color: "var(--red)", opacity: 0.6 }} />
              <div>
                <p className="text-sm mb-1" style={{ color: "var(--text-secondary)" }}>
                  Autopilot is disabled. When enabled, it will:
                </p>
                <ul className="text-xs space-y-0.5 ml-4 list-disc" style={{ color: "var(--text-tertiary)" }}>
                  <li>Scrape competitor channels daily for top-performing videos</li>
                  <li>Analyze title, hook, and script patterns from high-CTR content</li>
                  <li>Sync your YouTube metrics and extract learnings automatically</li>
                  <li>Apply proven patterns to every new video it generates</li>
                </ul>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Stat Cards */}
      <motion.div variants={item} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Videos Produced"
          value={state.videos_produced}
          color="var(--turquoise)"
          icon={Brain}
        />
        <StatCard
          label="Avg CTR"
          value={state.channel_avg_ctr > 0 ? `${state.channel_avg_ctr}%` : "--"}
          color="var(--green)"
          icon={TrendingUp}
        />
        {/* Editable Target / Month */}
        <div
          className="glass-card p-5 relative overflow-hidden"
          style={{ borderColor: "rgba(212, 168, 82, 0.2)" }}
        >
          <div
            className="absolute top-0 left-0 right-0 h-0.5"
            style={{ background: "var(--gold)" }}
          />
          {editingTarget ? (
            <div>
              <p
                className="text-[11px] font-medium uppercase tracking-wider mb-2"
                style={{ color: "var(--gold)" }}
              >
                Target / Month
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={targetValue}
                  onChange={(e) => setTargetValue(parseInt(e.target.value) || 1)}
                  min={1}
                  max={30}
                  className="w-16 rounded-lg px-2 py-1 text-xl font-semibold font-body focus:outline-none"
                  style={{
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(212, 168, 82, 0.3)",
                    color: "var(--text-primary)",
                  }}
                  autoFocus
                />
                <button
                  onClick={handleSaveTarget}
                  disabled={savingTarget}
                  className="rounded-lg p-1.5 transition-colors"
                  style={{ color: "var(--green)", background: "rgba(0, 230, 138, 0.1)" }}
                >
                  <Check size={16} />
                </button>
                <button
                  onClick={() => {
                    setEditingTarget(false);
                    setTargetValue(config.videos_per_month);
                  }}
                  className="rounded-lg p-1.5 transition-colors"
                  style={{ color: "var(--red)", background: "rgba(255, 77, 106, 0.1)" }}
                >
                  <X size={16} />
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => {
                setTargetValue(config.videos_per_month);
                setEditingTarget(true);
              }}
              className="group text-left w-full"
            >
              <p
                className="text-[11px] font-medium uppercase tracking-wider mb-1"
                style={{ color: "var(--gold)" }}
              >
                Target / Month
              </p>
              <p
                className="text-2xl font-semibold font-body"
                style={{ color: "var(--text-primary)" }}
              >
                {config.videos_per_month}
              </p>
              <p
                className="text-[11px] mt-1 font-mono"
                style={{ color: "var(--text-secondary)" }}
              >
                click to edit
              </p>
            </button>
          )}
        </div>

        {/* Videos per Scrape */}
        <div
          className="glass-card p-5 relative overflow-hidden"
          style={{ borderColor: "rgba(0, 212, 170, 0.2)" }}
        >
          <div
            className="absolute top-0 left-0 right-0 h-0.5"
            style={{ background: "var(--turquoise)" }}
          />
          {editingScrapeLimit ? (
            <div>
              <p
                className="text-[11px] font-medium uppercase tracking-wider mb-2"
                style={{ color: "var(--turquoise)" }}
              >
                Videos / Scrape
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={scrapeLimitValue}
                  onChange={(e) => setScrapeLimitValue(parseInt(e.target.value) || 5)}
                  min={5}
                  max={50}
                  className="w-16 rounded-lg px-2 py-1 text-xl font-semibold font-body focus:outline-none"
                  style={{
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(0, 212, 170, 0.3)",
                    color: "var(--text-primary)",
                  }}
                  autoFocus
                />
                <button
                  onClick={handleSaveScrapeLimit}
                  disabled={savingScrapeLimit}
                  className="rounded-lg p-1.5 transition-colors"
                  style={{ color: "var(--green)", background: "rgba(0, 230, 138, 0.1)" }}
                >
                  <Check size={16} />
                </button>
                <button
                  onClick={() => {
                    setEditingScrapeLimit(false);
                    setScrapeLimitValue(config.videos_per_scrape);
                  }}
                  className="rounded-lg p-1.5 transition-colors"
                  style={{ color: "var(--red)", background: "rgba(255, 77, 106, 0.1)" }}
                >
                  <X size={16} />
                </button>
              </div>
              <p
                className="text-[10px] mt-2 font-mono"
                style={{ color: "var(--text-tertiary)" }}
              >
                per competitor channel, daily
              </p>
            </div>
          ) : (
            <button
              onClick={() => {
                setScrapeLimitValue(config.videos_per_scrape);
                setEditingScrapeLimit(true);
              }}
              className="group text-left w-full"
            >
              <p
                className="text-[11px] font-medium uppercase tracking-wider mb-1"
                style={{ color: "var(--turquoise)" }}
              >
                Videos / Scrape
              </p>
              <p
                className="text-2xl font-semibold font-body"
                style={{ color: "var(--text-primary)" }}
              >
                {config.videos_per_scrape}
              </p>
              <p
                className="text-[11px] mt-1 font-mono"
                style={{ color: "var(--text-secondary)" }}
              >
                click to edit
              </p>
            </button>
          )}
        </div>
      </motion.div>

      {/* Top Recommendations */}
      {candidates.length === 0 && !isLoading && (
        <motion.div variants={item}>
          <EmptyState
            icon={Rocket}
            title="No candidates available"
            description="Add competitor channels and run a scrape to generate recommendations"
            actionLabel="Set Up Competitor Channels"
            actionHref="/discovery"
          />
        </motion.div>
      )}
      {scorecards && scorecards.length > 0 && (
        <motion.div variants={item}>
          <GlassCard>
            <div className="flex items-center justify-between mb-5">
              <h2
                className="text-[11px] font-semibold uppercase tracking-wider"
                style={{ color: "var(--text-secondary)" }}
              >
                Video Scorecards
              </h2>
              <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                what the engine did + what each video taught us
              </span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {scorecards.map((sc) => (
                <ScorecardCard key={sc.video_id} sc={sc} />
              ))}
            </div>
          </GlassCard>
        </motion.div>
      )}
      {candidates.length > 0 && (
        <motion.div variants={item}>
          <GlassCard>
            <div className="flex items-center justify-between mb-5">
              <h2
                className="text-[11px] font-semibold uppercase tracking-wider"
                style={{ color: "var(--text-secondary)" }}
              >
                Top Recommendations
              </h2>
              <Link
                href="/discovery"
                className="text-xs font-medium transition-colors hover:brightness-125"
                style={{ color: "var(--turquoise)" }}
              >
                View All
                <ChevronRight size={12} className="inline ml-0.5" />
              </Link>
            </div>
            <div className="space-y-2">
              {candidates.slice(0, 5).map((candidate, i) => {
                const medals = [
                  { bg: "rgba(212, 168, 68, 0.2)", color: "var(--gold)", label: "1st" },
                  { bg: "rgba(192, 192, 192, 0.15)", color: "#C0C0C0", label: "2nd" },
                  { bg: "rgba(205, 127, 50, 0.15)", color: "#CD7F32", label: "3rd" },
                  { bg: "rgba(255,255,255,0.05)", color: "var(--text-tertiary)", label: `${i + 1}` },
                  { bg: "rgba(255,255,255,0.05)", color: "var(--text-tertiary)", label: `${i + 1}` },
                ];
                const medal = medals[Math.min(i, 4)];
                const videoId = candidate.url?.match(
                  /(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/
                )?.[1];
                const thumbUrl = videoId
                  ? `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`
                  : null;

                return (
                  <Link
                    key={candidate.id}
                    href="/discovery"
                    className="flex items-center gap-4 p-3 rounded-xl transition-all duration-200"
                    style={{
                      background: "rgba(255,255,255,0.02)",
                      border: "1px solid rgba(255,255,255,0.04)",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = "rgba(255,255,255,0.05)";
                      e.currentTarget.style.borderColor = "rgba(0, 212, 170, 0.15)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "rgba(255,255,255,0.02)";
                      e.currentTarget.style.borderColor = "rgba(255,255,255,0.04)";
                    }}
                  >
                    {/* Rank badge */}
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
                      style={{ background: medal.bg, color: medal.color }}
                    >
                      {medal.label}
                    </div>

                    {thumbUrl && (
                      <img
                        src={thumbUrl}
                        alt=""
                        className="w-20 h-12 rounded-lg object-cover shrink-0"
                      />
                    )}
                    <div className="flex-1 min-w-0">
                      <p
                        className="text-sm font-medium truncate"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {candidate.title}
                      </p>
                      <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                        {candidate.source} &middot; {Math.round(candidate.hours_old)}h ago
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p
                        className="text-sm font-bold"
                        style={{ color: "var(--turquoise)" }}
                      >
                        {candidate.confidence.toFixed(0)}
                      </p>
                      <p
                        className="text-[10px] uppercase tracking-wider"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        conf
                      </p>
                    </div>
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setLaunchingId(candidate.id);
                        launchMutation.mutate(candidate.id);
                      }}
                      disabled={launchingId === candidate.id}
                      className="ml-1 shrink-0 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all cursor-pointer"
                      style={{
                        background: "rgba(0, 212, 170, 0.15)",
                        color: "var(--turquoise)",
                        border: "1px solid rgba(0, 212, 170, 0.25)",
                        opacity: launchingId === candidate.id ? 0.5 : 1,
                      }}
                    >
                      {launchingId === candidate.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Rocket size={12} />
                      )}
                      {launchingId === candidate.id ? "Launching..." : "Launch"}
                    </button>
                  </Link>
                );
              })}
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Confidence Weights */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <Sliders size={16} style={{ color: "var(--turquoise)" }} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Confidence Weights
              </h2>
            </div>
            {editingWeights ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSaveWeights}
                  disabled={savingWeights}
                  className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
                  style={{ background: "rgba(0,230,138,0.15)", color: "var(--green)", border: "1px solid rgba(0,230,138,0.25)" }}
                >
                  {savingWeights ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                  Save
                </button>
                <button
                  onClick={() => setEditingWeights(false)}
                  className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
                  style={{ background: "rgba(255,77,106,0.1)", color: "var(--red)" }}
                >
                  <X size={12} /> Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => { setDraftWeights({ ...weights }); setEditingWeights(true); }}
                className="text-[11px] font-mono transition-colors"
                style={{ color: "var(--text-tertiary)" }}
              >
                edit
              </button>
            )}
          </div>
          <p className="text-[11px] mb-5" style={{ color: "var(--text-secondary)" }}>
            How candidates are scored. Higher weight = more influence on the confidence score.
          </p>

          <div className="space-y-4">
            {Object.entries(weights).map(([key, value]) => (
              <div key={key}>
                <div className="flex items-center justify-between text-xs mb-1.5">
                  <span style={{ color: "var(--text-secondary)" }}>
                    {WEIGHT_LABELS[key] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                  </span>
                  <span className="font-mono font-medium" style={{ color: "var(--turquoise)" }}>
                    {(Number(editingWeights ? (draftWeights[key] ?? value) : value) * 100).toFixed(0)}%
                  </span>
                </div>
                {editingWeights ? (
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={Math.round((draftWeights[key] ?? Number(value)) * 100)}
                    onChange={(e) => setDraftWeights((prev) => ({ ...prev, [key]: parseInt(e.target.value) / 100 }))}
                    className="w-full h-2 rounded-full appearance-none cursor-pointer"
                    style={{ background: `linear-gradient(to right, var(--turquoise) ${Math.round((draftWeights[key] ?? Number(value)) * 100)}%, rgba(255,255,255,0.06) ${Math.round((draftWeights[key] ?? Number(value)) * 100)}%)`, accentColor: "var(--turquoise)" }}
                  />
                ) : (
                  <div className="h-2 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: "var(--turquoise)" }}
                      initial={{ width: 0 }}
                      animate={{ width: `${Number(value) * 100}%` }}
                      transition={{ duration: 1, ease: "easeOut" as const }}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </GlassCard>
      </motion.div>

      {/* Thresholds */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <Shield size={16} style={{ color: "var(--gold)" }} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Thresholds
              </h2>
            </div>
            {editingThresholds ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSaveThresholds}
                  disabled={savingThresholds}
                  className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
                  style={{ background: "rgba(0,230,138,0.15)", color: "var(--green)", border: "1px solid rgba(0,230,138,0.25)" }}
                >
                  {savingThresholds ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                  Save
                </button>
                <button
                  onClick={() => setEditingThresholds(false)}
                  className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
                  style={{ background: "rgba(255,77,106,0.1)", color: "var(--red)" }}
                >
                  <X size={12} /> Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => { setDraftThresholds({ ...config.thresholds }); setEditingThresholds(true); }}
                className="text-[11px] font-mono transition-colors"
                style={{ color: "var(--text-tertiary)" }}
              >
                edit
              </button>
            )}
          </div>
          <p className="text-[11px] mb-5" style={{ color: "var(--text-secondary)" }}>
            Minimum quality gates. Ideas below these thresholds are skipped.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {Object.entries(config.thresholds).map(([key, value]) => {
              const meta = THRESHOLD_LABELS[key] || { label: key.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase()), suffix: "", min: 0, max: 100, step: 1 };
              const displayValue = editingThresholds ? (draftThresholds[key] ?? value) : value;
              return (
                <div
                  key={key}
                  className="rounded-xl px-4 py-3"
                  style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{meta.label}</span>
                    <span className="text-sm font-mono font-medium" style={{ color: "var(--gold)" }}>
                      {Number(displayValue)}{meta.suffix}
                    </span>
                  </div>
                  {editingThresholds ? (
                    <input
                      type="range"
                      min={meta.min}
                      max={meta.max}
                      step={meta.step}
                      value={draftThresholds[key] ?? Number(value)}
                      onChange={(e) => setDraftThresholds((prev) => ({ ...prev, [key]: parseFloat(e.target.value) }))}
                      className="w-full h-2 rounded-full appearance-none cursor-pointer"
                      style={{ accentColor: "var(--gold)" }}
                    />
                  ) : (
                    <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ background: "var(--gold)", width: `${(Number(value) / meta.max) * 100}%` }}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </GlassCard>
      </motion.div>

      {/* YouTube Metrics Sync */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <BarChart3 size={16} style={{ color: "var(--orange)" }} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                YouTube Metrics
              </h2>
            </div>
            <button
              onClick={handleSync}
              disabled={isSyncing || syncStatus?.is_running}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all disabled:opacity-50"
              style={{
                background: "rgba(255, 120, 73, 0.15)",
                color: "var(--orange)",
                border: "1px solid rgba(255, 120, 73, 0.25)",
              }}
            >
              {isSyncing || syncStatus?.is_running ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <RefreshCw size={12} />
              )}
              {isSyncing || syncStatus?.is_running ? "Syncing..." : "Sync Now"}
            </button>
          </div>

          {/* Progress bar while syncing */}
          {(isSyncing || syncStatus?.is_running) && syncStatus && (
            <div className="mb-4">
              <div className="flex items-center justify-between text-[11px] mb-1.5">
                <span style={{ color: "var(--text-secondary)" }}>
                  Syncing metrics from YouTube...
                </span>
                <span className="font-mono" style={{ color: "var(--orange)" }}>
                  {syncStatus.videos_synced}/{syncStatus.videos_total || "?"}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                <motion.div
                  className="h-full rounded-full"
                  style={{ background: "var(--orange)" }}
                  animate={{
                    width: syncStatus.videos_total
                      ? `${(syncStatus.videos_synced / syncStatus.videos_total) * 100}%`
                      : "30%",
                  }}
                  transition={{ duration: 0.5 }}
                />
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <div>
              <p className="text-[11px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>
                Last Sync
              </p>
              <p className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
                {syncStatus?.last_run ? timeAgo(syncStatus.last_run) : "Never"}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>
                Videos Synced
              </p>
              <p className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
                {syncStatus?.videos_synced ?? "--"}
              </p>
            </div>
            {syncStatus?.error && (
              <div className="col-span-2 sm:col-span-1">
                <p className="text-[11px] uppercase tracking-wider mb-1" style={{ color: "var(--red)" }}>
                  Last Error
                </p>
                <p className="text-xs truncate" style={{ color: "var(--red)", opacity: 0.8 }}>
                  {syncStatus.error}
                </p>
              </div>
            )}
          </div>
        </GlassCard>
      </motion.div>

      {/* Background Tasks */}
      {bgTasks && (
        <motion.div variants={item}>
          <GlassCard>
            <div className="flex items-center gap-2 mb-4">
              <Clock size={16} style={{ color: "var(--purple)" }} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Background Tasks
              </h2>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {(
                [
                  { key: "scrape" as const, label: "Auto-Scrape", interval: "Daily" },
                  { key: "youtube_sync" as const, label: "YouTube Sync", interval: "Every 6h" },
                  { key: "learning_extraction" as const, label: "Learning Extraction", interval: "Every 24h" },
                  { key: "title_analysis" as const, label: "Title Analysis", interval: "Every 24h" },
                ] as const
              ).map(({ key, label, interval }) => {
                const task = bgTasks[key];
                const hasError = !!task.last_error;
                return (
                  <div
                    key={key}
                    className="rounded-xl px-4 py-3"
                    style={{
                      background: "rgba(255,255,255,0.03)",
                      border: `1px solid ${hasError ? "rgba(255,77,106,0.2)" : "rgba(255,255,255,0.05)"}`,
                    }}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                        {label}
                      </span>
                      {task.is_running ? (
                        <StatusPill label="Running" color="orange" pulse size="sm" />
                      ) : hasError ? (
                        <StatusPill label="Error" color="red" size="sm" />
                      ) : (
                        <StatusPill label="OK" color="green" size="sm" />
                      )}
                    </div>
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-[11px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                          Last Run
                        </p>
                        <p className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                          {task.last_run ? timeAgo(task.last_run) : "Never"}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-[11px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                          Interval
                        </p>
                        <p className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                          {interval}
                        </p>
                      </div>
                    </div>
                    {hasError && (
                      <div className="flex items-start gap-1.5 mt-2 pt-2" style={{ borderTop: "1px solid rgba(255,77,106,0.15)" }}>
                        <AlertCircle size={12} className="shrink-0 mt-0.5" style={{ color: "var(--red)" }} />
                        <p className="text-[11px] leading-tight" style={{ color: "var(--red)", opacity: 0.8 }}>
                          {task.last_error}
                        </p>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Learned Patterns */}
      {learnings.length > 0 && (
        <motion.div variants={item}>
          <GlassCard>
            <div className="flex items-center gap-2 mb-1">
              <Lightbulb size={16} style={{ color: "var(--turquoise)" }} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Learned Patterns
              </h2>
            </div>
            <p className="text-[11px] mb-5" style={{ color: "var(--text-secondary)" }}>
              Patterns discovered from video performance
            </p>

            <div className="space-y-2">
              {learnings.map((learning) => (
                <div
                  key={learning.id}
                  className="flex items-center justify-between rounded-xl px-4 py-3"
                  style={{
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.05)",
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <span
                      className="text-sm block truncate"
                      style={{ color: "var(--text-primary)" }}
                    >
                      {learning.pattern}
                    </span>
                    <div className="flex items-center gap-2 mt-1">
                      <StatusPill
                        label={learning.category}
                        color={CATEGORY_COLORS[learning.category] || "turquoise"}
                        size="sm"
                      />
                      <span
                        className="text-[11px] font-mono"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        {Math.round(learning.confidence)}% confidence
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 ml-3 shrink-0">
                    {learning.effect && (
                      <span
                        className="text-sm font-medium"
                        style={{ color: "var(--green)" }}
                      >
                        {learning.effect}
                      </span>
                    )}
                    <span
                      className="text-[11px] font-mono"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      n={learning.sample_size}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>
        </motion.div>
      )}
    </motion.div>
  );
}

function ScorecardCard({ sc }: { sc: VideoScorecard }) {
  const dot = (s: string) =>
    s === "win" ? "#1D9E75" : s === "weak" ? "#D85A30" : "var(--text-tertiary)";
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
    >
      {sc.thumbnail_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={sc.thumbnail_url} alt="" className="w-full aspect-video object-cover" />
      ) : (
        <div
          className="w-full aspect-video flex items-center justify-center text-[10px]"
          style={{ background: "rgba(255,255,255,0.04)", color: "var(--text-tertiary)" }}
        >
          no thumbnail yet
        </div>
      )}
      <div className="p-3">
        <p
          className="text-xs font-semibold mb-2"
          style={{
            color: "var(--text-primary)",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {sc.youtube_url ? (
            <a href={sc.youtube_url} target="_blank" rel="noopener noreferrer" className="hover:brightness-125">
              {sc.title}
            </a>
          ) : (
            sc.title
          )}
        </p>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] mb-3" style={{ color: "var(--text-secondary)" }}>
          {sc.views != null && <span>{sc.views.toLocaleString()} views</span>}
          {sc.ctr != null && <span>{sc.ctr.toFixed(1)}% CTR</span>}
          {sc.avg_retention != null && <span>{Math.round(sc.avg_retention)}% retention</span>}
          {!sc.synced && <span style={{ color: "var(--text-tertiary)" }}>analytics pending</span>}
        </div>
        {sc.applied.length > 0 && (
          <div className="mb-2.5">
            <p className="text-[9px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>
              what the system did
            </p>
            {sc.applied.map((a, i) => (
              <p key={i} className="text-[10px] leading-snug mb-0.5" style={{ color: "var(--text-secondary)" }}>
                · {a}
              </p>
            ))}
          </div>
        )}
        <div>
          <p className="text-[9px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>
            lessons
          </p>
          {sc.lessons.map((l, i) => (
            <div key={i} className="flex items-start gap-1.5 mb-0.5">
              <span
                className="mt-1 rounded-full flex-shrink-0"
                style={{ width: 6, height: 6, background: dot(l.state) }}
              />
              <p className="text-[10px] leading-snug" style={{ color: "var(--text-secondary)" }}>
                <span style={{ color: "var(--text-primary)" }}>{l.component}:</span> {l.text}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
