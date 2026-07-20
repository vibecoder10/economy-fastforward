"use client";

// Feature board (C65) — "suggest a feature" + upvotes + a status ladder.
// The platform's FIRST deliberately cross-tenant surface: every customer
// sees the SAME board (tasks/decisions.md 2026-07-20 "Feature board" entry).

import { useState } from "react";
import { motion } from "framer-motion";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowBigUp, Lightbulb, Plus, X } from "lucide-react";
import {
  createFeatureRequest,
  getFeatureBoard,
  getWorkspaces,
  unvoteFeatureRequest,
  updateFeatureRequestStatus,
  voteFeatureRequest,
  type FeatureBoardStatus,
  type FeatureRequest,
} from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";

const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.06 } } };
const item = { hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0, transition: { duration: 0.4 } } };

const STATUS_TABS: { value: FeatureBoardStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "under_review", label: "Under Review" },
  { value: "planned", label: "Planned" },
  { value: "building", label: "Building" },
  { value: "in_beta", label: "In Beta" },
  { value: "shipped", label: "Shipped" },
  { value: "declined", label: "Declined" },
];

const STATUS_PILL: Record<FeatureBoardStatus, { label: string; color: string }> = {
  under_review: { label: "Under Review", color: "gold" },
  planned: { label: "Planned", color: "turquoise" },
  building: { label: "Building", color: "purple" },
  in_beta: { label: "In Beta", color: "orange" },
  shipped: { label: "Shipped", color: "green" },
  declined: { label: "Declined", color: "red" },
};

const NEXT_STATUS: FeatureBoardStatus[] = [
  "under_review", "planned", "building", "in_beta", "shipped", "declined",
];

