"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import {
  Film,
  TrendingUp,
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
  CheckCircle2,
  Clock,
  Video,
} from "lucide-react";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/components/auth/AuthProvider";
import { ChatHome } from "@/components/chat/ChatHome";

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

  // Authenticated: the chat-first creative producer is now the home screen.
  // The full dashboard lives at /dashboard (and in the sidebar).
  return <ChatHome />;
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
    name: "Basic",
    price: 50,
    icon: Zap,
    tagline: "Everything you need to make videos",
    features: ["Full 18-stage pipeline", "12 videos/month", "All visual styles", "Review & edit every stage"],
  },
  {
    key: "pro",
    name: "Pro",
    price: 100,
    icon: Crown,
    tagline: "The full AI engine, on autopilot",
    popular: true,
    features: ["Everything in Basic", "30 videos/month", "Autopilot mode", "Analytics & learnings", "Competitor analysis", "Discovery ideas"],
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
          7-day free trial. No credit card required. BYOK — bring your own API keys.
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
              Start your 7-day free trial. Full features, no credit card.
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
