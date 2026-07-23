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
import {
  getStaticDocuReadiness, parseStaticDocuCaption, staticDocuViewLabel,
} from "@/lib/static-docu";
import { toDisplayImageUrl } from "@/lib/utils";

interface ImagesStagePanelProps {
  videoId: string;
  taskWatcher: TaskWatcherBridge;
}

type CardStatus = "done" | "generating" | "qa_rejected" | "blocked_no_reference" | "missing" | "other";

const STATUS_META: Record<CardStatus, { label: string; color: string; pulse?: boolean }> = {
  done: { label: "Ready", color: "var(--green)" },
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

/**
 * Roster-style grid of generated static-documentary views — one card per
 * aircraft/scene, with 1–3 ordered view tiles inside it. Script rows still
 * drive the cards so a unit whose generation never produced an asset remains
 * visible as missing instead of silently vanishing.
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

  const pictureReadiness = useMemo(() => {
    const sceneNumbers = new Set<number>();
    for (const s of (scenes ?? []) as ScriptScene[]) {
      if (s.scene != null) sceneNumbers.add(s.scene);
    }
    return getStaticDocuReadiness(assets ?? [], Array.from(sceneNumbers));
  }, [assets, scenes]);

  const rows = pictureReadiness.units.map((unit) => {
    const scriptRow = (scenes ?? []).find((scene) => scene.scene === unit.scene);
    const caption = unit.assets
      .map((asset) => parseStaticDocuCaption(asset.caption))
      .find((value) => value?.title);
    return { ...unit, scriptRow, caption };
  });
  const doneCount = pictureReadiness.readyUnits;

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
          No Aircraft Yet
        </p>
        <p className="text-sm max-w-md mx-auto" style={{ color: "var(--text-tertiary)" }}>
          Write the script first — each aircraft will receive a three-quarter, top-oblique, and detail view.
        </p>
      </GlassCard>
    );
  }

  const blockedCount = pictureReadiness.blockedUnits;

  return (
    <div className="space-y-6">
      <GlassCard className="p-5">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <p className="text-lg font-display flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <Images size={20} style={{ color: "var(--turquoise)" }} /> Aircraft Views
            </p>
            <p className="text-sm mt-1 max-w-xl" style={{ color: "var(--text-tertiary)" }}>
              Two verified views make an aircraft ready; three are targeted: three-quarter, top-oblique, and detail.
            </p>
            <p
              className="text-sm mt-2 font-semibold"
              style={{ color: doneCount === rows.length ? "var(--green)" : blockedCount > 0 ? "var(--red)" : "var(--gold)" }}
            >
              {doneCount}/{rows.length} aircraft ready · {pictureReadiness.readyViews} views approved
              {blockedCount > 0 ? ` — ${blockedCount} need${blockedCount === 1 ? "s" : ""} attention below.` : ""}
            </p>
          </div>
        </div>
      </GlassCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        {rows.map(({
          scene, scriptRow, assets: unitAssets, caption, status: unitState,
          readyViews, minimumViews, targetViews,
        }) => {
          const status: CardStatus = unitState === "ready"
            ? "done"
            : unitState === "generating"
              ? "generating"
              : unitState === "blocked"
                ? "qa_rejected"
                : "missing";
          const meta = STATUS_META[status];
          const title = caption?.title || scriptRow?.scene_text?.slice(0, 60) || `Scene ${scene}`;
          const sub = caption?.sub;
          const specs = caption?.specs ?? [];
          const busy = redrawingScene === scene;
          return (
            <GlassCard key={scene} className="p-4 flex flex-col gap-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }} title={`Scene ${scene}: ${title}`}>
                  {scene} · {title}
                </p>
                <span
                  className={`inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0 ${meta.pulse ? "animate-pulse" : ""}`}
                  style={{ color: meta.color, border: `1px solid ${meta.color}` }}
                >
                  {status === "done" ? <CheckCircle2 size={11} /> : status === "qa_rejected" ? <AlertTriangle size={11} /> : status === "generating" ? <Loader2 size={11} className="animate-spin" /> : null}
                  {meta.label} · {readyViews}/{minimumViews} min
                </span>
              </div>
              {sub && (
                <p className="text-[11px] leading-snug truncate" style={{ color: "var(--text-tertiary)" }} title={sub}>
                  {sub}
                </p>
              )}
              {specs.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {specs.slice(0, 2).map((spec) => (
                    <span
                      key={spec}
                      className="text-[10px] px-2 py-1 rounded-full"
                      style={{ color: "var(--gold)", background: "rgba(168,131,69,0.1)", border: "1px solid rgba(168,131,69,0.28)" }}
                    >
                      {spec}
                    </span>
                  ))}
                </div>
              )}

              {unitAssets.length > 0 ? (
                <div className="grid grid-cols-3 gap-2">
                  {unitAssets.map((asset) => {
                    const viewStatus = cardStatusFor(asset.status);
                    const viewMeta = STATUS_META[viewStatus];
                    const viewCaption = parseStaticDocuCaption(asset.caption);
                    const viewLabel = staticDocuViewLabel(viewCaption, asset.image_index);
                    // Rejected renders are parked in drive_image_url so the
                    // operator can inspect them without letting render_static
                    // ship them before explicit approval.
                    const imgUrl = asset.image_url
                      || (viewStatus === "qa_rejected" ? asset.drive_image_url : null);
                    return (
                      <div key={asset.id} className="min-w-0">
                        <div
                          className="aspect-[4/3] rounded-lg overflow-hidden flex items-center justify-center relative"
                          style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                        >
                          {imgUrl ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={toDisplayImageUrl(imgUrl)}
                              alt={`${title} — ${viewLabel}`}
                              className="w-full h-full object-cover"
                            />
                          ) : viewStatus === "blocked_no_reference" ? (
                            <ImageOff size={20} style={{ color: "var(--red)", opacity: 0.55 }} />
                          ) : (
                            <Images
                              size={20}
                              className={viewMeta.pulse ? "animate-pulse" : undefined}
                              style={{ color: "var(--text-tertiary)", opacity: 0.4 }}
                            />
                          )}
                        </div>
                        <p className="text-[9px] mt-1 truncate font-semibold" style={{ color: "var(--text-secondary)" }} title={viewLabel}>
                          {viewLabel}
                        </p>
                        <p className="text-[9px] truncate" style={{ color: viewMeta.color }}>
                          {viewStatus === "other" ? asset.status : viewMeta.label}
                        </p>
                        {viewStatus === "qa_rejected" && asset.id && (
                          <button
                            onClick={() => handleApprove(asset.id, scene)}
                            disabled={approvingId === asset.id}
                            className="w-full mt-1 px-1 py-1 rounded text-[9px] font-semibold disabled:opacity-40 flex items-center justify-center gap-1"
                            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                          >
                            {approvingId === asset.id ? <Loader2 size={9} className="animate-spin" /> : <ThumbsUp size={9} />}
                            {approvingId === asset.id ? "Approving…" : "Approve"}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div
                  className="w-full aspect-video rounded-lg flex items-center justify-center"
                  style={{ background: "var(--bg-elevated)", border: "1px dashed var(--border)" }}
                >
                  <Images size={28} style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
                </div>
              )}

              {unitState === "blocked" && unitAssets.some((asset) => asset.status === "blocked_no_reference") && (
                <p className="text-[10px] leading-snug" style={{ color: "var(--red)" }}>
                  No verified reference photo — fix it on the Roster tab, then redraw.
                </p>
              )}
              {unitState === "ready" && readyViews < targetViews && (
                <p className="text-[10px] leading-snug" style={{ color: "var(--gold)" }}>
                  Render-ready with {readyViews} verified views; one optional view still needs attention.
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
                  {busy ? "Redrawing views…" : "Redraw all views"}
                </button>
              </div>
            </GlassCard>
          );
        })}
      </div>
    </div>
  );
}
