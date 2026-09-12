"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, ExternalLink, ListVideo, Loader2, Play, RotateCcw } from "lucide-react";
import {
  addToQueue,
  getActiveTenant,
  getQueue,
  getWorkspaces,
  patchQueueItem,
  type QueueDeliveryMode,
  type QueueItem,
} from "@/lib/api";
import {
  defaultQueueDeliveryMode,
  defaultQueueRunMode,
  parseTitleLines,
  queueLifecycle,
  type QueueLifecycle,
  type QueueRunMode,
} from "./title-list-queue-model";

const LIFECYCLE_LABEL: Record<QueueLifecycle, string> = {
  queued: "Queued",
  running: "Running",
  retrying: "Retrying",
  completed: "Completed",
  failed: "Failed",
  blocked: "Blocked",
};

const LIFECYCLE_COLOR: Record<QueueLifecycle, string> = {
  queued: "var(--text-secondary)",
  running: "var(--turquoise)",
  retrying: "var(--gold)",
  completed: "var(--green)",
  failed: "var(--red)",
  blocked: "var(--orange)",
};

function QueueStatus({ item }: { item: QueueItem }) {
  const lifecycle = queueLifecycle(item);
  return (
    <div className="flex items-start gap-2">
      <span
        className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
        style={{ background: LIFECYCLE_COLOR[lifecycle] }}
        aria-hidden
      />
      <div className="min-w-0">
        <p className="text-[11px] font-semibold" style={{ color: LIFECYCLE_COLOR[lifecycle] }}>
          {LIFECYCLE_LABEL[lifecycle]}
          {item.attempt_count > 0 && lifecycle !== "completed" ? ` · attempt ${item.attempt_count} of 3` : ""}
        </p>
        {item.last_error && (
          <p className="mt-0.5 text-[10px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            {item.last_error}
          </p>
        )}
      </div>
    </div>
  );
}

