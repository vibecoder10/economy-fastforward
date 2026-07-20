"use client";

import { useState, useMemo, useCallback } from "react";
import { Upload, Copy, ExternalLink, CheckCircle, AlertTriangle, ChevronRight, Loader2, Sparkles, Save } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { runPipelineStage, advanceVideo, generateVideoSeo, saveVideoSeo, getYouTubeStatus } from "@/lib/api";
import type { VideoDetail } from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { useToast } from "@/components/ui/toast";

const PIPELINE_ORDER = [
  "idea_logged", "approved", "researching", "ready_for_scripting", "scripting",
  "ready_for_voice", "voice", "ready_for_image_prompts", "ready_for_images",
  "ready_for_storyboards", "ready_for_storyboard_images",
  "ready_for_sound_design", "ready_for_sound_effects",
  "ready_for_video_scripts", "ready_for_video_generation",
  "ready_for_thumbnail", "ready_to_render", "rendering", "rendered",
  "uploaded", "uploaded_draft", "done",
];

function getUploadStatus(status: string, youtubeUrl?: string | null): string {
  if (youtubeUrl) return "uploaded_draft";
  const idx = PIPELINE_ORDER.indexOf(status);
  if (idx < 0) return "pending";
  if (status === "done" || status === "uploaded" || status === "uploaded_draft") return status;
  if (idx >= PIPELINE_ORDER.indexOf("rendered")) return "ready";
  return "pending";
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: "Not Rendered", color: "orange" },
  ready: { label: "Ready to Upload", color: "turquoise" },
  uploaded: { label: "Uploaded", color: "green" },
  uploaded_draft: { label: "Draft", color: "gold" },
  done: { label: "Published", color: "green" },
};

interface UploadTabProps {
  video: VideoDetail & {
    id: string;
    title?: string;
    thumbnailUrl?: string | null;
    uploadDate?: string | null;
  };
  onAdvanced?: () => void;
}

function extractVideoId(url: string | null | undefined): string | null {
  if (!url) return null;
  const match = url.match(/(?:v=|youtu\.be\/)([A-Za-z0-9_-]{11})/);
  return match ? match[1] : null;
}

