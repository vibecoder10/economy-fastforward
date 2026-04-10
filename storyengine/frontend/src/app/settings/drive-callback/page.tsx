"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export default function DriveCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      setStatus("error");
      setError("No authorization code received from Google.");
      return;
    }

    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    if (!token) {
      setStatus("error");
      setError("Not logged in. Please log in and try again.");
      return;
    }

    // Exchange the auth code for tokens via our backend
    fetch(`${API_URL}/api/auth/google-drive/callback`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ code }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || "Failed to connect Google Drive");
        }
        return res.json();
      })
      .then(() => {
        setStatus("success");
        // Redirect back to settings after a brief success message
        setTimeout(() => router.replace("/settings"), 1500);
      })
      .catch((err) => {
        setStatus("error");
        setError(err.message);
      });
  }, [searchParams, router]);

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg-void)" }}>
      <div
        className="p-8 rounded-2xl text-center max-w-sm"
        style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
      >
        {status === "loading" && (
          <>
            <Loader2 size={32} className="animate-spin mx-auto mb-4" style={{ color: "var(--turquoise)" }} />
            <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
              Connecting Google Drive...
            </p>
          </>
        )}
        {status === "success" && (
          <>
            <CheckCircle2 size={32} className="mx-auto mb-4" style={{ color: "var(--green)" }} />
            <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
              Google Drive connected!
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
              Redirecting to settings...
            </p>
          </>
        )}
        {status === "error" && (
          <>
            <XCircle size={32} className="mx-auto mb-4" style={{ color: "var(--red)" }} />
            <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
              Connection failed
            </p>
            <p className="text-xs mt-2" style={{ color: "var(--text-tertiary)" }}>
              {error}
            </p>
            <button
              onClick={() => router.replace("/settings")}
              className="mt-4 px-4 py-2 rounded-lg text-xs font-medium"
              style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
            >
              Back to Settings
            </button>
          </>
        )}
      </div>
    </div>
  );
}
