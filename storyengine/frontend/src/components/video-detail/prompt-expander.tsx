"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Pencil, Check, X } from "lucide-react";

interface PromptExpanderProps {
  prompt: string;
  onSave?: (newPrompt: string) => void;
  label?: string;
  previewLength?: number;
}

export function PromptExpander({
  prompt,
  onSave,
  label = "Prompt",
  previewLength = 80,
}: PromptExpanderProps) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(prompt);

  const preview = prompt.length > previewLength
    ? prompt.slice(0, previewLength) + "..."
    : prompt;

  const handleSave = () => {
    onSave?.(editText);
    setEditing(false);
  };

  const handleCancel = () => {
    setEditText(prompt);
    setEditing(false);
  };

  return (
    <div
      className="rounded-lg"
      style={{ background: "var(--bg-card-hover)", border: "1px solid var(--border)" }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        {expanded ? (
          <ChevronDown size={12} style={{ color: "var(--text-muted)" }} />
        ) : (
          <ChevronRight size={12} style={{ color: "var(--text-muted)" }} />
        )}
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{label}:</span>
        {!expanded && (
          <span className="text-xs truncate flex-1" style={{ color: "var(--text-secondary)" }}>
            {preview}
          </span>
        )}
      </button>
      {expanded && (
        <div className="px-3 pb-3">
          {editing ? (
            <div className="space-y-2">
              <textarea
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                className="w-full rounded-md px-3 py-2 text-xs outline-none resize-y min-h-[80px]"
                style={{
                  background: "var(--bg-primary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
              <div className="flex gap-2">
                <button
                  onClick={handleSave}
                  className="flex items-center gap-1 text-xs px-3 py-1 rounded"
                  style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
                >
                  <Check size={10} /> Save
                </button>
                <button
                  onClick={handleCancel}
                  className="flex items-center gap-1 text-xs px-3 py-1 rounded"
                  style={{ color: "var(--text-muted)" }}
                >
                  <X size={10} /> Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-2">
              <p className="text-xs flex-1" style={{ color: "var(--text-secondary)", lineHeight: 1.6 }}>
                {prompt}
              </p>
              {onSave && (
                <button
                  onClick={() => setEditing(true)}
                  className="flex-shrink-0 p-1 rounded"
                  style={{ color: "var(--text-muted)" }}
                >
                  <Pencil size={12} />
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
