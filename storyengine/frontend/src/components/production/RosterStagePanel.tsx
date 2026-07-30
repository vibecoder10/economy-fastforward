"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, XCircle, ImageIcon, RefreshCw, Loader2, Link2, Ban, Info } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { useToast } from "@/components/ui/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useSharedTaskWatcher, type TaskWatcherBridge } from "@/hooks/use-task-poller";
import {
  recheckRosterReferences,
  seedRosterReference,
  type RosterDashboard,
} from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";

interface RosterStagePanelProps {
  videoId: string;
  rosterDashboard: RosterDashboard | undefined;
  isLoading: boolean;
  onRefresh: () => void;
  taskWatcher: TaskWatcherBridge;
}

/**
 * C3c Roster stage panel — static-documentary videos only. Every machine in
 * the locked roster needs a REAL, vision-verified reference photo before any
 * downstream script/voice/image spend: this is the entire point of the
 * static_docu reference pipeline (130a0901's fail-closed law + 6f1200d7's
 * roster-time prefetch). This panel makes that state visible and gives the
 * operator two free (no-spend) fixes for a machine prefetch missed:
 *   - "Add photo": paste a URL, runs the SAME host+vision-verify+cache chain
 *     prefetch already uses (routes/pipeline.py's roster-seed-reference).
 *   - "Re-check": re-run prefetch for the machines still missing one.
 */
