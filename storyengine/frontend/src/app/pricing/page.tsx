"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Zap,
  Crown,
  Building2,
  CheckCircle2,
  X,
  ArrowRight,
  Sparkles,
  Brain,
  BarChart3,
  Users,
  Film,
  Shield,
} from "lucide-react";
import { useAuth } from "@/components/auth/AuthProvider";
import { createCheckout } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

const PLANS = [
  {
    key: "starter",
    name: "Starter",
    price: 25,
    icon: Zap,
    tagline: "For solo creators getting started",
    features: [
      { text: "Full video pipeline (18 stages)", included: true },
      { text: "1 channel", included: true },
      { text: "4 videos per month", included: true },
      { text: "Manual mode only", included: true },
      { text: "1 visual style", included: true },
      { text: "Basic settings", included: true },
      { text: "Autopilot", included: false },
      { text: "Analytics & Learnings", included: false },
      { text: "Competitor scraping", included: false },
      { text: "Team management", included: false },
    ],
  },
  {
    key: "pro",
    name: "Pro",
    price: 40,
    icon: Crown,
    tagline: "For creators who want AI-powered growth",
    popular: true,
    features: [
      { text: "Full video pipeline (18 stages)", included: true },
      { text: "1 channel", included: true },
      { text: "15 videos per month", included: true },
      { text: "Autopilot mode", included: true },
      { text: "3 visual styles", included: true },
      { text: "Analytics dashboard", included: true },
      { text: "Learnings & patterns", included: true },
      { text: "Competitor analysis", included: true },
      { text: "Discovery ideas", included: true },
      { text: "Team management", included: false },
    ],
  },
  {
    key: "agency",
    name: "Agency",
    price: 75,
    icon: Building2,
    tagline: "For teams managing multiple channels",
    features: [
      { text: "Full video pipeline (18 stages)", included: true },
      { text: "Multi-channel support", included: true },
      { text: "50 videos per month", included: true },
      { text: "Autopilot mode", included: true },
      { text: "All visual styles", included: true },
      { text: "Analytics dashboard", included: true },
      { text: "Learnings & patterns", included: true },
      { text: "Competitor analysis", included: true },
      { text: "Discovery ideas", included: true },
      { text: "Team (3 seats)", included: true },
    ],
  },
] as const;

const VALUE_PROPS = [
  { icon: Film, title: "Topic in, video out", desc: "18-stage pipeline: research, script, voice, images, storyboards, thumbnail, render, upload." },
  { icon: Brain, title: "Gets smarter over time", desc: "Every video teaches the system what works for your audience. CTR improves automatically." },
  { icon: BarChart3, title: "Performance intelligence", desc: "CTR monitoring, post-mortems, competitor analysis, and pattern learnings." },
  { icon: Shield, title: "You stay in control", desc: "Review and approve every stage. Edit scripts inline. Pick your visual style." },
];

function isStripeUrl(url: string): boolean {
  return url.startsWith("https://checkout.stripe.com") || url.startsWith("https://billing.stripe.com");
}

