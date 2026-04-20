"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Check, Youtube, BarChart3, Sparkles } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import { getMyYouTubeVideos, type MyYouTubeVideo } from "@/lib/api";
import { humanizeError } from "@/lib/errors";

interface YouTubeConnectStepProps {
  connected: boolean;
  channelName: string | null;
  onConnect: () => void;
  onNext: () => void;
  onSkip: () => void;
  connecting: boolean;
  syncing?: boolean;
  onStartSync?: () => void;
  // Voice-learn step (Flow B slice 2): parent fires learn-voice when user
  // advances, these props drive the "learning your voice..." UI inline.
  voiceLearning?: boolean;
  voiceLearned?: boolean;
  voiceSourceCount?: number;
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function YouTubeConnectStep({
  connected,
  channelName,
  onConnect,
  onNext,
  onSkip,
  connecting,
  syncing,
  onStartSync,
  voiceLearning = false,
  voiceLearned = false,
  voiceSourceCount = 0,
}: YouTubeConnectStepProps) {
  // Flow B: after OAuth succeeds, fetch the user's top-performing videos.
  // Presence of videos tells us they're an existing-channel user (not a
  // brand-new creator) and sets up the voice-learn step that will follow
  // in a later onboarding screen.
  const [topVideos, setTopVideos] = useState<MyYouTubeVideo[] | null>(null);
  const [loadingVideos, setLoadingVideos] = useState(false);
  const [videosError, setVideosError] = useState<string | null>(null);

  // Auto-trigger metrics sync when YouTube gets connected
  useEffect(() => {
    if (connected && onStartSync) {
      onStartSync();
    }
  }, [connected, onStartSync]);

  // Auto-fetch the user's own top videos when connection flips on.
  // Runs in parallel with the analytics sync above — distinct data source.
  useEffect(() => {
    if (!connected || topVideos !== null || loadingVideos) return;
    let cancelled = false;
    setLoadingVideos(true);
    setVideosError(null);
    getMyYouTubeVideos(5, "views")
      .then((res) => {
        if (cancelled) return;
        setTopVideos(res.videos);
      })
      .catch((err) => {
        if (cancelled) return;
        // Don't block onboarding if the fetch fails — user can still
        // continue. The voice-learn step is additive, not required.
        setVideosError(humanizeError(err, "We couldn't load your videos yet."));
      })
      .finally(() => {
        if (!cancelled) setLoadingVideos(false);
      });
    return () => {
      cancelled = true;
    };
  }, [connected, topVideos, loadingVideos]);

  const hasVideos = topVideos !== null && topVideos.length > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="w-full max-w-lg mx-auto"
    >
      <GlassCard className="flex flex-col items-center text-center gap-6 py-10">
        <div>
          <h2
            className="text-xl font-semibold font-body mb-1"
            style={{ color: "var(--text-primary)" }}
          >
            Connect YouTube
          </h2>
          <p
            className="text-sm font-body"
            style={{ color: "var(--text-secondary)" }}
          >
            Link your channel to unlock analytics and auto-sync performance data.
          </p>
        </div>

        {connected ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.3 }}
            className="w-full space-y-3"
          >
            <GlassCard
              className="border"
              style={{ borderColor: "var(--success)" }}
            >
              <div className="flex items-center gap-3">
                <Check size={20} style={{ color: "var(--success)" }} />
                <span
                  className="text-sm font-semibold font-body"
                  style={{ color: "var(--text-primary)" }}
                >
                  Connected: {channelName}
                </span>
              </div>
            </GlassCard>

            {loadingVideos && (
              <div className="flex items-center justify-center gap-2 py-2">
                <Spinner size="sm" />
                <span className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
                  Detecting your top videos...
                </span>
              </div>
            )}

            {hasVideos && topVideos && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.1 }}
                className="space-y-2"
              >
                <div
                  className="flex items-center justify-center gap-2 text-xs font-body pt-1"
                  style={{ color: "var(--accent)" }}
                >
                  <Sparkles size={14} />
                  <span>
                    We found {topVideos.length} top-performing video{topVideos.length === 1 ? "" : "s"} on your channel
                  </span>
                </div>
                <div className="space-y-1.5 text-left">
                  {topVideos.map((v) => (
                    <div
                      key={v.video_id}
                      className="flex items-center gap-3 rounded-lg px-3 py-2"
                      style={{
                        background: "rgba(255,255,255,0.04)",
                        border: "1px solid rgba(255,255,255,0.08)",
                      }}
                    >
                      {v.thumbnail && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={v.thumbnail}
                          alt=""
                          className="w-12 h-9 rounded object-cover flex-shrink-0"
                        />
                      )}
                      <div className="flex-1 min-w-0">
                        <div
                          className="text-xs font-body truncate"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {v.title}
                        </div>
                        <div
                          className="text-[10px] font-body"
                          style={{ color: "var(--text-tertiary)" }}
                        >
                          {formatCount(v.views)} views
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <p
                  className="text-[11px] font-body pt-1"
                  style={{ color: "var(--text-tertiary)" }}
                >
                  We'll use these to learn your voice in the next step.
                </p>
              </motion.div>
            )}

            {topVideos !== null && topVideos.length === 0 && !loadingVideos && (
              <p
                className="text-xs font-body"
                style={{ color: "var(--text-tertiary)" }}
              >
                No videos found on this channel yet — no worries, we'll help you plan your first one.
              </p>
            )}

            {videosError && (
              <p
                className="text-xs font-body"
                style={{ color: "var(--text-tertiary)" }}
              >
                {videosError}
              </p>
            )}

            {syncing && (
              <div className="flex items-center justify-center gap-2">
                <Spinner size="sm" />
                <span className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
                  Syncing your analytics in the background...
                </span>
              </div>
            )}

            {voiceLearning && (
              <div className="flex items-center justify-center gap-2 pt-1">
                <Spinner size="sm" />
                <span className="text-xs font-body" style={{ color: "var(--accent)" }}>
                  Learning your voice from your top videos...
                </span>
              </div>
            )}

            {voiceLearned && voiceSourceCount > 0 && (
              <div
                className="flex items-center justify-center gap-2 text-xs font-body pt-1"
                style={{ color: "var(--success)" }}
              >
                <Check size={14} />
                <span>
                  Voice learned from your top {voiceSourceCount} video{voiceSourceCount === 1 ? "" : "s"} — we'll pre-fill your style
                </span>
              </div>
            )}
          </motion.div>
        ) : (
          <>
            <div className="flex items-center gap-2 text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
              <BarChart3 size={14} />
              <span>Your analytics dashboard will populate automatically</span>
            </div>
            <ActionButton
              icon={Youtube}
              onClick={onConnect}
              disabled={connecting}
            >
              {connecting ? (
                <span className="flex items-center gap-2">
                  <Spinner size="sm" /> Connecting...
                </span>
              ) : (
                "Connect YouTube"
              )}
            </ActionButton>
          </>
        )}

        <div className="flex flex-col items-center gap-3 pt-2">
          <ActionButton onClick={onNext} disabled={voiceLearning}>
            {voiceLearning ? (
              <span className="flex items-center gap-2">
                <Spinner size="sm" /> Learning your voice...
              </span>
            ) : (
              "Continue"
            )}
          </ActionButton>

          {!connected && (
            <button
              onClick={onSkip}
              className="text-xs font-body hover:underline"
              style={{ color: "var(--text-secondary)" }}
            >
              Skip — you can connect later in Settings
            </button>
          )}
        </div>
      </GlassCard>
    </motion.div>
  );
}
