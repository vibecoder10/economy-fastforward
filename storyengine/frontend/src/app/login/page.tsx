"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/AuthProvider";
import { Spinner } from "@/components/ui/spinner";
import { getOnboardingStatus } from "@/lib/api";
import { humanizeError } from "@/lib/errors";

export default function LoginPage() {
  const { user, isLoading, loginWithEmail, register } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function redirectAfterAuth() {
    try {
      const status = await getOnboardingStatus();
      router.replace(status.completed ? "/" : "/onboarding"); // chat is the home screen
    } catch {
      // Default to onboarding when status check fails (e.g. missing DB columns)
      // A new user needs onboarding; a returning user will be redirected to dashboard
      // by the onboarding page itself once it detects completion.
      router.replace("/onboarding");
    }
  }

  useEffect(() => {
    if (!isLoading && user) {
      redirectAfterAuth();
    }
  }, [user, isLoading]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (isRegister) {
        await register(email, password, displayName);
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

  if (user) return null;

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
      </div>
    </div>
  );
}
