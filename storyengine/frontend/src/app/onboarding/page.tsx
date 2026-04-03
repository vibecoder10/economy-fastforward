"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  updateChannelProfile,
  setApiKey,
  testApiKey,
  getOnboardingStatus,
  type TestKeyResponse,
} from "@/lib/api";
import { Spinner } from "@/components/ui/spinner";
import {
  Check,
  ChevronRight,
  Tv,
  Key,
  Rocket,
  AlertCircle,
} from "lucide-react";

const STEPS = [
  { label: "Channel", icon: Tv },
  { label: "API Keys", icon: Key },
  { label: "Ready!", icon: Rocket },
];

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);

  // Redirect to dashboard if onboarding already complete
  useEffect(() => {
    getOnboardingStatus()
      .then((status) => {
        if (status.completed) router.replace("/dashboard");
      })
      .catch(() => {});
  }, [router]);

  // Step 1: Channel Identity
  const [channelName, setChannelName] = useState("");
  const [niche, setNiche] = useState("");
  const [audience, setAudience] = useState("");
  const [channelSaving, setChannelSaving] = useState(false);
  const [channelError, setChannelError] = useState<string | null>(null);

  // Step 2: API Keys
  const [anthropicKey, setAnthropicKey] = useState("");
  const [keySaving, setKeySaving] = useState(false);
  const [keyTesting, setKeyTesting] = useState(false);
  const [keyResult, setKeyResult] = useState<TestKeyResponse | null>(null);
  const [keyError, setKeyError] = useState<string | null>(null);

  async function handleSaveChannel() {
    if (!channelName.trim() || !niche.trim()) return;
    setChannelSaving(true);
    setChannelError(null);
    try {
      await updateChannelProfile({
        channel_name: channelName.trim(),
        niche: niche.trim(),
        target_audience: audience.trim() || undefined,
      });
      setStep(1);
    } catch (err) {
      setChannelError(
        err instanceof Error ? err.message : "Failed to save channel"
      );
    } finally {
      setChannelSaving(false);
    }
  }

  async function handleSaveAndTestKey() {
    if (!anthropicKey.trim()) return;
    setKeySaving(true);
    setKeyError(null);
    setKeyResult(null);
    try {
      await setApiKey("anthropic_api_key", anthropicKey.trim());
      setKeyTesting(true);
      const result = await testApiKey("anthropic_api_key");
      setKeyResult(result);
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : "Failed to save key");
    } finally {
      setKeySaving(false);
      setKeyTesting(false);
    }
  }

  const inputStyle = {
    background: "rgba(255,255,255,0.06)",
    border: "1px solid rgba(255,255,255,0.1)",
    color: "var(--text-primary)",
  };

  return (
    <div className="flex items-center justify-center min-h-screen px-4 py-12">
      <div className="w-full max-w-lg">
        {/* Progress Bar */}
        <div className="flex items-center justify-center gap-0 mb-10">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            const done = i < step;
            const active = i === step;
            return (
              <div key={s.label} className="flex items-center">
                <div className="flex flex-col items-center">
                  <div
                    className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold transition-all"
                    style={{
                      background: done
                        ? "var(--turquoise)"
                        : active
                          ? "var(--gold)"
                          : "rgba(255,255,255,0.08)",
                      color: done || active ? "#000" : "var(--text-tertiary)",
                    }}
                  >
                    {done ? <Check size={18} /> : <Icon size={18} />}
                  </div>
                  <span
                    className="text-[10px] mt-1.5 font-mono uppercase tracking-wider"
                    style={{
                      color: done
                        ? "var(--turquoise)"
                        : active
                          ? "var(--gold)"
                          : "var(--text-tertiary)",
                    }}
                  >
                    {s.label}
                  </span>
                </div>
                {i < STEPS.length - 1 && (
                  <div
                    className="w-16 h-px mx-2 mb-5"
                    style={{
                      background: i < step ? "var(--turquoise)" : "rgba(255,255,255,0.1)",
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Card */}
        <div
          className="p-8 rounded-2xl"
          style={{
            background: "rgba(15,22,38,0.65)",
            border: "1px solid rgba(0,212,170,0.12)",
            backdropFilter: "blur(24px)",
          }}
        >
          {/* Step 1: Channel Identity */}
          {step === 0 && (
            <div className="flex flex-col gap-5">
              <div>
                <h2
                  className="font-display text-2xl mb-1"
                  style={{ color: "var(--text-primary)" }}
                >
                  Your Channel
                </h2>
                <p
                  className="text-sm"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Tell us about your YouTube channel so we can tailor your
                  experience.
                </p>
              </div>

              <div>
                <label
                  className="block text-[11px] uppercase tracking-wider mb-1.5 font-mono"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Channel Name *
                </label>
                <input
                  type="text"
                  placeholder="e.g. Economy FastForward"
                  value={channelName}
                  onChange={(e) => setChannelName(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg text-sm outline-none"
                  style={inputStyle}
                />
              </div>

              <div>
                <label
                  className="block text-[11px] uppercase tracking-wider mb-1.5 font-mono"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Niche *
                </label>
                <input
                  type="text"
                  placeholder="e.g. Geopolitics & Economy"
                  value={niche}
                  onChange={(e) => setNiche(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg text-sm outline-none"
                  style={inputStyle}
                />
              </div>

              <div>
                <label
                  className="block text-[11px] uppercase tracking-wider mb-1.5 font-mono"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Target Audience (optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Curious adults interested in global economics"
                  value={audience}
                  onChange={(e) => setAudience(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg text-sm outline-none"
                  style={inputStyle}
                />
              </div>

              {channelError && (
                <p className="text-xs flex items-center gap-1" style={{ color: "var(--error)" }}>
                  <AlertCircle size={12} /> {channelError}
                </p>
              )}

              <button
                onClick={handleSaveChannel}
                disabled={channelSaving || !channelName.trim() || !niche.trim()}
                className="w-full py-3 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition-opacity"
                style={{
                  background: "var(--accent)",
                  color: "#000",
                  opacity:
                    channelSaving || !channelName.trim() || !niche.trim()
                      ? 0.5
                      : 1,
                }}
              >
                {channelSaving ? (
                  <Spinner size="sm" />
                ) : (
                  <>
                    Continue <ChevronRight size={16} />
                  </>
                )}
              </button>

              <button
                onClick={() => setStep(1)}
                className="text-xs text-center py-1"
                style={{ color: "var(--text-tertiary)" }}
              >
                Skip for now
              </button>
            </div>
          )}

          {/* Step 2: API Keys */}
          {step === 1 && (
            <div className="flex flex-col gap-5">
              <div>
                <h2
                  className="font-display text-2xl mb-1"
                  style={{ color: "var(--text-primary)" }}
                >
                  Connect Your AI
                </h2>
                <p
                  className="text-sm"
                  style={{ color: "var(--text-secondary)" }}
                >
                  StoryEngine uses your own API keys. Start with Anthropic
                  (Claude) — it powers scripts, research, and analysis.
                </p>
              </div>

              <div>
                <label
                  className="block text-[11px] uppercase tracking-wider mb-1.5 font-mono"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Anthropic API Key
                </label>
                <input
                  type="password"
                  placeholder="sk-ant-..."
                  value={anthropicKey}
                  onChange={(e) => {
                    setAnthropicKey(e.target.value);
                    setKeyResult(null);
                    setKeyError(null);
                  }}
                  className="w-full px-4 py-3 rounded-lg text-sm outline-none font-mono"
                  style={inputStyle}
                />
                <p
                  className="text-[10px] mt-1"
                  style={{ color: "var(--text-tertiary)" }}
                >
                  Get your key at console.anthropic.com → API Keys
                </p>
              </div>

              {keyResult && (
                <div
                  className="flex items-center gap-2 text-sm px-3 py-2 rounded-lg"
                  style={{
                    background: keyResult.success
                      ? "rgba(0,230,138,0.1)"
                      : "rgba(255,77,106,0.1)",
                    color: keyResult.success ? "var(--green)" : "var(--red)",
                  }}
                >
                  {keyResult.success ? (
                    <Check size={14} />
                  ) : (
                    <AlertCircle size={14} />
                  )}
                  {keyResult.message}
                </div>
              )}

              {keyError && (
                <p className="text-xs flex items-center gap-1" style={{ color: "var(--error)" }}>
                  <AlertCircle size={12} /> {keyError}
                </p>
              )}

              <button
                onClick={handleSaveAndTestKey}
                disabled={keySaving || keyTesting || !anthropicKey.trim()}
                className="w-full py-3 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition-opacity"
                style={{
                  background: "var(--gold)",
                  color: "#000",
                  opacity:
                    keySaving || keyTesting || !anthropicKey.trim() ? 0.5 : 1,
                }}
              >
                {keySaving || keyTesting ? (
                  <>
                    <Spinner size="sm" />{" "}
                    {keyTesting ? "Testing..." : "Saving..."}
                  </>
                ) : (
                  "Save & Test Key"
                )}
              </button>

              <button
                onClick={() => setStep(2)}
                className="w-full py-3 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition-opacity"
                style={{
                  background: "transparent",
                  color: "var(--accent)",
                  border: "1px solid var(--accent)",
                  opacity: 1,
                }}
              >
                Continue <ChevronRight size={16} />
              </button>

              <button
                onClick={() => setStep(2)}
                className="text-xs text-center py-1"
                style={{ color: "var(--text-tertiary)" }}
              >
                Skip for now
              </button>
            </div>
          )}

          {/* Step 3: Done */}
          {step === 2 && (
            <div className="flex flex-col items-center gap-6 py-4">
              <div
                className="w-16 h-16 rounded-full flex items-center justify-center"
                style={{ background: "var(--turquoise)" }}
              >
                <Check size={32} color="#000" strokeWidth={3} />
              </div>
              <div className="text-center">
                <h2
                  className="font-display text-2xl mb-2"
                  style={{ color: "var(--text-primary)" }}
                >
                  Your Studio is Ready
                </h2>
                <p
                  className="text-sm"
                  style={{ color: "var(--text-secondary)" }}
                >
                  You can always update your channel settings and add more API
                  keys later in Settings.
                </p>
              </div>
              <button
                onClick={() => router.replace("/dashboard")}
                className="w-full py-3 rounded-lg text-sm font-semibold flex items-center justify-center gap-2"
                style={{
                  background: "var(--accent)",
                  color: "#000",
                }}
              >
                <Rocket size={16} /> Start Creating
              </button>
            </div>
          )}
        </div>

        {/* Skip setup link — shown on all steps */}
        <p
          className="text-[11px] text-center mt-4 cursor-pointer"
          style={{ color: "var(--text-tertiary)" }}
          onClick={() => router.replace("/dashboard")}
        >
          Skip setup, go to Dashboard →
        </p>
      </div>
    </div>
  );
}
