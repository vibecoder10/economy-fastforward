"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CheckCircle2,
  FolderDown,
  FolderUp,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { useToast } from "@/components/ui/toast";
import { useTaskPoller } from "@/hooks/use-task-poller";
import {
  approveCast,
  deleteCharacter,
  designCharacters,
  getVideoCharacters,
  importCastFromProject,
  regenerateCharacter,
  saveCastToProject,
  updateCharacter,
  uploadCharacterImage,
  type VideoCharacter,
  type VideoDetail,
} from "@/lib/api";
import { humanizeError } from "@/lib/errors";

interface CharactersTabProps {
  video: VideoDetail & { id: string };
  onApproved?: () => void;
}

/**
 * Per-video character design — THE character-consistency moment.
 * Generate a portrait per script character (in the video's visual style),
 * regenerate / edit / upload replacements, then Approve the cast. Approved
 * references lock character appearance across storyboards and images.
 */
export function CharactersTab({ video, onApproved }: CharactersTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [taskRunning, setTaskRunning] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDesc, setEditDesc] = useState("");
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  const { data, isLoading } = useQuery({
    queryKey: ["video-characters", video.id],
    queryFn: () => getVideoCharacters(video.id),
  });

  const characters: VideoCharacter[] = data?.characters ?? [];
  const approvedAt = data?.approved_at ?? null;
  const allHaveImages = characters.length > 0 && characters.every((c) => c.reference_url);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["video-characters", video.id] });
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
    },
    onFailed: (error) => {
      setTaskRunning(false);
      refresh();
      toast.error(humanizeError(error, "Character design hit a snag."));
    },
  });

  const designMutation = useMutation({
    mutationFn: () => designCharacters(video.id),
    onSuccess: () => setTaskRunning(true),
    onError: (err) => toast.error(humanizeError(err, "We couldn't start character design.")),
  });

  const regenMutation = useMutation({
    mutationFn: (charId: string) => regenerateCharacter(video.id, charId),
    onSuccess: () => setTaskRunning(true),
    onError: (err) => toast.error(humanizeError(err, "We couldn't redesign that character.")),
  });

  const approveMutation = useMutation({
    mutationFn: () => approveCast(video.id),
    onSuccess: (res) => {
      refresh();
      toast.success(`Cast approved (${res.count}) — storyboards are unlocked.`);
      onApproved?.();
    },
    onError: (err) => toast.error(humanizeError(err, "We couldn't approve the cast.")),
  });

  const saveMutation = useMutation({
    mutationFn: () => saveCastToProject(video.id),
    onSuccess: (res) => toast.success(`Saved ${res.count} character(s) to the project for your next videos.`),
    onError: (err) => toast.error(humanizeError(err, "We couldn't save the cast to the project.")),
  });

  const importMutation = useMutation({
    mutationFn: () => importCastFromProject(video.id),
    onSuccess: (res) => {
      refresh();
      toast.success(res.count > 0 ? `Imported ${res.count} saved character(s).` : "All saved characters are already here.");
    },
    onError: (err) => toast.error(humanizeError(err, "We couldn't import the project cast.")),
  });

  const handleUpload = async (charId: string, file: File | undefined) => {
    if (!file) return;
    try {
      await uploadCharacterImage(video.id, charId, file);
      refresh();
      toast.success("Reference image replaced.");
    } catch (err) {
      toast.error(humanizeError(err, "Upload failed."));
    }
  };

  const handleSaveDesc = async (charId: string) => {
    try {
      await updateCharacter(video.id, charId, { description: editDesc });
      setEditingId(null);
      refresh();
      toast.success("Description updated — regenerate to apply it to the portrait.");
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't save the description."));
    }
  };

  const handleDelete = async (charId: string, name: string) => {
    if (!window.confirm(`Remove ${name} from this video's cast?`)) return;
    try {
      await deleteCharacter(video.id, charId);
      refresh();
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't remove the character."));
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
              <Users size={20} style={{ color: "var(--turquoise)" }} /> Character Design
            </p>
            <p className="text-sm mt-1 max-w-xl" style={{ color: "var(--text-tertiary)" }}>
              Lock how every character looks BEFORE storyboards and images. These
              references are sent with every generation so the same character looks
              the same in every frame.
            </p>
            {approvedAt ? (
              <p className="text-sm mt-2 flex items-center gap-1.5" style={{ color: "var(--green)" }}>
                <CheckCircle2 size={15} /> Cast approved — storyboards unlocked.
              </p>
            ) : characters.length > 0 ? (
              <p className="text-sm mt-2" style={{ color: "var(--gold)" }}>
                Review the cast below, then approve to unlock storyboards.
              </p>
            ) : null}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <ActionButton
              icon={taskRunning ? Loader2 : Users}
              onClick={() => designMutation.mutate()}
              disabled={taskRunning || designMutation.isPending}
            >
              {taskRunning
                ? (taskMessage || "Designing…")
                : characters.length > 0
                  ? "Redesign Cast"
                  : "Design Characters"}
            </ActionButton>
            <ActionButton
              variant="outline"
              icon={FolderDown}
              onClick={() => importMutation.mutate()}
              disabled={taskRunning || importMutation.isPending}
            >
              Use Saved Cast
            </ActionButton>
          </div>
        </div>
      </GlassCard>

      {/* Empty state */}
      {characters.length === 0 && !taskRunning && (
        <GlassCard className="p-12 text-center">
          <Users size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
          <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
            No Characters Designed Yet
          </p>
          <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
            Hit “Design Characters” — we read the script, find the recurring cast,
            and generate a reference portrait for each one (~$0.03 per character).
            Videos with no on-screen characters can skip this step.
          </p>
        </GlassCard>
      )}

      {/* Character cards */}
      {characters.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {characters.map((c) => (
            <GlassCard key={c.id} className="p-4 flex flex-col gap-3">
              <div
                className="w-full aspect-square rounded-lg overflow-hidden flex items-center justify-center"
                style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
              >
                {c.reference_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={c.reference_url} alt={c.name} className="w-full h-full object-cover" />
                ) : (
                  <Users size={32} style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
                )}
              </div>

              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>
                  {c.name}
                </p>
                <span
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                  style={{
                    color: c.status === "approved" ? "var(--green)" : "var(--gold)",
                    border: `1px solid ${c.status === "approved" ? "var(--green)" : "var(--gold)"}`,
                  }}
                >
                  {c.status === "approved" ? "approved" : c.source === "project" ? "from project" : "draft"}
                </span>
              </div>

              {editingId === c.id ? (
                <div className="space-y-2">
                  <textarea
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
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
                      onClick={() => handleSaveDesc(c.id)}
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
                    setEditingId(c.id);
                    setEditDesc(c.description || "");
                  }}
                >
                  {c.description || "No description — click to add one."}
                </p>
              )}

              <div className="flex items-center gap-1.5 mt-auto">
                <button
                  onClick={() => regenMutation.mutate(c.id)}
                  disabled={taskRunning}
                  title="Regenerate this portrait (~$0.03)"
                  className="flex-1 px-2 py-1.5 rounded-lg text-[11px] font-semibold disabled:opacity-40 flex items-center justify-center gap-1"
                  style={{ background: "var(--purple)", color: "var(--bg-void)" }}
                >
                  <RefreshCw size={12} /> Redo
                </button>
                <button
                  onClick={() => fileInputs.current[c.id]?.click()}
                  disabled={taskRunning}
                  title="Upload your own reference image"
                  className="flex-1 px-2 py-1.5 rounded-lg text-[11px] font-semibold disabled:opacity-40 flex items-center justify-center gap-1"
                  style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
                >
                  <Upload size={12} /> Upload
                </button>
                <button
                  onClick={() => handleDelete(c.id, c.name)}
                  disabled={taskRunning}
                  title="Remove from cast"
                  className="px-2 py-1.5 rounded-lg disabled:opacity-40"
                  style={{ color: "var(--red)", border: "1px solid var(--border)" }}
                >
                  <Trash2 size={12} />
                </button>
                <input
                  ref={(el) => { fileInputs.current[c.id] = el; }}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => handleUpload(c.id, e.target.files?.[0])}
                />
              </div>
            </GlassCard>
          ))}
        </div>
      )}

      {/* Approve bar */}
      {characters.length > 0 && (
        <GlassCard className="p-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
              {approvedAt
                ? "Cast is locked in. Re-approving after changes updates the references."
                : allHaveImages
                  ? "Happy with everyone? Approve to unlock storyboards."
                  : "Every character needs an image (generate or upload) before approval."}
            </p>
            <div className="flex items-center gap-2">
              <ActionButton
                variant="outline"
                icon={FolderUp}
                onClick={() => saveMutation.mutate()}
                disabled={!allHaveImages || saveMutation.isPending}
              >
                Save Cast to Project
              </ActionButton>
              <ActionButton
                icon={approveMutation.isPending ? Loader2 : CheckCircle2}
                onClick={() => approveMutation.mutate()}
                disabled={!allHaveImages || taskRunning || approveMutation.isPending}
              >
                {approvedAt ? "Re-approve Cast" : "Approve Cast"}
              </ActionButton>
            </div>
          </div>
        </GlassCard>
      )}
    </div>
  );
}
