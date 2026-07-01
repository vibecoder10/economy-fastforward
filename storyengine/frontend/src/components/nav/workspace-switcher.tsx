"use client";

// Channel Manager command center: the Slack-style workspace switcher. Lists the
// operator's client channels and switches the active one (which re-scopes the
// whole app via the X-Active-Tenant header + a full reload). Renders nothing for
// normal single-channel users, so their sidebar is unchanged.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, ChevronsUpDown, Check, Plus, Trash2 } from "lucide-react";
import {
  getWorkspaces,
  getActiveTenant,
  setActiveTenant,
  createWorkspace,
  removeWorkspace,
} from "@/lib/api";

export function WorkspaceSwitcher({ collapsed }: { collapsed?: boolean }) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const { data } = useQuery({ queryKey: ["workspaces"], queryFn: getWorkspaces });

  // Only operators (or anyone who somehow belongs to >1 tenant) see the switcher.
  if (!data || (!data.is_operator && data.workspaces.length <= 1)) return null;

  const active = getActiveTenant();
  const current = data.workspaces.find((w) => w.tenant_id === active) ?? data.workspaces[0];
  // "Operating a client channel" = an active workspace explicitly set to something
  // other than the home (first/original) workspace. This is the danger state to
  // make unmissable, so uploads/actions don't land on the wrong client.
  const homeTenant = data.workspaces[0]?.tenant_id;
  const isClient = !!active && active !== homeTenant;

  async function addClient() {
    const name = window.prompt("New client channel name (e.g. DesignedUsed):")?.trim();
    if (!name) return;
    setCreating(true);
    try {
      const ws = await createWorkspace(name);
      setActiveTenant(ws.tenant_id); // reloads into the new workspace
    } catch (e) {
      alert(e instanceof Error ? e.message : "Couldn't create workspace");
      setCreating(false);
    }
  }

  async function remove(w: { tenant_id: string; name: string }) {
    const okToRemove = window.confirm(
      `Remove "${w.name}" from your command center?\n\n` +
        "This only unlinks it from your switcher — the channel's videos, keys, and " +
        "settings are kept, and you can re-add it later.",
    );
    if (!okToRemove) return;
    try {
      await removeWorkspace(w.tenant_id);
      // If we removed the one we're currently in, drop back to home; else refresh.
      if (getActiveTenant() === w.tenant_id) setActiveTenant(null);
      else window.location.reload();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Couldn't remove workspace");
    }
  }

  return (
    <div className="relative px-2 pt-2">
      {!collapsed && isClient && (
        <div
          className="px-1 pb-1 text-[9px] font-bold uppercase tracking-wider"
          style={{ color: "var(--gold)" }}
        >
          ● Operating client channel
        </div>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        title={collapsed ? `${isClient ? "Client: " : ""}${current?.name}` : undefined}
        className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg transition-colors hover:brightness-110 ${
          collapsed ? "justify-center" : ""
        }`}
        style={{
          background: isClient ? "rgba(212, 168, 82, 0.12)" : "var(--bg-surface)",
          border: `1px solid ${isClient ? "var(--gold)" : "var(--border-subtle)"}`,
        }}
      >
        <Building2
          size={16}
          className="shrink-0"
          style={{ color: isClient ? "var(--gold)" : "var(--turquoise)" }}
        />
        {!collapsed && (
          <>
            <span
              className="text-sm font-medium font-body truncate flex-1 text-left"
              style={{ color: "var(--text-primary)" }}
            >
              {current?.name ?? "Workspace"}
            </span>
            <ChevronsUpDown size={14} className="shrink-0" style={{ color: "var(--text-tertiary)" }} />
          </>
        )}
      </button>

      {open && (
        <div
          className={`absolute z-50 mt-1 rounded-lg py-1 shadow-xl ${collapsed ? "left-full ml-2 top-2" : "left-2 right-2"}`}
          style={{ background: "var(--bg-deep)", border: "1px solid var(--border)", minWidth: 180 }}
        >
          <div
            className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-tertiary)" }}
          >
            Client channels
          </div>
          {data.workspaces.map((w) => (
            <div
              key={w.tenant_id}
              className="group flex items-center transition-colors hover:bg-[var(--bg-surface)]"
            >
              <button
                onClick={() => setActiveTenant(w.tenant_id)}
                className="flex items-center gap-2 flex-1 min-w-0 px-3 py-2 text-left"
              >
                <Building2 size={14} className="shrink-0" style={{ color: "var(--text-tertiary)" }} />
                <span className="text-sm font-body truncate flex-1" style={{ color: "var(--text-primary)" }}>
                  {w.name}
                </span>
                {w.tenant_id === current?.tenant_id && (
                  <Check size={14} className="shrink-0" style={{ color: "var(--turquoise)" }} />
                )}
              </button>
              {/* Remove control — hidden on the home workspace so you can't unlink your base. */}
              {w.tenant_id !== homeTenant && (
                <button
                  onClick={() => remove(w)}
                  title={`Remove ${w.name} from command center`}
                  className="shrink-0 px-2 py-2 opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ color: "var(--text-tertiary)" }}
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          ))}
          {data.is_operator && (
            <button
              onClick={addClient}
              disabled={creating}
              className="flex items-center gap-2 w-full px-3 py-2 text-left transition-colors hover:bg-[var(--bg-surface)] disabled:opacity-50"
              style={{ borderTop: "1px solid var(--border-subtle)", color: "var(--turquoise)" }}
            >
              <Plus size={14} className="shrink-0" />
              <span className="text-sm font-body">{creating ? "Creating…" : "Add client channel"}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
