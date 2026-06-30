"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { Lock, Sparkles, X, AlertTriangle, Mail } from "lucide-react";
import { useAuth } from "./AuthProvider";
import { useQuery } from "@tanstack/react-query";
import { getSubscription, resendVerification } from "@/lib/api";
import { Sidebar } from "@/components/nav/sidebar";
import { BottomTabs } from "@/components/nav/bottom-tabs";
import { Spinner } from "@/components/ui/spinner";
import { PipelineNotificationProvider } from "@/components/notifications/PipelineNotificationProvider";

const PUBLIC_PATHS = ["/login", "/onboarding", "/pricing", "/forgot-password", "/reset-password", "/verify-email", "/terms", "/privacy", "/demo"];

// Routes that require Pro plan or above
const PRO_PATHS = ["/autopilot", "/learnings", "/competitors", "/discovery"];

function isPlanAtLeast(plan: string | undefined, required: "starter" | "pro" | "agency"): boolean {
  // "unlimited" is the comped / owner tier (mirrors backend rate_limit.py) and must
  // outrank every paid tier — without it, unlimited accounts fell through to 0 (free)
  // and got locked out of Pro features like Autopilot.
  const tiers: Record<string, number> = { free: 0, starter: 1, pro: 2, agency: 3, unlimited: 99 };
  return (tiers[plan || "free"] ?? 0) >= (tiers[required] ?? 0);
}

export function AuthenticatedShell({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isPublicPath = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  const isHome = pathname === "/";

  useEffect(() => {
    if (isLoading) return;
    if (!user && !isPublicPath && !isHome) {
      router.replace("/login");
    }
  }, [user, isLoading, isPublicPath, isHome, router]);

  // Public pages (login, pricing) render without shell
  if (isPublicPath) {
    return <div className="min-h-screen relative z-10">{children}</div>;
  }

  // Home page: no shell for unauthenticated visitors (landing page)
  if (isHome && !user && !isLoading) {
    return <div className="min-h-screen relative z-10">{children}</div>;
  }

  // Show loading while checking auth
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen relative z-10">
        <Spinner size="lg" />
      </div>
    );
  }

  // Not authenticated — will redirect via useEffect
  if (!user) return null;

  // Check plan gating for Pro-only routes
  const isProRoute = PRO_PATHS.some((p) => pathname.startsWith(p));
  const hasAccess = !isProRoute || isPlanAtLeast(user.plan, "pro");

  // Authenticated — full app shell
  return (
    <PipelineNotificationProvider>
      <div className="flex min-h-screen relative z-10">
        <Sidebar />
        <main className="flex-1 pb-16 md:pb-0 md:ml-60 overflow-x-hidden">
          <VerifyEmailBanner />
          <TrialBanner />
          <div className="mx-auto max-w-[1400px] px-4 pt-20 pb-6 sm:px-6 md:px-12 md:py-10">
            {hasAccess ? children : <UpgradePrompt />}
          </div>
        </main>
        <BottomTabs />
      </div>
    </PipelineNotificationProvider>
  );
}

function VerifyEmailBanner() {
  const { user } = useAuth();
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");

  // Only show for accounts that exist but haven't confirmed their email.
  // (email_verified is undefined on older sessions — only banner on explicit false.)
  if (!user || user.email_verified !== false) return null;

  async function resend() {
    setState("sending");
    try {
      await resendVerification();
      setState("sent");
    } catch {
      setState("idle");
    }
  }

  return (
    <div
      className="px-4 py-3 pl-16 flex flex-col items-stretch gap-3 sm:pl-4 sm:flex-row sm:items-center sm:justify-between"
      style={{
        background: "rgba(0, 212, 170, 0.08)",
        borderBottom: "1px solid rgba(0, 212, 170, 0.2)",
      }}
    >
      <div className="flex items-start gap-2 text-sm font-body sm:items-center" style={{ color: "var(--text-primary)" }}>
        <Mail size={16} className="mt-0.5 shrink-0 sm:mt-0" style={{ color: "var(--accent)" }} />
        <span className="leading-snug">Confirm your email to start creating videos. Check your inbox for the link.</span>
      </div>
      <button
        onClick={resend}
        disabled={state !== "idle"}
        className="w-full shrink-0 px-4 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 sm:w-auto sm:py-1.5"
        style={{ background: "var(--accent)", color: "#0A0A0B", opacity: state === "idle" ? 1 : 0.7 }}
      >
        {state === "sent" ? "Sent — check your inbox" : state === "sending" ? "Sending…" : "Resend email"}
      </button>
    </div>
  );
}