export default function IdeasPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<FeatureBoardStatus | "">("");
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [archetype, setArchetype] = useState("");

  const { data: workspaces } = useQuery({ queryKey: ["workspaces"], queryFn: getWorkspaces });
  const isOperator = !!workspaces?.is_operator;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["feature-board", statusFilter],
    queryFn: () => getFeatureBoard(statusFilter || undefined),
  });

  const createMutation = useMutation({
    mutationFn: createFeatureRequest,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["feature-board"] });
      setTitle("");
      setBody("");
      setArchetype("");
      setShowForm(false);
    },
  });

  const voteMutation = useMutation({
    mutationFn: ({ id, voted }: { id: string; voted: boolean }) =>
      voted ? unvoteFeatureRequest(id) : voteFeatureRequest(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["feature-board"] }),
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, status, declined_reason }: { id: string; status: FeatureBoardStatus; declined_reason?: string }) =>
      updateFeatureRequestStatus(id, status, declined_reason),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["feature-board"] }),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    createMutation.mutate({
      title: title.trim(),
      body: body.trim() || undefined,
      channel_archetype: archetype.trim() || undefined,
    });
  }

  function handleStatusChange(req: FeatureRequest, next: FeatureBoardStatus) {
    let declined_reason: string | undefined;
    if (next === "declined") {
      declined_reason = window.prompt("Reason for declining (optional):") || undefined;
    }
    statusMutation.mutate({ id: req.id, status: next, declined_reason });
  }

  const requests = data?.requests ?? [];

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold font-body flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
            <Lightbulb size={24} style={{ color: "var(--turquoise)" }} />
            Ideas
          </h1>
          <p className="text-sm font-body mt-1" style={{ color: "var(--text-secondary)" }}>
            Suggest a feature, upvote what you want most — every StoryEngine customer sees the same board.
          </p>
        </div>
        <ActionButton icon={showForm ? X : Plus} onClick={() => setShowForm((s) => !s)}>
          {showForm ? "Cancel" : "Suggest a feature"}
        </ActionButton>
      </div>

      {showForm && (
        <GlassCard>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="text-xs font-semibold font-body uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
                Title
              </label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={120}
                required
                placeholder="e.g. Per-scene voice casting"
                className="w-full mt-1 px-3 py-2 rounded-lg text-sm font-body outline-none"
                style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
              />
            </div>
            <div>
              <label className="text-xs font-semibold font-body uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
                Details (optional)
              </label>
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                maxLength={2000}
                rows={3}
                placeholder="What would this let you do?"
                className="w-full mt-1 px-3 py-2 rounded-lg text-sm font-body outline-none resize-none"
                style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
              />
            </div>
            <div>
              <label className="text-xs font-semibold font-body uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
                What kind of channel do you run? (optional)
              </label>
              <input
                value={archetype}
                onChange={(e) => setArchetype(e.target.value)}
                placeholder="e.g. talking-head explainer"
                className="w-full mt-1 px-3 py-2 rounded-lg text-sm font-body outline-none"
                style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
              />
            </div>
            {createMutation.isError && (
              <p className="text-xs font-body" style={{ color: "var(--red)" }}>
                {(createMutation.error as Error)?.message || "Couldn't submit — try again."}
              </p>
            )}
            <div className="flex justify-end">
              <ActionButton disabled={createMutation.isPending || !title.trim()}>
                {createMutation.isPending ? "Submitting…" : "Submit suggestion"}
              </ActionButton>
            </div>
          </form>
        </GlassCard>
      )}

      <div className="flex flex-wrap gap-2">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setStatusFilter(tab.value)}
            className="px-3 py-1.5 rounded-full text-xs font-semibold font-body transition-colors"
            style={{
              background: statusFilter === tab.value ? "var(--turquoise-dim)" : "var(--bg-surface)",
              color: statusFilter === tab.value ? "var(--turquoise)" : "var(--text-secondary)",
              border: `1px solid ${statusFilter === tab.value ? "var(--turquoise)" : "var(--border-subtle)"}`,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="flex justify-center py-12">
          <Spinner size="lg" />
        </div>
      )}

      {!isLoading && error && (
        <ErrorCard message={(error as Error)?.message || "Couldn't load the feature board."} onRetry={() => refetch()} />
      )}

      {!isLoading && !error && requests.length === 0 && (
        <EmptyState
          icon={Lightbulb}
          title="No suggestions yet"
          description="Be the first to suggest a feature — every customer sees the same board."
          actionLabel={showForm ? undefined : "Suggest a feature"}
          onAction={showForm ? undefined : () => setShowForm(true)}
        />
      )}

      {!isLoading && !error && requests.length > 0 && (
        <motion.div variants={container} initial="hidden" animate="show" className="space-y-3">
          {requests.map((req) => {
            const pill = STATUS_PILL[req.status];
            return (
              <motion.div key={req.id} variants={item}>
                <GlassCard className="flex gap-4">
                  <button
                    onClick={() => voteMutation.mutate({ id: req.id, voted: req.voted_by_me })}
                    disabled={voteMutation.isPending}
                    title={req.voted_by_me ? "Remove your upvote" : "Upvote this"}
                    className="flex flex-col items-center justify-center gap-0.5 px-2 py-1 rounded-lg shrink-0 h-fit transition-colors"
                    style={{
                      background: req.voted_by_me ? "var(--turquoise-dim)" : "var(--bg-surface)",
                      border: `1px solid ${req.voted_by_me ? "var(--turquoise)" : "var(--border-subtle)"}`,
                      color: req.voted_by_me ? "var(--turquoise)" : "var(--text-secondary)",
                    }}
                  >
                    <ArrowBigUp size={18} fill={req.voted_by_me ? "currentColor" : "none"} />
                    <span className="text-sm font-semibold font-body">{req.vote_count}</span>
                  </button>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-sm font-semibold font-body" style={{ color: "var(--text-primary)" }}>
                        {req.title}
                      </h3>
                      <StatusPill label={pill.label} color={pill.color} />
                      {req.is_mine && <StatusPill label="Yours" color="turquoise" />}
                    </div>
                    {req.body && (
                      <p className="text-sm font-body mt-1 whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                        {req.body}
                      </p>
                    )}
                    {req.channel_archetype && (
                      <p className="text-xs font-body mt-1" style={{ color: "var(--text-tertiary)" }}>
                        Channel: {req.channel_archetype}
                      </p>
                    )}
                    {req.status === "declined" && req.declined_reason && (
                      <p className="text-xs font-body mt-1" style={{ color: "var(--red)" }}>
                        Declined: {req.declined_reason}
                      </p>
                    )}

                    {isOperator && (
                      <div className="mt-3 flex items-center gap-2">
                        <label className="text-[10px] font-semibold font-body uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
                          Move to
                        </label>
                        <select
                          value={req.status}
                          onChange={(e) => handleStatusChange(req, e.target.value as FeatureBoardStatus)}
                          disabled={statusMutation.isPending}
                          className="text-xs font-body px-2 py-1 rounded-lg outline-none"
                          style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
                        >
                          {NEXT_STATUS.map((s) => (
                            <option key={s} value={s}>
                              {STATUS_PILL[s].label}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                </GlassCard>
              </motion.div>
            );
          })}
        </motion.div>
      )}
    </div>
  );
}
