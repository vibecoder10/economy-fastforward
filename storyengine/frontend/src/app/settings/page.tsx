"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Youtube, MessageSquare, Database, HardDrive } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { MOCK_SETTINGS } from "@/lib/mock-data";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const INTEGRATION_ICONS: Record<string, React.ElementType> = {
  YouTube: Youtube,
  Slack: MessageSquare,
  Airtable: Database,
  "Google Drive": HardDrive,
};

const ACCENT_COLORS = [
  "#ffffff", "#FF4D6A", "#FF7849", "#FFD058", "#00E68A",
  "#00D4AA", "#00B4D8", "#8B5CF6", "#C084FC", "#EC4899",
  "#F472B6", "#6B7280",
];

export default function SettingsPage() {
  const [settings, setSettings] = useState(MOCK_SETTINGS);
  const [niche, setNiche] = useState(settings.niche);
  const [visualStyle, setVisualStyle] = useState(settings.visualStyle);
  const [selectedColor, setSelectedColor] = useState(3); // turquoise index

  const toggleFramework = (name: string) => {
    setSettings((prev) => ({
      ...prev,
      frameworks: prev.frameworks.map((f) =>
        f.name === name ? { ...f, enabled: !f.enabled } : f
      ),
    }));
  };

  return (
    <motion.div className="space-y-8 max-w-3xl mx-auto" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item}>
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Channel Settings
        </h1>
      </motion.div>

      {/* Channel Profile */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Channel Profile
          </h2>
        </div>
        <GlassCard className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-secondary)" }}>
                Channel name
              </label>
              <input
                type="text"
                defaultValue={settings.channelName}
                className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none"
                style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              />
            </div>
            <div>
              <label className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-secondary)" }}>
                Niche
              </label>
              <FilterSelect
                options={[
                  { value: "Geopolitics", label: "Geopolitics" },
                  { value: "Finance", label: "Finance" },
                  { value: "Economy", label: "Economy" },
                  { value: "Tech", label: "Tech" },
                ]}
                value={niche}
                onChange={setNiche}
              />
            </div>
            <div>
              <label className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-secondary)" }}>
                Target audience
              </label>
              <textarea
                defaultValue={settings.targetAudience}
                rows={3}
                className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none resize-none"
                style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              />
            </div>
          </div>
        </GlassCard>
      </motion.div>

      {/* Visual Identity */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Visual Identity
          </h2>
        </div>
        <GlassCard className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-[auto_1fr_1fr] gap-6 items-start">
            {/* Preview placeholder */}
            <div
              className="w-28 h-20 rounded-lg flex items-center justify-center"
              style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}
            >
              <svg width="40" height="30" viewBox="0 0 40 30" className="opacity-20">
                <rect x="2" y="4" width="25" height="20" fill="none" stroke="var(--text-tertiary)" strokeWidth="1" />
                <line x1="2" y1="4" x2="8" y2="0" stroke="var(--text-tertiary)" strokeWidth="1" />
                <line x1="27" y1="4" x2="33" y2="0" stroke="var(--text-tertiary)" strokeWidth="1" />
              </svg>
            </div>

            <div>
              <label className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-secondary)" }}>
                Preview
              </label>
              <FilterSelect
                options={[
                  { value: "cinematic_illustration", label: "Cinematic Illustration" },
                  { value: "holographic_hud", label: "Holographic HUD" },
                  { value: "cinematic_dossier", label: "Cinematic Dossier" },
                  { value: "clay_mannequin", label: "Clay Mannequin" },
                ]}
                value={visualStyle}
                onChange={setVisualStyle}
              />
            </div>

            <div>
              <label className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-secondary)" }}>
                Accent color
              </label>
              <div className="flex flex-wrap gap-2">
                {ACCENT_COLORS.map((color, i) => (
                  <button
                    key={i}
                    onClick={() => setSelectedColor(i)}
                    className="w-7 h-7 rounded-full transition-all"
                    style={{
                      background: color,
                      border: selectedColor === i ? "3px solid white" : "2px solid transparent",
                      boxShadow: selectedColor === i ? `0 0 8px ${color}66` : "none",
                    }}
                  />
                ))}
              </div>
            </div>
          </div>
        </GlassCard>
      </motion.div>

      {/* Frameworks */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Frameworks
          </h2>
        </div>
        <GlassCard className="p-6">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {settings.frameworks.map((fw) => (
              <button
                key={fw.name}
                onClick={() => toggleFramework(fw.name)}
                className="flex items-center gap-2 px-3 py-2 rounded-lg transition-all text-sm"
                style={{
                  background: fw.enabled ? "var(--turquoise-dim)" : "var(--bg-elevated)",
                  border: `1px solid ${fw.enabled ? "var(--turquoise)" : "var(--border-subtle)"}`,
                  color: fw.enabled ? "var(--turquoise)" : "var(--text-secondary)",
                }}
              >
                {/* Toggle pill */}
                <div
                  className="w-8 h-4 rounded-full relative transition-all shrink-0"
                  style={{
                    background: fw.enabled ? "var(--turquoise)" : "var(--bg-surface)",
                  }}
                >
                  <div
                    className="w-3 h-3 rounded-full absolute top-0.5 transition-all"
                    style={{
                      background: fw.enabled ? "var(--bg-void)" : "var(--text-tertiary)",
                      left: fw.enabled ? "calc(100% - 14px)" : "2px",
                    }}
                  />
                </div>
                <span className="text-xs font-medium truncate">{fw.name}</span>
              </button>
            ))}
          </div>
        </GlassCard>
      </motion.div>

      {/* Integrations */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Integrations
          </h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {settings.integrations.map((integration) => {
            const Icon = INTEGRATION_ICONS[integration.name] || Database;
            return (
              <GlassCard key={integration.name} className="p-5">
                <div className="flex items-center gap-3 mb-3">
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center"
                    style={{ background: "var(--bg-elevated)" }}
                  >
                    <Icon size={20} style={{ color: "var(--text-secondary)" }} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                      {integration.name}
                    </p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <div
                        className="w-1.5 h-1.5 rounded-full"
                        style={{ background: integration.connected ? "var(--green)" : "var(--red)" }}
                      />
                      <span className="text-[10px]" style={{ color: integration.connected ? "var(--green)" : "var(--red)" }}>
                        {integration.connected ? "Connected" : "Disconnected"}
                      </span>
                    </div>
                  </div>
                </div>
                <button
                  className="w-full py-2 rounded-lg text-xs font-medium transition-all"
                  style={{
                    background: "var(--bg-elevated)",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border-subtle)",
                  }}
                >
                  Configure
                </button>
              </GlassCard>
            );
          })}
        </div>
      </motion.div>

      {/* Save button */}
      <motion.div variants={item} className="flex justify-center pt-4 pb-8">
        <ActionButton variant="filled">Save Changes</ActionButton>
      </motion.div>
    </motion.div>
  );
}