function TrialBanner() {
  const pathname = usePathname();
  const [dismissed, setDismissed] = useState(false);
  const { data: subscription } = useQuery({
    queryKey: ["subscription"],
    queryFn: getSubscription,
    refetchInterval: 60000,
  });

  // Don't show on pricing or login pages
  if (["/pricing", "/login"].some((p) => pathname.startsWith(p))) return null;
  if (!subscription) return null;

  const { trial_active, trial_days_remaining, plan } = subscription;
  const isFree = (plan || "free") === "free";

  // Trial expired banner (persistent, not dismissible)
  if (!trial_active && isFree) {
    return (
      <div
        className="px-4 py-3 flex items-center justify-between gap-3"
        style={{
          background: "rgba(255, 77, 106, 0.08)",
          borderBottom: "1px solid rgba(255, 77, 106, 0.2)",
        }}
      >
        <div className="flex items-center gap-2 text-sm font-body" style={{ color: "var(--red)" }}>
          <AlertTriangle size={16} />
          <span>Your trial has ended. Upgrade to Pro to unlock Autopilot, Analytics, and more.</span>
        </div>
        <Link
          href="/pricing"
          className="shrink-0 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all hover:brightness-110"
          style={{
            background: "linear-gradient(135deg, var(--gold), #B8922E)",
            color: "#0A0A0B",
          }}
        >
          Upgrade
        </Link>
      </div>
    );
  }

  // Trial expiring soon banner (dismissible, shows when <= 3 days left)
  if (trial_active && trial_days_remaining <= 3 && !dismissed) {
    return (
      <div
        className="px-4 py-3 flex items-center justify-between gap-3"
        style={{
          background: "rgba(212, 168, 82, 0.08)",
          borderBottom: "1px solid rgba(212, 168, 82, 0.2)",
        }}
      >
        <div className="flex items-center gap-2 text-sm font-body" style={{ color: "var(--gold)" }}>
          <Sparkles size={16} />
          <span>Your Pro trial ends in {trial_days_remaining} day{trial_days_remaining !== 1 ? "s" : ""}. Upgrade now to keep all features.</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Link
            href="/pricing"
            className="px-4 py-1.5 rounded-lg text-xs font-semibold transition-all hover:brightness-110"
            style={{
              background: "linear-gradient(135deg, var(--gold), #B8922E)",
              color: "#0A0A0B",
            }}
          >
            Upgrade
          </Link>
          <button onClick={() => setDismissed(true)} style={{ color: "var(--text-tertiary)" }}>
            <X size={16} />
          </button>
        </div>
      </div>
    );
  }

  return null;
}

function UpgradePrompt() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
      <div
        className="w-20 h-20 rounded-full flex items-center justify-center mb-6"
        style={{ background: "rgba(212, 168, 82, 0.15)" }}
      >
        <Lock size={36} style={{ color: "var(--gold)" }} />
      </div>
      <h1 className="text-3xl font-display font-bold mb-3" style={{ color: "var(--text-primary)" }}>
        Pro Feature
      </h1>
      <p className="text-base mb-8 max-w-md" style={{ color: "var(--text-secondary)" }}>
        Autopilot, Analytics, Learnings, Competitors, and Discovery are available on the
        Pro plan. Upgrade to unlock AI-powered intelligence that makes your channel smarter
        over time.
      </p>
      <Link
        href="/pricing"
        className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-sm transition-all hover:brightness-110"
        style={{
          background: "linear-gradient(135deg, var(--gold), #B8922E)",
          color: "#0A0A0B",
        }}
      >
        <Sparkles size={16} />
        Upgrade to Pro
      </Link>
      <p className="text-xs mt-4" style={{ color: "var(--text-tertiary)" }}>
        Starting at $40/month
      </p>
    </div>
  );
}

export { isPlanAtLeast, PRO_PATHS };
