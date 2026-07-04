"use client";

import { useRef, useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CheckCircle2,
  Loader2,
  MapPin,
  MapPinOff,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { useToast } from "@/components/ui/toast";
import { useTaskPoller } from "@/hooks/use-task-poller";
import {
  approveEnvironments,
  deleteEnvironment,
  designEnvironments,
  getEnvironments,
  regenerateEnvironment,
  skipEnvironments,
  updateEnvironment,
  uploadEnvironmentImage,
  type VideoEnvironment,
  type VideoDetail,
  getPipelineTaskStatus,
} from "@/lib/api";
import { humanizeError } from "@/lib/errors";
import { toDisplayImageUrl } from "@/lib/utils";

interface EnvironmentsTabProps {
  video: VideoDetail & { id: string };
  onApproved?: () => void;
}

/**
 * Per-video environment design — the location-consistency moment.
 * Generate a reference image per script location (in the video's visual style),
 * regenerate / edit / upload replacements, then Approve the environments.
 * Approved references lock how each location looks across storyboards and images.
 */
export function EnvironmentsTab({ video, onApproved }: EnvironmentsTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [taskRunning, setTaskRunning] = useState(false);

  // Rehydrate after a page refresh: pick the running task back up so the tab
  // shows live progress instead of dead buttons (state used to be
  // session-local; a refresh went blind while the backend kept working).
  useEffect(() => {
    let cancelled = false;
    getPipelineTaskStatus(video.id)
      .then((task) => {
        if (cancelled || !task || task.status !== "running") return;
        const msg = (task.message || "").toLowerCase();
        if (msg.includes("environment") || msg.includes("location")) setTaskRunning(true);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [video.id]);
  const [approving, setApproving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDesc, setEditDesc] = useState("");
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  const { data, isLoading } = useQuery({
    queryKey: ["video-environments", video.id],
    queryFn: () => getEnvironments(video.id),
  });

  const environments: VideoEnvironment[] = data?.environments ?? [];
  const approvedAt = data?.approved_at ?? null;
  const allHaveImages = environments.length > 0 && environments.every((e) => e.reference_url);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["video-environments", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
  };

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 3000,
    onComplete: (msg) => {
      setTaskRunning(false);
      refresh();
      if (msg) toast.success(msg);
      // Approve runs as a background task now — advance to Scenes only once it
      // actually finishes (locations locked).
      if (approving) {
        setApproving(false);
        onApproved?.();
      }
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setApproving(false);
      refresh();
      toast.error(humanizeError(error, "Environment design hit a snag."));
    },
  });

  const designMutation = useMutation({
    mutationFn: () => designEnvironments(video.id),
    onSuccess: () => setTaskRunning(true),
    onError: (err) => toast.error(humanizeError(err, "We couldn't start environment design.")),
  });

  const regenMutation = useMutation({
    mutationFn: (envId: string) => regenerateEnvironment(video.id, envId),
    onSuccess: () => setTaskRunning(true),
    onError: (err) => toast.error(humanizeError(err, "We couldn't redesign that environment.")),
  });

  const approveMutation = useMutation({
    mutationFn: () => approveEnvironments(video.id),
    // Approve is a background task — flip into the polled "approving" state so
    // the button shows live progress ("Locking in kitchen (1/8)…") instead of a
    // ~100s silent request that trips the fetch timeout ("servers hit a snag").
    // onApproved fires from the poller onComplete.
    onSuccess: () => {
      setApproving(true);
      setTaskRunning(true);
    },
    onError: (err) => toast.error(humanizeError(err, "We couldn't approve the environments.")),
  });

  // For location-less videos (talking head, explainer): mark "no locations" so
  // the storyboard gate passes without designing any.
  const skipMutation = useMutation({
    mutationFn: () => skipEnvironments(video.id),
    onSuccess: () => {
      refresh();
      toast.success("Marked as no locations — storyboards unlocked.");
      onApproved?.();
    },
    onError: (err) => toast.error(humanizeError(err, "We couldn't skip environments.")),
  });

  const handleSkip = () => {
    if (window.confirm("Skip environment design? Use this only if the video has no real locations to keep consistent.")) {
      skipMutation.mutate();
    }
  };

  const handleUpload = async (envId: string, file: File | undefined) => {
    if (!file) return;
    try {
      await uploadEnvironmentImage(video.id, envId, file);
      refresh();
      toast.success("Reference image replaced.");
    } catch (err) {
      toast.error(humanizeError(err, "Upload failed."));
    }
  };

  const handleSaveDesc = async (envId: string) => {
    try {
      await updateEnvironment(video.id, envId, { description: editDesc });
      setEditingId(null);
      refresh();
      toast.success("Description updated — regenerate to apply it to the reference image.");
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't save the description."));
    }
  };

  const handleDelete = async (envId: string, name: string) => {
    if (!window.confirm(`Remove ${name} from this video's environments?`)) return;
    try {
      await deleteEnvironment(video.id, envId);
      refresh();
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't remove the environment."));
    }
  };

  if (isLoading) {
    return (
      <GlassCard className="p-12 text-center">
        <Loader2 size={28} className="animate-spin mx-auto" style={{ color: "var(--turquoise)" }} />
      </GlassCard>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header / status */}
      <GlassCard className="p-5">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <p className="text-lg font-display flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <MapPin size={20} style={{ color: "var(--turquoise)" }} /> Environment Design
            </p>
            <p className="text-sm mt-1 max-w-xl" style={{ color: "var(--text-tertiary)" }}>
              Lock how every location looks BEFORE storyboards and images. These
              references are sent with every generation so the same place looks
              the same in every frame.
            </p>
            {approvedAt ? (
              <p className="text-sm mt-2 flex items-center gap-1.5" style={{ color: "var(--green)" }}>
                <CheckCircle2 size={15} /> Environments approved — references locked.
              </p>
            ) : environments.length > 0 ? (
              <p className="text-sm mt-2" style={{ color: "var(--gold)" }}>
                Review the locations below, then approve to lock the references.
              </p>
            ) : null}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <ActionButton
              icon={taskRunning && !approving ? Loader2 : MapPin}
              onClick={() => designMutation.mutate()}
              disabled={taskRunning || designMutation.isPending}
            >
              {taskRunning && !approving
                ? (taskMessage || "Designing…")
                : environments.length > 0
                  ? "Redesign Environments"
                  : "Design Environments"}
            </ActionButton>
            {!approvedAt && (
              <ActionButton
                variant="outline"
                icon={skipMutation.isPending ? Loader2 : MapPinOff}
                onClick={handleSkip}
                disabled={taskRunning || skipMutation.isPending}
              >
                No locations — skip
              </ActionButton>
            )}
          </div>
        </div>
      </GlassCard>

      {/* Empty state */}
      {environments.length === 0 && !taskRunning && (
        <GlassCard className="p-12 text-center">
          <MapPin size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
          <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
            No Environments Designed Yet
          </p>
          <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
            Hit “Design Environments” — we read the script, find the recurring
            locations, and generate a reference image for each one (~$0.03 per
            location). Videos with no distinct locations can skip this step.
          </p>
        </GlassCard>
      )}

      {/* Environment cards */}
      {environments.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {environments.map((e) => (
            <GlassCard key={e.id} className="p-4 flex flex-col gap-3">
              <div
                className="w-full aspect-square rounded-lg overflow-hidden flex items-center justify-center"
                style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
              >
                {e.reference_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={toDisplayImageUrl(e.reference_url)} alt={e.name} className="w-full h-full object-cover" />
                ) : (
                  <MapPin size={32} style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
                )}
              </div>

              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>
                  {e.name}
                </p>
                <span
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                  style={{
                    color: e.status === "approved" ? "var(--green)" : "var(--gold)",
                    border: `1px solid ${e.status === "approved" ? "var(--green)" : "var(--gold)"}`,
                  }}
                >
                  {e.status === "approved" ? "approved" : e.source === "project" ? "from project" : "draft"}
                </span>
              </div>

              {editingId === e.id ? (
                <div className="space-y-2">
                  <textarea
                    value={editDesc}
                    onChange={(ev) => setEditDesc(ev.target.value)}
                    rows={4}
                    className="w-full px-3 py-2 rounded-lg text-xs font-body outline-none resize-none"
                    style={{
                      background: "var(--bg-elevated)",
                      color: "var(--text-primary)",
                      border: "1px solid var(--border)",
                    }}
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleSaveDesc(e.id)}
                      className="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold"
                      style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                    >
                      <Check size={12} className="inline mr-1" />Save
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold"
                      style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <p
                  className="text-xs leading-relaxed line-clamp-3 cursor-pointer"
                  style={{ color: "var(--text-tertiary)" }}
                  title="Click to edit the description"
                  onClick={() => {
                    setEditingId(e.id);
                    setEditDesc(e.description || "");
                  }}
                >
                  {e.description || "No description — click to add one."}
                </p>
              )}

              <div className="flex items-center gap-1.5 mt-auto">
                <button
                  onClick={() => regenMutation.mutate(e.id)}
                  disabled={taskRunning}
                  title="Regenerate this reference (~$0.03)"
                  className="flex-1 px-2 py-1.5 rounded-lg text-[11px] font-semibold disabled:opacity-40 flex items-center justify-center gap-1"
                  style={{ background: "var(--purple)", color: "var(--bg-void)" }}
                >
                  <RefreshCw size={12} /> Redo
                </button>
                <button
                  onClick={() => fileInputs.current[e.id]?.click()}
                  disabled={taskRunning}
                  title="Upload your own reference image"
                  className="flex-1 px-2 py-1.5 rounded-lg text-[11px] font-semibold disabled:opacity-40 flex items-center justify-center gap-1"
                  style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
                >
                  <Upload size={12} /> Upload
                </button>
                <button
                  onClick={() => handleDelete(e.id, e.name)}
                  disabled={taskRunning}
                  title="Remove from environments"
                  className="px-2 py-1.5 rounded-lg disabled:opacity-40"
                  style={{ color: "var(--red)", border: "1px solid var(--border)" }}
                >
                  <Trash2 size={12} />
                </button>
                <input
                  ref={(el) => { fileInputs.current[e.id] = el; }}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(ev) => handleUpload(e.id, ev.target.files?.[0])}
                />
              </div>
            </GlassCard>
          ))}
        </div>
      )}

      {/* Approve bar */}
      {environments.length > 0 && (
        <GlassCard className="p-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
              {approvedAt
                ? "Environments are locked in. Re-approving after changes updates the references."
                : allHaveImages
                  ? "Happy with every location? Approve to lock the references."
                  : "Every environment needs an image (generate or upload) before approval."}
            </p>
            <div className="flex items-center gap-2">
              <ActionButton
                icon={approving || approveMutation.isPending ? Loader2 : CheckCircle2}
                onClick={() => approveMutation.mutate()}
                disabled={!allHaveImages || taskRunning || approveMutation.isPending}
              >
                {approving
                  ? (taskMessage || "Approving…")
                  : approvedAt
                    ? "Re-approve Environments"
                    : "Approve Environments"}
              </ActionButton>
            </div>
          </div>
        </GlassCard>
      )}
    </div>
  );
}
