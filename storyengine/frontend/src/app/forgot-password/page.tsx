"use client";

import { useState } from "react";
import { forgotPassword } from "@/lib/api";
import { Spinner } from "@/components/ui/spinner";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await forgotPassword(email);
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

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
          Reset Password
        </h1>
        <p
          className="text-sm mb-8 text-center"
          style={{ color: "var(--text-secondary)" }}
        >
          {sent
            ? "Check your email for a reset link"
            : "Enter your email to receive a reset link"}
        </p>

        {sent ? (
          <div className="flex flex-col items-center gap-4">
            <div
              className="w-14 h-14 rounded-full flex items-center justify-center"
              style={{ background: "rgba(0,212,170,0.15)" }}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <p className="text-xs text-center" style={{ color: "var(--text-secondary)" }}>
              If an account exists with that email, you will receive a password reset link.
            </p>
            <a
              href="/login"
              className="text-sm font-semibold"
              style={{ color: "var(--accent)" }}
            >
              Back to login
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
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
              {submitting ? <Spinner size="sm" /> : "Send Reset Link"}
            </button>
          </form>
        )}

        {error && (
          <p className="text-xs mt-4 text-center" style={{ color: "var(--error)" }}>
            {error}
          </p>
        )}

        {!sent && (
          <p className="text-xs mt-6 text-center">
            <a href="/login" style={{ color: "var(--text-secondary)" }}>
              Back to login
            </a>
          </p>
        )}
      </div>
    </div>
  );
}
