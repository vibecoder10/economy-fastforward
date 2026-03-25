"use client";

import { useState, useRef } from "react";
import { motion } from "framer-motion";
import {
  Upload,
  Wand2,
  User,
  Palette,
  Eye,
  Sparkles,
  X,
  Check,
  Image as ImageIcon,
  Plus,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { FilterSelect } from "@/components/ui/FilterSelect";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const VISUAL_STYLES = [
  {
    id: "cinematic_illustration",
    name: "Cinematic Illustration",
    description: "Photorealistic editorial illustration with Rembrandt lighting and dramatic compositions",
    tags: ["Dossier 60%", "Schema 22%", "Echo 18%"],
  },
  {
    id: "holographic_hud",
    name: "Holographic HUD",
    description: "Data overlay aesthetics with glowing nodes, circuit patterns, and sci-fi interfaces",
    tags: ["Neon", "Data Grid", "Tech"],
  },
  {
    id: "cinematic_dossier",
    name: "Cinematic Dossier",
    description: "Intelligence briefing style with redacted text, stamps, and classified document aesthetics",
    tags: ["Documents", "Stamps", "Intel"],
  },
  {
    id: "clay_mannequin",
    name: "Clay Mannequin",
    description: "3D clay render with faceless mannequin figures, matte gray surfaces, golden chest glow",
    tags: ["3D", "Faceless", "Minimal"],
  },
];

const ACCENT_COLORS = [
  { name: "Cold Teal", value: "#00D4AA" },
  { name: "Muted Crimson", value: "#C44545" },
  { name: "Warm Amber", value: "#D4A852" },
  { name: "Muted Green", value: "#3A9A5A" },
];

interface CharacterRef {
  id: string;
  name: string;
  description: string;
  imagePreview?: string;
}

export default function ProfilePage() {
  const [activeStyle, setActiveStyle] = useState("cinematic_illustration");
  const [accentColor, setAccentColor] = useState("#00D4AA");
  const [characters, setCharacters] = useState<CharacterRef[]>([
    {
      id: "c1",
      name: "The Narrator",
      description: "Stern middle-aged man in dark suit, silver temples, authoritative presence",
    },
  ]);
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<string | null>(null);
  const [newCharName, setNewCharName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const charFileRef = useRef<HTMLInputElement>(null);

  // Simulate AI visual profile analysis
  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      setUploadedImage(ev.target?.result as string);
      setIsAnalyzing(true);
      setAnalysisResult(null);

      // Simulate AI analysis delay
      setTimeout(() => {
        setIsAnalyzing(false);
        setAnalysisResult(JSON.stringify({
          style_profile: {
            name: "Custom Profile",
            base_style: "cinematic_illustration",
            color_palette: {
              primary: "#1A1A2E",
              accent: "#E94560",
              secondary: "#0F3460",
              highlight: "#F0C75E",
            },
            lighting: "Rembrandt with warm fill, dramatic shadows",
            composition: "Rule of thirds, subject left, negative space right",
            texture: "Film grain 15%, vignette, subtle chromatic aberration",
            mood: "Tense, conspiratorial, high-stakes",
          },
          detected_elements: [
            "Dark background with gradient",
            "Strong directional lighting from upper left",
            "Saturated accent colors on muted base",
            "Editorial illustration style",
            "Dramatic facial expressions",
          ],
        }, null, 2));
      }, 3000);
    };
    reader.readAsDataURL(file);
  };

  const handleCharacterUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !newCharName) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      setCharacters((prev) => [
        ...prev,
        {
          id: `c${Date.now()}`,
          name: newCharName,
          description: "Uploaded character reference — AI will extract visual traits for consistency",
          imagePreview: ev.target?.result as string,
        },
      ]);
      setNewCharName("");
    };
    reader.readAsDataURL(file);
  };

  const removeCharacter = (id: string) => {
    setCharacters((prev) => prev.filter((c) => c.id !== id));
  };

  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item}>
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Visual Profile
        </h1>
        <p className="text-sm mt-2" style={{ color: "var(--text-secondary)" }}>
          Configure your channel's visual identity, style system, and character consistency.
        </p>
      </motion.div>

      {/* === SECTION 1: AI Image-to-Visual Profile === */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--purple)", paddingLeft: 16 }}>
          <Wand2 size={18} style={{ color: "var(--purple)" }} />
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            AI Visual Profile Generator
          </h2>
        </div>

        <GlassCard className="p-6">
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            Upload a reference image and AI will analyze it to generate a JSON visual profile — extracting colors, lighting, composition, texture, and mood.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Upload area */}
            <div>
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleImageUpload}
                accept="image/*"
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full aspect-video rounded-xl flex flex-col items-center justify-center gap-3 transition-all hover:brightness-110"
                style={{
                  background: uploadedImage ? "var(--bg-elevated)" : "var(--bg-surface)",
                  border: `2px dashed ${uploadedImage ? "var(--purple)" : "var(--border)"}`,
                  backgroundImage: uploadedImage ? `url(${uploadedImage})` : undefined,
                  backgroundSize: "cover",
                  backgroundPosition: "center",
                }}
              >
                {!uploadedImage && (
                  <>
                    <Upload size={32} style={{ color: "var(--text-tertiary)" }} />
                    <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                      Drop image or click to upload
                    </span>
                    <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                      PNG, JPG up to 10MB
                    </span>
                  </>
                )}
                {uploadedImage && isAnalyzing && (
                  <div className="absolute inset-0 bg-black/60 rounded-xl flex items-center justify-center">
                    <div className="flex items-center gap-3">
                      <Sparkles size={20} className="animate-spin-slow" style={{ color: "var(--purple)" }} />
                      <span className="text-sm font-medium" style={{ color: "var(--purple)" }}>
                        Analyzing visual style...
                      </span>
                    </div>
                  </div>
                )}
              </button>
              {uploadedImage && (
                <button
                  onClick={() => {
                    setUploadedImage(null);
                    setAnalysisResult(null);
                  }}
                  className="mt-2 text-xs flex items-center gap-1"
                  style={{ color: "var(--text-tertiary)" }}
                >
                  <X size={12} /> Clear image
                </button>
              )}
            </div>

            {/* Result / JSON output */}
            <div>
              {!analysisResult && !isAnalyzing && (
                <div
                  className="w-full aspect-video rounded-xl flex items-center justify-center"
                  style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
                >
                  <div className="text-center">
                    <Eye size={24} style={{ color: "var(--text-tertiary)" }} className="mx-auto mb-2" />
                    <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                      JSON profile will appear here
                    </p>
                  </div>
                </div>
              )}
              {isAnalyzing && (
                <div
                  className="w-full aspect-video rounded-xl flex items-center justify-center"
                  style={{ background: "var(--bg-surface)", border: "1px solid var(--purple-dim)" }}
                >
                  <div className="space-y-2 w-3/4">
                    {[80, 60, 90, 45, 70].map((w, i) => (
                      <div
                        key={i}
                        className="h-2 rounded animate-pulse"
                        style={{ width: `${w}%`, background: "var(--purple-dim)" }}
                      />
                    ))}
                  </div>
                </div>
              )}
              {analysisResult && (
                <div className="relative">
                  <pre
                    className="text-[11px] font-mono p-4 rounded-xl overflow-auto max-h-64"
                    style={{
                      background: "var(--bg-surface)",
                      color: "var(--turquoise)",
                      border: "1px solid var(--turquoise-dim)",
                    }}
                  >
                    {analysisResult}
                  </pre>
                  <div className="flex gap-2 mt-3">
                    <ActionButton variant="filled">
                      <Check size={14} /> Apply Profile
                    </ActionButton>
                    <ActionButton variant="outline">Edit JSON</ActionButton>
                  </div>
                </div>
              )}
            </div>
          </div>
        </GlassCard>
      </motion.div>

      {/* === SECTION 2: Visual Style Selector === */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <Palette size={18} style={{ color: "var(--turquoise)" }} />
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Visual Style System
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {VISUAL_STYLES.map((style) => (
            <GlassCard
              key={style.id}
              hover
              onClick={() => setActiveStyle(style.id)}
              className="p-5 cursor-pointer"
              style={{
                borderColor: activeStyle === style.id ? "var(--turquoise)" : undefined,
                borderWidth: activeStyle === style.id ? 2 : undefined,
              }}
            >
              <div className="flex items-start justify-between mb-2">
                <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  {style.name}
                </h3>
                {activeStyle === style.id && (
                  <StatusPill label="Active" color="turquoise" size="sm" />
                )}
              </div>
              <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                {style.description}
              </p>
              <div className="flex gap-1.5 flex-wrap">
                {style.tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-[10px] font-mono px-2 py-0.5 rounded"
                    style={{ background: "var(--bg-elevated)", color: "var(--text-tertiary)" }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </GlassCard>
          ))}
        </div>

        {/* Accent color */}
        <GlassCard className="p-5 mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
            Channel Accent Color
          </h3>
          <div className="flex gap-4 flex-wrap">
            {ACCENT_COLORS.map((c) => (
              <button
                key={c.value}
                onClick={() => setAccentColor(c.value)}
                className="flex items-center gap-2 px-3 py-2 rounded-lg transition-all"
                style={{
                  background: accentColor === c.value ? `${c.value}15` : "var(--bg-elevated)",
                  border: `2px solid ${accentColor === c.value ? c.value : "var(--border-subtle)"}`,
                }}
              >
                <div className="w-4 h-4 rounded-full" style={{ background: c.value }} />
                <span className="text-xs font-medium" style={{ color: accentColor === c.value ? c.value : "var(--text-secondary)" }}>
                  {c.name}
                </span>
              </button>
            ))}
          </div>
        </GlassCard>
      </motion.div>

      {/* === SECTION 3: Character Consistency === */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--green)", paddingLeft: 16 }}>
          <User size={18} style={{ color: "var(--green)" }} />
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Character Consistency
          </h2>
        </div>

        <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
          Upload character reference images to lock visual identity across all scenes. The pipeline will use these as BYOC (Bring Your Own Character) references for consistent faces, clothing, and poses.
        </p>

        {/* Character cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {characters.map((char) => (
            <GlassCard key={char.id} className="p-0 overflow-hidden">
              {/* Image area */}
              <div
                className="aspect-square relative flex items-center justify-center"
                style={{
                  background: char.imagePreview ? undefined : "var(--bg-elevated)",
                  backgroundImage: char.imagePreview ? `url(${char.imagePreview})` : undefined,
                  backgroundSize: "cover",
                  backgroundPosition: "center",
                }}
              >
                {!char.imagePreview && (
                  <User size={40} style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
                )}
                <button
                  onClick={() => removeCharacter(char.id)}
                  className="absolute top-2 right-2 w-6 h-6 rounded-full flex items-center justify-center"
                  style={{ background: "rgba(0,0,0,0.6)", color: "var(--text-secondary)" }}
                >
                  <X size={12} />
                </button>
              </div>
              <div className="p-4">
                <h4 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                  {char.name}
                </h4>
                <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  {char.description}
                </p>
              </div>
            </GlassCard>
          ))}

          {/* Add character card */}
          <GlassCard className="p-0 overflow-hidden">
            <div
              className="aspect-square flex flex-col items-center justify-center gap-3 cursor-pointer"
              style={{ background: "var(--bg-surface)" }}
              onClick={() => charFileRef.current?.click()}
            >
              <Plus size={32} style={{ color: "var(--text-tertiary)" }} />
              <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                Add Character
              </span>
            </div>
            <div className="p-4">
              <input
                type="text"
                placeholder="Character name..."
                value={newCharName}
                onChange={(e) => setNewCharName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none"
                style={{
                  background: "var(--bg-elevated)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              />
              <input
                type="file"
                ref={charFileRef}
                onChange={handleCharacterUpload}
                accept="image/*"
                className="hidden"
              />
            </div>
          </GlassCard>
        </div>
      </motion.div>

      {/* Save */}
      <motion.div variants={item} className="flex justify-center pt-4 pb-8">
        <ActionButton variant="filled">Save Visual Profile</ActionButton>
      </motion.div>
    </motion.div>
  );
}