export function RosterStagePanel({ videoId, rosterDashboard, isLoading, onRefresh, taskWatcher }: RosterStagePanelProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [taskRunning, setTaskRunning] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const [pendingUrl, setPendingUrl] = useState<Record<string, string>>({});
  const [seeding, setSeeding] = useState<string | null>(null);
  const [seedError, setSeedError] = useState<Record<string, string>>({});
  const [manualOverride, setManualOverride] = useState<Record<string, boolean>>({});

  // UX-1 (2026-07-29): a sweep takes ~10min for a 23-machine roster (serial,
  // Wikimedia-politeness-throttled) and used to leave the panel frozen at its
  // starting "0/23" the whole time — a user watching it had no way to tell
  // "broken" from "15 machines in." The backend now republishes an honest
  // "X/Y verified so far" onto the task-status message every ~5s (see
  // routes/pipeline.py's recheck_roster_references), so this poll (already
  // running every ~3s for completion/failure) also drives: (1) `liveMessage`
  // for the climbing headline text, (2) a roster-dashboard refetch on every
  // tick so verified photos pop into the grid live, not just at the end.
  const { message: liveMessage } = useSharedTaskWatcher({
    bridge: taskWatcher,
    enabled: taskRunning,
    onProgress: () => {
      queryClient.invalidateQueries({ queryKey: ["roster-dashboard", videoId] });
    },
    onComplete: (msg) => {
      setTaskRunning(false);
      setRechecking(false);
      queryClient.invalidateQueries({ queryKey: ["roster-dashboard", videoId] });
      onRefresh();
      if (msg) toast.success(msg);
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setRechecking(false);
      toast.error(`Re-check failed: ${error}`);
    },
  });

  // The bridge's own `running` is always-on for this video's single task
  // slot (see use-task-poller.ts), so it already reflects a sweep kicked off
  // before this panel mounted — a page reload or revisit mid-sweep, a
  // recheck started elsewhere, OR (UX-2, 2026-07-30 — the bug a fresh-eyes
  // audit found in f615772a) the AUTOMATIC sweep dispatch_roster_prefetch
  // fires the instant research completes. That auto sweep never runs in
  // this video's main task-status lane at all — it only ever writes a
  // background_tasks row (static_docu.py's _run_tracked_roster_prefetch,
  // task_type='roster_prefetch'), which routes/pipeline.py's
  // GET /task/{video_id} surfaces via its DB fallback — so before this
  // fix, `taskWatcher.message` during an auto sweep was whatever that row's
  // message happened to be, and the ONLY thing that ever contained the
  // literal substring "machine reference" was the manual recheck path
  // (routes/pipeline.py's recheck_roster_references). The panel showed no
  // spinner and every missing card sat on the frozen "missing + paste a
  // URL" form for the whole ~10-minute auto sweep — exactly the original
  // incident, just reached via the path that matters (automatic, not
  // manual).
  //
  // Fix: task_type is now a structured field on the SAME task-status
  // response (both the manual recheck and the automatic sweep tag their
  // background_tasks row/entry "roster_prefetch" — see routes/pipeline.py's
  // recheck_roster_references and static_docu.py's
  // _ROSTER_PREFETCH_TASK_TYPE), so this checks that first. The substring
  // check is kept as a defensive fallback only (e.g. an older cached
  // response, or some future code path that writes a "machine reference"
  // message without also setting task_type) — task_type is the primary,
  // authoritative signal because it can't accidentally match unrelated
  // pipeline text the way a human-readable message can.
  const bridgeIsRosterSweep =
    taskWatcher.running &&
    (taskWatcher.taskType === "roster_prefetch" ||
      (taskWatcher.message || "").toLowerCase().includes("machine reference"));

  useEffect(() => {
    if (bridgeIsRosterSweep && !taskRunning) {
      setTaskRunning(true);
    }
  }, [bridgeIsRosterSweep, taskRunning]);

  const showRunning = taskRunning || bridgeIsRosterSweep;

  const handleRecheck = async () => {
    setRechecking(true);
    try {
      await recheckRosterReferences(videoId);
      setTaskRunning(true);
    } catch (err) {
      setRechecking(false);
      toast.error(`Couldn't start the re-check: ${(err as Error).message}`);
    }
  };

  const handleAddPhoto = async (machine: string) => {
    const url = (pendingUrl[machine] || "").trim();
    if (!url) return;
    setSeeding(machine);
    setSeedError((prev) => ({ ...prev, [machine]: "" }));
    try {
      const result = await seedRosterReference(videoId, machine, url);
      if (result.status === "verified") {
        toast.success(`${machine}: reference photo verified.`);
        setPendingUrl((prev) => ({ ...prev, [machine]: "" }));
        queryClient.invalidateQueries({ queryKey: ["roster-dashboard", videoId] });
        onRefresh();
      } else {
        setSeedError((prev) => ({ ...prev, [machine]: result.reason || "That photo was rejected." }));
      }
    } catch (err) {
      setSeedError((prev) => ({ ...prev, [machine]: (err as Error).message || "Couldn't check that URL." }));
    } finally {
      setSeeding(null);
    }
  };

  if (isLoading) {
    return (
      <GlassCard className="p-12 text-center">
        <Loader2 size={28} className="animate-spin mx-auto" style={{ color: "var(--turquoise)" }} />
      </GlassCard>
    );
  }

  const units = rosterDashboard?.units ?? [];
  const total = rosterDashboard?.total ?? 0;
  const verifiedCount = units.filter((u) => u.reference?.status === "verified").length;
  // Same never-built rule as StaticDocuStageRail's roster gate (2026-07-30):
  // a cancelled programme (retryable === false) can never have a photo, so it
  // must satisfy the roster rather than hold the summary at "fix the missing
  // photos" forever. Keep both computations in step - the panel summary and
  // the stage tile above it must never contradict each other.
  const neverBuiltCount = units.filter(
    (u) => u.reference?.status !== "verified" && u.reference?.retryable === false,
  ).length;
  const allVerified = total > 0 && verifiedCount + neverBuiltCount >= total;

  if (total === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <ImageIcon size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          No Machine Roster Yet
        </p>
        <p className="text-sm max-w-md mx-auto" style={{ color: "var(--text-tertiary)" }}>
          Run Research to discover this video&apos;s machine roster — reference
          photos are then automatically looked up for every machine on the list.
        </p>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-6">
      <GlassCard className="p-5">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <p className="text-lg font-display flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <ImageIcon size={20} style={{ color: "var(--turquoise)" }} /> Machine Roster & Reference Photos
            </p>
            <p className="text-sm mt-1 max-w-xl" style={{ color: "var(--text-tertiary)" }}>
              Every machine needs a real, verified reference photo before script or
              voice spend — this is the gate that stops an invented machine from
              ever reaching the screen.
            </p>
            {showRunning ? (
              <p
                className="text-sm mt-2 font-semibold flex items-center gap-2"
                style={{ color: "var(--turquoise)" }}
              >
                <Loader2 size={14} className="animate-spin shrink-0" />
                {liveMessage || "Re-checking machine references…"}
              </p>
            ) : (
              <p
                className="text-sm mt-2 font-semibold"
                style={{ color: allVerified ? "var(--green)" : "var(--gold)" }}
              >
                {verifiedCount}/{total} verified
                {neverBuiltCount > 0 ? ` + ${neverBuiltCount} never built` : ""}
                {allVerified ? " — roster is clear to proceed." : " — fix the missing photos below."}
              </p>
            )}
            {showRunning && (
              <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
                This roster is large enough that a full sweep can take several
                minutes — the count above updates on its own as each machine
                clears. No need to add photos manually while this runs.
              </p>
            )}
          </div>
          <ActionButton
            icon={rechecking || showRunning ? Loader2 : RefreshCw}
            variant="outline"
            onClick={handleRecheck}
            disabled={rechecking || showRunning}
          >
            {rechecking || showRunning ? "Re-checking…" : "Re-check missing"}
          </ActionButton>
        </div>
      </GlassCard>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {units.map((u) => {
          const verified = u.reference?.status === "verified";
          // C8: a "missing" card used to look identical whether the machine
          // just hasn't been reached yet, will never have a photo, or was
          // genuinely checked and failed. never_built (retryable === false)
          // is the one state where retrying can never help — everything
          // else (no_candidates / fetch_failed / vision_rejected / error)
          // is worth another Re-check or a manually pasted photo.
          const neverBuilt = u.reference?.retryable === false;
          const missReason = u.reference?.reason_detail;
          return (
            <GlassCard key={u.machine} className="p-4 flex flex-col gap-3">
              <div
                className="w-full aspect-video rounded-lg overflow-hidden flex items-center justify-center"
                style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
              >
                {verified && u.reference?.hosted_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={toDisplayImageUrl(u.reference.hosted_url)}
                    alt={u.machine}
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <ImageIcon size={28} style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
                )}
              </div>

              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }} title={u.machine}>
                  {u.machine}
                </p>
                {verified ? (
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                    style={{ color: "var(--green)", border: "1px solid var(--green)" }}
                  >
                    <CheckCircle2 size={11} /> verified
                  </span>
                ) : showRunning && !manualOverride[u.machine] ? (
                  // UX-1: while an automatic sweep is mid-flight, a red
                  // "missing" badge reads as "the machine gave up" — it
                  // hasn't, this unit just hasn't been reached yet (or is
                  // being retried right now). Say that instead.
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                    style={{ color: "var(--turquoise)", border: "1px solid var(--turquoise)" }}
                  >
                    <Loader2 size={11} className="animate-spin" /> checking…
                  </span>
                ) : neverBuilt ? (
                  // C8: distinct from "missing" — no amount of retrying will
                  // ever produce a photo for this machine (e.g. a cancelled
                  // program that never left the drawing board).
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                    style={{ color: "var(--text-tertiary)", border: "1px solid var(--text-tertiary)" }}
                  >
                    <Ban size={11} /> never built
                  </span>
                ) : (
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                    style={{ color: "var(--red)", border: "1px solid var(--red)" }}
                  >
                    <XCircle size={11} /> missing
                  </span>
                )}
              </div>

              {/* C8: WHY this machine is missing — absent for a unit that
                  simply hasn't been swept yet, shown once a reason has
                  actually been recorded. Held back during a live sweep so
                  a card mid-retry doesn't flash a stale reason from the
                  attempt before it. */}
              {!verified && !showRunning && missReason && (
                <p
                  className="text-[11px] leading-snug flex items-start gap-1.5"
                  style={{ color: neverBuilt ? "var(--text-tertiary)" : "var(--gold)" }}
                >
                  <Info size={12} className="shrink-0 mt-0.5" />
                  <span>{missReason}</span>
                </p>
              )}

              {!verified && !neverBuilt && showRunning && !manualOverride[u.machine] && (
                <button
                  onClick={() => setManualOverride((prev) => ({ ...prev, [u.machine]: true }))}
                  className="text-[11px] text-left underline underline-offset-2 opacity-70 hover:opacity-100"
                  style={{ color: "var(--text-tertiary)" }}
                >
                  Don&apos;t want to wait? Add a photo manually instead.
                </button>
              )}

              {/* neverBuilt gets NO paste-a-URL/retry affordance at all —
                  presenting the same "try again" form as a genuinely
                  retryable miss would tell the operator retrying might
                  work when it structurally cannot. */}
              {!verified && !neverBuilt && (!showRunning || manualOverride[u.machine]) && (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5">
                    <Link2 size={12} style={{ color: "var(--text-tertiary)" }} className="shrink-0" />
                    <input
                      type="url"
                      placeholder="Paste an image URL…"
                      value={pendingUrl[u.machine] || ""}
                      onChange={(e) => setPendingUrl((prev) => ({ ...prev, [u.machine]: e.target.value }))}
                      disabled={seeding === u.machine}
                      className="flex-1 min-w-0 px-2 py-1 rounded-md text-[11px] outline-none disabled:opacity-40"
                      style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                    />
                  </div>
                  <button
                    onClick={() => handleAddPhoto(u.machine)}
                    disabled={seeding === u.machine || !(pendingUrl[u.machine] || "").trim()}
                    className="w-full px-2 py-1.5 rounded-lg text-[11px] font-semibold disabled:opacity-40 flex items-center justify-center gap-1"
                    style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                  >
                    {seeding === u.machine ? <Loader2 size={12} className="animate-spin" /> : null}
                    {seeding === u.machine ? "Checking…" : "Add photo"}
                  </button>
                  {seedError[u.machine] && (
                    <p className="text-[10px] leading-snug" style={{ color: "var(--red)" }}>
                      {seedError[u.machine]}
                    </p>
                  )}
                </div>
              )}
            </GlassCard>
          );
        })}
      </div>
    </div>
  );
}
