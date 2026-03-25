"use client";

import { useState } from "react";
import { Upload, Copy, ExternalLink, CheckCircle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import type { Video } from "@/lib/types";

const MOCK_STATUS: string = "uploaded_draft";
const MOCK_VIDEO_ID = "dQw4w9WgXcQ";
const MOCK_URL = `https://www.youtube.com/watch?v=${MOCK_VIDEO_ID}`;
const MOCK_UPLOAD_DATE = "2026-03-24T14:30:00Z";

const MOCK_DESCRIPTION = `Iran's shadow economy has been quietly building an alternative financial infrastructure that Western sanctions failed to anticipate.

Key insights:
- The IRGC controls over 40% of Iran's non-oil GDP through a network of front companies
- China's Belt and Road Initiative provided the critical bypass to SWIFT sanctions
- The parallel banking system now processes $12B annually outside Western oversight
- Three decades of sanctions created the very economic resilience the West sought to prevent

Sources:
- RAND Corporation: "Iran's Political Economy" (2024)
- Council on Foreign Relations: Shadow Banking Report
- IMF Working Paper: Sanctions Evasion Mechanisms

#economy #iran #geopolitics #sanctions #finance`;

const MOCK_TAGS = [
  "Iran Economy",
  "Sanctions",
  "Shadow Banking",
  "Geopolitics",
  "IRGC",
  "Belt and Road",
  "China Iran",
  "Economic Warfare",
];

const MOCK_HASHTAGS = ["#economy", "#iran", "#geopolitics", "#sanctions"];

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: "Not Uploaded", color: "orange" },
  uploaded_draft: { label: "Draft", color: "gold" },
  published: { label: "Published", color: "green" },
};

interface UploadTabProps {
  video: Video;
}

export function UploadTab({ video }: UploadTabProps) {
  const [title, setTitle] = useState(video.title || "Iran's $400B Shadow Empire");
  const [description, setDescription] = useState(MOCK_DESCRIPTION);
  const [copied, setCopied] = useState(false);
  const [confirmUpload, setConfirmUpload] = useState(false);

  const statusCfg = STATUS_MAP[MOCK_STATUS] || STATUS_MAP.pending;
  const isPublished = MOCK_STATUS === "published";

  const handleCopy = () => {
    navigator.clipboard.writeText(MOCK_URL);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Left column */}
      <div className="space-y-4">
        {/* Preview card: video + thumbnail side by side */}
        <GlassCard className="p-0 overflow-hidden">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-0">
            {/* Video placeholder */}
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

            {/* Thumbnail placeholder */}
            <div
              className="aspect-video relative flex items-center justify-center"
              style={{ background: "var(--bg-void)" }}
            >
              {video.thumbnailUrl ? (
                <img src={video.thumbnailUrl} alt="Thumbnail" className="w-full h-full object-cover" />
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
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-4"
            style={{ color: "var(--text-secondary)" }}
          >
            SEO Preview
          </h3>

          {/* Title input */}
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

          {/* Description textarea */}
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

          {/* Tags */}
          <div className="mb-4">
            <label
              className="text-[10px] font-medium uppercase tracking-wider block mb-2"
              style={{ color: "var(--text-tertiary)" }}
            >
              Tags
            </label>
            <div className="flex flex-wrap gap-1.5">
              {MOCK_TAGS.map((tag) => (
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
          </div>

          {/* Hashtags */}
          <div>
            <label
              className="text-[10px] font-medium uppercase tracking-wider block mb-2"
              style={{ color: "var(--text-tertiary)" }}
            >
              Hashtags
            </label>
            <div className="flex flex-wrap gap-1.5">
              {MOCK_HASHTAGS.map((ht) => (
                <span
                  key={ht}
                  className="text-[10px] font-mono px-2 py-1 rounded-full"
                  style={{
                    background: "rgba(212, 168, 82, 0.1)",
                    color: "var(--gold)",
                    border: "1px solid rgba(212, 168, 82, 0.2)",
                  }}
                >
                  {ht}
                </span>
              ))}
            </div>
          </div>
        </GlassCard>

        {/* YouTube URL display */}
        {MOCK_VIDEO_ID && (
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
                href={MOCK_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-mono flex-1 truncate hover:underline"
                style={{ color: "var(--turquoise)" }}
              >
                {MOCK_URL}
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
              {
                label: "Upload Date",
                value: new Date(MOCK_UPLOAD_DATE).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                }),
              },
              { label: "Video ID", value: MOCK_VIDEO_ID },
              { label: "Visibility", value: isPublished ? "Public" : "Unlisted" },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {row.label}
                </span>
                <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>

        <div className="space-y-2">
          {confirmUpload ? (
            <ActionButton
              variant="filled"
              icon={Upload}
              className="w-full"
              onClick={() => setConfirmUpload(false)}
            >
              Confirm Upload
            </ActionButton>
          ) : (
            <button
              className="w-full inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98]"
              style={{ background: "var(--gold)", color: "var(--bg-void)", border: "1px solid var(--gold)" }}
              onClick={() => setConfirmUpload(true)}
            >
              <Upload size={16} />
              Upload to YouTube
            </button>
          )}
          <ActionButton variant="outline" icon={Copy} className="w-full" onClick={handleCopy}>
            {copied ? "Copied!" : "Copy URL"}
          </ActionButton>
          <ActionButton variant="outline" icon={ExternalLink} className="w-full">
            Open in YouTube Studio
          </ActionButton>
        </div>
      </div>
    </div>
  );
}
