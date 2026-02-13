"use client";

import { useState, useEffect, useCallback } from "react";

interface ChannelProfileSummary {
  id: string;
  name: string;
  isDefault: boolean;
  updatedAt: string;
}

interface ChannelProfileFull {
  id: string;
  name: string;
  isDefault: boolean;
  narrativeConfig: {
    defaultTone: string;
    defaultSceneCount: number;
    narrativeFramework: string;
    customFrameworkPrompt?: string;
    writerGuidance: string;
    exampleScripts?: string[];
  };
  visualConfig: {
    stylePrefix: string;
    styleSuffix: string;
    materialVocabulary: Record<string, string[]>;
    defaultShotRotation: string[];
    wordBudget: { min: number; max: number };
    textRules: { maxElements: number; maxWordsPerElement: number };
    thumbnailStyle: string;
  };
  visualAnchors: { name: string; description: string }[];
}

export default function ChannelProfilesPage() {
  const [profiles, setProfiles] = useState<ChannelProfileSummary[]>([]);
  const [editing, setEditing] = useState<ChannelProfileFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const fetchProfiles = useCallback(async () => {
    try {
      const res = await fetch("/api/profiles");
      if (res.ok) {
        const data = await res.json();
        setProfiles(data);
      }
    } catch {
      // ignore
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  async function handleEdit(id: string) {
    try {
      const res = await fetch(`/api/profiles/${id}`);
      if (res.ok) {
        const data = await res.json();
        setEditing(data);
      }
    } catch {
      setMessage({ type: "error", text: "Failed to load profile" });
    }
  }

  async function handleSave() {
    if (!editing) return;
    setSaving(true);
    setMessage(null);

    try {
      const res = await fetch(`/api/profiles/${editing.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editing),
      });

      if (res.ok) {
        setMessage({ type: "success", text: "Profile saved" });
        setEditing(null);
        fetchProfiles();
      } else {
        const data = await res.json();
        setMessage({ type: "error", text: data.error || "Failed to save" });
      }
    } catch {
      setMessage({ type: "error", text: "Network error" });
    }
    setSaving(false);
  }

  async function handleCreate() {
    try {
      const res = await fetch("/api/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "New Profile" }),
      });

      if (res.ok) {
        const data = await res.json();
        fetchProfiles();
        handleEdit(data.id);
      }
    } catch {
      setMessage({ type: "error", text: "Failed to create profile" });
    }
  }

  if (loading) {
    return (
      <div className="max-w-3xl">
        <h1 className="text-3xl font-bold mb-8">Channel Profiles</h1>
        <div className="text-text-secondary">Loading...</div>
      </div>
    );
  }

  if (editing) {
    return (
      <div className="max-w-3xl">
        <div className="flex items-center gap-4 mb-8">
          <button
            onClick={() => setEditing(null)}
            className="text-text-secondary hover:text-text-primary transition-colors"
          >
            &larr; Back
          </button>
          <h1 className="text-3xl font-bold">Edit Profile</h1>
        </div>

        {message && (
          <div
            className={`p-3 rounded-lg mb-6 text-sm ${
              message.type === "success"
                ? "bg-success/10 border border-success/30 text-success"
                : "bg-error/10 border border-error/30 text-error"
            }`}
          >
            {message.text}
          </div>
        )}

        <div className="space-y-6">
          {/* Profile Name */}
          <div className="p-5 bg-surface border border-border rounded-xl">
            <label className="block text-sm font-medium text-text-secondary mb-2">
              Profile Name
            </label>
            <input
              type="text"
              value={editing.name}
              onChange={(e) =>
                setEditing({ ...editing, name: e.target.value })
              }
              className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary focus:outline-none focus:border-accent transition-colors"
            />
          </div>

          {/* Narrative Config */}
          <div className="p-5 bg-surface border border-border rounded-xl space-y-4">
            <h3 className="font-semibold text-lg">Narrative Configuration</h3>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Default Tone
              </label>
              <input
                type="text"
                value={editing.narrativeConfig.defaultTone}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    narrativeConfig: {
                      ...editing.narrativeConfig,
                      defaultTone: e.target.value,
                    },
                  })
                }
                className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary focus:outline-none focus:border-accent transition-colors"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Default Scene Count
              </label>
              <input
                type="number"
                value={editing.narrativeConfig.defaultSceneCount}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    narrativeConfig: {
                      ...editing.narrativeConfig,
                      defaultSceneCount: parseInt(e.target.value) || 20,
                    },
                  })
                }
                min={4}
                max={30}
                className="w-32 px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary focus:outline-none focus:border-accent transition-colors"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Narrative Framework
              </label>
              <select
                value={editing.narrativeConfig.narrativeFramework}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    narrativeConfig: {
                      ...editing.narrativeConfig,
                      narrativeFramework: e.target.value,
                    },
                  })
                }
                className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary focus:outline-none focus:border-accent transition-colors"
              >
                <option value="past_present_future">Past / Present / Future</option>
                <option value="problem_solution">Problem / Solution</option>
                <option value="chronological">Chronological</option>
                <option value="custom">Custom</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Writer Guidance
              </label>
              <textarea
                value={editing.narrativeConfig.writerGuidance}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    narrativeConfig: {
                      ...editing.narrativeConfig,
                      writerGuidance: e.target.value,
                    },
                  })
                }
                rows={4}
                className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary focus:outline-none focus:border-accent transition-colors resize-y"
              />
            </div>
          </div>

          {/* Visual Config */}
          <div className="p-5 bg-surface border border-border rounded-xl space-y-4">
            <h3 className="font-semibold text-lg">Visual Configuration</h3>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Style Prefix
              </label>
              <textarea
                value={editing.visualConfig.stylePrefix}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    visualConfig: {
                      ...editing.visualConfig,
                      stylePrefix: e.target.value,
                    },
                  })
                }
                rows={3}
                className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary focus:outline-none focus:border-accent transition-colors resize-y text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Style Suffix
              </label>
              <textarea
                value={editing.visualConfig.styleSuffix}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    visualConfig: {
                      ...editing.visualConfig,
                      styleSuffix: e.target.value,
                    },
                  })
                }
                rows={3}
                className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary focus:outline-none focus:border-accent transition-colors resize-y text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">
                Thumbnail Style
              </label>
              <textarea
                value={editing.visualConfig.thumbnailStyle}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    visualConfig: {
                      ...editing.visualConfig,
                      thumbnailStyle: e.target.value,
                    },
                  })
                }
                rows={2}
                className="w-full px-4 py-2.5 bg-background border border-border rounded-lg text-text-primary focus:outline-none focus:border-accent transition-colors resize-y text-sm"
              />
            </div>
          </div>

          {/* Visual Anchors */}
          <div className="p-5 bg-surface border border-border rounded-xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-lg">Visual Anchors</h3>
              <button
                onClick={() =>
                  setEditing({
                    ...editing,
                    visualAnchors: [
                      ...editing.visualAnchors,
                      { name: "", description: "" },
                    ],
                  })
                }
                className="text-sm text-accent hover:text-accent-hover transition-colors"
              >
                + Add Anchor
              </button>
            </div>

            {editing.visualAnchors.map((anchor, idx) => (
              <div key={idx} className="flex gap-3">
                <input
                  type="text"
                  value={anchor.name}
                  onChange={(e) => {
                    const anchors = [...editing.visualAnchors];
                    anchors[idx] = { ...anchors[idx], name: e.target.value };
                    setEditing({ ...editing, visualAnchors: anchors });
                  }}
                  placeholder="Anchor name"
                  className="w-1/3 px-3 py-2 bg-background border border-border rounded-lg text-text-primary text-sm focus:outline-none focus:border-accent transition-colors"
                />
                <input
                  type="text"
                  value={anchor.description}
                  onChange={(e) => {
                    const anchors = [...editing.visualAnchors];
                    anchors[idx] = {
                      ...anchors[idx],
                      description: e.target.value,
                    };
                    setEditing({ ...editing, visualAnchors: anchors });
                  }}
                  placeholder="Description"
                  className="flex-1 px-3 py-2 bg-background border border-border rounded-lg text-text-primary text-sm focus:outline-none focus:border-accent transition-colors"
                />
                <button
                  onClick={() => {
                    const anchors = editing.visualAnchors.filter(
                      (_, i) => i !== idx
                    );
                    setEditing({ ...editing, visualAnchors: anchors });
                  }}
                  className="px-3 py-2 text-error hover:bg-error/10 rounded-lg transition-colors text-sm"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-8 flex gap-4">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-8 py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 text-background font-semibold rounded-lg transition-colors"
          >
            {saving ? "Saving..." : "Save Profile"}
          </button>
          <button
            onClick={() => setEditing(null)}
            className="px-8 py-3 border border-border hover:border-border-hover text-text-primary rounded-lg transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Channel Profiles</h1>
          <p className="text-text-secondary mt-1">
            Configure narrative and visual defaults for your content
          </p>
        </div>
        <button
          onClick={handleCreate}
          className="px-6 py-2.5 bg-accent hover:bg-accent-hover text-background font-semibold rounded-lg transition-colors"
        >
          New Profile
        </button>
      </div>

      {message && (
        <div
          className={`p-3 rounded-lg mb-6 text-sm ${
            message.type === "success"
              ? "bg-success/10 border border-success/30 text-success"
              : "bg-error/10 border border-error/30 text-error"
          }`}
        >
          {message.text}
        </div>
      )}

      <div className="space-y-3">
        {profiles.map((profile) => (
          <div
            key={profile.id}
            className="flex items-center justify-between p-5 bg-surface border border-border rounded-xl"
          >
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold">{profile.name}</h3>
                {profile.isDefault && (
                  <span className="text-xs px-2 py-0.5 bg-accent/10 text-accent rounded">
                    Default
                  </span>
                )}
              </div>
              <p className="text-sm text-text-tertiary mt-1">
                Updated {new Date(profile.updatedAt).toLocaleDateString()}
              </p>
            </div>
            <button
              onClick={() => handleEdit(profile.id)}
              className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-surface-hover transition-colors"
            >
              Edit
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
