"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import Link from "next/link";
import {
  Film,
  Loader2,
  DollarSign,
  TrendingUp,
  Plus,
  ChevronRight,
  Sparkles,
  Brain,
  BarChart3,
  Wand2,
  ArrowRight,
  Play,
  Mic,
  Image as ImageIcon,
  Upload,
  Zap,
  Crown,
  Building2,
  CheckCircle2,
  X,
  Clock,
  Video,
  Users,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatCard } from "@/components/ui/StatCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";
import { Spinner } from "@/components/ui/spinner";
import {
  getDashboardSummary,
  getVideos,
  getActivity,
  getPendingReview,
  type VideoSummary,
  type DashboardSummary,
  type ActivityEntry,
  getUsage,
  type UsageLimits,
} from "@/lib/api";
import { PIPELINE_STAGES, COMPLETED_STATUSES, getStageLabel } from "@/lib/constants";
import { formatCost, timeAgo } from "@/lib/utils";
import { useAuth } from "@/components/auth/AuthProvider";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

function getStageColor(key: string): string {
  const map: Record<string, string> = {
    idea_logged: "var(--text-secondary)",
    ready_for_scripting: "var(--turquoise)",
    ready_for_voice: "var(--turquoise)",
    ready_for_storyboards: "var(--turquoise)",
    ready_for_images: "var(--turquoise)",
    ready_for_thumbnail: "var(--gold)",
    ready_to_render: "var(--orange)",
    rendered: "var(--green)",
    uploaded_draft: "var(--gold)",
    done: "var(--green)",
  };
  return map[key] || "var(--text-secondary)";
}

function computeProgress(status: string | null): number {
  if (!status) return 0;
  const idx = PIPELINE_STAGES.findIndex((s) => s.key === status);
  if (idx < 0) return 0;
  return Math.round(((idx + 1) / PIPELINE_STAGES.length) * 100);
}

const ACTIVITY_DOT_COLOR: Record<string, string> = {
  completed: "var(--green)",
  running: "var(--turquoise)",
  failed: "var(--red)",
  started: "var(--turquoise)",
  pending: "var(--text-tertiary)",
};

export default function HomePage() {
  const { user, isLoading: authLoading } = useAuth();

  // Show spinner only while checking auth
  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  // Unauthenticated: show landing page
  if (!user) {
    return <LandingPage />;
  }

  // Authenticated: show production dashboard
  return <Dashboard />;
}

/* ─── Landing Page (unauthenticated) ─── */

const PIPELINE_STEPS = [
  { icon: Wand2, label: "Research", desc: "Deep-dive factual research" },
  { icon: Film, label: "Script", desc: "6-act narrative structure" },
  { icon: Mic, label: "Voice", desc: "AI voice synthesis" },
  { icon: ImageIcon, label: "Visuals", desc: "Cinematic image generation" },
  { icon: Play, label: "Render", desc: "Full video production" },
  { icon: Upload, label: "Upload", desc: "YouTube draft ready" },
];

const VALUE_PROPS = [
  {
    icon: Film,
    title: "Topic in, video out",
    desc: "18-stage pipeline handles research, scripting, voice, images, storyboards, thumbnails, rendering, and upload.",
  },
  {
    icon: Brain,
    title: "Gets smarter over time",
    desc: "Every video teaches the system what works for your audience. CTR improves automatically.",
  },
  {
    icon: BarChart3,
    title: "Performance intelligence",
    desc: "CTR monitoring, post-mortems, competitor analysis, and pattern learnings compound with every video.",
  },
  {
    icon: Sparkles,
    title: "You stay in control",
    desc: "Review and approve every stage. Edit scripts inline. Pick your visual style. Publish when ready.",
  },
];

const STATS = [
  { value: "18", label: "Pipeline Stages", icon: Wand2 },
  { value: "<15min", label: "Idea to Draft", icon: Clock },
  { value: "4+", label: "Visual Styles", icon: Video },
  { value: "24/7", label: "CTR Monitoring", icon: TrendingUp },
];

