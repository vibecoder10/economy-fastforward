"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { youtubeOAuthCallback } from "@/lib/api";
import { humanizeError } from "@/lib/errors";

export default function YouTubeCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [channelName, setChannelName] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      setStatus("error");
      setError("No authorization code received from Google.");
      return;
    }

    youtubeOAuthCallback(code)
      .then((data) => {
        setStatus("success");
        setChannelName(data.channel_name || "");

        // Redirect back to origin page (chat onboarding, old wizard, or settings)
        const origin = localStorage.getItem("youtube_oauth_origin");
        localStorage.removeItem("youtube_oauth_origin");

        const redirectTo = origin === "chat"
          ? "/?connected=yt"
          : origin === "/onboarding"
            ? "/onboarding?yt_connected=true"
            : "/settings";

        setTimeout(() => router.replace(redirectTo), 1500);
      })
      .catch((err) => {
        setStatus("error");
        setError(humanizeError(err, "We couldn't connect YouTube. Try again."));
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
              Connecting YouTube...
            </p>
          </>
        )}
        {status === "success" && (
          <>
            <CheckCircle2 size={32} className="mx-auto mb-4" style={{ color: "var(--green)" }} />
            <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
              YouTube Connected!
            </p>
            {channelName && (
              <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
                {channelName}
              </p>
            )}
            <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
              Redirecting...
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