export default function PricingPage() {
  const { user } = useAuth();
  const toast = useToast();
  const router = useRouter();
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);

  async function handleSubscribe(planKey: string) {
    if (!user) {
      router.push("/login");
      return;
    }
    setCheckoutLoading(planKey);
    try {
      const res = await createCheckout(planKey, `${window.location.origin}/settings`, `${window.location.origin}/pricing`);
      if (!isStripeUrl(res.checkout_url)) {
        toast.error("Invalid checkout URL — redirect blocked");
        setCheckoutLoading(null);
        return;
      }
      window.location.href = res.checkout_url;
    } catch {
      setCheckoutLoading(null);
    }
  }

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-void)" }}>
      {/* Navigation bar */}
      <nav className="flex items-center justify-between px-6 py-4 max-w-6xl mx-auto">
        <Link href="/" className="flex items-center gap-2">
          <Sparkles size={20} style={{ color: "var(--turquoise)" }} />
          <span className="font-display font-bold text-lg" style={{ color: "var(--text-primary)" }}>
            StoryEngine
          </span>
        </Link>
        <div className="flex items-center gap-3">
          {user ? (
            <Link
              href="/dashboard"
              className="px-4 py-2 rounded-lg text-sm font-medium transition-all hover:brightness-110"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              Dashboard
            </Link>
          ) : (
            <>
              <Link
                href="/login"
                className="px-4 py-2 rounded-lg text-sm font-medium"
                style={{ color: "var(--text-secondary)" }}
              >
                Sign in
              </Link>
              <Link
                href="/login"
                className="px-4 py-2 rounded-lg text-sm font-medium transition-all hover:brightness-110"
                style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
              >
                Get Started
              </Link>
            </>
          )}
        </div>
      </nav>

      {/* Hero */}
      <motion.div
        variants={container}
        initial="hidden"
        animate="show"
        className="max-w-6xl mx-auto px-6 pt-12 pb-16 text-center"
      >
        <motion.h1
          variants={item}
          className="text-4xl sm:text-5xl font-display font-bold mb-4"
          style={{ color: "var(--text-primary)" }}
        >
          Simple pricing for{" "}
          <span style={{ color: "var(--turquoise)" }}>serious creators</span>
        </motion.h1>
        <motion.p
          variants={item}
          className="text-lg max-w-xl mx-auto mb-4"
          style={{ color: "var(--text-secondary)" }}
        >
          AI-powered video production that gets smarter with every video you publish.
          Bring your own API keys. Pay only for the platform.
        </motion.p>
        <motion.p
          variants={item}
          className="text-xs font-mono"
          style={{ color: "var(--text-tertiary)" }}
        >
          BYOK — You bring your own API keys (Anthropic, ElevenLabs, Kie.ai). Platform cost is separate from AI cost.
        </motion.p>
      </motion.div>

      {/* Plan cards */}
      <motion.div
        variants={container}
        initial="hidden"
        animate="show"
        className="max-w-5xl mx-auto px-6 grid grid-cols-1 md:grid-cols-3 gap-6 mb-20"
      >
        {PLANS.map((plan) => {
          const Icon = plan.icon;
          const isPopular = "popular" in plan && plan.popular;
          return (
            <motion.div
              key={plan.key}
              variants={item}
              className="relative rounded-2xl p-6 flex flex-col"
              style={{
                background: "rgba(15,22,38,0.65)",
                backdropFilter: "blur(24px)",
                border: isPopular ? "1px solid var(--turquoise)" : "1px solid var(--border-subtle)",
              }}
            >
              {isPopular && (
                <div
                  className="absolute -top-3 left-1/2 -translate-x-1/2 px-4 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider"
                  style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                >
                  Most Popular
                </div>
              )}

              <div className="flex items-center gap-2 mb-2">
                <Icon size={20} style={{ color: isPopular ? "var(--turquoise)" : "var(--text-secondary)" }} />
                <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  {plan.name}
                </span>
              </div>

              <p className="text-xs mb-4" style={{ color: "var(--text-tertiary)" }}>
                {plan.tagline}
              </p>

              <div className="flex items-baseline gap-1 mb-6">
                <span className="text-4xl font-display font-bold" style={{ color: "var(--text-primary)" }}>
                  ${plan.price}
                </span>
                <span className="text-sm" style={{ color: "var(--text-tertiary)" }}>
                  /month
                </span>
              </div>

              <ul className="space-y-2.5 mb-8 flex-1">
                {plan.features.map((f) => (
                  <li key={f.text} className="flex items-start gap-2 text-xs">
                    {f.included ? (
                      <CheckCircle2
                        size={14}
                        className="mt-0.5 shrink-0"
                        style={{ color: "var(--turquoise)" }}
                      />
                    ) : (
                      <X
                        size={14}
                        className="mt-0.5 shrink-0"
                        style={{ color: "var(--text-tertiary)" }}
                      />
                    )}
                    <span style={{ color: f.included ? "var(--text-secondary)" : "var(--text-tertiary)" }}>
                      {f.text}
                    </span>
                  </li>
                ))}
              </ul>

              <button
                onClick={() => handleSubscribe(plan.key)}
                disabled={checkoutLoading !== null}
                className="w-full py-3 rounded-xl text-sm font-semibold transition-all hover:brightness-110 flex items-center justify-center gap-2"
                style={
                  isPopular
                    ? { background: "var(--turquoise)", color: "var(--bg-void)" }
                    : { background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }
                }
              >
                {checkoutLoading === plan.key ? (
                  <span className="animate-spin inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full" />
                ) : (
                  <>
                    {user ? "Subscribe" : "Get Started"}
                    <ArrowRight size={14} />
                  </>
                )}
              </button>
            </motion.div>
          );
        })}
      </motion.div>

      {/* Value propositions */}
      <motion.div
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true }}
        className="max-w-5xl mx-auto px-6 pb-20"
      >
        <motion.h2
          variants={item}
          className="text-2xl font-display font-bold text-center mb-10"
          style={{ color: "var(--text-primary)" }}
        >
          Why creators choose StoryEngine
        </motion.h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          {VALUE_PROPS.map((vp) => {
            const VpIcon = vp.icon;
            return (
              <motion.div
                key={vp.title}
                variants={item}
                className="rounded-xl p-5"
                style={{
                  background: "rgba(15,22,38,0.45)",
                  border: "1px solid var(--border-subtle)",
                }}
              >
                <div className="flex items-center gap-3 mb-2">
                  <div
                    className="w-9 h-9 rounded-lg flex items-center justify-center"
                    style={{ background: "var(--turquoise-dim)" }}
                  >
                    <VpIcon size={18} style={{ color: "var(--turquoise)" }} />
                  </div>
                  <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                    {vp.title}
                  </h3>
                </div>
                <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {vp.desc}
                </p>
              </motion.div>
            );
          })}
        </div>
      </motion.div>

      {/* FAQ / CTA */}
      <div className="max-w-3xl mx-auto px-6 pb-20 text-center">
        <p className="text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
          All plans include a 14-day free trial. No credit card required.
        </p>
        <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
          Questions?{" "}
          <Link href="/login" className="underline" style={{ color: "var(--turquoise)" }}>
            Sign up
          </Link>{" "}
          and try it free, or reach out at support@storyengine.ai
        </p>
      </div>
    </div>
  );
}
