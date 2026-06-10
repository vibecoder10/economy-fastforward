"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, RefreshCw, Wand2 } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { modelVideo, retryModelVideo } from "@/lib/api";
import { humanizeError } from "@/lib/errors";

interface ModelVideoModalProps {
  open: boolean;
  onClose: () => void;
}

const YT_HINT = /(?:youtube\.com\/(?:watch|shorts|embed|live)|youtu\.be\/)/;

/**
 * "Model A Video" — paste a YouTube link, we analyze it and create a brand-new
 * modeled idea + prompt pack as a fresh video in the pipeline. The backend task
 * is polled via the shared pipeline task endpoint, so progress messages stream
 * straight from the modeling stages (extract → analyze → generate → save).
 */
export function ModelVideoModal({ open, onClose }: ModelVideoModalProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [url, setUrl] = useState("");
  const [videoId, setVideoId] = useState<string | null>(null);
  const [phase, setPhase] = useState<"input" | "running" | "failed">("input");
  const [submitting, setSubmitting] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  const { message } = useTaskPoller({
    videoId: videoId ?? "",
    enabled: phase === "running" && !!videoId,
    interval: 3000,
    onComplete: (msg) => {
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(msg || "Modeled idea ready — opening it now.");
      handleReset();
      onClose();
      if (videoId) router.push(`/pipeline/${videoId}`);
    },
    onFailed: (err) => {
      setErrorText(humanizeError(err, "We couldn't finish modeling that video."));
      setPhase("failed");
    },
  });

  const handleReset = () => {
    setUrl("");
    setVideoId(null);
    setPhase("input");
    setErrorText(null);
    setSubmitting(false);
  };

  const handleClose = () => {
    if (phase === "running") {
      toast.info("Modeling continues in the background — the new video will appear in your pipeline.");
    }
    handleReset();
    onClose();
  };

  const handleSubmit = async () => {
    const trimmed = url.trim();
    if (!YT_HINT.test(trimmed)) {
      setErrorText("Paste a YouTube video link (youtube.com or youtu.be).");
      return;
    }
    setSubmitting(true);
    setErrorText(null);
    try {
      const res = await modelVideo(trimmed);
      setVideoId(res.video_id);
      setPhase("running");
    } catch (err) {
      setErrorText(humanizeError(err, "We couldn't start modeling that video."));
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetry = async () => {
    if (!videoId) {
      setPhase("input");
      return;
    }
    setSubmitting(true);
    setErrorText(null);
    try {
      await retryModelVideo(videoId);
      setPhase("running");
    } catch (err) {
      setErrorText(humanizeError(err, "We couldn't restart modeling."));
      setPhase("failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={handleClose} title="Model A Video" size="md">
      {phase === "input" && (
        <div className="space-y-4">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Paste a YouTube video you admire. We&apos;ll study why it works — title,
            hook, pacing, visual style — and create a brand-new video idea for your
            channel with a full prompt pack, ready to review before anything is generated.
          </p>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !submitting) handleSubmit();
            }}
            placeholder="https://www.youtube.com/watch?v=..."
            autoFocus
            className="w-full px-4 py-3 rounded-lg text-sm font-body outline-none transition-all"
            style={{
              background: "var(--bg-elevated)",
              color: "var(--text-primary)",
              border: "1px solid var(--border)",
            }}
          />
          {errorText && (
            <p className="text-sm flex items-center gap-2" style={{ color: "var(--red)" }}>
              <AlertTriangle size={14} /> {errorText}
            </p>
          )}
          <button
            onClick={handleSubmit}
            disabled={submitting || !url.trim()}
            className="w-full px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50 flex items-center justify-center gap-2"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : <Wand2 size={16} />}
            {submitting ? "Starting…" : "Model This Video"}
          </button>
        </div>
      )}

      {phase === "running" && (
        <div className="space-y-4 py-2 text-center">
          <Loader2 size={28} className="animate-spin mx-auto" style={{ color: "var(--turquoise)" }} />
          <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            {message || "Modeling your reference video…"}
          </p>
          <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            This takes a minute or two. You can close this — the new video will
            appear in your pipeline when it&apos;s ready.
          </p>
        </div>
      )}

      {phase === "failed" && (
        <div className="space-y-4 py-2">
          <p className="text-sm flex items-start gap-2" style={{ color: "var(--red)" }}>
            <AlertTriangle size={16} className="shrink-0 mt-0.5" />
            {errorText || "We couldn't finish modeling that video."}
          </p>
          <div className="flex gap-3">
            <button
              onClick={handleRetry}
              disabled={submitting}
              className="flex-1 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50 flex items-center justify-center gap-2"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              {submitting ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
              Retry
            </button>
            <button
              onClick={() => {
                setPhase("input");
                setErrorText(null);
              }}
              className="flex-1 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all"
              style={{
                background: "transparent",
                color: "var(--text-secondary)",
                border: "1px solid var(--border)",
              }}
            >
              Different Link
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
