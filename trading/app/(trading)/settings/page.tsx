"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";

export default function TradingSettingsPage() {
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [showManual, setShowManual] = useState(false);

  // Kalshi login fields
  const [kalshiEmail, setKalshiEmail] = useState("");
  const [kalshiPassword, setKalshiPassword] = useState("");

  // Manual API key fields
  const [apiKeyId, setApiKeyId] = useState("");
  const [privateKey, setPrivateKey] = useState("");

  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  useEffect(() => {
    fetch("/api/trading/credentials")
      .then((r) => r.json())
      .then((data) => {
        setConfigured(data.configured ?? false);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const handleKalshiLogin = async () => {
    setSaving(true);
    setMessage(null);

    try {
      const res = await fetch("/api/trading/kalshi-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: kalshiEmail, password: kalshiPassword }),
      });

      const data = await res.json();
      if (!res.ok) {
        setMessage({ type: "error", text: data.error || "Login failed" });
      } else {
        setMessage({
          type: "success",
          text: "Kalshi account connected! API keys generated automatically.",
        });
        setConfigured(true);
        setKalshiEmail("");
        setKalshiPassword("");
      }
    } catch {
      setMessage({ type: "error", text: "Network error — could not reach server" });
    }
    setSaving(false);
  };

  const handleManualSave = async () => {
    setSaving(true);
    setMessage(null);

    try {
      const res = await fetch("/api/trading/credentials", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apiKeyId, privateKey }),
      });

      const data = await res.json();
      if (!res.ok) {
        setMessage({ type: "error", text: data.error || "Failed to save" });
      } else {
        setMessage({ type: "success", text: "Kalshi account connected!" });
        setConfigured(true);
        setApiKeyId("");
        setPrivateKey("");
      }
    } catch {
      setMessage({ type: "error", text: "Network error" });
    }
    setSaving(false);
  };

  const handleDisconnect = async () => {
    if (!confirm("Disconnect your Kalshi account?")) return;

    try {
      await fetch("/api/trading/credentials", { method: "DELETE" });
      setConfigured(false);
      setMessage({ type: "success", text: "Account disconnected" });
    } catch {
      setMessage({ type: "error", text: "Failed to disconnect" });
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setMessage(null);

    try {
      const res = await fetch("/api/kalshi/portfolio");
      const data = await res.json();

      if (data.connected && data.balance) {
        const bal = (data.balance.balance / 100).toFixed(2);
        setMessage({
          type: "success",
          text: `Connection successful! Balance: $${bal}`,
        });
      } else {
        setMessage({ type: "error", text: "Could not verify connection" });
      }
    } catch {
      setMessage({ type: "error", text: "Connection test failed" });
    }
    setTesting(false);
  };

  if (loading) {
    return (
      <div className="max-w-2xl animate-pulse space-y-6">
        <div className="h-8 bg-surface rounded w-1/3" />
        <div className="h-64 bg-surface rounded-xl" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Trading Settings</h1>
        <p className="text-text-secondary mt-1">
          Connect your Kalshi account to trade prediction markets
        </p>
      </div>

      {/* Connection status */}
      <div className="bg-surface border border-border rounded-xl p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "w-3 h-3 rounded-full",
                configured ? "bg-success" : "bg-text-tertiary"
              )}
            />
            <span className="font-medium">
              {configured ? "Kalshi Connected" : "Kalshi Not Connected"}
            </span>
          </div>
          {configured && (
            <div className="flex gap-3">
              <button
                onClick={handleTest}
                disabled={testing}
                className="px-4 py-2 text-sm bg-surface-hover hover:bg-border rounded-lg transition-colors disabled:opacity-50"
              >
                {testing ? "Testing..." : "Test Connection"}
              </button>
              <button
                onClick={handleDisconnect}
                className="px-4 py-2 text-sm text-error hover:bg-error/10 rounded-lg transition-colors"
              >
                Disconnect
              </button>
            </div>
          )}
        </div>

        {!configured && (
          <>
            {/* Kalshi Sign-In (primary flow) */}
            <div className="space-y-4">
              <div className="bg-background rounded-lg p-4">
                <h3 className="text-sm font-semibold mb-1">
                  Sign in with your Kalshi account
                </h3>
                <p className="text-xs text-text-tertiary">
                  We&apos;ll generate API keys automatically. Your Kalshi password is
                  never stored — it&apos;s only used once to create secure API keys.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-text-secondary mb-1.5">
                  Kalshi Email
                </label>
                <input
                  type="email"
                  value={kalshiEmail}
                  onChange={(e) => setKalshiEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full px-4 py-3 bg-background border border-border rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent transition-colors text-sm"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-secondary mb-1.5">
                  Kalshi Password
                </label>
                <input
                  type="password"
                  value={kalshiPassword}
                  onChange={(e) => setKalshiPassword(e.target.value)}
                  placeholder="Your Kalshi password"
                  className="w-full px-4 py-3 bg-background border border-border rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent transition-colors text-sm"
                />
              </div>

              <button
                onClick={handleKalshiLogin}
                disabled={saving || !kalshiEmail || !kalshiPassword}
                className="w-full py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 text-background font-semibold rounded-lg transition-colors"
              >
                {saving ? "Connecting..." : "Connect Kalshi Account"}
              </button>

              <p className="text-xs text-text-tertiary text-center">
                Don&apos;t have an account?{" "}
                <a
                  href="https://kalshi.com/sign-up"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-accent hover:underline"
                >
                  Sign up at Kalshi
                </a>
              </p>
            </div>

            {/* Divider */}
            <div className="flex items-center gap-4 my-6">
              <div className="flex-1 h-px bg-border" />
              <button
                onClick={() => setShowManual(!showManual)}
                className="text-xs text-text-tertiary hover:text-text-secondary transition-colors"
              >
                {showManual
                  ? "Hide manual setup"
                  : "Or connect with API keys manually"}
              </button>
              <div className="flex-1 h-px bg-border" />
            </div>

            {/* Manual API key entry (collapsed by default) */}
            {showManual && (
              <div className="space-y-4">
                <div className="bg-background rounded-lg p-4">
                  <h3 className="text-sm font-semibold mb-2">
                    Manual API Key Setup
                  </h3>
                  <ol className="text-sm text-text-secondary space-y-1.5 list-decimal list-inside">
                    <li>
                      Go to{" "}
                      <a
                        href="https://kalshi.com/account/profile"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-accent hover:underline"
                      >
                        kalshi.com/account/profile
                      </a>
                    </li>
                    <li>Scroll to API Keys and click &ldquo;Create API Key&rdquo;</li>
                    <li>Copy your API Key ID and download the private key file</li>
                    <li>Paste both below</li>
                  </ol>
                </div>

                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1.5">
                    API Key ID
                  </label>
                  <input
                    type="text"
                    value={apiKeyId}
                    onChange={(e) => setApiKeyId(e.target.value)}
                    placeholder="e.g., abc123-def456-..."
                    className="w-full px-4 py-3 bg-background border border-border rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent transition-colors font-mono text-sm"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1.5">
                    Private Key (RSA PEM)
                  </label>
                  <textarea
                    value={privateKey}
                    onChange={(e) => setPrivateKey(e.target.value)}
                    placeholder={
                      "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
                    }
                    rows={6}
                    className="w-full px-4 py-3 bg-background border border-border rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent transition-colors font-mono text-xs"
                  />
                </div>

                <button
                  onClick={handleManualSave}
                  disabled={saving || !apiKeyId || !privateKey}
                  className="w-full py-3 bg-surface-hover hover:bg-border disabled:opacity-50 text-text-primary font-semibold rounded-lg transition-colors"
                >
                  {saving ? "Connecting..." : "Connect with API Keys"}
                </button>

                <p className="text-xs text-text-tertiary text-center">
                  Credentials are encrypted with AES-256-GCM before storage.
                </p>
              </div>
            )}
          </>
        )}

        {/* Message */}
        {message && (
          <div
            className={cn(
              "p-3 rounded-lg text-sm mt-4",
              message.type === "success"
                ? "bg-success/10 text-success border border-success/20"
                : "bg-error/10 text-error border border-error/20"
            )}
          >
            {message.text}
          </div>
        )}
      </div>

      {/* Fund account instructions */}
      <div className="bg-surface border border-border rounded-xl p-6">
        <h2 className="text-lg font-semibold mb-3">Fund Your Account</h2>
        <p className="text-sm text-text-secondary mb-4">
          To start trading, deposit funds directly through Kalshi:
        </p>
        <ol className="text-sm text-text-secondary space-y-1.5 list-decimal list-inside">
          <li>
            Log in at{" "}
            <a
              href="https://kalshi.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:underline"
            >
              kalshi.com
            </a>
          </li>
          <li>Go to Portfolio &rarr; Deposit</li>
          <li>Add $50 or more via bank transfer or debit card</li>
          <li>Your balance will appear here automatically</li>
        </ol>
        <p className="text-xs text-text-tertiary mt-4">
          Kalshi is CFTC-regulated. Your funds are held in segregated accounts.
        </p>
      </div>
    </div>
  );
}