export function TitleListQueue() {
  const queryClient = useQueryClient();
  const [titleText, setTitleText] = useState("");
  const [modeChoice, setModeChoice] = useState<{ tenantId: string; mode: QueueRunMode } | null>(null);
  const [deliveryChoice, setDeliveryChoice] = useState<{ tenantId: string; mode: QueueDeliveryMode } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const queueQuery = useQuery({
    queryKey: ["production-queue"],
    queryFn: getQueue,
    refetchInterval: 5000,
    refetchOnWindowFocus: true,
  });
  const workspaceQuery = useQuery({
    queryKey: ["workspaces"],
    queryFn: getWorkspaces,
  });

  const items = queueQuery.data?.items ?? [];
  const orderedItems = useMemo(
    () => [...items].sort((left, right) => left.position - right.position),
    [items],
  );
  const titles = useMemo(() => parseTitleLines(titleText), [titleText]);
  const activeTenant = getActiveTenant();
  const currentWorkspace = workspaceQuery.data?.workspaces.find((workspace) => workspace.tenant_id === activeTenant)
    ?? workspaceQuery.data?.workspaces[0];
  const inferredMode = defaultQueueRunMode(currentWorkspace, items);
  const selectedMode =
    modeChoice && modeChoice.tenantId === currentWorkspace?.tenant_id ? modeChoice.mode : inferredMode;
  const inferredDelivery = defaultQueueDeliveryMode(currentWorkspace);
  const selectedDelivery =
    deliveryChoice && deliveryChoice.tenantId === currentWorkspace?.tenant_id
      ? deliveryChoice.mode
      : inferredDelivery;

  const refreshQueue = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["production-queue"] }),
      queryClient.invalidateQueries({ queryKey: ["calendar-plan"] }),
    ]);
  };

  const runMutation = useMutation({
    mutationFn: () =>
      addToQueue(
        titles.map((title) => ({ title })),
        {
          continuous: true,
          required_render_mode: selectedMode === "static_docu" ? "static_docu" : null,
          delivery_mode: selectedDelivery,
        },
      ),
    onSuccess: async (response) => {
      setTitleText("");
      setNotice(
        response.launch
          ? `${response.count} title${response.count === 1 ? "" : "s"} queued. The first build is running.`
          : response.message || `${response.count} title${response.count === 1 ? "" : "s"} queued.`,
      );
      await refreshQueue();
    },
    onError: () => setNotice(null),
  });

  const retryMutation = useMutation({
    mutationFn: (id: string) => patchQueueItem(id, { status: "queued" }),
    onMutate: (id) => setRetryingId(id),
    onSuccess: refreshQueue,
    onSettled: () => setRetryingId(null),
  });

  const runError = runMutation.error instanceof Error ? runMutation.error.message : null;
  const retryError = retryMutation.error instanceof Error ? retryMutation.error.message : null;

  return (
    <section
      className="mb-8 rounded-xl p-4 md:p-5"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(64,224,208,0.18)" }}
      aria-labelledby="title-list-heading"
    >
      <div className="flex items-start gap-3">
        <ListVideo size={18} className="mt-0.5 shrink-0" style={{ color: "var(--turquoise)" }} />
        <div>
          <h2 id="title-list-heading" className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            Run a title list
          </h2>
          <p className="mt-1 text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
            Paste one title per line. StoryEngine builds them in order, one at a time,
            {selectedDelivery === "youtube_unlisted"
              ? ` then uploads each one unlisted to ${currentWorkspace?.name || "the selected YouTube channel"} for review.`
              : " and keeps each rendered video in StoryEngine for review."}
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_520px]">
        <div>
          <label htmlFor="title-list" className="mb-1.5 block text-[11px] font-medium" style={{ color: "var(--text-secondary)" }}>
            Video titles
          </label>
          <textarea
            id="title-list"
            value={titleText}
            onChange={(event) => {
              setTitleText(event.target.value);
              setNotice(null);
            }}
            rows={6}
            placeholder={"Why the Concorde disappeared\nThe bridge that was designed but never built\nHow the original survived longer than its replacement"}
            className="w-full resize-y rounded-lg px-3 py-2 text-xs outline-none transition-colors focus:border-[var(--turquoise)]"
            style={{
              background: "rgba(0,0,0,0.2)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
          <p className="mt-1 text-[10px]" style={{ color: "var(--text-tertiary)" }}>
            {titles.length} unique title{titles.length === 1 ? "" : "s"} ready
          </p>
        </div>

        <div className="grid content-start gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="title-list-mode" className="mb-1.5 block text-[11px] font-medium" style={{ color: "var(--text-secondary)" }}>
              Production mode
            </label>
            <select
              id="title-list-mode"
              value={selectedMode}
              disabled={workspaceQuery.isLoading || workspaceQuery.isError}
              onChange={(event) =>
                setModeChoice({
                  tenantId: currentWorkspace?.tenant_id || "current",
                  mode: event.target.value as QueueRunMode,
                })
              }
              className="w-full rounded-lg px-3 py-2 text-xs outline-none"
              style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
            >
              <option value="static_docu">Static documentary</option>
              <option value="channel_default">Current channel default</option>
            </select>
          </div>
          <div>
            <label htmlFor="title-list-delivery" className="mb-1.5 block text-[11px] font-medium" style={{ color: "var(--text-secondary)" }}>
              Delivery
            </label>
            <select
              id="title-list-delivery"
              value={selectedDelivery}
              disabled={workspaceQuery.isLoading || workspaceQuery.isError}
              onChange={(event) =>
                setDeliveryChoice({
                  tenantId: currentWorkspace?.tenant_id || "current",
                  mode: event.target.value as QueueDeliveryMode,
                })
              }
              className="w-full rounded-lg px-3 py-2 text-xs outline-none"
              style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
            >
              <option value="youtube_unlisted">Upload unlisted to YouTube</option>
              <option value="render_only">Keep rendered video in StoryEngine</option>
            </select>
          </div>
          <p className="text-[10px] leading-relaxed sm:col-span-2" style={{ color: "var(--text-tertiary)" }}>
            {currentWorkspace
              ? `${currentWorkspace.name}: ${selectedMode === "static_docu" ? "requires the static-documentary renderer" : "uses its saved channel format"}. ${selectedDelivery === "youtube_unlisted" ? "Delivery is unlisted to its connected YouTube channel." : "Delivery stays in StoryEngine."}`
              : workspaceQuery.isError
                ? "This workspace’s saved profile could not be loaded."
                : "Loading this workspace’s saved profile…"}
          </p>
          <button
            type="button"
            onClick={() => runMutation.mutate()}
            disabled={titles.length === 0 || runMutation.isPending || workspaceQuery.isLoading || workspaceQuery.isError}
            className="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-xs font-semibold transition-opacity disabled:cursor-not-allowed disabled:opacity-40 sm:col-span-2"
            style={{ background: "var(--turquoise)", color: "#07110f" }}
          >
            {runMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {runMutation.isPending ? "Starting list…" : "Run list continuously"}
          </button>
        </div>
      </div>

      {(notice || runError || retryError) && (
        <div
          className="mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-[11px]"
          style={{
            background: runError || retryError ? "rgba(255,92,92,0.08)" : "rgba(70,211,154,0.08)",
            color: runError || retryError ? "var(--red)" : "var(--green)",
          }}
          role={runError || retryError ? "alert" : "status"}
        >
          {runError || retryError ? <AlertCircle size={14} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={14} className="mt-0.5 shrink-0" />}
          <span>{runError || retryError || notice}</span>
        </div>
      )}

      {queueQuery.isError && (
        <p className="mt-4 text-[11px]" style={{ color: "var(--red)" }} role="alert">
          Queue status could not be loaded: {queueQuery.error instanceof Error ? queueQuery.error.message : "Unknown error"}
        </p>
      )}

      {items.length > 0 && (
        <div className="mt-5 border-t pt-4" style={{ borderColor: "var(--border-subtle)" }}>
          <div className="mb-2 flex items-center justify-between gap-3">
            <h3 className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>Title lifecycle</h3>
            <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>Refreshes automatically</span>
          </div>
          <div className="space-y-2">
            {orderedItems.map((item, index) => {
              const lifecycle = queueLifecycle(item);
              return (
                <div
                  key={item.id}
                  className="grid gap-2 rounded-lg p-2.5 md:grid-cols-[28px_1fr_210px_auto] md:items-start"
                  style={{ background: "rgba(255,255,255,0.025)", border: "1px solid var(--border-subtle)" }}
                >
                  <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{index + 1}</span>
                  <p className="min-w-0 text-xs font-medium" style={{ color: "var(--text-primary)" }}>{item.title}</p>
                  <QueueStatus item={item} />
                  <div className="flex items-center gap-2 md:justify-end">
                    {item.video_id && (
                      <Link
                        href={`/pipeline/${item.video_id}`}
                        className="inline-flex items-center gap-1 text-[10px] font-medium hover:underline"
                        style={{ color: "var(--turquoise)" }}
                      >
                        Open <ExternalLink size={10} />
                      </Link>
                    )}
                    {(lifecycle === "failed" || lifecycle === "blocked") && item.status === "failed" && (
                      <button
                        type="button"
                        onClick={() => retryMutation.mutate(item.id)}
                        disabled={retryMutation.isPending}
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium disabled:opacity-40"
                        style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}
                      >
                        {retryingId === item.id ? <Loader2 size={10} className="animate-spin" /> : <RotateCcw size={10} />}
                        Retry
                      </button>
                    )}
                    {lifecycle === "blocked" && (
                      <Link href="/autopilot" className="text-[10px] hover:underline" style={{ color: "var(--orange)" }}>
                        Review limits
                      </Link>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
