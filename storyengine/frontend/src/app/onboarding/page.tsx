"use client";

import { Suspense, useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  updateChannelProfile,
  setApiKey,
  testApiKey,
  getOnboardingStatus,
  getReadinessStatus,
  generateSystemPrompts,
  getYouTubeConnectUrl,
  getYouTubeStatus,
  syncYouTubeMetrics,
} from "@/lib/api";
import { humanizeError } from "@/lib/errors";
import { Spinner } from "@/components/ui/spinner";
import { ChannelIdentityStep } from "@/components/onboarding/ChannelIdentityStep";
import { StyleSetupStep } from "@/components/onboarding/StyleSetupStep";
import { ApiKeysStep } from "@/components/onboarding/ApiKeysStep";
import { YouTubeConnectStep } from "@/components/onboarding/YouTubeConnectStep";
import { CreateVideoStep } from "@/components/onboarding/CreateVideoStep";
import { Check, User, Palette, Key, Youtube, Film } from "lucide-react";

// Single unified step sequence — no branching
const STEPS = [
  { key: "channel", label: "Channel", icon: User },
  { key: "keys", label: "Tools", icon: Key },
  { key: "style", label: "Style", icon: Palette },
  { key: "youtube", label: "YouTube", icon: Youtube },
  { key: "video", label: "First Video", icon: Film },
];

export default function OnboardingPage() {
  return (
    <Suspense>
      <OnboardingContent />
    </Suspense>
  );
}

function OnboardingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState(0);
  const [displayName, setDisplayName] = useState("");

  // Channel state
  const [channelName, setChannelName] = useState("");
  const [niche, setNiche] = useState("");
  const [audience, setAudience] = useState("");
  const [channelSaving, setChannelSaving] = useState(false);
  const [channelError, setChannelError] = useState<string | null>(null);

  // YouTube state
  const [ytConnected, setYtConnected] = useState(false);
  const [ytChannelName, setYtChannelName] = useState<string | null>(null);
  const [ytConnecting, setYtConnecting] = useState(false);
  const [ytSyncing, setYtSyncing] = useState(false);

  // Style state
  const [styleDescription, setStyleDescription] = useState("");
  const [styleGenerating, setStyleGenerating] = useState(false);
  const [styleGenerated, setStyleGenerated] = useState(false);
  const [styleSummary, setStyleSummary] = useState<string | null>(null);
  const [styleError, setStyleError] = useState<string | null>(null);

  // API keys state
  const [apiKeys, setApiKeys] = useState<
    { key: string; label: string; reason: string; url: string; configured: boolean }[]
  >([]);

  // Network-health banner: set when the initial status load fails, so the
  // user sees "we couldn't load your progress" rather than an empty Step 1.
  const [statusLoadFailed, setStatusLoadFailed] = useState(false);

  // Check if onboarding is already complete, and auto-advance past completed steps
  useEffect(() => {
    getOnboardingStatus()
      .then((status) => {
        if (status.completed) {
          router.replace("/dashboard");
          return;
        }
        if (status.display_name) setDisplayName(status.display_name);

        // Auto-advance past completed steps (order: channel → keys → style → youtube → video)
        const s = status.steps;
        const keysComplete = s.api_keys.configured === s.api_keys.required;
        if (s.channel_configured && keysComplete && s.style_generated) {
          setStep(3); // YouTube step
        } else if (s.channel_configured && keysComplete) {
          setStep(2); // Style step
        } else if (s.channel_configured) {
          setStep(1); // Keys step
          loadApiKeys();
        }
      })
      .catch(() => {
        setStatusLoadFailed(true);
      })
      .finally(() => setLoading(false));
  }, [router]);

  // Check YouTube status on mount (in case returning from OAuth)
  useEffect(() => {
    getYouTubeStatus()
      .then((status) => {
        if (status.connected) {
          setYtConnected(true);
          setYtChannelName(status.channel_name);
          if (status.channel_name && !channelName) {
            setChannelName(status.channel_name);
          }
        }
      })
      .catch(() => {});
  }, []);

  // Handle return from YouTube OAuth — auto-advance to YouTube step
  useEffect(() => {
    if (searchParams.get("yt_connected") === "true") {
      setYtConnected(true);
      // Find the YouTube step index and go to it
      const ytIdx = STEPS.findIndex((s) => s.key === "youtube");
      if (ytIdx >= 0) setStep(ytIdx);
    }
  }, [searchParams]);

  // Load API key readiness when reaching keys step
  const loadApiKeys = useCallback(async () => {
    try {
      const status = await getReadinessStatus();
      const all: { key: string; label: string; reason: string; url: string; configured: boolean }[] = [];
      for (const k of status.missing_keys) {
        all.push({ ...k, configured: false });
      }
      for (const key of status.configured_keys) {
        all.push({
          key,
          label: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
          reason: "",
          url: "",
          configured: true,
        });
      }
      all.sort((a, b) => (a.configured === b.configured ? 0 : a.configured ? 1 : -1));
      setApiKeys(all);
    } catch {
      setApiKeys([
        { key: "anthropic_api_key", label: "Anthropic (Claude)", reason: "Scripts, research, analysis", url: "https://console.anthropic.com", configured: false },
        { key: "elevenlabs_api_key", label: "ElevenLabs API Key", reason: "Voice narration", url: "https://elevenlabs.io", configured: false },
        { key: "elevenlabs_voice_id", label: "ElevenLabs Voice ID", reason: "Voice selection", url: "https://elevenlabs.io", configured: false },
        { key: "kie_ai_api_key", label: "Kie.ai", reason: "Image & video generation", url: "https://kie.ai", configured: false },
        { key: "openai_api_key", label: "OpenAI (Whisper)", reason: "Audio transcription", url: "https://platform.openai.com", configured: false },
      ]);
    }
  }, []);

  // --- Handlers ---

  async function handleSaveChannel() {
    if (!channelName.trim()) return;
    setChannelSaving(true);
    setChannelError(null);
    try {
      await updateChannelProfile({
        channel_name: channelName.trim(),
        niche: niche.trim() || undefined,
        target_audience: audience.trim() || undefined,
      });
      loadApiKeys();
      setStep(1); // Keys step
    } catch (err) {
      setChannelError(humanizeError(err, "We couldn't save your channel. Please try again."));
    } finally {
      setChannelSaving(false);
    }
  }

  async function handleConnectYouTube() {
    setYtConnecting(true);
    try {
      localStorage.setItem("youtube_oauth_origin", "/onboarding");
      const { auth_url } = await getYouTubeConnectUrl();
      window.location.href = auth_url;
    } catch {
      setYtConnecting(false);
    }
  }

  const handleStartSync = useCallback(async () => {
    if (ytSyncing) return;
    setYtSyncing(true);
    try {
      await syncYouTubeMetrics();
    } catch {
      // Sync runs in background, non-blocking
    }
  }, [ytSyncing]);

  async function handleGenerateStyle() {
    if (!styleDescription.trim()) return;
    setStyleGenerating(true);
    setStyleError(null);
    try {
      const result = await generateSystemPrompts({
        style_description: styleDescription.trim(),
        channel_name: channelName || undefined,
        niche: niche || undefined,
        target_audience: audience || undefined,
      });
      setStyleGenerated(true);
      setStyleSummary(result.summary || "Your custom style has been generated.");
    } catch (err) {
      setStyleError(humanizeError(err, "We couldn't generate your style. Please try again."));
    } finally {
      setStyleGenerating(false);
    }
  }

  async function handleSaveApiKey(keyName: string, value: string): Promise<boolean> {
    try {
      await setApiKey(keyName, value);
      return true;
    } catch {
      return false;
    }
  }

  async function handleTestApiKey(keyName: string): Promise<boolean> {
    try {
      const result = await testApiKey(keyName);
      if (result.success) {
        setApiKeys((prev) =>
          prev.map((k) => (k.key === keyName ? { ...k, configured: true } : k))
        );
      }
      return result.success === true;
    } catch {
      return false;
    }
  }

  function handleNext() {
    const nextStep = step + 1;
    if (nextStep >= STEPS.length) {
      router.replace("/dashboard");
      return;
    }

    // Load API keys when reaching the keys step
    const nextKey = STEPS[nextStep]?.key;
    if (nextKey === "keys") {
      loadApiKeys();
    }

    setStep(nextStep);
  }

  function handleSkip() {
    handleNext();
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spinner />
      </div>
    );
  }

  const currentStepKey = STEPS[step]?.key;

  return (
    <div className="flex items-center justify-center min-h-screen px-4 py-12">
      <div className="w-full max-w-xl">
        {statusLoadFailed && (
          <div
            role="status"
            data-testid="onboarding-network-banner"
            className="mb-6 px-4 py-3 rounded-lg text-sm text-center"
            style={{
              background: "rgba(255, 180, 0, 0.08)",
              border: "1px solid rgba(255, 180, 0, 0.35)",
              color: "var(--gold)",
            }}
          >
            We couldn&apos;t load your progress. Check your connection and refresh — any data you enter below may not save until we reconnect.
          </div>
        )}

        {/* Progress Bar */}
        <div className="flex items-center justify-center gap-0 mb-10">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            const done = i < step;
            const active = i === step;
            return (
              <div key={s.key} className="flex items-center">
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
                    className="w-12 h-px mx-1.5 mb-5"
                    style={{
                      background: i < step ? "var(--turquoise)" : "rgba(255,255,255,0.1)",
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Step Content */}
        <div
          className="p-8 rounded-2xl"
          style={{
            background: "rgba(15,22,38,0.65)",
            border: "1px solid rgba(0,212,170,0.12)",
            backdropFilter: "blur(24px)",
          }}
        >
          {currentStepKey === "channel" && (
            <ChannelIdentityStep
              channelName={channelName}
              niche={niche}
              audience={audience}
              onChange={(field, value) => {
                if (field === "channelName") setChannelName(value);
                else if (field === "niche") setNiche(value);
                else if (field === "audience") setAudience(value);
              }}
              onNext={handleSaveChannel}
              saving={channelSaving}
              error={channelError}
            />
          )}

          {currentStepKey === "style" && (
            <StyleSetupStep
              styleDescription={styleDescription}
              onChange={setStyleDescription}
              onGenerate={handleGenerateStyle}
              onNext={handleNext}
              onSkip={handleSkip}
              generating={styleGenerating}
              generated={styleGenerated}
              summary={styleSummary}
              error={styleError}
            />
          )}

          {currentStepKey === "keys" && (
            <ApiKeysStep
              keys={apiKeys}
              onSaveKey={handleSaveApiKey}
              onTestKey={handleTestApiKey}
              onNext={handleNext}
            />
          )}

          {currentStepKey === "youtube" && (
            <YouTubeConnectStep
              connected={ytConnected}
              channelName={ytChannelName}
              onConnect={handleConnectYouTube}
              onNext={handleNext}
              onSkip={handleSkip}
              connecting={ytConnecting}
              syncing={ytSyncing}
              onStartSync={handleStartSync}
            />
          )}

          {currentStepKey === "video" && (
            <CreateVideoStep
              onComplete={() => {
                // Redirect handled inside CreateVideoStep
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
