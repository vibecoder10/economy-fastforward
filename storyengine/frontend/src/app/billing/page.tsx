"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import Link from "next/link";
import {
  Crown, Zap, CheckCircle2, X, CreditCard, Loader2,
  BarChart3, Film, ArrowRight, Clock, Shield,
} from "lucide-react";
import {
  getSubscription, createCheckout, createBillingPortal, getUsage,
} from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { timeAgo } from "@/lib/utils";

const TRUSTED_STRIPE_DOMAINS = [
  "https://checkout.stripe.com",
  "https://billing.stripe.com",
];

function isStripeUrl(url: string): boolean {
  return TRUSTED_STRIPE_DOMAINS.some((d) => url.startsWith(d));
}

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

const PLANS = [
  {
    key: "starter",
    name: "Basic",
    price: 50,
    icon: Zap,
    color: "var(--turquoise)",
    videos: 12,
    renderMin: 60,
    features: [
      { text: "Full production pipeline", included: true },
      { text: "12 videos/month", included: true },
      { text: "All visual styles", included: true },
      { text: "Review & edit every stage", included: true },
      { text: "Autopilot", included: false },
      { text: "Analytics & Learnings", included: false },
      { text: "Competitor scraping", included: false },
      { text: "Discovery ideas", included: false },
    ],
  },
  {
    key: "pro",
    name: "Pro",
    price: 100,
    icon: Crown,
    color: "var(--gold)",
    popular: true,
    videos: 30,
    renderMin: 180,
    features: [
      { text: "Everything in Basic", included: true },
      { text: "30 videos/month", included: true },
      { text: "Autopilot mode", included: true },
      { text: "Analytics & Learnings", included: true },
      { text: "Competitor scraping", included: true },
      { text: "Discovery ideas", included: true },
    ],
  },
];

