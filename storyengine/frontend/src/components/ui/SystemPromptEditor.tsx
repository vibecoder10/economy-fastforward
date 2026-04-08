"use client";

import { useState } from "react";
import { ChevronDown, Save, RotateCcw, Loader2 } from "lucide-react";

interface SystemPromptEditorProps {
  label: string;
  currentValue: string | null;
  onSave: (text: string) => Promise<void>;
  onReset: () => Promise<string>;
  saveLabel?: string;
}

export function SystemPromptEditor({ label, currentValue, onSave, onReset, saveLabel }: SystemPromptEditorProps) {
  const [expanded, setExpanded] = useState(false);
  const [text, setText] = useState(currentValue || "");
  const [loaded, setLoaded] = useState(!!currentValue);
  const [saving, setSaving] = useState(false);

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: "1px solid rgba(255,255,255,0.08)" }}
    >
      <button
        onClick={async () => {
          if (!expanded && !loaded && !currentValue) {
            try {
              const defaultText = await onReset();
              setText(defaultText);
              setLoaded(true);
            } catch { /* keep empty */ }
          }
          setExpanded(!expanded);
        }}
        className="w-full flex items-center justify-between px-4 py-3 text-xs font-semibold transition-all hover:brightness-110"
        style={{ background: "rgba(255,255,255,0.03)", color: "var(--text-secondary)" }}
      >
        <span className="flex items-center gap-2">
          <ChevronDown size={14} className={`transition-transform ${expanded ? "" : "-rotate-90"}`} />
          {label}
        </span>
        <span className="text-[10px] font-mono" style={{ color: currentValue ? "var(--green)" : "var(--text-tertiary)" }}>
          {currentValue ? "Custom" : "Default"}
        </span>
      </button>
      {expanded && (
        <div className="px-4 pb-4 pt-2" style={{ background: "rgba(0,0,0,0.2)" }}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="w-full rounded-lg p-3 text-[11px] font-mono leading-relaxed resize-y"
            style={{
              background: "rgba(0,0,0,0.3)",
              color: "var(--text-primary)",
              border: "1px solid rgba(255,255,255,0.08)",
              minHeight: "200px",
              maxHeight: "500px",
            }}
            rows={12}
          />
          <div className="flex items-center gap-2 mt-2">
            <button
              onClick={async () => {
                setSaving(true);
                try {
                  await onSave(text);
                } catch (err) {
                  alert(`Save failed: ${(err as Error).message}`);
                } finally {
                  setSaving(false);
                }
              }}
              disabled={saving}
              className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 disabled:opacity-50 transition-all hover:brightness-110"
              style={{ background: "var(--green)", color: "var(--bg-void)" }}
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              {saveLabel || "Save to Video"}
            </button>
            <button
              onClick={async () => {
                try {
                  const defaultText = await onReset();
                  setText(defaultText);
                } catch (err) {
                  alert(`Reset failed: ${(err as Error).message}`);
                }
              }}
              className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 transition-all hover:brightness-110"
              style={{ color: "var(--text-tertiary)", border: "1px solid rgba(255,255,255,0.1)" }}
            >
              <RotateCcw size={12} />
              Reset to Default
            </button>
            <span className="text-[9px] font-mono ml-2" style={{ color: "var(--text-tertiary)" }}>
              {text.length} chars
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
