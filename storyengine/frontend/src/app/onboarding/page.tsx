"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
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
  getYouTubeSyncStatus,
  type ReadinessKey,
} from "@/lib/api";
import { Spinner } from "@/components/ui/spinner";
import { UserTypeStep } from "@/components/onboarding/UserTypeStep";
import { ChannelIdentityStep } from "@/components/onboarding/ChannelIdentityStep";
import { StyleSetupStep } from "@/components/onboarding/StyleSetupStep";
import { ApiKeysStep } from "@/components/onboarding/ApiKeysStep";
import { YouTubeConnectStep } from "@/components/onboarding/YouTubeConnectStep";
import { ImportDataStep } from "@/components/onboarding/ImportDataStep";
import { ReadyStep } from "@/components/onboarding/ReadyStep";
import { Check, User, Palette, Key, Youtube, Download, Rocket } from "lucide-react";

// Step definitions per user type
const FRESH_STEPS = [
  { key: "type", label: "You", icon: User },
  { key: "channel", label: "Channel", icon: User },
  { key: "style", label: "Style", icon: Palette },
  { key: "keys", label: "Tools", icon: Key },
  { key: "ready", label: "Ready!", icon: Rocket },
];

const EXISTING_STEPS = [
  { key: "type", label: "You", icon: User },
  { key: "channel", label: "Channel", icon: Youtube },
  { key: "style", label: "Style", icon: Palette },
  { key: "keys", label: "Tools", icon: Key },
  { key: "import", label: "Import", icon: Download },
  { key: "ready", label: "Ready!", icon: Rocket },
];

export default function OnboardingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState(0);
  const [userType, setUserType] = useState<"new_creator" | "existing_channel" | null>(null);
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

  // Import state
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<{ videos_synced: number; videos_total: number } | null>(null);

  const steps = userType === "existing_channel" ? EXISTING_STEPS : FRESH_STEPS;

  // Check if onboarding is already complete
  useEffect(() => {
    getOnboardingStatus()
      .then((status) => {
        if (status.completed) {
          router.replace("/dashboard");
          return;
        }
        if (status.display_name) setDisplayName(status.display_name);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [router]);

  // Load API key readiness when reaching keys step
  const loadApiKeys = useCallback(async () => {
    try {
      const status = await getReadinessStatus();
      const all: { key: string; label: string; reason: string; url: string; configured: boolean }[] = [];
      for (const k of status.missing_keys) {
        all.push({ ...k, configured: false });
      }
      for (const key of status.configured_keys) {
        // Find the label from missing_keys or use key name
        all.push({ key, label: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()), reason: "", url: "", configured: true });
      }
      // Sort: unconfigured first
      all.sort((a, b) => (a.configured === b.configured ? 0 : a.configured ? 1 : -1));
      setApiKeys(all);
    } catch {
      // Fallback with static list
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

  function handleUserTypeSelect(type: "new_creator" | "existing_channel") {
    setUserType(type);
    updateChannelProfile({ user_type: type }).catch(() => {});
    setStep(1);
  }

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
      setStep(2);
    } catch (err) {
      setChannelError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setChannelSaving(false);
    }
  }

  async function handleConnectYouTube() {
    setYtConnecting(true);
    try {
      const { auth_url } = await getYouTubeConnectUrl();
      window.location.href = auth_url;
    } catch {
      setYtConnecting(false);
    }
  }

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
      setStyleError(err instanceof Error ? err.message : "Failed to generate style");
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

  async function handleSyncChannel() {
    setSyncing(true);
    try {
      await syncYouTubeMetrics();
      // Poll for completion
      const poll = setInterval(async () => {
        try {
          const status = await getYouTubeSyncStatus();
          if (!status.is_running) {
            clearInterval(poll);
            setSyncing(false);
            setSyncResult({
              videos_synced: status.videos_synced || 0,
              videos_total: status.videos_total || 0,
            });
          }
        } catch {
          clearInterval(poll);
          setSyncing(false);
        }
      }, 3000);
    } catch {
      setSyncing(false);
    }
  }

  function handleNext() {
    const nextStep = step + 1;
    if (nextStep >= steps.length) {
      router.replace("/dashboard");
      return;
    }

    // Load API keys when reaching the keys step
    const nextKey = steps[nextStep]?.key;
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

  const currentStepKey = steps[step]?.key;

  return (
    <div className="flex items-center justify-center min-h-screen px-4 py-12">
      <div className="w-full max-w-xl">
        {/* Progress Bar — hidden on user type selection */}
        {step > 0 && (
          <div className="flex items-center justify-center gap-0 mb-10">
            {steps.slice(1).map((s, i) => {
              const actualIdx = i + 1;
              const Icon = s.icon;
              const done = actualIdx < step;
              const active = actualIdx === step;
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
                  {i < steps.length - 2 && (
                    <div
                      className="w-12 h-px mx-1.5 mb-5"
                      style={{
                        background: actualIdx < step ? "var(--turquoise)" : "rgba(255,255,255,0.1)",
                      }}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Step Content */}
        {currentStepKey === "type" && (
          <UserTypeStep onSelect={handleUserTypeSelect} />
        )}

        {currentStepKey === "channel" && (
          <div
            className="p-8 rounded-2xl"
            style={{
              background: "rgba(15,22,38,0.65)",
              border: "1px solid rgba(0,212,170,0.12)",
              backdropFilter: "blur(24px)",
            }}
          >
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
              onSkip={handleSkip}
              saving={channelSaving}
              error={channelError}
              showYouTubeConnect={userType === "existing_channel"}
              youtubeConnected={ytConnected}
              youtubeChannelName={ytChannelName || undefined}
              onConnectYouTube={handleConnectYouTube}
            />
          </div>
        )}

        {currentStepKey === "style" && (
          <div
            className="p-8 rounded-2xl"
            style={{
              background: "rgba(15,22,38,0.65)",
              border: "1px solid rgba(0,212,170,0.12)",
              backdropFilter: "blur(24px)",
            }}
          >
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
          </div>
        )}

        {currentStepKey === "keys" && (
          <div
            className="p-8 rounded-2xl"
            style={{
              background: "rgba(15,22,38,0.65)",
              border: "1px solid rgba(0,212,170,0.12)",
              backdropFilter: "blur(24px)",
            }}
          >
            <ApiKeysStep
              keys={apiKeys}
              onSaveKey={handleSaveApiKey}
              onTestKey={handleTestApiKey}
              onNext={handleNext}
              onSkip={handleSkip}
            />
          </div>
        )}

        {currentStepKey === "import" && (
          <div
            className="p-8 rounded-2xl"
            style={{
              background: "rgba(15,22,38,0.65)",
              border: "1px solid rgba(0,212,170,0.12)",
              backdropFilter: "blur(24px)",
            }}
          >
            <ImportDataStep
              onSync={handleSyncChannel}
              onNext={handleNext}
              onSkip={handleSkip}
              syncing={syncing}
              syncResult={syncResult}
            />
          </div>
        )}

        {currentStepKey === "ready" && (
          <ReadyStep
            displayName={displayName || channelName || "Creator"}
            onStart={() => router.replace("/pipeline?first=true")}
          />
        )}

        {/* Skip setup link — shown on all steps except ready */}
        {currentStepKey !== "ready" && (
          <p
            className="text-[11px] text-center mt-4 cursor-pointer hover:underline"
            style={{ color: "var(--text-tertiary)" }}
            onClick={() => router.replace("/dashboard")}
          >
            Skip setup, go to Dashboard →
          </p>
        )}
      </div>
    </div>
  );
}