export default function BillingPage() {
  const toast = useToast();
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);

  const { data: subscription, isLoading: subLoading } = useQuery({
    queryKey: ["subscription"],
    queryFn: getSubscription,
  });

  const { data: usage } = useQuery({
    queryKey: ["usage"],
    queryFn: getUsage,
  });

  const handleSubscribe = async (planKey: string) => {
    setCheckoutLoading(planKey);
    try {
      const res = await createCheckout(planKey, `${window.location.origin}/billing?success=1`, `${window.location.origin}/billing`);
      if (!isStripeUrl(res.checkout_url)) {
        toast.error("Invalid checkout URL. Please contact support.");
        setCheckoutLoading(null);
        return;
      }
      window.location.href = res.checkout_url;
    } catch {
      toast.error("Failed to start checkout. Is Stripe configured?");
      setCheckoutLoading(null);
    }
  };

  const handleManageSubscription = async () => {
    setPortalLoading(true);
    try {
      const res = await createBillingPortal(`${window.location.origin}/billing`);
      if (!isStripeUrl(res.portal_url)) {
        toast.error("Invalid billing portal URL. Please contact support.");
        setPortalLoading(false);
        return;
      }
      window.location.href = res.portal_url;
    } catch {
      toast.error("Failed to open billing portal. Is Stripe configured?");
      setPortalLoading(false);
    }
  };

  if (subLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  const currentPlan = subscription?.plan || "free";
  const isTrialActive = subscription?.trial_active ?? false;
  const trialDays = subscription?.trial_days_remaining ?? 0;

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="max-w-4xl mx-auto px-4 py-8 space-y-8"
    >
      {/* Header */}
      <motion.div variants={item}>
        <h1 className="text-3xl font-display font-bold mb-1" style={{ color: "var(--text-primary)" }}>
          Billing & Plan
        </h1>
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          Manage your subscription, usage, and payment method.
        </p>
      </motion.div>

      {/* Current Plan Card */}
      <motion.div variants={item}>
        <GlassCard className="p-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center"
                style={{ background: "var(--gold-dim)" }}
              >
                <Crown size={24} style={{ color: "var(--gold)" }} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-semibold capitalize" style={{ color: "var(--text-primary)" }}>
                    {currentPlan} Plan
                  </h2>
                  {subscription?.stripe_status && (
                    <span
                      className="text-[10px] font-mono px-2 py-0.5 rounded-full"
                      style={{
                        background: subscription.stripe_status === "active" ? "var(--green-dim)" : "var(--gold-dim)",
                        color: subscription.stripe_status === "active" ? "var(--green)" : "var(--gold)",
                      }}
                    >
                      {subscription.stripe_status}
                    </span>
                  )}
                </div>
                {isTrialActive && (
                  <p className="text-xs mt-0.5" style={{ color: trialDays <= 3 ? "var(--warning)" : "var(--turquoise)" }}>
                    <Clock size={11} className="inline mr-1" />
                    Pro Trial — {trialDays} day{trialDays !== 1 ? "s" : ""} remaining
                  </p>
                )}
                {!isTrialActive && currentPlan === "free" && (
                  <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                    Trial ended. Upgrade for full access.
                  </p>
                )}
              </div>
            </div>
            {subscription?.has_subscription && (
              <button
                onClick={handleManageSubscription}
                disabled={portalLoading}
                className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all hover:brightness-110"
                style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
              >
                {portalLoading ? <Loader2 size={14} className="animate-spin" /> : <CreditCard size={14} />}
                Manage Subscription
              </button>
            )}
          </div>
        </GlassCard>
      </motion.div>

      {/* Usage */}
      {usage && (
        <motion.div variants={item}>
          <GlassCard className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
                This Month&apos;s Usage
              </h3>
              {usage.period_start && (
                <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                  Since {new Date(usage.period_start).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                </span>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {[
                { label: "Videos Created", used: usage.usage.videos_created, limit: usage.limits.videos_per_month, icon: Film },
                { label: "Render Minutes", used: Math.round(usage.usage.render_minutes), limit: usage.limits.render_minutes, icon: BarChart3 },
              ].map(({ label, used, limit, icon: Icon }) => {
                const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
                const barColor = pct >= 90 ? "var(--red)" : pct >= 70 ? "var(--gold)" : "var(--turquoise)";
                return (
                  <div key={label}>
                    <div className="flex items-center gap-2 mb-2">
                      <Icon size={14} style={{ color: "var(--text-tertiary)" }} />
                      <span className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>{label}</span>
                    </div>
                    <div className="flex items-baseline gap-1.5 mb-2">
                      <span className="text-2xl font-display font-bold" style={{ color: barColor }}>{used}</span>
                      <span className="text-sm" style={{ color: "var(--text-tertiary)" }}>/ {limit}</span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
                      <motion.div
                        className="h-full rounded-full"
                        style={{ background: barColor }}
                        initial={{ width: 0 }}
                        animate={{ width: `${pct}%` }}
                        transition={{ duration: 0.8, ease: "easeOut" }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Plan Comparison */}
      <motion.div variants={item}>
        <h3 className="text-[11px] font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
          {subscription?.has_subscription ? "Change Plan" : "Choose a Plan"}
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {PLANS.map((plan) => {
            const isCurrent = currentPlan === plan.key || subscription?.stripe_plan === plan.key;
            const Icon = plan.icon;
            return (
              <GlassCard
                key={plan.key}
                className="p-5 relative overflow-hidden"
                style={isCurrent ? { border: `1px solid ${plan.color}` } : undefined}
              >
                {plan.popular && (
                  <div
                    className="absolute top-0 right-0 text-[9px] font-semibold uppercase tracking-wider px-3 py-1 rounded-bl-lg"
                    style={{ background: plan.color, color: "var(--bg-void)" }}
                  >
                    Most Popular
                  </div>
                )}
                <div className="flex items-center gap-2 mb-3">
                  <Icon size={18} style={{ color: isCurrent ? plan.color : "var(--text-secondary)" }} />
                  <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{plan.name}</span>
                </div>
                <p className="text-3xl font-display font-bold mb-1" style={{ color: "var(--text-primary)" }}>
                  ${plan.price}<span className="text-xs font-body font-normal" style={{ color: "var(--text-tertiary)" }}>/mo</span>
                </p>
                <p className="text-[10px] mb-4" style={{ color: "var(--text-tertiary)" }}>
                  {plan.videos} videos · {plan.renderMin} render min
                </p>
                <ul className="space-y-2 mb-5">
                  {plan.features.map((f) => (
                    <li key={f.text} className="text-xs flex items-center gap-2" style={{ color: f.included ? "var(--text-secondary)" : "var(--text-tertiary)" }}>
                      {f.included ? (
                        <CheckCircle2 size={13} style={{ color: "var(--turquoise)" }} />
                      ) : (
                        <X size={13} style={{ color: "var(--text-tertiary)", opacity: 0.5 }} />
                      )}
                      {f.text}
                    </li>
                  ))}
                </ul>
                {isCurrent ? (
                  <div
                    className="text-center text-xs font-medium py-2.5 rounded-lg"
                    style={{ background: `color-mix(in srgb, ${plan.color} 15%, transparent)`, color: plan.color }}
                  >
                    Current Plan
                  </div>
                ) : (
                  <button
                    onClick={() => handleSubscribe(plan.key)}
                    disabled={checkoutLoading !== null}
                    className="w-full py-2.5 rounded-lg text-xs font-semibold transition-all hover:brightness-110 flex items-center justify-center gap-1.5"
                    style={{ background: plan.color, color: "var(--bg-void)" }}
                  >
                    {checkoutLoading === plan.key ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <>
                        {currentPlan === "free" || !subscription?.has_subscription ? "Subscribe" : "Switch"}
                        <ArrowRight size={13} />
                      </>
                    )}
                  </button>
                )}
              </GlassCard>
            );
          })}
        </div>
      </motion.div>

      {/* BYOK Note */}
      <motion.div variants={item}>
        <GlassCard className="p-5">
          <div className="flex items-start gap-3">
            <Shield size={18} style={{ color: "var(--turquoise)", marginTop: 2, flexShrink: 0 }} />
            <div>
              <h4 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                Bring Your Own Keys (BYOK)
              </h4>
              <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                You provide your own API keys (Anthropic, ElevenLabs, Kie.ai, Google).
                Your subscription covers the platform — AI costs are separate and go directly to the providers.{" "}
                <Link href="/settings/keys" className="underline" style={{ color: "var(--turquoise)" }}>
                  Manage API Keys →
                </Link>
              </p>
            </div>
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
