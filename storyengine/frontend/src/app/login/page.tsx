"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/AuthProvider";
import { Spinner } from "@/components/ui/spinner";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
            auto_select?: boolean;
          }) => void;
          renderButton: (
            element: HTMLElement,
            config: { theme?: string; size?: string; width?: number; shape?: string; text?: string }
          ) => void;
        };
      };
    };
  }
}

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

export default function LoginPage() {
  const { user, isLoading, login } = useAuth();
  const router = useRouter();
  const buttonRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);

  // Redirect if already logged in
  useEffect(() => {
    if (!isLoading && user) {
      router.replace("/");
    }
  }, [user, isLoading, router]);

  // Load Google Identity Services script and render button
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || isLoading || user) return;

    function initGoogle() {
      if (!window.google || !buttonRef.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleCredentialResponse,
      });
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: "filled_black",
        size: "large",
        width: 320,
        shape: "pill",
        text: "signin_with",
      });
    }

    // If script already loaded
    if (window.google) {
      initGoogle();
      return;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = initGoogle;
    document.head.appendChild(script);

    return () => {
      // Cleanup only if we added it
      if (script.parentNode) script.parentNode.removeChild(script);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, user]);

  async function handleCredentialResponse(response: { credential: string }) {
    setError(null);
    setLoggingIn(true);
    try {
      await login(response.credential);
      router.replace("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed. Please try again.");
    } finally {
      setLoggingIn(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spinner size="lg" />
      </div>
    );
  }

  if (user) return null; // Redirecting

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
        <h1
          className="font-display text-3xl mb-2"
          style={{ color: "var(--text-primary)" }}
        >
          StoryEngine
        </h1>
        <p
          className="text-sm mb-8"
          style={{ color: "var(--text-secondary)" }}
        >
          AI-powered video production pipeline
        </p>

        {loggingIn ? (
          <div className="flex flex-col items-center gap-3 py-4">
            <Spinner size="md" />
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Signing in...
            </span>
          </div>
        ) : (
          <div className="flex justify-center">
            <div ref={buttonRef} />
          </div>
        )}

        {!GOOGLE_CLIENT_ID && (
          <p
            className="text-xs mt-4"
            style={{ color: "var(--warning)" }}
          >
            Set NEXT_PUBLIC_GOOGLE_CLIENT_ID to enable Google Sign-In
          </p>
        )}

        {error && (
          <p
            className="text-xs mt-4"
            style={{ color: "var(--error)" }}
          >
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
