"use client";

// Channel Manager command center: the Slack-style workspace switcher. Lists the
// operator's client channels and switches the active one (which re-scopes the
// whole app via the X-Active-Tenant header + a full reload). Renders nothing for
// normal single-channel users, so their sidebar is unchanged.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, ChevronsUpDown, Check, Plus } from "lucide-react";
import {
  getWorkspaces,
  getActiveTenant,
  setActiveTenant,
  createWorkspace,
} from "@/lib/api";

export function WorkspaceSwitcher({ collapsed }: { collapsed?: boolean }) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const { data } = useQuery({ queryKey: ["workspaces"], queryFn: getWorkspaces });

  // Only operators (or anyone who somehow belongs to >1 tenant) see the switcher.
  if (!data || (!data.is_operator && data.workspaces.length <= 1)) return null;

  const active = getActiveTenant();
  const current = data.workspaces.find((w) => w.tenant_id === active) ?? data.workspaces[0];

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

  return (
    <div className="relative px-2 pt-2">
      <button
        onClick={() => setOpen((o) => !o)}
        title={collapsed ? current?.name : undefined}
        className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg transition-colors hover:brightness-110 ${
          collapsed ? "justify-center" : ""
        }`}
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
      >
        <Building2 size={16} className="shrink-0" style={{ color: "var(--turquoise)" }} />
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
            <button
              key={w.tenant_id}
              onClick={() => setActiveTenant(w.tenant_id)}
              className="flex items-center gap-2 w-full px-3 py-2 text-left transition-colors hover:bg-[var(--bg-surface)]"
            >
              <Building2 size={14} className="shrink-0" style={{ color: "var(--text-tertiary)" }} />
              <span className="text-sm font-body truncate flex-1" style={{ color: "var(--text-primary)" }}>
                {w.name}
              </span>
              {w.tenant_id === current?.tenant_id && (
                <Check size={14} className="shrink-0" style={{ color: "var(--turquoise)" }} />
              )}
            </button>
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
