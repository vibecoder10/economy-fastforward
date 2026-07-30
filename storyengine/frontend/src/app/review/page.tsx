"use client";
import { Spinner } from "@/components/ui/spinner";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getPendingReview, approveAsset, rejectAsset, advanceVideo, approveStoryboard, rejectStoryboard,
  getArbiterFindings, type ReviewItem, type ArbiterFinding, type ArbiterFindingInstance,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";
import {
  FileText, Image, Palette, LayoutGrid, ChevronRight, Check, X,
  ShieldAlert, Snowflake, HelpCircle, ChevronDown,
} from "lucide-react";

type ReviewTab = "scripts" | "storyboards" | "thumbnails" | "images" | "findings";
type PendingKey = "scripts" | "storyboards" | "thumbnails" | "images";

// Frame Arbiter findings tab (D5 chunk A7, storyengine/FRAME-ARBITER-PLAN.md).
// Classification -> badge classes, following THIS file's own idiom (Tailwind
// arbitrary-value CSS-var classes, e.g. the storyboard approve/reject buttons
// below use bg-[var(--success)]/20) rather than a different badge component
// from elsewhere in the app.
function classificationClasses(classification: string): string {
  switch (classification) {
    case "MODEL_DEFECT":
      return "bg-[var(--error)]/20 text-[var(--error)]";
    case "AUTHORING_DEFECT":
      return "bg-[var(--warning)]/20 text-[var(--warning)]";
    case "TASTE_QUESTION":
      return "bg-[var(--accent)]/20 text-[var(--accent)]";
    case "OK":
      return "bg-[var(--success)]/20 text-[var(--success)]";
    default:
      return "bg-white/10 text-[var(--text-secondary)]";
  }
}

function classificationLabel(classification: string): string {
  switch (classification) {
    case "MODEL_DEFECT":
      return "Model defect";
    case "AUTHORING_DEFECT":
      return "Authoring defect";
    case "TASTE_QUESTION":
      return "Taste question";
    case "OK":
      return "Clean";
    default:
      return classification;
  }
}

