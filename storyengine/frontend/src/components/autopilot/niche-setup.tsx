"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { setupNiche, addNicheChannel } from "@/lib/api";
import { Globe, Plus, ArrowRight, Check } from "lucide-react";

const YOUTUBE_CATEGORIES = [
  "Education",
  "News & Politics",
  "Science & Technology",
  "Entertainment",
  "People & Blogs",
  "Film & Animation",
  "Gaming",
  "Music",
  "Sports",
  "How-to & Style",
  "Comedy",
  "Autos & Vehicles",
];

interface NicheSetupProps {
  onComplete: () => void;
}

export function NicheSetup({ onComplete }: NicheSetupProps) {
  const [step, setStep] = useState(1);
  const [category, setCategory] = useState("");
  const [subNiche, setSubNiche] = useState("");
  const [channels, setChannels] = useState<{ name: string; url: string }[]>([]);
  const [channelUrl, setChannelUrl] = useState("");
  const [channelName, setChannelName] = useState("");
  const queryClient = useQueryClient();

  const saveMutation = useMutation({
    mutationFn: async () => {
      await setupNiche(category, subNiche);
      for (const ch of channels) {
        await addNicheChannel(ch.name, ch.url);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["niche-config"] });
      queryClient.invalidateQueries({ queryKey: ["niche-channels"] });
      onComplete();
    },
  });

  const addChannel = () => {
    if (channelUrl.trim() && channelName.trim()) {
      setChannels([...channels, { name: channelName.trim(), url: channelUrl.trim() }]);
      setChannelUrl("");
      setChannelName("");
    }
  };

  return (
    <div className="max-w-lg mx-auto py-12">
      <div className="text-center mb-8">
        <Globe size={48} className="mx-auto mb-4" style={{ color: "var(--amber)" }} />
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          Set Up Your Niche
        </h1>
        <p className="mt-2" style={{ color: "var(--text-secondary)" }}>
          Tell us what you create so we can find the best topics for you.
        </p>
      </div>

      {/* Step indicators */}
      <div className="flex items-center justify-center gap-2 mb-8">
        {[1, 2, 3].map((s) => (
          <div
            key={s}
            className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold"
            style={{
              background: step >= s ? "var(--amber)" : "var(--bg-card)",
              color: step >= s ? "var(--bg-primary)" : "var(--text-muted)",
              border: `1px solid ${step >= s ? "var(--amber)" : "var(--border)"}`,
            }}
          >
            {step > s ? <Check size={14} /> : s}
          </div>
        ))}
      </div>

      {/* Step 1: Category */}
      {step === 1 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            YouTube Category
          </h2>
          <div className="grid grid-cols-2 gap-2">
            {YOUTUBE_CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                className="px-4 py-3 rounded-lg text-sm font-medium text-left transition-colors"
                style={{
                  background: category === cat ? "rgba(212, 168, 68, 0.15)" : "var(--bg-card)",
                  color: category === cat ? "var(--amber)" : "var(--text-secondary)",
                  border: `1px solid ${category === cat ? "var(--amber)" : "var(--border)"}`,
                }}
              >
                {cat}
              </button>
            ))}
          </div>
          <button
            onClick={() => category && setStep(2)}
            disabled={!category}
            className="w-full py-3 rounded-lg text-sm font-semibold disabled:opacity-40 flex items-center justify-center gap-2"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            Next <ArrowRight size={16} />
          </button>
        </div>
      )}

      {/* Step 2: Sub-niche */}
      {step === 2 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Your Specific Focus
          </h2>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Within {category}, what's your niche?
          </p>
          <input
            type="text"
            value={subNiche}
            onChange={(e) => setSubNiche(e.target.value)}
            placeholder="e.g., Geopolitics, Personal Finance, AI Explained"
            className="w-full rounded-lg px-4 py-3 text-sm outline-none"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
          <button
            onClick={() => subNiche.trim() && setStep(3)}
            disabled={!subNiche.trim()}
            className="w-full py-3 rounded-lg text-sm font-semibold disabled:opacity-40 flex items-center justify-center gap-2"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            Next <ArrowRight size={16} />
          </button>
        </div>
      )}

      {/* Step 3: Competitor channels */}
      {step === 3 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Add Competitor Channels
          </h2>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Paste YouTube channel URLs you want to track.
          </p>

          {/* Added channels */}
          {channels.map((ch, i) => (
            <div
              key={i}
              className="flex items-center gap-3 px-3 py-2 rounded-lg"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            >
              <Check size={14} style={{ color: "var(--green)" }} />
              <span className="text-sm flex-1" style={{ color: "var(--text-primary)" }}>
                {ch.name}
              </span>
            </div>
          ))}

          {/* Add channel form */}
          <div className="space-y-2">
            <input
              type="text"
              value={channelName}
              onChange={(e) => setChannelName(e.target.value)}
              placeholder="Channel name (e.g., CaspianReport)"
              className="w-full rounded-lg px-4 py-2.5 text-sm outline-none"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
            />
            <div className="flex gap-2">
              <input
                type="text"
                value={channelUrl}
                onChange={(e) => setChannelUrl(e.target.value)}
                placeholder="https://youtube.com/@channel"
                className="flex-1 rounded-lg px-4 py-2.5 text-sm outline-none"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
                onKeyDown={(e) => e.key === "Enter" && addChannel()}
              />
              <button
                onClick={addChannel}
                disabled={!channelUrl.trim() || !channelName.trim()}
                className="px-4 py-2.5 rounded-lg disabled:opacity-40"
                style={{ background: "var(--bg-card-hover)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              >
                <Plus size={16} />
              </button>
            </div>
          </div>

          <button
            onClick={() => saveMutation.mutate()}
            disabled={channels.length === 0 || saveMutation.isPending}
            className="w-full py-3 rounded-lg text-sm font-semibold disabled:opacity-40"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            {saveMutation.isPending ? "Setting up..." : `Start Scanning ${channels.length} Channel${channels.length !== 1 ? "s" : ""} \u2192`}
          </button>
        </div>
      )}
    </div>
  );
}
