"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import Link from "next/link";
import { Lock, Sparkles } from "lucide-react";
import { useAuth } from "./AuthProvider";
import { Sidebar } from "@/components/nav/sidebar";
import { BottomTabs } from "@/components/nav/bottom-tabs";
import { Spinner } from "@/components/ui/spinner";

const PUBLIC_PATHS = ["/login", "/onboarding", "/pricing", "/forgot-password", "/reset-password"];

// Routes that require Pro plan or above
const PRO_PATHS = ["/autopilot", "/analytics", "/learnings", "/competitors", "/discovery"];

function isPlanAtLeast(plan: string | undefined, required: "starter" | "pro" | "agency"): boolean {
  const tiers: Record<string, number> = { free: 0, starter: 1, pro: 2, agency: 3 };
  return (tiers[plan || "free"] ?? 0) >= (tiers[required] ?? 0);
}

export function AuthenticatedShell({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isPublicPath = PUBLIC_PATHS.some((p) => pathname.startsWith(p));

  useEffect(() => {
    if (isLoading) return;
    if (!user && !isPublicPath) {
      router.replace("/login");
    }
  }, [user, isLoading, isPublicPath, router]);

  // Public pages (login) render without shell
  if (isPublicPath) {
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
    <div className="flex min-h-screen relative z-10">
      <Sidebar />
      <main className="flex-1 pb-16 md:pb-0 md:ml-60 overflow-x-hidden">
        <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 md:px-12 md:py-10">
          {hasAccess ? children : <UpgradePrompt />}
        </div>
      </main>
      <BottomTabs />
    </div>
  );
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
