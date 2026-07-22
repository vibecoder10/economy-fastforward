"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2, AlertTriangle, ImageOff, Images, Loader2, RefreshCw, ThumbsUp,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm";
import { useSharedTaskWatcher, type TaskWatcherBridge } from "@/hooks/use-task-poller";
import {
  getVideoAssets, getVideoScript, sendChatTurn, approveStaticQaRender, type Asset, type ScriptScene,
} from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";

interface ImagesStagePanelProps {
  videoId: string;
  taskWatcher: TaskWatcherBridge;
}

type CardStatus = "done" | "generating" | "qa_rejected" | "blocked_no_reference" | "missing" | "other";

const STATUS_META: Record<CardStatus, { label: string; color: string; pulse?: boolean }> = {
  done: { label: "Done", color: "var(--green)" },
  generating: { label: "Generating…", color: "var(--gold)", pulse: true },
  qa_rejected: { label: "Needs review", color: "var(--gold)" },
  blocked_no_reference: { label: "No reference", color: "var(--red)" },
  missing: { label: "Missing", color: "var(--text-tertiary)" },
  other: { label: "", color: "var(--text-tertiary)" },
};

function cardStatusFor(status: string | null | undefined): CardStatus {
  if (!status) return "missing";
  if (status === "done" || status === "generating" || status === "qa_rejected" || status === "blocked_no_reference") {
    return status;
  }
  // Any other status string (an asset row exists, but under a value this panel
  // doesn't specifically know) — show it plainly rather than guessing or
  // crashing. Keeps this panel forward-compatible with whatever the
  // in-flight qa_rejected-parking work above (another session) may still add.
  return "other";
}

/** Static-documentary caption is stored as JSONB but the /assets route casts it
 * to text (`caption::text`) so it always arrives as a plain string here — parse
 * defensively, never throw on an odd/legacy row. */
function parseCaption(raw: string | null | undefined): { title?: string; sub?: string } | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") return parsed as { title?: string; sub?: string };
  } catch {
    // legacy/odd row — fall through
  }
  return null;
}

/**
 * C6: roster-style grid of the GENERATED scene images for a static-documentary
 * video — one card per SCENE (driven off the script rows, not the assets, so a
 * scene whose image generation never produced a row still shows a "missing"
 * card instead of silently vanishing from the grid). Modeled directly on
 * RosterStagePanel's card layout.
 *
 * Redraw has no clean REST path today: /api/pipeline/coverage-images calls
 * generate_coverage_for_video directly (the regular multi-angle path), not
 * PipelineExecutor.run_coverage_images — the one method that actually branches
 * static_docu videos to the one-archival-image path. That branch is reachable
 * ONLY through the chat action registry (backend/actions.py's "images" verb),
 * so Redraw goes through the same two-step chat quote->confirm chat.py already
 * uses for every other paid door, instead of a direct REST call.
 */
