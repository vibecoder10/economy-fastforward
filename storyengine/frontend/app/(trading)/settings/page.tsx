"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";

export default function TradingSettingsPage() {
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
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

  const handleSave = async () => {
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
        setMessage({ type: "success", text: "Kalshi account connected successfully!" });
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
            {/* Instructions */}
            <div className="bg-background rounded-lg p-4 mb-6">
              <h3 className="text-sm font-semibold mb-2">How to get your API keys:</h3>
              <ol className="text-sm text-text-secondary space-y-1.5 list-decimal list-inside">
                <li>Go to <span className="text-accent">kalshi.com</span> and sign in</li>
                <li>Navigate to Settings &rarr; API Keys</li>
                <li>Click &ldquo;Create API Key&rdquo;</li>
                <li>Copy your API Key ID and download the private key file</li>
                <li>Paste both below</li>
              </ol>
              <p className="text-xs text-text-tertiary mt-3">
                Your credentials are encrypted with AES-256-GCM before storage. We never see your keys in plaintext.
              </p>
            </div>

            {/* Form */}
            <div className="space-y-4">
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
                  placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;...&#10;-----END RSA PRIVATE KEY-----"
                  rows={6}
                  className="w-full px-4 py-3 bg-background border border-border rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent transition-colors font-mono text-xs"
                />
              </div>
            </div>
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

        {/* Save button */}
        {!configured && (
          <button
            onClick={handleSave}
            disabled={saving || !apiKeyId || !privateKey}
            className="mt-6 w-full py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 text-background font-semibold rounded-lg transition-colors"
          >
            {saving ? "Connecting..." : "Connect Kalshi Account"}
          </button>
        )}
      </div>

      {/* Deposit instructions */}
      <div className="bg-surface border border-border rounded-xl p-6">
        <h2 className="text-lg font-semibold mb-3">Fund Your Account</h2>
        <p className="text-sm text-text-secondary mb-4">
          To start trading, deposit funds directly through Kalshi:
        </p>
        <ol className="text-sm text-text-secondary space-y-1.5 list-decimal list-inside">
          <li>Log in to your Kalshi account at <span className="text-accent">kalshi.com</span></li>
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
