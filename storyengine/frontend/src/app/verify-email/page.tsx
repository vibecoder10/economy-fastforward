"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { verifyEmail } from "@/lib/api";
import { Spinner } from "@/components/ui/spinner";

function VerifyEmailInner() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("Missing verification token. Please use the link from your email.");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await verifyEmail(token);
        if (!cancelled) setStatus("success");
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : "";
        setStatus("error");
        setMessage(
          msg.includes("expired")
            ? "This link has expired. Log in and resend the verification email."
            : "This link is invalid or already used. Try logging in."
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

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
        {status === "loading" && (
          <>
            <Spinner size="lg" />
            <p className="text-sm mt-4" style={{ color: "var(--text-secondary)" }}>
              Confirming your email…
            </p>
          </>
        )}

        {status === "success" && (
          <div className="flex flex-col items-center gap-4">
            <div
              className="w-14 h-14 rounded-full flex items-center justify-center"
              style={{ background: "rgba(0,212,170,0.15)" }}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <h1 className="font-display text-2xl" style={{ color: "var(--text-primary)" }}>
              Email confirmed
            </h1>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              You&apos;re all set — you can start creating videos.
            </p>
            <a href="/dashboard" className="text-sm font-semibold" style={{ color: "var(--accent)" }}>
              Go to your dashboard
            </a>
          </div>
        )}

        {status === "error" && (
          <div className="flex flex-col items-center gap-4">
            <h1 className="font-display text-2xl" style={{ color: "var(--text-primary)" }}>
              Couldn&apos;t confirm
            </h1>
            <p className="text-sm" style={{ color: "var(--error)" }}>
              {message}
            </p>
            <a href="/login" className="text-sm font-semibold" style={{ color: "var(--accent)" }}>
              Back to login
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen">
          <Spinner size="lg" />
        </div>
      }
    >
      <VerifyEmailInner />
    </Suspense>
  );
}
