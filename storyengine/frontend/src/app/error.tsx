"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw, Home } from "lucide-react";
import Link from "next/link";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[StoryEngine] Unhandled error:", error);
  }, [error]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "60vh",
        padding: 32,
        textAlign: "center",
        gap: 20,
      }}
    >
      <div
        style={{
          width: 64,
          height: 64,
          borderRadius: 16,
          background: "rgba(255,77,106,0.12)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AlertTriangle size={32} style={{ color: "var(--red)" }} />
      </div>

      <div>
        <h2
          className="font-display"
          style={{
            fontSize: 24,
            color: "var(--text-primary)",
            marginBottom: 8,
          }}
        >
          Something went wrong
        </h2>
        <p
          style={{
            fontSize: 14,
            color: "var(--text-secondary)",
            maxWidth: 400,
            lineHeight: 1.5,
          }}
        >
          An unexpected error occurred. Try refreshing, or head back to the dashboard.
        </p>
      </div>

      {error.message && process.env.NODE_ENV === "development" && (
        <pre
          style={{
            fontSize: 11,
            color: "var(--red)",
            background: "rgba(255,77,106,0.08)",
            border: "1px solid rgba(255,77,106,0.15)",
            borderRadius: 8,
            padding: "8px 12px",
            maxWidth: 500,
            overflow: "auto",
            textAlign: "left",
            fontFamily: "var(--font-mono)",
          }}
        >
          {error.message}
        </pre>
      )}

      <div style={{ display: "flex", gap: 12 }}>
        <button
          onClick={reset}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "10px 20px",
            borderRadius: 10,
            background: "var(--turquoise)",
            color: "#05080D",
            border: "none",
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          <RefreshCw size={16} />
          Try Again
        </button>
        <Link
          href="/dashboard"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "10px 20px",
            borderRadius: 10,
            background: "rgba(255,255,255,0.06)",
            color: "var(--text-primary)",
            border: "1px solid rgba(255,255,255,0.08)",
            fontSize: 14,
            fontWeight: 500,
            textDecoration: "none",
          }}
        >
          <Home size={16} />
          Dashboard
        </Link>
      </div>
    </div>
  );
}
