"use client";

import { FileQuestion, Home, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

export default function NotFound() {
  const router = useRouter();

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
          background: "rgba(212,168,82,0.12)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <FileQuestion size={32} style={{ color: "var(--gold)" }} />
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
          Page not found
        </h2>
        <p
          style={{
            fontSize: 14,
            color: "var(--text-secondary)",
            maxWidth: 380,
            lineHeight: 1.5,
          }}
        >
          The page you&apos;re looking for doesn&apos;t exist or may have been moved.
        </p>
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        <button
          onClick={() => router.back()}
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
            cursor: "pointer",
          }}
        >
          <ArrowLeft size={16} />
          Go Back
        </button>
        <Link
          href="/dashboard"
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
