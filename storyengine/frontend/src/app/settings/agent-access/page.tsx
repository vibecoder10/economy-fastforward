"use client";

// Settings → Agent access (checklist P2.4c, chunk C28; tasks/storyengine-
// copilot-ux-map.md §7). Mint/list/revoke UI for the MCP agent tokens
// C26 shipped as session-authed routes (routes/agent_access.py) — this page
// is the only caller. Deliberately mirrors /settings/keys' component
// vocabulary (Card/Modal/Spinner, the same secret-management visual
// language) since an agent token is, structurally, the same kind of thing a
// user is used to managing there: a secret they mint once and revoke later.

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Check,
  Clock,
  Copy,
  KeyRound,
  Plus,
  ShieldOff,
  AlertCircle,
} from "lucide-react";
import { HubTabs, PROFILE_TABS } from "@/components/nav/hub-tabs";
import { Card, Modal, Spinner } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import {
  getAgentTokens,
  createAgentToken,
  revokeAgentToken,
  type AgentToken,
  type AgentTokenCreated,
} from "@/lib/api";
import { API_URL } from "@/lib/env";
import { humanizeError } from "@/lib/errors";
import { cn } from "@/lib/utils";

const MCP_ENDPOINT = `${API_URL}/api/mcp`;

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export default function AgentAccessPage() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const [createOpen, setCreateOpen] = useState(false);
  const [tokenName, setTokenName] = useState("");
  // Holds the ONE response that ever carries the plaintext token — never
  // written to any cache, never re-fetched. Cleared on modal close, so it
  // lives only as long as this component's own in-memory state.
  const [mintedToken, setMintedToken] = useState<AgentTokenCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<AgentToken | null>(null);

  const {
    data: tokens,
    isLoading,
    error: fetchError,
  } = useQuery({
    queryKey: ["agentTokens"],
    queryFn: getAgentTokens,
  });

  const createMutation = useMutation({
    mutationFn: (name: string) => createAgentToken(name),
    onSuccess: (result) => {
      setMintedToken(result);
      queryClient.invalidateQueries({ queryKey: ["agentTokens"] });
    },
    onError: (err) => {
      toast.error(humanizeError(err, "Couldn't create that token."));
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => revokeAgentToken(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agentTokens"] });
      toast.success("Token revoked.");
    },
    onError: (err) => {
      toast.error(humanizeError(err, "Couldn't revoke that token."));
    },
    onSettled: () => setRevokeTarget(null),
  });

  const closeCreateModal = () => {
    setCreateOpen(false);
    setTokenName("");
    setMintedToken(null);
    setCopied(false);
  };

  const handleCopy = () => {
    if (!mintedToken) return;
    navigator.clipboard.writeText(mintedToken.token);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const activeTokens = (tokens ?? []).filter((t) => !t.revoked_at);
  const revokedTokens = (tokens ?? []).filter((t) => t.revoked_at);

  return (
    <div className="space-y-6 max-w-3xl">
      <HubTabs tabs={PROFILE_TABS} />
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold">Agent access</h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Let an AI agent (Claude, or any MCP client) work on your videos on your behalf — same pipeline, same
            cost quotes, attributed back to you.
          </p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-black"
        >
          <Plus size={16} />
          Create token
        </button>
      </div>

      {/* How to connect — honest about the dark flag: this endpoint exists
          in the codebase but only responds when the server operator has
          MCP_ENABLED=true set. */}
      <Card>
        <div className="p-4 space-y-2">
          <h2 className="text-sm font-semibold">How to connect</h2>
          <p className="text-xs text-[var(--text-secondary)]">
            Point your MCP client at this endpoint and use a token below as the bearer credential:
          </p>
          <code className="block rounded bg-[var(--background)] px-3 py-2 text-xs break-all">
            {MCP_ENDPOINT}
          </code>
          <p className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
            <AlertCircle size={12} className="shrink-0" />
            Requires MCP to be enabled on your server — ask your administrator if connections aren&apos;t
            working yet.
          </p>
        </div>
      </Card>

      {/* Token list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" />
        </div>
      ) : fetchError ? (
        <div className="flex items-center gap-2 rounded-lg bg-[var(--error)]/10 p-4 text-sm text-[var(--error)]">
          <AlertCircle size={16} />
          Failed to load agent tokens: {humanizeError(fetchError, "Something went wrong.")}
        </div>
      ) : (tokens ?? []).length === 0 ? (
        <Card>
          <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
            <Bot size={32} className="text-[var(--text-secondary)]" />
            <div>
              <p className="font-medium">No agent tokens yet</p>
              <p className="mt-1 text-sm text-[var(--text-secondary)]">
                Create one to let an AI agent connect to your account over MCP.
              </p>
            </div>
          </div>
        </Card>
      ) : (
        <div className="space-y-3">
          {activeTokens.map((t) => (
            <AgentTokenCard
              key={t.id}
              token={t}
              onRevoke={() => setRevokeTarget(t)}
              revoking={revokeMutation.isPending && revokeTarget?.id === t.id}
            />
          ))}
          {revokedTokens.length > 0 && (
            <>
              <p className="pt-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                Revoked
              </p>
              {revokedTokens.map((t) => (
                <AgentTokenCard key={t.id} token={t} onRevoke={() => {}} revoking={false} />
              ))}
            </>
          )}
        </div>
      )}

      {/* Create token modal — form, then the ONE-TIME plaintext reveal */}
      <Modal open={createOpen} onClose={closeCreateModal} title="Create agent token" size="md">
        {mintedToken ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-[var(--success)]">
              <Check size={18} />
              <p className="font-medium">Token created</p>
            </div>
            <div>
              <label className="text-xs font-medium text-[var(--text-secondary)]">Your token</label>
              <div className="mt-1 flex items-center gap-2">
                <code className="flex-1 truncate rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs">
                  {mintedToken.token}
                </code>
                <button
                  type="button"
                  onClick={handleCopy}
                  aria-label="Copy token to clipboard"
                  title="Copy token to clipboard"
                  className={cn(
                    "flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors",
                    copied
                      ? "bg-[var(--success)]/15 text-[var(--success)]"
                      : "bg-[var(--surface-elevated)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  )}
                >
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>
            <div className="flex items-start gap-2 rounded-lg bg-[var(--warning)]/10 p-3 text-xs text-[var(--warning)]">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span>
                This is shown once — copy it now. If you lose it, revoke this token and create a new one.
              </span>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={closeCreateModal}
                className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-black"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const name = tokenName.trim();
              if (name) createMutation.mutate(name);
            }}
            className="space-y-4"
          >
            <div className="flex flex-col gap-1.5">
              <label htmlFor="agent-token-name" className="text-sm font-medium text-[var(--text-secondary)]">
                Name
              </label>
              <input
                id="agent-token-name"
                type="text"
                value={tokenName}
                onChange={(e) => setTokenName(e.target.value)}
                placeholder="e.g. Claude Desktop, my laptop…"
                autoFocus
                autoComplete="off"
                disabled={createMutation.isPending}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent)] disabled:opacity-50"
              />
              <p className="text-xs text-[var(--text-secondary)]">
                A label to tell this connection apart from others later — not shown to the agent.
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeCreateModal}
                disabled={createMutation.isPending}
                className="rounded-lg px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!tokenName.trim() || createMutation.isPending}
                className="flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-black disabled:opacity-50"
              >
                {createMutation.isPending && <Spinner size="sm" className="text-black" />}
                {createMutation.isPending ? "Creating…" : "Create token"}
              </button>
            </div>
          </form>
        )}
      </Modal>

      {/* Revoke confirm */}
      <Modal open={revokeTarget !== null} onClose={() => setRevokeTarget(null)} title="Revoke token" size="sm">
        {revokeTarget && (
          <div className="space-y-4">
            <p className="text-sm text-[var(--text-secondary)]">
              Revoke <strong className="text-[var(--text-primary)]">{revokeTarget.name}</strong>? Any agent
              using this token will lose access immediately. This can&apos;t be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRevokeTarget(null)}
                className="rounded-lg px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => revokeMutation.mutate(revokeTarget.id)}
                disabled={revokeMutation.isPending}
                className="flex items-center gap-2 rounded-lg bg-[var(--error)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {revokeMutation.isPending && <Spinner size="sm" className="text-white" />}
                {revokeMutation.isPending ? "Revoking…" : "Revoke"}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function AgentTokenCard({
  token,
  onRevoke,
  revoking,
}: {
  token: AgentToken;
  onRevoke: () => void;
  revoking: boolean;
}) {
  const revoked = !!token.revoked_at;
  return (
    <Card>
      <div className="flex items-start justify-between gap-3 p-4">
        <div className="flex items-start gap-3 min-w-0">
          <div
            className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
              revoked ? "bg-[var(--surface-elevated)]" : "bg-green-500/10"
            )}
          >
            <KeyRound size={18} className={revoked ? "text-[var(--text-tertiary)]" : "text-green-500"} />
          </div>
          <div className="min-w-0">
            <h3
              className={cn("font-medium truncate", revoked && "line-through text-[var(--text-tertiary)]")}
            >
              {token.name}
            </h3>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--text-tertiary)]">
              <span>Created {formatDate(token.created_at)}</span>
              <span className="flex items-center gap-1">
                <Clock size={11} />
                Last used {formatDate(token.last_used_at)}
              </span>
              {revoked && (
                <span className="rounded bg-[var(--error)]/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--error)]">
                  Revoked {formatDate(token.revoked_at)}
                </span>
              )}
            </div>
          </div>
        </div>
        {!revoked && (
          <button
            onClick={onRevoke}
            disabled={revoking}
            aria-label={`Revoke token ${token.name}`}
            className="flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-[var(--error)] hover:bg-[var(--error)]/10 disabled:opacity-50"
          >
            <ShieldOff size={14} />
            Revoke
          </button>
        )}
      </div>
    </Card>
  );
}
