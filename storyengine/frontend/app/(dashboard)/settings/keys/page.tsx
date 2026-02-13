"use client";

import { useState, useEffect } from "react";

interface KeyStatus {
  anthropicKey: boolean;
  kieAiKey: boolean;
  elevenLabsKey: boolean;
}

export default function ApiKeysPage() {
  const [anthropicKey, setAnthropicKey] = useState("");
  const [kieAiKey, setKieAiKey] = useState("");
  const [elevenLabsKey, setElevenLabsKey] = useState("");
  const [status, setStatus] = useState<KeyStatus>({
    anthropicKey: false,
    kieAiKey: false,
    elevenLabsKey: false,
  });
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState<string | null>(null);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  useEffect(() => {
    fetchKeyStatus();
  }, []);

  async function fetchKeyStatus() {
    try {
      const res = await fetch("/api/keys");
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch {
      // Keys not configured yet
    }
  }

  async function handleSave() {
    setSaving(true);
    setMessage(null);

    try {
      const res = await fetch("/api/keys", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          anthropicKey: anthropicKey || undefined,
          kieAiKey: kieAiKey || undefined,
          elevenLabsKey: elevenLabsKey || undefined,
        }),
      });

      if (res.ok) {
        setMessage({ type: "success", text: "API keys saved successfully" });
        setAnthropicKey("");
        setKieAiKey("");
        setElevenLabsKey("");
        fetchKeyStatus();
      } else {
        const data = await res.json();
        setMessage({ type: "error", text: data.error || "Failed to save keys" });
      }
    } catch {
      setMessage({ type: "error", text: "Network error" });
    }

    setSaving(false);
  }

  async function handleValidate(keyType: string) {
    setValidating(keyType);
    setMessage(null);

    try {
      const res = await fetch("/api/keys/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyType }),
      });

      const data = await res.json();

      if (data.valid) {
        setMessage({ type: "success", text: `${keyType} key is valid` });
      } else {
        setMessage({
          type: "error",
          text: `${keyType} key validation failed: ${data.error || "unknown error"}`,
        });
      }
    } catch {
      setMessage({ type: "error", text: "Validation request failed" });
    }

    setValidating(null);
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-3xl font-bold mb-2">API Keys</h1>
      <p className="text-text-secondary mb-8">
        Bring Your Own Keys (BYOK) to use your own API accounts. Keys are
        encrypted at rest. If no keys are provided, platform keys will be used
        (usage metered to your account).
      </p>

      {message && (
        <div
          className={`p-3 rounded-lg mb-6 text-sm ${
            message.type === "success"
              ? "bg-success/10 border border-success/30 text-success"
              : "bg-error/10 border border-error/30 text-error"
          }`}
        >
          {message.text}
        </div>
      )}

      <div className="space-y-6">
        {/* Anthropic */}
        <div className="p-5 bg-surface border border-border rounded-xl">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="font-semibold">Anthropic API Key</h3>
              <p className="text-sm text-text-secondary">
                Used for beat sheet, script, and image prompt generation
              </p>
            </div>
            <div className="flex items-center gap-2">
              {status.anthropicKey && (
                <span className="text-xs px-2 py-1 bg-success/10 text-success rounded">
                  Configured
                </span>
              )}
              {status.anthropicKey && (
                <button
                  onClick={() => handleValidate("anthropic")}
                  disabled={validating === "anthropic"}
                  className="text-xs px-3 py-1 border border-border rounded hover:bg-surface-hover transition-colors disabled:opacity-50"
                >
                  {validating === "anthropic" ? "Testing..." : "Test"}
                </button>
              )}
            </div>
          </div>
          <input
            type="password"
            value={anthropicKey}
            onChange={(e) => setAnthropicKey(e.target.value)}
            className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent transition-colors text-sm font-mono"
            placeholder="sk-ant-..."
          />
        </div>

        {/* Kie.ai */}
        <div className="p-5 bg-surface border border-border rounded-xl">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="font-semibold">Kie.ai API Key</h3>
              <p className="text-sm text-text-secondary">
                Used for image generation (Seed Dream) and thumbnails (Nano
                Banana Pro)
              </p>
            </div>
            <div className="flex items-center gap-2">
              {status.kieAiKey && (
                <span className="text-xs px-2 py-1 bg-success/10 text-success rounded">
                  Configured
                </span>
              )}
              {status.kieAiKey && (
                <button
                  onClick={() => handleValidate("kieAi")}
                  disabled={validating === "kieAi"}
                  className="text-xs px-3 py-1 border border-border rounded hover:bg-surface-hover transition-colors disabled:opacity-50"
                >
                  {validating === "kieAi" ? "Testing..." : "Test"}
                </button>
              )}
            </div>
          </div>
          <input
            type="password"
            value={kieAiKey}
            onChange={(e) => setKieAiKey(e.target.value)}
            className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent transition-colors text-sm font-mono"
            placeholder="Enter your Kie.ai API key"
          />
        </div>

        {/* ElevenLabs */}
        <div className="p-5 bg-surface border border-border rounded-xl">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="font-semibold">ElevenLabs API Key</h3>
              <p className="text-sm text-text-secondary">
                Used for voiceover generation (future)
              </p>
            </div>
            <div className="flex items-center gap-2">
              {status.elevenLabsKey && (
                <span className="text-xs px-2 py-1 bg-success/10 text-success rounded">
                  Configured
                </span>
              )}
              {status.elevenLabsKey && (
                <button
                  onClick={() => handleValidate("elevenLabs")}
                  disabled={validating === "elevenLabs"}
                  className="text-xs px-3 py-1 border border-border rounded hover:bg-surface-hover transition-colors disabled:opacity-50"
                >
                  {validating === "elevenLabs" ? "Testing..." : "Test"}
                </button>
              )}
            </div>
          </div>
          <input
            type="password"
            value={elevenLabsKey}
            onChange={(e) => setElevenLabsKey(e.target.value)}
            className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent transition-colors text-sm font-mono"
            placeholder="Enter your ElevenLabs API key"
          />
        </div>
      </div>

      <div className="mt-8">
        <button
          onClick={handleSave}
          disabled={saving || (!anthropicKey && !kieAiKey && !elevenLabsKey)}
          className="px-8 py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 text-background font-semibold rounded-lg transition-colors"
        >
          {saving ? "Saving..." : "Save Keys"}
        </button>
      </div>
    </div>
  );
}