export function ImagesStagePanel({ videoId, taskWatcher }: ImagesStagePanelProps) {
  const toast = useToast();
  const confirmDialog = useConfirm();
  const queryClient = useQueryClient();
  const [redrawingScene, setRedrawingScene] = useState<number | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);

  const { data: assets, isLoading: assetsLoading } = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
  });
  const { data: scenes, isLoading: scenesLoading } = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
    queryClient.invalidateQueries({ queryKey: ["video-actions", videoId] });
  };

  useSharedTaskWatcher({
    bridge: taskWatcher,
    enabled: redrawingScene !== null,
    onComplete: (msg) => {
      setRedrawingScene(null);
      refresh();
      if (msg) toast.success(msg);
    },
    onFailed: (error) => {
      const scene = redrawingScene;
      setRedrawingScene(null);
      toast.error(`Scene ${scene ?? ""} redraw failed: ${error}`);
    },
  });

  // One card per scene, driven off the script (not the assets) — a scene whose
  // image generation blew up so hard the placeholder row got deleted (a real
  // failure mode: generate_static_images_for_video deletes the row on a total
  // provider failure) still needs a "missing" card, not a gap in the grid.
  const rows = useMemo(() => {
    const assetByScene = new Map<number, Asset>();
    for (const a of assets ?? []) {
      if (a.scene == null) continue;
      // Static-documentary assets are generation_method='static_docu'; older
      // rows that predate this column being selected carry null — keep those
      // too rather than hiding a real picture behind a strict equality check.
      if (a.generation_method && a.generation_method !== "static_docu") continue;
      assetByScene.set(a.scene, a);
    }
    const sceneNumbers = new Set<number>();
    for (const s of (scenes ?? []) as ScriptScene[]) {
      if (s.scene != null) sceneNumbers.add(s.scene);
    }
    for (const scene of assetByScene.keys()) sceneNumbers.add(scene);
    return Array.from(sceneNumbers).sort((a, b) => a - b).map((scene) => {
      const scriptRow = (scenes ?? []).find((s) => s.scene === scene);
      const asset = assetByScene.get(scene) || null;
      const caption = parseCaption(asset?.caption);
      return { scene, scriptRow, asset, caption };
    });
  }, [assets, scenes]);

  const doneCount = rows.filter((r) => cardStatusFor(r.asset?.status) === "done").length;

  const handleRedraw = async (scene: number) => {
    setRedrawingScene(scene);
    try {
      const first = await sendChatTurn({
        video_id: videoId,
        message: `Redo scene ${scene}'s picture`,
        ui_context: { tab: "pictures", scene },
      });
      const confirmCard = first.cards?.find((c) => c.id === "confirm_action");
      if (!confirmCard) {
        toast.error(first.assistant_text || `Couldn't queue scene ${scene}'s redraw — try again.`);
        setRedrawingScene(null);
        return;
      }
      const ok = await confirmDialog({ title: confirmCard.label, message: first.assistant_text });
      if (!ok) {
        setRedrawingScene(null);
        return;
      }
      await sendChatTurn({
        video_id: videoId,
        conversation_id: first.conversation_id,
        selections: { confirm_action: "yes" },
      });
      taskWatcher.markStarted();
    } catch (err) {
      toast.error(`Couldn't redraw scene ${scene}: ${(err as Error).message}`);
      setRedrawingScene(null);
    }
  };

  const handleApprove = async (assetId: string, scene: number) => {
    setApprovingId(assetId);
    try {
      await approveStaticQaRender(assetId);
      toast.success(`Scene ${scene} approved — it'll ship in the render.`);
      refresh();
    } catch (err) {
      toast.error(`Couldn't approve scene ${scene}: ${(err as Error).message}`);
    } finally {
      setApprovingId(null);
    }
  };

  if (assetsLoading || scenesLoading) {
    return (
      <GlassCard className="p-12 text-center">
        <Loader2 size={28} className="animate-spin mx-auto" style={{ color: "var(--turquoise)" }} />
      </GlassCard>
    );
  }

  if (rows.length === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <Images size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          No Segments Yet
        </p>
        <p className="text-sm max-w-md mx-auto" style={{ color: "var(--text-tertiary)" }}>
          Write the script first — this video draws one archival picture per segment.
        </p>
      </GlassCard>
    );
  }

  const blockedCount = rows.filter((r) => {
    const s = cardStatusFor(r.asset?.status);
    return s === "blocked_no_reference" || s === "qa_rejected";
  }).length;

  return (
    <div className="space-y-6">
      <GlassCard className="p-5">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <p className="text-lg font-display flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <Images size={20} style={{ color: "var(--turquoise)" }} /> Segment Pictures
            </p>
            <p className="text-sm mt-1 max-w-xl" style={{ color: "var(--text-tertiary)" }}>
              One real archival image per segment — held over the narration, no animation.
            </p>
            <p
              className="text-sm mt-2 font-semibold"
              style={{ color: doneCount === rows.length ? "var(--green)" : blockedCount > 0 ? "var(--red)" : "var(--gold)" }}
            >
              {doneCount}/{rows.length} done
              {blockedCount > 0 ? ` — ${blockedCount} need${blockedCount === 1 ? "s" : ""} attention below.` : ""}
            </p>
          </div>
        </div>
      </GlassCard>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {rows.map(({ scene, scriptRow, asset, caption }) => {
          const status = cardStatusFor(asset?.status);
          const meta = STATUS_META[status];
          const displayLabel = status === "other" ? (asset?.status || "unknown") : meta.label;
          // qa_rejected keeps the render on drive_image_url (image_url is
          // cleared so render_static.py never ships an unreviewed picture) —
          // show it anyway so the operator can actually judge it before
          // approving or redrawing.
          const imgUrl = asset?.image_url
            || (status === "qa_rejected" ? asset?.drive_image_url : null);
          const title = caption?.title || scriptRow?.scene_text?.slice(0, 60) || `Scene ${scene}`;
          const sub = caption?.sub;
          const busy = redrawingScene === scene;
          return (
            <GlassCard key={scene} className="p-4 flex flex-col gap-3">
              <div
                className="w-full aspect-video rounded-lg overflow-hidden flex items-center justify-center relative"
                style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
              >
                {imgUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={toDisplayImageUrl(imgUrl)}
                    alt={title}
                    className="w-full h-full object-cover"
                  />
                ) : status === "blocked_no_reference" ? (
                  <ImageOff size={28} style={{ color: "var(--red)", opacity: 0.5 }} />
                ) : (
                  <Images
                    size={28}
                    className={meta.pulse ? "animate-pulse" : undefined}
                    style={{ color: "var(--text-tertiary)", opacity: 0.4 }}
                  />
                )}
              </div>

              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }} title={`Scene ${scene}: ${title}`}>
                  {scene} · {title}
                </p>
                <span
                  className={`inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0 ${meta.pulse ? "animate-pulse" : ""}`}
                  style={{ color: meta.color, border: `1px solid ${meta.color}` }}
                >
                  {status === "done" ? <CheckCircle2 size={11} /> : status === "blocked_no_reference" ? <ImageOff size={11} /> : status === "qa_rejected" ? <AlertTriangle size={11} /> : status === "generating" ? <Loader2 size={11} className="animate-spin" /> : null}
                  {displayLabel}
                </span>
              </div>
              {sub && (
                <p className="text-[11px] leading-snug truncate" style={{ color: "var(--text-tertiary)" }} title={sub}>
                  {sub}
                </p>
              )}
              {status === "blocked_no_reference" && (
                <p className="text-[10px] leading-snug" style={{ color: "var(--red)" }}>
                  No verified reference photo — fix it on the Roster tab, then redraw.
                </p>
              )}

              <div className="flex gap-2 mt-auto">
                <button
                  onClick={() => handleRedraw(scene)}
                  disabled={busy || redrawingScene !== null}
                  className="flex-1 px-2 py-1.5 rounded-lg text-[11px] font-semibold disabled:opacity-40 flex items-center justify-center gap-1"
                  style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                >
                  {busy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                  {busy ? "Redrawing…" : "Redraw"}
                </button>
                {status === "qa_rejected" && asset?.id && (
                  <button
                    onClick={() => handleApprove(asset.id, scene)}
                    disabled={approvingId === asset.id}
                    className="flex-1 px-2 py-1.5 rounded-lg text-[11px] font-semibold disabled:opacity-40 flex items-center justify-center gap-1"
                    style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                  >
                    {approvingId === asset.id ? <Loader2 size={12} className="animate-spin" /> : <ThumbsUp size={12} />}
                    {approvingId === asset.id ? "Approving…" : "Approve"}
                  </button>
                )}
              </div>
            </GlassCard>
          );
        })}
      </div>
    </div>
  );
}
