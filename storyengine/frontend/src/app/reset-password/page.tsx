"use client";

import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { resetPassword } from "@/lib/api";
import { Spinner } from "@/components/ui/spinner";
import { humanizeError } from "@/lib/errors";

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setSubmitting(true);
    try {
      await resetPassword(token, newPassword);
      setSuccess(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("expired")) {
        setError("This reset link has expired. Please request a new one.");
      } else if (msg.includes("Invalid") || msg.includes("invalid")) {
        setError("This reset link is invalid. Please request a new one.");
      } else if (msg.includes("already been used")) {
        setError("This reset link has already been used. Please request a new one.");
      } else {
        setError(humanizeError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <div className="flex items-center justify-center min-h-screen px-4">
        <div
          className="w-full max-w-sm p-8 rounded-2xl text-center"
          style={{
            background: "rgba(15,22,38,0.65)",
            border: "1px solid rgba(0,212,170,0.12)",
            backdropFilter: "blur(24px)",
          }}
        >
          <p className="text-sm mb-4" style={{ color: "var(--error)" }}>
            Missing reset token. Please use the link from your email.
          </p>
          <a
            href="/forgot-password"
            className="text-sm font-semibold"
            style={{ color: "var(--accent)" }}
          >
            Request a new reset link
          </a>
        </div>
      </div>
    );
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
          New Password
        </h1>
        <p
          className="text-sm mb-8 text-center"
          style={{ color: "var(--text-secondary)" }}
        >
          {success ? "Your password has been updated" : "Enter your new password"}
        </p>

        {success ? (
          <div className="flex flex-col items-center gap-4">
            <div
              className="w-14 h-14 rounded-full flex items-center justify-center"
              style={{ background: "rgba(0,212,170,0.15)" }}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
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
              type="password"
              placeholder="New password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
              className="w-full px-4 py-3 rounded-lg text-sm outline-none"
              style={{
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.1)",
                color: "var(--text-primary)",
              }}
            />
            <input
              type="password"
              placeholder="Confirm password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
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
              {submitting ? <Spinner size="sm" /> : "Update Password"}
            </button>
          </form>
        )}

        {error && (
          <div className="mt-4 text-center">
            <p className="text-xs mb-2" style={{ color: "var(--error)" }}>
              {error}
            </p>
            {(error.includes("expired") || error.includes("invalid") || error.includes("already")) && (
              <a
                href="/forgot-password"
                className="text-xs font-semibold"
                style={{ color: "var(--accent)" }}
              >
                Request a new reset link
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen">
          <Spinner size="lg" />
        </div>
      }
    >
      <ResetPasswordForm />
    </Suspense>
  );
}
