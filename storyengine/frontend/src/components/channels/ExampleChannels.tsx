"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, X, RefreshCw } from "lucide-react";
import {
  getNicheChannels,
  addNicheChannel,
  removeNicheChannel,
  scrapeCompetitorChannels,
  getScrapeStatus,
} from "@/lib/api";

// Derive a readable channel name from a pasted YouTube URL.
function channelNameFromUrl(url: string): string {
  const match =
    url.match(/@([^/?]+)/)?.[1] ||
    url.match(/\/c\/([^/?]+)/)?.[1] ||
    url.match(/\/channel\/([^/?]+)/)?.[1];
  try {
    return match || new URL(url).pathname.split("/").filter(Boolean).pop() || "Unknown";
  } catch {
    return match || "Unknown";
  }
}

/**
 * Manage the user's example/modeling channels — add by URL, delete, re-sync.
 * Free for all plans; feeds the title generator. Shared by the Profile page
 * (variant="full") and the New Video modal (variant="compact").
 */
export function ExampleChannels({ variant = "full" }: { variant?: "full" | "compact" }) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const compact = variant === "compact";

  const { data: channels, isLoading } = useQuery({
    queryKey: ["niche-channels"],
    queryFn: getNicheChannels,
    staleTime: 60000,
  });

  const { data: scrapeStatus } = useQuery({
    queryKey: ["scrape-status"],
    queryFn: getScrapeStatus,
    refetchInterval: (q) => (q.state.data?.is_running ? 3000 : false),
  });
  const scraping = scrapeStatus?.is_running ?? false;

  const addMutation = useMutation({
    mutationFn: (u: string) => addNicheChannel(channelNameFromUrl(u), u),
    onSuccess: () => {
      setUrl("");
      setError("");
      queryClient.invalidateQueries({ queryKey: ["niche-channels"] });
    },
    onError: (e: Error) => setError(e.message || "Couldn't add that channel — check the link."),
  });

  const deleteMutation = useMutation({
    mutationFn: removeNicheChannel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["niche-channels"] }),
  });

  const resyncMutation = useMutation({
    mutationFn: scrapeCompetitorChannels,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["scrape-status"] }),
  });

  const submit = () => {
    const u = url.trim();
    if (!u) return;
    if (!u.includes("youtube.com") && !u.startsWith("@")) {
      setError("Paste a YouTube channel link (or @handle).");
      return;
    }
    addMutation.mutate(u);
  };

  const list = channels ?? [];

  return (
    <div className="space-y-3">
      {/* Add by URL */}
      <div>
        <div className="flex gap-2">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="Paste a YouTube channel link…"
            className="flex-1 px-3 py-2 rounded-lg text-sm font-body outline-none"
            style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
            onFocus={(e) => (e.target.style.borderColor = "var(--turquoise)")}
            onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!url.trim() || addMutation.isPending}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            {addMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Add
          </button>
        </div>
        {error && (
          <p className="text-[11px] mt-1.5" style={{ color: "var(--red)" }}>{error}</p>
        )}
      </div>

      {/* List */}
      {isLoading ? (
        <div className="flex items-center gap-2 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
          <Loader2 size={12} className="animate-spin" /> Loading channels…
        </div>
      ) : list.length === 0 ? (
        <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
          No channels yet. Paste a YouTube channel you want your videos modeled on.
        </p>
      ) : (
        <div className="space-y-1.5">
          {list.map((ch) => {
            const name =
              ch.channel_name && ch.channel_name !== "None"
                ? ch.channel_name
                : ch.channel_url?.match(/@([^/]+)/)?.[1] || `Channel ${ch.id.slice(0, 6)}`;
            return (
              <div
                key={ch.id}
                className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg"
                style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}
              >
                <div className="min-w-0">
                  <div className="text-sm truncate" style={{ color: "var(--text-primary)" }}>{name}</div>
                  {!compact && ch.channel_url && (
                    <div className="text-[10px] truncate" style={{ color: "var(--text-tertiary)" }}>{ch.channel_url}</div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    if (confirm(`Remove "${name}"?`)) deleteMutation.mutate(ch.id);
                  }}
                  className="p-1 rounded hover:bg-red-500/20 shrink-0"
                  title={`Remove ${name}`}
                  aria-label={`Remove ${name}`}
                >
                  <X size={14} style={{ color: "var(--text-tertiary)" }} />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Re-sync */}
      {list.length > 0 && (
        <button
          type="button"
          onClick={() => resyncMutation.mutate()}
          disabled={scraping || resyncMutation.isPending}
          className="inline-flex items-center gap-1.5 text-[11px] font-medium transition-colors disabled:opacity-50"
          style={{ color: "var(--turquoise)" }}
        >
          <RefreshCw size={11} className={scraping ? "animate-spin" : ""} />
          {scraping
            ? `Re-syncing… ${scrapeStatus?.channels_done ?? 0}/${scrapeStatus?.channels_total ?? 0}`
            : "Re-sync channels"}
        </button>
      )}
    </div>
  );
}