// A plain findings row — MODEL_DEFECT / AUTHORING_DEFECT. No frame image or
// free-text reason is shown because none is persisted anywhere yet (see
// backend/routes/review.py's get_findings docstring): arbiter_fingerprints
// (D5/A2) is a CLASS-level record (rule_id/failure_class + stage), not a
// per-frame instance. What's shown below is everything that IS real.
function FindingRow({ finding }: { finding: ArbiterFinding }) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", classificationClasses(finding.classification))}>
            {classificationLabel(finding.classification)}
          </span>
          {finding.frozen && (
            <span className="flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-medium text-[var(--text-secondary)]">
              <Snowflake size={11} /> Frozen
            </span>
          )}
        </div>
        <span className="text-[11px] text-[var(--text-secondary)]">{finding.violation_count}&times;</span>
      </div>
      <p className="mt-2 text-sm font-medium">{finding.failure_class}</p>
      {finding.rule_id && (
        <p className="mt-0.5 text-xs text-[var(--text-secondary)]">Rule: {finding.rule_id}</p>
      )}
      <p className="mt-1 font-mono text-[11px] text-[var(--text-secondary)]">
        {finding.fingerprint_key} &middot; {finding.stage}
      </p>
      {finding.last_seen_at && (
        <p className="mt-1 text-[11px] text-[var(--text-secondary)]">
          Last seen {new Date(finding.last_seen_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}

// TASTE_QUESTION decision card. DoC #6 (FRAME-ARBITER-PLAN.md): "TASTE_QUESTION
// cards require a manual tap and are never auto-acted." Tapping only toggles
// local expand/collapse state below — there is no mutation, no fetch, no
// approve/dismiss call wired here at all, so it is structurally incapable of
// auto-acting. Turning a decision into a real ruling is a later chunk (A8,
// upsert_quality_rule wire-up), not this tab.
function TasteDecisionCard({ finding }: { finding: ArbiterFinding }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-xl border border-[var(--accent)]/40 bg-[var(--accent)]/10 p-4">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <div className="flex items-center gap-2">
          <HelpCircle size={16} className="text-[var(--accent)]" />
          <p className="text-sm font-medium">{finding.failure_class}</p>
        </div>
        <ChevronDown size={16} className={cn("text-[var(--text-secondary)] transition-transform", expanded && "rotate-180")} />
      </button>
      <p className="mt-1 text-xs text-[var(--text-secondary)]">
        Directorial call needed — the arbiter flagged this as a preference question, not a defect. Seen {finding.violation_count}&times;.
      </p>
      {expanded && (
        <div className="mt-3 space-y-1 border-t border-[var(--accent)]/20 pt-3 text-xs text-[var(--text-secondary)]">
          <p>Fingerprint: <span className="font-mono">{finding.fingerprint_key}</span></p>
          <p>Stage: {finding.stage}</p>
          {finding.rule_id && <p>Rule: {finding.rule_id}</p>}
          {finding.last_seen_at && <p>Last seen: {new Date(finding.last_seen_at).toLocaleString()}</p>}
          <p className="pt-1">No action fires from this card — a ruling (a later chunk) is what turns this into a prompt/gate/repair fix.</p>
        </div>
      )}
    </div>
  );
}

// D8 chunk 3b: one `arbiter_findings` row — a single judged frame/panel
// INSTANCE (migration 146), not a class-level fingerprint. This is the
// detail layer that sits under FindingRow's own class-level summary above
// — same card idiom (classificationClasses/Label, rounded-xl border card),
// widened with the per-instance fields FindingRow never had: an image
// thumbnail when the judge call attached one, the station/reference the
// judge actually looked at, and which video/scene it came from.
function InstanceRow({ instance }: { instance: ArbiterFindingInstance }) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", classificationClasses(instance.classification))}>
            {classificationLabel(instance.classification)}
          </span>
          <span className="font-mono text-[11px] text-[var(--text-secondary)]">
            {instance.station} &middot; {instance.reference}
          </span>
        </div>
        {instance.cost != null && (
          <span className="whitespace-nowrap text-[11px] text-[var(--text-secondary)]">
            ${instance.cost.toFixed(4)}
          </span>
        )}
      </div>
      {instance.image_url && (
        <div className="mt-2 overflow-hidden rounded-lg">
          <img src={instance.image_url} alt="" className="max-h-40 w-full object-cover" />
        </div>
      )}
      <p className="mt-2 text-sm">{instance.description || instance.failure_class || "No description"}</p>
      <p className="mt-1 text-xs text-[var(--text-secondary)]">
        {instance.video_title || "Untitled"}
        {instance.scene != null ? ` · Scene ${instance.scene}` : ""}
        {instance.label ? ` · ${instance.label}` : ""}
      </p>
      {instance.created_at && (
        <p className="mt-1 text-[11px] text-[var(--text-secondary)]">
          {new Date(instance.created_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}

export default function ReviewPage() {
  const [activeTab, setActiveTab] = useState<ReviewTab>("scripts");
  const [selectedItem, setSelectedItem] = useState<ReviewItem | null>(null);
  const [imageReviewIndex, setImageReviewIndex] = useState(0);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error: reviewError } = useQuery({
    queryKey: ["pending-review"],
    queryFn: getPendingReview,
  });

  const { data: findingsData, isLoading: findingsLoading, error: findingsError } = useQuery({
    queryKey: ["arbiter-findings"],
    queryFn: getArbiterFindings,
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pending-review"] }),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pending-review"] }),
  });

  const advanceMutation = useMutation({
    mutationFn: (id: string) => advanceVideo(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pending-review"] }),
  });

  const approveStoryboardMutation = useMutation({
    mutationFn: (scriptId: string) => { setPendingId(scriptId); return approveStoryboard(scriptId); },
    onSettled: () => { setPendingId(null); queryClient.invalidateQueries({ queryKey: ["pending-review"] }); },
  });

  const rejectStoryboardMutation = useMutation({
    mutationFn: (scriptId: string) => { setPendingId(scriptId); return rejectStoryboard(scriptId); },
    onSettled: () => { setPendingId(null); queryClient.invalidateQueries({ queryKey: ["pending-review"] }); },
  });

  const tabs: { key: ReviewTab; label: string; icon: typeof FileText; count: number }[] = [
    { key: "scripts", label: "Scripts", icon: FileText, count: data?.scripts.length ?? 0 },
    { key: "storyboards", label: "Storyboards", icon: LayoutGrid, count: data?.storyboards.length ?? 0 },
    { key: "thumbnails", label: "Thumbnails", icon: Palette, count: data?.thumbnails.length ?? 0 },
    { key: "images", label: "Images", icon: Image, count: data?.images.length ?? 0 },
    { key: "findings", label: "Findings", icon: ShieldAlert, count: findingsData?.findings.length ?? 0 },
  ];

  const totalPending = tabs.reduce((sum, t) => sum + t.count, 0);
  const currentItems = activeTab === "findings" ? [] : (data?.[activeTab as PendingKey] ?? []);

  // Image batch review mode
  const imageItems = data?.images ?? [];
  const currentImage = imageItems[imageReviewIndex];

  // Frame Arbiter findings tab (D5 chunk A7) — two independent lists off a
  // separate query/endpoint, see getArbiterFindings. TASTE_QUESTION findings
  // are split out into their own decision-card section (never mixed into the
  // plain findings list, and never auto-acted — see TasteDecisionCard above).
  const arbiterFindings = findingsData?.findings ?? [];
  const arbiterSpend = findingsData?.spend ?? [];
  // D8 chunk 3b: per-instance rows (migration 146) — the actual judged
  // frame/panel history the two class-level lists above summarize. Kept as
  // its own list rather than merged into arbiterFindings: the two have
  // different shapes (ArbiterFinding vs ArbiterFindingInstance) and
  // different identity (one row per CLASS vs one row per JUDGMENT).
  const findingInstances = findingsData?.instances ?? [];
  const tasteQuestions = arbiterFindings.filter((f) => f.classification === "TASTE_QUESTION");
  const otherFindings = arbiterFindings.filter((f) => f.classification !== "TASTE_QUESTION");
  const findingsTrulyEmpty = arbiterFindings.length === 0 && arbiterSpend.length === 0 && findingInstances.length === 0;
  const findingsRanClean = arbiterFindings.length === 0 && (arbiterSpend.length > 0 || findingInstances.length > 0);

  // Active tab's own loading/error state — the findings tab reads from a
  // different query than every other tab, so the shared Loading/Error/Empty
  // blocks below need to watch the right one.
  const activeIsLoading = activeTab === "findings" ? findingsLoading : isLoading;
  const activeError = activeTab === "findings" ? findingsError : reviewError;
  const activeIsEmpty = activeTab === "findings" ? findingsTrulyEmpty : currentItems.length === 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Review</h1>
        {totalPending > 0 && (
          <span className="rounded-full bg-[var(--accent)]/20 px-2.5 py-1 text-xs font-medium text-[var(--accent)]">
            {totalPending} pending
          </span>
        )}
      </div>

      {/* Tab selector */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              onClick={() => {
                setActiveTab(tab.key);
                setSelectedItem(null);
                setImageReviewIndex(0);
              }}
              className={cn(
                "flex flex-shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                activeTab === tab.key
                  ? "bg-[var(--accent)] text-black"
                  : "bg-[var(--surface)] text-[var(--text-secondary)]"
              )}
            >
              <Icon size={14} />
              {tab.label}
              {tab.count > 0 && (
                <span className={cn(
                  "ml-0.5 rounded-full px-1.5 py-0.5 text-[10px]",
                  activeTab === tab.key ? "bg-black/20" : "bg-white/10"
                )}>
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Loading */}
      {activeIsLoading && (
        <div className="flex items-center justify-center py-16">
          <Spinner size="lg" />
        </div>
      )}

      {activeError && !activeIsLoading && (
        <ErrorCard message={(activeError as Error).message} onRetry={() => window.location.reload()} />
      )}

      {/* Empty state */}
      {!activeIsLoading && !activeError && activeIsEmpty && (
        <EmptyState
          icon={
            activeTab === "scripts" ? FileText
            : activeTab === "storyboards" ? LayoutGrid
            : activeTab === "thumbnails" ? Palette
            : activeTab === "findings" ? ShieldAlert
            : Image
          }
          title={activeTab === "findings" ? "No arbiter findings yet" : `No ${activeTab} pending review`}
          description={
            activeTab === "findings"
              ? "The judge has not run — findings will appear here once the frame arbiter judges a scene."
              : "Items appear here when pipeline stages complete"
          }
        />
      )}

      {/* Scripts */}
      {activeTab === "scripts" && !selectedItem && (
        <div className="space-y-2">
          {currentItems.map((item) => (
            <button
              key={item.video_id}
              onClick={() => setSelectedItem(item)}
              className="flex w-full items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left transition-colors hover:bg-[var(--surface-elevated)]"
            >
              <div>
                <p className="font-medium">{item.title}</p>
                <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                  {item.word_count?.toLocaleString()} words
                </p>
              </div>
              <ChevronRight size={16} className="text-[var(--text-secondary)]" />
            </button>
          ))}
        </div>
      )}

      {/* Script reader */}
      {activeTab === "scripts" && selectedItem && (
        <div className="space-y-4">
          <button
            onClick={() => setSelectedItem(null)}
            className="text-xs text-[var(--accent)]"
          >
            ← Back to list
          </button>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <h2 className="mb-4 text-lg font-semibold">{selectedItem.title}</h2>
            <div className="prose prose-invert max-w-none text-[16px] leading-[1.6] text-[var(--text-primary)]">
              <p className="whitespace-pre-wrap">Script content will load from API...</p>
            </div>
          </div>
          <div className="sticky bottom-16 z-10 flex gap-2 rounded-xl bg-[var(--surface)] p-3 md:bottom-0">
            <button
              onClick={() => {
                advanceMutation.mutate(selectedItem.video_id);
                setSelectedItem(null);
              }}
              className="flex-1 rounded-lg bg-[var(--accent)] py-3 text-sm font-medium text-black"
            >
              Approve Script
            </button>
            <button
              onClick={() => setSelectedItem(null)}
              className="rounded-lg border border-[var(--border)] px-4 py-3 text-sm font-medium text-[var(--text-secondary)]"
            >
              Skip
            </button>
          </div>
        </div>
      )}

      {/* Storyboards */}
      {activeTab === "storyboards" && (
        <div className="space-y-4">
          {currentItems.map((item) => (
            <div
              key={item.script_id || item.video_id}
              className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"
            >
              <p className="mb-3 font-medium">{item.title || "Untitled"}</p>
              <p className="mb-2 text-xs text-[var(--text-secondary)]">Scene {item.scene}</p>
              <div className="grid grid-cols-3 gap-2">
                {item.storyboard_1_url && (
                  <div className="overflow-hidden rounded-lg">
                    <img src={item.storyboard_1_url} alt="Grid 1" className="w-full" />
                  </div>
                )}
                {item.storyboard_2_url && (
                  <div className="overflow-hidden rounded-lg">
                    <img src={item.storyboard_2_url} alt="Grid 2" className="w-full" />
                  </div>
                )}
                {item.storyboard_3_url && (
                  <div className="overflow-hidden rounded-lg">
                    <img src={item.storyboard_3_url} alt="Grid 3" className="w-full" />
                  </div>
                )}
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => item.script_id && approveStoryboardMutation.mutate(item.script_id)}
                  disabled={pendingId === item.script_id}
                  className="flex-1 rounded-lg bg-[var(--success)]/20 py-2 text-sm font-medium text-[var(--success)] disabled:opacity-50"
                >
                  {pendingId === item.script_id && approveStoryboardMutation.isPending ? "Approving..." : "Approve"}
                </button>
                <button
                  onClick={() => item.script_id && rejectStoryboardMutation.mutate(item.script_id)}
                  disabled={pendingId === item.script_id}
                  className="flex-1 rounded-lg bg-[var(--error)]/20 py-2 text-sm font-medium text-[var(--error)] disabled:opacity-50"
                >
                  {pendingId === item.script_id && rejectStoryboardMutation.isPending ? "Rejecting..." : "Reject"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Thumbnails */}
      {activeTab === "thumbnails" && (
        <div className="space-y-4">
          {/* Group by video */}
          {currentItems.map((item) => (
            <div
              key={item.asset_id}
              className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"
            >
              <p className="mb-3 text-sm font-medium">{item.title}</p>
              <div className="grid grid-cols-2 gap-2">
                {item.url && (
                  <button
                    onClick={() => item.asset_id && approveMutation.mutate(item.asset_id)}
                    className="group relative overflow-hidden rounded-lg"
                  >
                    <img src={item.url} alt="" className="aspect-video w-full object-cover" />
                    <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/40">
                      <Check size={24} className="text-white opacity-0 transition-opacity group-hover:opacity-100" />
                    </div>
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Images batch review */}
      {activeTab === "images" && imageItems.length > 0 && (
        <div className="space-y-4">
          {/* Progress */}
          <div className="flex items-center justify-between text-sm text-[var(--text-secondary)]">
            <span>Image {imageReviewIndex + 1} of {imageItems.length}</span>
            <div className="h-1 flex-1 mx-3 rounded-full bg-white/5">
              <div
                className="h-1 rounded-full bg-[var(--accent)] transition-all"
                style={{ width: `${((imageReviewIndex + 1) / imageItems.length) * 100}%` }}
              />
            </div>
          </div>

          {/* Current image */}
          {currentImage && (
            <div className="overflow-hidden rounded-xl">
              {currentImage.url && (
                <img src={currentImage.url} alt="" className="aspect-video w-full object-cover" />
              )}
              {currentImage.prompt && (
                <p className="mt-2 text-xs text-[var(--text-secondary)]">{currentImage.prompt}</p>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={() => {
                if (currentImage?.asset_id) rejectMutation.mutate(currentImage.asset_id);
                setImageReviewIndex((i) => Math.min(i + 1, imageItems.length - 1));
              }}
              className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--error)]/20 text-sm font-medium text-[var(--error)]"
            >
              <X size={16} /> Reject
            </button>
            <button
              onClick={() => setImageReviewIndex((i) => Math.min(i + 1, imageItems.length - 1))}
              className="flex min-h-[44px] items-center justify-center rounded-lg border border-[var(--border)] px-4 text-sm text-[var(--text-secondary)]"
            >
              Skip
            </button>
            <button
              onClick={() => {
                if (currentImage?.asset_id) approveMutation.mutate(currentImage.asset_id);
                setImageReviewIndex((i) => Math.min(i + 1, imageItems.length - 1));
              }}
              className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--success)]/20 text-sm font-medium text-[var(--success)]"
            >
              <Check size={16} /> Approve
            </button>
          </div>
        </div>
      )}

      {/* Frame Arbiter findings (D5 chunk A7) */}
      {activeTab === "findings" && !findingsLoading && !findingsError && (
        <div className="space-y-5">
          {findingsRanClean && (
            <p className="text-xs text-[var(--text-secondary)]">
              The judge has run and found nothing wrong in the scenes below — no defects logged.
            </p>
          )}

          {arbiterSpend.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
                QA spend
              </p>
              {arbiterSpend.map((s) => (
                <div
                  key={`${s.video_id}-${s.scene ?? "all"}`}
                  className="flex items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3"
                >
                  <div>
                    <p className="text-sm font-medium">
                      {s.video_title || "Untitled"}
                      {s.scene != null ? ` · Scene ${s.scene}` : ""}
                    </p>
                    <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                      {s.qa_passes} judge pass{s.qa_passes === 1 ? "" : "es"}
                      {s.last_judged_at ? ` · last ${new Date(s.last_judged_at).toLocaleString()}` : ""}
                    </p>
                  </div>
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    ${s.total_cost.toFixed(4)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {tasteQuestions.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
                Needs your call
              </p>
              {tasteQuestions.map((f) => (
                <TasteDecisionCard key={f.id} finding={f} />
              ))}
            </div>
          )}

          {otherFindings.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
                Findings
              </p>
              {otherFindings.map((f) => (
                <FindingRow key={f.id} finding={f} />
              ))}
            </div>
          )}

          {/* D8 chunk 3b: per-instance judgment history — the actual judged
              frames/panels the class-level summaries above are built from.
              Most-recent-first (server-capped, see routes/review.py). */}
          {findingInstances.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
                Judged frames &amp; panels
              </p>
              {findingInstances.map((instance) => (
                <InstanceRow key={instance.id} instance={instance} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