const PRICING_TIERS = [
  {
    key: "starter",
    name: "Starter",
    price: 25,
    icon: Zap,
    tagline: "For solo creators getting started",
    features: ["Full 18-stage pipeline", "1 channel", "4 videos/month", "1 visual style", "Manual mode"],
  },
  {
    key: "creator",
    name: "Creator",
    price: 40,
    icon: Crown,
    tagline: "For creators who want AI-powered growth",
    popular: true,
    features: ["Everything in Starter", "15 videos/month", "Autopilot mode", "Analytics & learnings", "Competitor analysis", "3 visual styles"],
  },
  {
    key: "agency",
    name: "Agency",
    price: 75,
    icon: Building2,
    tagline: "For teams managing multiple channels",
    features: ["Everything in Creator", "Unlimited videos", "Multi-channel", "Team management", "Priority rendering", "Custom styles"],
  },
];

const landingContainer = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.12 } },
};
const landingItem = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: "easeOut" as const } },
};

function LandingPage() {
  return (
    <div className="min-h-screen" style={{ background: "var(--bg-void)" }}>
      {/* Nav */}
      <nav className="flex items-center justify-between px-6 py-4 max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <Sparkles size={20} style={{ color: "var(--turquoise)" }} />
          <span className="font-display font-bold text-lg" style={{ color: "var(--text-primary)" }}>
            StoryEngine
          </span>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/pricing"
            className="text-sm font-medium transition-colors hover:brightness-125"
            style={{ color: "var(--text-secondary)" }}
          >
            Pricing
          </Link>
          <Link
            href="/login"
            className="text-sm font-medium transition-colors hover:brightness-125"
            style={{ color: "var(--text-secondary)" }}
          >
            Sign in
          </Link>
          <Link
            href="/login"
            className="px-4 py-2 rounded-lg text-sm font-semibold transition-all hover:brightness-110"
            style={{
              background: "linear-gradient(135deg, var(--turquoise), #00B894)",
              color: "#0A0A0B",
            }}
          >
            Get Started
          </Link>
        </div>
      </nav>

      {/* Section 1: Hero */}
      <section id="hero">
      <motion.div
        className="max-w-6xl mx-auto px-6 pt-16 pb-20 text-center"
        variants={landingContainer}
        initial="hidden"
        animate="show"
      >
        <motion.div variants={landingItem}>
          <span
            className="inline-block px-3 py-1 rounded-full text-xs font-semibold mb-6"
            style={{
              background: "rgba(0, 212, 170, 0.1)",
              color: "var(--turquoise)",
              border: "1px solid rgba(0, 212, 170, 0.2)",
            }}
          >
            AI Video Production for YouTube
          </span>
        </motion.div>

        <motion.h1
          variants={landingItem}
          className="text-5xl sm:text-6xl lg:text-7xl font-display font-bold leading-tight mb-6"
          style={{ color: "var(--text-primary)" }}
        >
          Topic in.{" "}
          <span style={{ color: "var(--turquoise)" }}>Video out.</span>
        </motion.h1>

        <motion.p
          variants={landingItem}
          className="text-lg sm:text-xl max-w-2xl mx-auto mb-10"
          style={{ color: "var(--text-secondary)" }}
        >
          The AI-powered production pipeline that turns your ideas into
          fully produced YouTube videos — research, script, voice, visuals,
          and render — while learning what works for your channel.
        </motion.p>

        <motion.div variants={landingItem} className="flex items-center justify-center gap-4">
          <Link
            href="/login"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-base font-semibold transition-all hover:brightness-110"
            style={{
              background: "linear-gradient(135deg, var(--turquoise), #00B894)",
              color: "#0A0A0B",
            }}
          >
            Start Free Trial
            <ArrowRight size={18} />
          </Link>
          <Link
            href="/pricing"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-base font-semibold transition-all hover:brightness-110"
            style={{
              background: "rgba(255, 255, 255, 0.05)",
              color: "var(--text-primary)",
              border: "1px solid rgba(255, 255, 255, 0.1)",
            }}
          >
            See Pricing
          </Link>
        </motion.div>

        <motion.p
          variants={landingItem}
          className="text-xs mt-4"
          style={{ color: "var(--text-tertiary)" }}
        >
          14-day free trial. No credit card required. BYOK — bring your own API keys.
        </motion.p>
      </motion.div>
      </section>

      {/* Section 2: How It Works */}
      <section id="how-it-works">
        <motion.div
          className="max-w-5xl mx-auto px-6 pb-20"
          variants={landingContainer}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-100px" }}
        >
          <motion.p
            variants={landingItem}
            className="text-center text-xs font-semibold uppercase tracking-widest mb-3"
            style={{ color: "var(--turquoise)" }}
          >
            How It Works
          </motion.p>
          <motion.h2
            variants={landingItem}
            className="text-center text-2xl sm:text-3xl font-display font-bold mb-12"
            style={{ color: "var(--text-primary)" }}
          >
            From idea to YouTube draft in one click
          </motion.h2>

          <motion.div variants={landingItem} className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
            {PIPELINE_STEPS.map((step, i) => (
              <div
                key={step.label}
                className="relative rounded-2xl p-4 text-center"
                style={{
                  background: "rgba(15, 22, 38, 0.65)",
                  border: "1px solid rgba(0, 212, 170, 0.12)",
                }}
              >
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center mx-auto mb-3"
                  style={{ background: "rgba(0, 212, 170, 0.1)" }}
                >
                  <step.icon size={20} style={{ color: "var(--turquoise)" }} />
                </div>
                <p className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                  {step.label}
                </p>
                <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                  {step.desc}
                </p>
                {i < PIPELINE_STEPS.length - 1 && (
                  <div
                    className="hidden lg:block absolute top-1/2 -right-3 text-xs"
                    style={{ color: "var(--text-tertiary)" }}
                  >
                    →
                  </div>
                )}
              </div>
            ))}
          </motion.div>
        </motion.div>
      </section>

      {/* Section 3: Features */}
      <section id="features">
        <motion.div
          className="max-w-5xl mx-auto px-6 pb-20"
          variants={landingContainer}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-100px" }}
        >
          <motion.p
            variants={landingItem}
            className="text-center text-xs font-semibold uppercase tracking-widest mb-3"
            style={{ color: "var(--turquoise)" }}
          >
            Features
          </motion.p>
          <motion.h2
            variants={landingItem}
            className="text-center text-2xl sm:text-3xl font-display font-bold mb-12"
            style={{ color: "var(--text-primary)" }}
          >
            Everything you need to scale your channel
          </motion.h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {VALUE_PROPS.map((v) => (
              <motion.div
                key={v.title}
                variants={landingItem}
                className="rounded-2xl p-6"
                style={{
                  background: "rgba(15, 22, 38, 0.65)",
                  border: "1px solid rgba(255, 255, 255, 0.06)",
                }}
              >
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center mb-4"
                  style={{ background: "rgba(0, 212, 170, 0.1)" }}
                >
                  <v.icon size={20} style={{ color: "var(--turquoise)" }} />
                </div>
                <h3 className="text-lg font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
                  {v.title}
                </h3>
                <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {v.desc}
                </p>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </section>

      {/* Section 4: Stats */}
      <section id="stats">
        <motion.div
          className="max-w-5xl mx-auto px-6 pb-20"
          variants={landingContainer}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-100px" }}
        >
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
            {STATS.map((stat) => (
              <motion.div
                key={stat.label}
                variants={landingItem}
                className="text-center rounded-2xl p-6"
                style={{
                  background: "rgba(15, 22, 38, 0.65)",
                  border: "1px solid rgba(0, 212, 170, 0.12)",
                }}
              >
                <stat.icon size={24} className="mx-auto mb-3" style={{ color: "var(--turquoise)" }} />
                <p className="text-3xl font-display font-bold mb-1" style={{ color: "var(--text-primary)" }}>
                  {stat.value}
                </p>
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {stat.label}
                </p>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </section>

      {/* Section 5: Pricing */}
      <section id="pricing">
        <motion.div
          className="max-w-5xl mx-auto px-6 pb-20"
          variants={landingContainer}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-100px" }}
        >
          <motion.p
            variants={landingItem}
            className="text-center text-xs font-semibold uppercase tracking-widest mb-3"
            style={{ color: "var(--turquoise)" }}
          >
            Pricing
          </motion.p>
          <motion.h2
            variants={landingItem}
            className="text-center text-2xl sm:text-3xl font-display font-bold mb-4"
            style={{ color: "var(--text-primary)" }}
          >
            Simple, transparent pricing
          </motion.h2>
          <motion.p
            variants={landingItem}
            className="text-center text-sm mb-12"
            style={{ color: "var(--text-secondary)" }}
          >
            BYOK — bring your own API keys. You pay platform cost + your own AI usage.
          </motion.p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {PRICING_TIERS.map((tier) => (
              <motion.div
                key={tier.key}
                variants={landingItem}
                className="relative rounded-2xl p-6 flex flex-col"
                style={{
                  background: tier.popular
                    ? "linear-gradient(135deg, rgba(0, 212, 170, 0.08), rgba(15, 22, 38, 0.65))"
                    : "rgba(15, 22, 38, 0.65)",
                  border: tier.popular
                    ? "1px solid rgba(0, 212, 170, 0.3)"
                    : "1px solid rgba(255, 255, 255, 0.06)",
                }}
              >
                {tier.popular && (
                  <span
                    className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider"
                    style={{ background: "var(--turquoise)", color: "#0A0A0B" }}
                  >
                    Most Popular
                  </span>
                )}
                <div className="mb-4">
                  <tier.icon size={24} style={{ color: tier.popular ? "var(--turquoise)" : "var(--text-secondary)" }} />
                </div>
                <h3 className="text-xl font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                  {tier.name}
                </h3>
                <p className="text-xs mb-4" style={{ color: "var(--text-tertiary)" }}>
                  {tier.tagline}
                </p>
                <div className="mb-6">
                  <span className="text-4xl font-display font-bold" style={{ color: "var(--text-primary)" }}>
                    ${tier.price}
                  </span>
                  <span className="text-sm" style={{ color: "var(--text-tertiary)" }}>/mo</span>
                </div>
                <ul className="space-y-2.5 mb-6 flex-1">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                      <CheckCircle2 size={16} className="shrink-0 mt-0.5" style={{ color: "var(--turquoise)" }} />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/login"
                  className="block text-center py-2.5 rounded-xl text-sm font-semibold transition-all hover:brightness-110"
                  style={{
                    background: tier.popular
                      ? "linear-gradient(135deg, var(--turquoise), #00B894)"
                      : "rgba(255, 255, 255, 0.05)",
                    color: tier.popular ? "#0A0A0B" : "var(--text-primary)",
                    border: tier.popular ? "none" : "1px solid rgba(255,255,255,0.1)",
                  }}
                >
                  Get Started
                </Link>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </section>

      {/* Section 6: CTA */}
      <section id="cta">
        <motion.div
          className="max-w-3xl mx-auto px-6 pb-24 text-center"
          variants={landingContainer}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-100px" }}
        >
          <motion.div
            variants={landingItem}
            className="rounded-2xl p-10"
            style={{
              background: "linear-gradient(135deg, rgba(0, 212, 170, 0.08), rgba(0, 212, 170, 0.02))",
              border: "1px solid rgba(0, 212, 170, 0.15)",
            }}
          >
            <h2
              className="text-2xl sm:text-3xl font-display font-bold mb-3"
              style={{ color: "var(--text-primary)" }}
            >
              Ready to produce smarter?
            </h2>
            <p className="text-base mb-6" style={{ color: "var(--text-secondary)" }}>
              Start your 14-day free trial. Full Pro features, no credit card.
            </p>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 px-8 py-3 rounded-xl text-base font-semibold transition-all hover:brightness-110"
              style={{
                background: "linear-gradient(135deg, var(--turquoise), #00B894)",
                color: "#0A0A0B",
              }}
            >
              Get Started Free
              <ArrowRight size={18} />
            </Link>
          </motion.div>
        </motion.div>
      </section>

      {/* Section 7: Footer */}
      <footer
        className="py-8 text-center text-xs space-y-2"
        style={{ color: "var(--text-tertiary)", borderTop: "1px solid rgba(255,255,255,0.06)" }}
      >
        <p>StoryEngine — AI Video Production for YouTube Creators</p>
        <div className="flex items-center justify-center gap-4">
          <Link href="/terms" className="hover:underline">Terms of Service</Link>
          <span>&middot;</span>
          <Link href="/privacy" className="hover:underline">Privacy Policy</Link>
        </div>
      </footer>
    </div>
  );
}

/* ─── Dashboard (authenticated) ─── */

function Dashboard() {
  const router = useRouter();

  const { data: summary, isLoading: summaryLoading, error: summaryError } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: getDashboardSummary,
  });

  const { data: videos, isLoading: videosLoading, error: videosError } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  const { data: activity } = useQuery({
    queryKey: ["activity"],
    queryFn: () => getActivity(),
  });

  const { data: pendingReview } = useQuery({
    queryKey: ["pending-review"],
    queryFn: getPendingReview,
  });

  const { data: usage } = useQuery({
    queryKey: ["billing-usage"],
    queryFn: getUsage,
  });

  const isLoading = summaryLoading || videosLoading;

  // Derived stats
  const stats = useMemo(() => {
    if (!videos) return null;

    const now = new Date();
    const thisMonth = videos.filter((v) => {
      if (!v.created_at) return false;
      const d = new Date(v.created_at);
      return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
    });

    const inProduction = videos.filter(
      (v) => v.status && !COMPLETED_STATUSES.has(v.status)
    );

    const publishedWithCtr = videos.filter((v) => v.ctr !== null && v.ctr !== undefined);
    const avgCtr =
      publishedWithCtr.length > 0
        ? publishedWithCtr.reduce((sum, v) => sum + (v.ctr || 0), 0) / publishedWithCtr.length
        : 0;

    const totalCost = videos.reduce((sum, v) => sum + (v.total_cost || 0), 0);
    const avgCost = videos.length > 0 ? totalCost / videos.length : 0;

    return {
      videosThisMonth: thisMonth.length,
      inProduction: inProduction.length,
      avgCost,
      avgCtr,
    };
  }, [videos]);

  // Pipeline distribution
  const stageDistribution = useMemo(() => {
    if (!summary?.pipeline_distribution) return [];
    return PIPELINE_STAGES.map((stage) => ({
      ...stage,
      count: summary.pipeline_distribution[stage.key] || 0,
    }));
  }, [summary]);

  // Recently active videos
  const recentVideos = useMemo(() => {
    if (!videos) return [];
    return [...videos]
      .sort((a, b) => {
        const aDate = a.updated_at ? new Date(a.updated_at).getTime() : 0;
        const bDate = b.updated_at ? new Date(b.updated_at).getTime() : 0;
        return bDate - aDate;
      })
      .slice(0, 5);
  }, [videos]);

  // Recent activity entries
  const recentActivity = useMemo(() => {
    if (!activity) return [];
    return activity.slice(0, 8);
  }, [activity]);

  // Pending review count
  const pendingCount = useMemo(() => {
    if (!pendingReview) return 0;
    return (
      pendingReview.scripts.length +
      pendingReview.thumbnails.length +
      pendingReview.images.length +
      pendingReview.storyboards.length
    );
  }, [pendingReview]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  if (summaryError || videosError) {
    return (
      <div className="space-y-6">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Production Overview
        </h1>
        <ErrorCard
          message={(summaryError as Error)?.message || (videosError as Error)?.message || "Failed to load dashboard"}
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Production Overview
        </h1>
        <ActionButton icon={Plus} onClick={() => router.push("/pipeline")}>
          Create Video
        </ActionButton>
      </motion.div>

      {/* Stat Cards */}
      <motion.div variants={item} className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Videos This Month"
          value={stats?.videosThisMonth ?? 0}
          color="var(--turquoise)"
          icon={Film}
        />
        <StatCard
          label="In Production"
          value={stats?.inProduction ?? 0}
          color="var(--orange)"
          icon={Loader2}
        />
        <StatCard
          label="Avg Cost / Video"
          value={formatCost(stats?.avgCost ?? 0)}
          color="var(--gold)"
          icon={DollarSign}
        />
        <StatCard
          label="Avg CTR"
          value={stats?.avgCtr ? `${stats.avgCtr.toFixed(1)}%` : "--"}
          color="var(--green)"
          icon={TrendingUp}
        />
      </motion.div>

      {/* Usage Meter + Quick Actions */}
      {usage && (
        <motion.div variants={item} className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Videos this month */}
          <GlassCard className="!p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] uppercase tracking-wider font-semibold" style={{ color: "var(--text-secondary)" }}>
                Videos
              </span>
              <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                {usage.usage.videos_created} / {usage.limits.videos_per_month}
              </span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(100, (usage.usage.videos_created / Math.max(1, usage.limits.videos_per_month)) * 100)}%`,
                  background: (() => {
                    const ratio = usage.usage.videos_created / Math.max(1, usage.limits.videos_per_month);
                    if (ratio >= 0.95) return "var(--red)";
                    if (ratio >= 0.8) return "var(--orange)";
                    return "var(--turquoise)";
                  })(),
                }}
              />
            </div>
          </GlassCard>

          {/* Render minutes */}
          <GlassCard className="!p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] uppercase tracking-wider font-semibold" style={{ color: "var(--text-secondary)" }}>
                Render Minutes
              </span>
              <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                {usage.usage.render_minutes} / {usage.limits.render_minutes}
              </span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(100, (usage.usage.render_minutes / Math.max(1, usage.limits.render_minutes)) * 100)}%`,
                  background: (() => {
                    const ratio = usage.usage.render_minutes / Math.max(1, usage.limits.render_minutes);
                    if (ratio >= 0.95) return "var(--red)";
                    if (ratio >= 0.8) return "var(--orange)";
                    return "var(--turquoise)";
                  })(),
                }}
              />
            </div>
          </GlassCard>

          {/* Quick actions */}
          <GlassCard className="!p-4">
            <span className="text-[11px] uppercase tracking-wider font-semibold block mb-2" style={{ color: "var(--text-secondary)" }}>
              Quick Actions
            </span>
            <div className="flex gap-2">
              {pendingCount > 0 && (
                <button
                  onClick={() => router.push("/review")}
                  className="flex-1 py-2 rounded-lg text-xs font-medium transition-colors hover:brightness-110"
                  style={{ background: "rgba(255,120,73,0.15)", color: "var(--orange)" }}
                >
                  Review ({pendingCount})
                </button>
              )}
              <button
                onClick={() => router.push("/pipeline")}
                className="flex-1 py-2 rounded-lg text-xs font-medium transition-colors hover:brightness-110"
                style={{ background: "rgba(0,212,170,0.15)", color: "var(--turquoise)" }}
              >
                + New Video
              </button>
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Pipeline Stage Tracker */}
      {stageDistribution.length > 0 && (
        <motion.div variants={item}>
          <GlassCard className="!p-4">
            <h2
              className="text-[11px] font-semibold uppercase tracking-wider mb-4"
              style={{ color: "var(--text-secondary)" }}
            >
              Pipeline
            </h2>
            <div className="flex items-end gap-1 h-20">
              {stageDistribution.map((stage) => {
                const maxCount = Math.max(...stageDistribution.map((s) => s.count), 1);
                const height = stage.count > 0 ? Math.max(16, (stage.count / maxCount) * 100) : 4;

                return (
                  <button
                    key={stage.key}
                    onClick={() => router.push(`/pipeline?filter=${stage.key}`)}
                    className="flex-1 flex flex-col items-center gap-1 group cursor-pointer"
                    title={`${stage.label}: ${stage.count} video${stage.count !== 1 ? "s" : ""}`}
                  >
                    {stage.count > 0 && (
                      <span
                        className="text-[10px] font-mono font-bold opacity-0 group-hover:opacity-100 transition-opacity"
                        style={{ color: getStageColor(stage.key) }}
                      >
                        {stage.count}
                      </span>
                    )}
                    <div
                      className="w-full rounded-t transition-all group-hover:brightness-125"
                      style={{
                        height: `${height}%`,
                        minHeight: 4,
                        background: stage.count > 0 ? getStageColor(stage.key) : "rgba(255,255,255,0.05)",
                        opacity: stage.count > 0 ? 1 : 0.3,
                      }}
                    />
                    <span
                      className="text-[9px] font-medium truncate w-full text-center"
                      style={{ color: "var(--text-tertiary)" }}
                    >
                      {stage.label}
                    </span>
                  </button>
                );
              })}
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Two-column: Activity + Recent Videos */}
      <motion.div variants={item} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Activity Feed */}
        <GlassCard>
          <div className="flex items-center justify-between mb-4">
            <h2
              className="text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-secondary)" }}
            >
              Activity
            </h2>
            {pendingCount > 0 && (
              <StatusPill
                label={`${pendingCount} pending`}
                color="orange"
                size="sm"
              />
            )}
          </div>

          {recentActivity.length === 0 ? (
            <EmptyState
              icon={Sparkles}
              title="No activity yet"
              description="Create your first video to get started."
              actionLabel="Create Video"
              actionHref="/pipeline"
            />
          ) : (
            <div className="space-y-3">
              {recentActivity.map((a) => (
                <div
                  key={a.id}
                  className="flex items-start gap-3 cursor-pointer rounded-lg p-2 transition-colors"
                  style={{ background: "transparent" }}
                  onClick={() => a.video_id && router.push(`/pipeline/${a.video_id}`)}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "rgba(255,255,255,0.03)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                  }}
                >
                  <div
                    className="w-2 h-2 rounded-full mt-1.5 shrink-0"
                    style={{ background: ACTIVITY_DOT_COLOR[a.status] || "var(--text-tertiary)" }}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm" style={{ color: "var(--text-primary)" }}>
                      {a.message || a.bot_name}{" "}
                      {a.video_title && (
                        <span style={{ color: "var(--text-secondary)" }}>
                          — {a.video_title}
                        </span>
                      )}
                    </p>
                    <p className="text-[11px] font-mono mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                      {timeAgo(a.created_at)}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        {/* Recent Videos */}
        <GlassCard>
          <div className="flex items-center justify-between mb-4">
            <h2
              className="text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-secondary)" }}
            >
              Recent Videos
            </h2>
            <button
              onClick={() => router.push("/pipeline")}
              className="text-xs font-medium transition-colors hover:brightness-125"
              style={{ color: "var(--turquoise)" }}
            >
              View All
              <ChevronRight size={12} className="inline ml-0.5" />
            </button>
          </div>

          {recentVideos.length === 0 ? (
            <EmptyState
              icon={Film}
              title="No videos yet"
              description="Create your first video to get started."
              actionLabel="Create Video"
              actionHref="/pipeline"
            />
          ) : (
            <div className="space-y-2">
              {recentVideos.map((v) => {
                const progress = computeProgress(v.status);
                return (
                  <button
                    key={v.id}
                    onClick={() => router.push(`/pipeline/${v.id}`)}
                    className="w-full flex items-center gap-3 p-3 rounded-xl text-left transition-all duration-200"
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
                    <div className="flex-1 min-w-0">
                      <p
                        className="text-sm font-medium truncate"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {v.video_title || "Untitled"}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <StatusPill
                          label={getStageLabel(v.status || "")}
                          color={
                            COMPLETED_STATUSES.has(v.status || "")
                              ? "green"
                              : "turquoise"
                          }
                          size="sm"
                        />
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {timeAgo(v.updated_at)}
                        </span>
                      </div>
                    </div>
                    {/* Progress bar */}
                    <div className="w-20 shrink-0">
                      <div className="flex items-center justify-end gap-1.5 mb-1">
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {progress}%
                        </span>
                      </div>
                      <div
                        className="h-1 rounded-full overflow-hidden"
                        style={{ background: "rgba(255,255,255,0.06)" }}
                      >
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${progress}%`,
                            background:
                              progress === 100 ? "var(--green)" : "var(--turquoise)",
                          }}
                        />
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
