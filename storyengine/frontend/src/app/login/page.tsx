"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/AuthProvider";
import { Spinner } from "@/components/ui/spinner";
import { humanizeError } from "@/lib/errors";

export default function LoginPage() {
  const { user, isLoading, loginWithEmail, register } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [betaCode, setBetaCode] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [betaNotice, setBetaNotice] = useState<{ applied: boolean } | null>(null);

  // Chat is the home screen and runs onboarding itself — ChatHome auto-starts the
  // guided setup (intent → API key → channel → …) for brand-new users and shows the
  // normal welcome for returning ones. So everyone lands on "/"; we no longer split
  // new users off to the legacy /onboarding wizard (which bypassed the key step).
  //
  // Exception: when a beta code notice is pending, hold off the redirect for a
  // moment so the user actually sees whether the code applied — otherwise this
  // effect fires the instant `user` is set and the notice never paints.
  useEffect(() => {
    if (!isLoading && user && !betaNotice) {
      router.replace("/");
    }
  }, [user, isLoading, betaNotice]);

  useEffect(() => {
    if (user && betaNotice) {
      const t = setTimeout(() => router.replace("/"), 2200);
      return () => clearTimeout(t);
    }
  }, [user, betaNotice]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBetaNotice(null);
    setSubmitting(true);
    try {
      if (isRegister) {
        const trimmedCode = betaCode.trim();
        const { betaApplied } = await register(email, password, displayName, trimmedCode || undefined);
        if (trimmedCode) {
          setBetaNotice({ applied: betaApplied });
        }
      } else {
        await loginWithEmail(email, password);
      }
      // redirect handled by useEffect when user state updates
    } catch (err) {
      setError(humanizeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spinner size="lg" />
      </div>
    );
  }

  // Once signed in we normally render nothing (the redirect effect above takes
  // over) — except right after a beta-code registration, where we hold on this
  // screen just long enough to show whether the code applied.
  if (user && !betaNotice) return null;

  return (
    <div className="flex items-center justify-center min-h-screen px-4">
      <div
        className="w-full max-w-sm p-8 rounded-2xl"
        style={{
          background: "rgba(15,22,38,0.65)",
          border: "1px solid rgba(0,212,170,0.12)",
          backdropFilter: "blur(24px)",
        }}
      >
        <h1
          className="font-display text-3xl mb-2 text-center"
          style={{ color: "var(--text-primary)" }}
        >
          StoryEngine
        </h1>

        {user && betaNotice ? (
          <>
            <p
              className="text-sm mb-2 text-center"
              style={{ color: "var(--text-secondary)" }}
            >
              Account created
            </p>
            <p
              className="text-sm mt-4 text-center"
              style={{ color: betaNotice.applied ? "var(--accent)" : "var(--text-secondary)" }}
            >
              {betaNotice.applied
                ? "Beta code applied — 2 months free 🎉"
                : "That beta code wasn't applied — you're on the standard 7-day trial."}
            </p>
            <p
              className="text-xs mt-6 text-center"
              style={{ color: "var(--text-secondary)" }}
            >
              Taking you in…
            </p>
          </>
        ) : (
          <>
            <p
              className="text-sm mb-8 text-center"
              style={{ color: "var(--text-secondary)" }}
            >
              {isRegister ? "Create your account" : "Sign in to your account"}
            </p>

            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              {isRegister && (
                <input
                  type="text"
                  placeholder="Display name"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg text-sm outline-none"
                  style={{
                    background: "rgba(255,255,255,0.06)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    color: "var(--text-primary)",
                  }}
                />
              )}
              {isRegister && (
                <input
                  type="text"
                  placeholder="Beta code (optional)"
                  value={betaCode}
                  onChange={(e) => setBetaCode(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg text-sm outline-none"
                  style={{
                    background: "rgba(255,255,255,0.06)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    color: "var(--text-primary)",
                  }}
                />
              )}
              <input
                type="email"
                placeholder="Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full px-4 py-3 rounded-lg text-sm outline-none"
                style={{
                  background: "rgba(255,255,255,0.06)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  color: "var(--text-primary)",
                }}
              />
              <input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                className="w-full px-4 py-3 rounded-lg text-sm outline-none"
                style={{
                  background: "rgba(255,255,255,0.06)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  color: "var(--text-primary)",
                }}
              />

              {!isRegister && (
                <a
                  href="/forgot-password"
                  className="text-xs self-end -mt-2"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Forgot password?
                </a>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="w-full py-3 rounded-lg text-sm font-semibold transition-opacity"
                style={{
                  background: "var(--accent)",
                  color: "#000",
                  opacity: submitting ? 0.6 : 1,
                }}
              >
                {submitting ? (
                  <Spinner size="sm" />
                ) : isRegister ? (
                  "Create Account"
                ) : (
                  "Sign In"
                )}
              </button>
            </form>

            {error && (
              <p
                className="text-xs mt-4 text-center"
                style={{ color: "var(--error)" }}
              >
                {error}
              </p>
            )}

            <p
              className="text-xs mt-6 text-center cursor-pointer"
              style={{ color: "var(--text-secondary)" }}
              onClick={() => {
                setIsRegister(!isRegister);
                setError(null);
              }}
            >
              {isRegister
                ? "Already have an account? Sign in"
                : "Don't have an account? Create one"}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