export function UploadTab({ video, onAdvanced }: UploadTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  // The YouTube channel this upload will land on, for the ACTIVE workspace. Names
  // the destination in the confirm so an operator never posts to the wrong client.
  const { data: ytStatus } = useQuery({ queryKey: ["youtube-status"], queryFn: getYouTubeStatus });
  const destChannel = ytStatus?.channel_name || null;
  const youtubeUrl = video.youtube_url;
  const videoIdYt = extractVideoId(youtubeUrl);
  const uploadStatus = getUploadStatus(video.status || "", youtubeUrl);
  const statusCfg = STATUS_MAP[uploadStatus] || STATUS_MAP.pending;
  const isNotRendered = uploadStatus === "pending";

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const vid = video as any;
  const videoTitle = vid.video_title || video.title || "";

  // SEO comes from the stored, content-driven metadata (videos.seo_*). No more
  // hardcoded #economy #geopolitics #finance, no title-only tag scraping.
  const [title, setTitle] = useState(videoTitle);
  const [description, setDescription] = useState<string>((vid.seo_description as string) || "");
  const [tagsStr, setTagsStr] = useState<string>(
    ((vid.seo_tags as string) || "").split(",").map((t: string) => t.trim()).filter(Boolean).join(", "),
  );
  const tags = useMemo(
    () => tagsStr.split(",").map((t) => t.trim()).filter(Boolean),
    [tagsStr],
  );
  const hasSeo = description.trim().length > 0;
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [confirmUpload, setConfirmUpload] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadComplete, setUploadComplete] = useState(!!youtubeUrl);

  const handleRegenerate = useCallback(async () => {
    setGenerating(true);
    try {
      const seo = await generateVideoSeo(video.id);
      setDescription(seo.description || "");
      setTagsStr((seo.tags || []).join(", "));
      toast.success("SEO generated from the video's content.");
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      toast.error(`Couldn't generate SEO: ${(err as Error).message}`);
    } finally {
      setGenerating(false);
    }
  }, [video.id, queryClient, toast]);

  const handleSaveSeo = useCallback(async () => {
    setSaving(true);
    try {
      await saveVideoSeo(video.id, { title, description, tags });
      toast.success("SEO saved — this is what gets uploaded.");
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      toast.error(`Couldn't save SEO: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  }, [video.id, title, description, tags, queryClient, toast]);

  const [advancing, setAdvancing] = useState(false);
  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      onAdvanced?.();
    } catch (err) {
      toast.error(`Failed to advance: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, queryClient, onAdvanced]);

  const handleCopy = useCallback(() => {
    if (!youtubeUrl) return;
    navigator.clipboard.writeText(youtubeUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [youtubeUrl]);

  const handleUpload = useCallback(async () => {
    setIsUploading(true);
    try {
      // Persist exactly what's on screen first, so the upload uses the creator's
      // edited title/description/tags — not a stale or regenerated version.
      await saveVideoSeo(video.id, { title, description, tags });
      await runPipelineStage(video.id, "upload");
      setUploadComplete(true);
    } catch (err) {
      toast.error(`Upload failed: ${(err as Error).message}`);
    } finally {
      setIsUploading(false);
      setConfirmUpload(false);
    }
  }, [video.id, title, description, tags, toast]);

  if (isNotRendered) {
    return (
      <GlassCard className="p-12 text-center">
        <Upload
          size={32}
          className="mx-auto mb-3"
          style={{ color: "var(--text-tertiary)", opacity: 0.4 }}
        />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Not Yet Rendered
        </p>
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
          The video must be rendered before it can be uploaded to YouTube.
          Go to the Render tab to start rendering.
        </p>
      </GlassCard>
    );
  }

  return (
    <>
    {/* Top action bar */}
    <div className="rounded-xl px-4 py-3 mb-4" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-4 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
          <span>Upload: <span style={{ color: statusCfg.color === "green" ? "var(--green)" : statusCfg.color === "gold" ? "var(--gold)" : statusCfg.color === "turquoise" ? "var(--turquoise)" : "var(--text-tertiary)" }}>{statusCfg.label}</span></span>
        </div>
        <button onClick={handleAdvanceStage} disabled={advancing}
          className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 disabled:opacity-50 transition-all hover:brightness-110"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
          {advancing ? <Loader2 size={12} className="animate-spin" /> : null}
          Advance Stage <ChevronRight size={12} />
        </button>
      </div>
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Left column */}
      <div className="space-y-4">
        {/* Preview */}
        <GlassCard className="p-0 overflow-hidden">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-0">
            <div
              className="aspect-video relative flex items-center justify-center"
              style={{ background: "var(--bg-elevated)" }}
            >
              <svg className="absolute inset-0 w-full h-full opacity-10">
                <defs>
                  <pattern id="up-grid-v" width="40" height="40" patternUnits="userSpaceOnUse">
                    <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--turquoise)" strokeWidth="0.5" />
                  </pattern>
                </defs>
                <rect width="100%" height="100%" fill="url(#up-grid-v)" />
              </svg>
              <div className="text-center z-10">
                <div
                  className="w-12 h-12 rounded-xl mx-auto mb-2 flex items-center justify-center"
                  style={{ background: "var(--turquoise-dim)" }}
                >
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                    <polygon points="10,8 16,12 10,16" fill="var(--turquoise)" />
                  </svg>
                </div>
                <p className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                  Video Preview
                </p>
              </div>
            </div>

            <div
              className="aspect-video relative flex items-center justify-center"
              style={{ background: "var(--bg-void)" }}
            >
              {video.thumbnail_url || vid.thumbnailUrl ? (
                <img
                  src={toDisplayImageUrl(video.thumbnail_url || vid.thumbnailUrl)}
                  alt="Thumbnail"
                  className="w-full h-full object-cover"
                />
              ) : (
                <>
                  <svg className="absolute inset-0 w-full h-full opacity-10">
                    <defs>
                      <pattern id="up-grid-t" width="40" height="40" patternUnits="userSpaceOnUse">
                        <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--gold)" strokeWidth="0.5" />
                      </pattern>
                    </defs>
                    <rect width="100%" height="100%" fill="url(#up-grid-t)" />
                  </svg>
                  <p className="text-[10px] font-mono z-10" style={{ color: "var(--text-tertiary)" }}>
                    Thumbnail
                  </p>
                </>
              )}
            </div>
          </div>
        </GlassCard>

        {/* SEO Preview */}
        <GlassCard className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h3
              className="text-xs font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-secondary)" }}
            >
              SEO Preview
            </h3>
            <div className="flex items-center gap-2">
              <button
                onClick={handleRegenerate}
                disabled={generating}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-semibold disabled:opacity-50 transition-all hover:brightness-110"
                style={{ color: "var(--turquoise)", border: "1px solid rgba(0,212,170,0.3)" }}
              >
                {generating ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
                {hasSeo ? "Regenerate" : "Generate SEO"}
              </button>
              <button
                onClick={handleSaveSeo}
                disabled={saving || !hasSeo}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-semibold disabled:opacity-40 transition-all hover:brightness-110"
                style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
              >
                {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
                Save
              </button>
            </div>
          </div>

          {!hasSeo && (
            <div
              className="rounded-lg px-3 py-2 mb-4 text-[11px]"
              style={{ background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.2)", color: "var(--text-secondary)" }}
            >
              No SEO yet. Tap <strong>Generate SEO</strong> to write a description + tags from this video&apos;s actual content.
            </div>
          )}

          <div className="mb-4">
            <label
              className="text-[10px] font-medium uppercase tracking-wider block mb-1"
              style={{ color: "var(--text-tertiary)" }}
            >
              Title
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none transition-all"
              style={{
                background: "var(--bg-elevated)",
                color: "var(--text-primary)",
                border: "1px solid var(--border)",
              }}
              onFocus={(e) => { e.target.style.borderColor = "var(--turquoise)"; }}
              onBlur={(e) => { e.target.style.borderColor = "var(--border)"; }}
            />
            <span
              className="text-[10px] font-mono mt-1 block text-right"
              style={{ color: title.length > 70 ? "var(--red)" : "var(--text-tertiary)" }}
            >
              {title.length}/100
            </span>
          </div>

          <div className="mb-4">
            <label
              className="text-[10px] font-medium uppercase tracking-wider block mb-1"
              style={{ color: "var(--text-tertiary)" }}
            >
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={8}
              className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none transition-all resize-none"
              style={{
                background: "var(--bg-elevated)",
                color: "var(--text-primary)",
                border: "1px solid var(--border)",
              }}
              onFocus={(e) => { e.target.style.borderColor = "var(--turquoise)"; }}
              onBlur={(e) => { e.target.style.borderColor = "var(--border)"; }}
            />
          </div>

          <div className="mb-1">
            <label
              className="text-[10px] font-medium uppercase tracking-wider block mb-1"
              style={{ color: "var(--text-tertiary)" }}
            >
              Tags (comma-separated)
            </label>
            <input
              type="text"
              value={tagsStr}
              onChange={(e) => setTagsStr(e.target.value)}
              placeholder="learn english, esl, slow english, listening practice"
              className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none transition-all"
              style={{
                background: "var(--bg-elevated)",
                color: "var(--text-primary)",
                border: "1px solid var(--border)",
              }}
              onFocus={(e) => { e.target.style.borderColor = "var(--turquoise)"; }}
              onBlur={(e) => { e.target.style.borderColor = "var(--border)"; }}
            />
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-[10px] font-mono px-2 py-1 rounded-full"
                    style={{
                      background: "var(--turquoise-dim)",
                      color: "var(--turquoise)",
                      border: "1px solid rgba(0, 212, 170, 0.2)",
                    }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        </GlassCard>

        {/* YouTube URL display */}
        {youtubeUrl && (
          <GlassCard className="p-4">
            <div className="flex items-center gap-3">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: "rgba(255, 0, 0, 0.15)" }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="#FF0000">
                  <path d="M23.5 6.2A3 3 0 0021.4 4C19.6 3.5 12 3.5 12 3.5s-7.6 0-9.4.5A3 3 0 00.5 6.2 31.9 31.9 0 000 12a31.9 31.9 0 00.5 5.8A3 3 0 002.6 20c1.8.5 9.4.5 9.4.5s7.6 0 9.4-.5a3 3 0 002.1-2.2A31.9 31.9 0 0024 12a31.9 31.9 0 00-.5-5.8zM9.8 15.5V8.5l6.2 3.5-6.2 3.5z" />
                </svg>
              </div>
              <a
                href={youtubeUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-mono flex-1 truncate hover:underline"
                style={{ color: "var(--turquoise)" }}
              >
                {youtubeUrl}
              </a>
              <button
                onClick={handleCopy}
                className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 transition-all"
                style={{
                  background: copied ? "rgba(0, 230, 138, 0.15)" : "var(--bg-elevated)",
                  color: copied ? "var(--green)" : "var(--text-secondary)",
                }}
              >
                {copied ? <CheckCircle size={14} /> : <Copy size={14} />}
              </button>
            </div>
          </GlassCard>
        )}
      </div>

      {/* Right sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Upload Status
          </h3>
          <div className="flex justify-center mb-4">
            <StatusPill label={statusCfg.label} color={statusCfg.color} size="md" />
          </div>
          <div className="space-y-3">
            {[
              ...(video.uploadDate || video.created_at
                ? [{
                    label: "Upload Date",
                    value: new Date(
                      (video.uploadDate || video.created_at) as string,
                    ).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    }),
                  }]
                : []),
              ...(videoIdYt ? [{ label: "Video ID", value: videoIdYt }] : []),
              {
                label: "Visibility",
                value: uploadStatus === "done" ? "Public" : "Unlisted",
              },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {row.label}
                </span>
                <span
                  className="text-sm font-mono font-medium"
                  style={{ color: "var(--text-primary)" }}
                >
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>

        <div className="space-y-2">
          {confirmUpload ? (
            <>
              {/* Confirmation warning — names the destination channel so an
                  operator can't upload to the wrong client by accident. */}
              <GlassCard className="p-3" style={{ borderColor: "var(--gold)", borderWidth: 1 }}>
                <div className="flex items-start gap-2">
                  <AlertTriangle
                    size={14}
                    className="flex-shrink-0 mt-0.5"
                    style={{ color: "var(--gold)" }}
                  />
                  <div className="text-[11px] leading-relaxed" style={{ color: "var(--gold)" }}>
                    {destChannel ? (
                      <p>
                        Uploading to YouTube channel{" "}
                        <span className="font-bold" style={{ color: "var(--text-primary)" }}>
                          {destChannel}
                        </span>{" "}
                        as an UNLISTED draft. Wrong channel? Switch workspace first.
                      </p>
                    ) : (
                      <p>
                        No YouTube channel is connected for this workspace — connect one in
                        Settings before uploading.
                      </p>
                    )}
                  </div>
                </div>
              </GlassCard>
              <button
                className="w-full inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  background: "transparent",
                  color: "var(--gold)",
                  border: "1px solid var(--gold)",
                }}
                onClick={handleUpload}
                disabled={isUploading || !destChannel}
              >
                <Upload size={16} />
                {isUploading ? "Uploading..." : "Confirm Upload"}
              </button>
              <ActionButton
                variant="outline"
                className="w-full"
                onClick={() => setConfirmUpload(false)}
              >
                Cancel
              </ActionButton>
            </>
          ) : (
            <button
              className="w-full inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                background: "transparent",
                color: "var(--gold)",
                border: "1px solid var(--gold)",
              }}
              onClick={() => setConfirmUpload(true)}
              disabled={uploadComplete && !!youtubeUrl}
            >
              <Upload size={16} />
              {uploadComplete && youtubeUrl ? "Uploaded" : "Upload to YouTube"}
            </button>
          )}
          {youtubeUrl && (
            <>
              <ActionButton
                variant="outline"
                icon={Copy}
                className="w-full"
                onClick={handleCopy}
              >
                {copied ? "Copied!" : "Copy URL"}
              </ActionButton>
              <ActionButton
                variant="outline"
                icon={ExternalLink}
                className="w-full"
                onClick={() => window.open(youtubeUrl, "_blank")}
              >
                Open in YouTube Studio
              </ActionButton>
            </>
          )}
        </div>
      </div>
    </div>
    </>
  );
}
