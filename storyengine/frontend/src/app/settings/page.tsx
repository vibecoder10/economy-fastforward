"use client";

import { Settings } from "lucide-react";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Settings</h1>

      <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] py-16">
        <Settings size={40} className="text-[var(--text-secondary)]" />
        <div className="text-center">
          <p className="font-medium">Settings coming soon</p>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Profile, channel config, API keys, and cost reports.
          </p>
        </div>
      </div>
    </div>
  );
}
