"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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
  Plus,
  Loader2,
  Save,
  CheckCircle2,
  Trash2,
  Pencil,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import {
  getCurrentProject,
  updateProject,
  type Project,
  type ProjectUpdate,
  type CharacterReference,
} from "@/lib/api";

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
    tags: ["Editorial", "Dramatic Lighting", "Photorealistic"],
    previewColor: "#1A1A2E",
    previewAccent: "#E94560",
  },
  {
    id: "holographic_hud",
    name: "Holographic HUD",
    description: "Data overlay aesthetics with glowing nodes, circuit patterns, and sci-fi interfaces",
    tags: ["Neon", "Data Overlay", "Sci-fi"],
    previewColor: "#0A192F",
    previewAccent: "#00D4FF",
  },
  {
    id: "cinematic_dossier",
    name: "Cinematic Dossier",
    description: "Intelligence briefing style with redacted text, stamps, and classified document aesthetics",
    tags: ["Documents", "Stamps", "Intelligence Briefing"],
    previewColor: "#2C1810",
    previewAccent: "#C44545",
  },
  {
    id: "clay_mannequin",
    name: "Clay Mannequin",
    description: "3D clay render with faceless mannequin figures, matte gray surfaces, golden chest glow",
    tags: ["3D", "Faceless", "Minimalist"],
    previewColor: "#2A2A2A",
    previewAccent: "#D4A852",
  },
];

const ACCENT_COLORS = [
  { name: "Cold Teal", value: "#00D4AA" },
  { name: "Muted Crimson", value: "#C44545" },
  { name: "Warm Amber", value: "#D4A852" },
  { name: "Muted Green", value: "#3A9A5A" },
];

export default function ProfilePage() {
  const queryClient = useQueryClient();

  // Fetch project data from Supabase
  const { data: project, isLoading } = useQuery({
    queryKey: ["currentProject"],
    queryFn: getCurrentProject,
  });

  // Local state — synced from server on load
  const [activeStyle, setActiveStyle] = useState("cinematic_illustration");
  const [accentColor, setAccentColor] = useState("#00D4AA");
  const [customAccentColor, setCustomAccentColor] = useState("");
  const [useCustomColor, setUseCustomColor] = useState(false);
  const [characters, setCharacters] = useState<CharacterReference[]>([]);
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<string | null>(null);
  const [isEditingJson, setIsEditingJson] = useState(false);
  const [editableJson, setEditableJson] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [applyStatus, setApplyStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);

  // New character form
  const [newCharName, setNewCharName] = useState("");
  const [newCharDescription, setNewCharDescription] = useState("");
  const [newCharImage, setNewCharImage] = useState<string | null>(null);

  // Editing existing character
  const [editingCharIdx, setEditingCharIdx] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const charFileRef = useRef<HTMLInputElement>(null);

  // Sync state from server
  useEffect(() => {
    if (project) {
      setActiveStyle(project.visual_style || "cinematic_illustration");
      setAccentColor(project.accent_color || "#00D4AA");
      if (project.custom_accent_color) {
        setCustomAccentColor(project.custom_accent_color);
        setUseCustomColor(!ACCENT_COLORS.some(c => c.value === project.accent_color));
      }
      setCharacters(project.character_references || []);
      if (project.visual_profile_json) {
        setAnalysisResult(JSON.stringify(project.visual_profile_json, null, 2));
      }
    }
  }, [project]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (data: ProjectUpdate) => updateProject(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["currentProject"] });
    },
  });

  // Quick-save a single field
  const saveField = useCallback(
    (data: ProjectUpdate) => {
      saveMutation.mutate(data);
    },
    [saveMutation]
  );

  // ---- AI Visual Profile Generator ----

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      setUploadedImage(ev.target?.result as string);
      setIsAnalyzing(true);
      setAnalysisResult(null);
      setIsEditingJson(false);

      // Simulate AI analysis (in production, this would call Claude Vision API)
      setTimeout(() => {
        setIsAnalyzing(false);
        const result = JSON.stringify({
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
        }, null, 2);
        setAnalysisResult(result);
        setEditableJson(result);
      }, 3000);
    };
    reader.readAsDataURL(file);
  };

  const handleApplyProfile = async () => {
    const jsonStr = isEditingJson ? editableJson : analysisResult;
    if (!jsonStr) return;

    try {
      const parsed = JSON.parse(jsonStr);
      setApplyStatus("saving");
      await updateProject({ visual_profile_json: parsed });
      queryClient.invalidateQueries({ queryKey: ["currentProject"] });
      setAnalysisResult(JSON.stringify(parsed, null, 2));
      setIsEditingJson(false);
      setApplyStatus("saved");
      setTimeout(() => setApplyStatus("idle"), 2000);
    } catch {
      // Invalid JSON
    }
  };

  // ---- Style Selection ----

  const handleStyleSelect = (styleId: string) => {
    setActiveStyle(styleId);
    saveField({ visual_style: styleId });
  };

  // ---- Accent Color ----

  const handlePresetColor = (color: string) => {
    setAccentColor(color);
    setUseCustomColor(false);
    saveField({ accent_color: color, custom_accent_color: undefined });
  };

  const handleCustomColor = (color: string) => {
    setCustomAccentColor(color);
    setUseCustomColor(true);
    setAccentColor(color);
    saveField({ accent_color: color, custom_accent_color: color });
  };

  // ---- Characters ----

  const handleAddCharacter = () => {
    if (!newCharName.trim()) return;
    const newChar: CharacterReference = {
      name: newCharName.trim(),
      description: newCharDescription.trim(),
      image_url: newCharImage || undefined,
    };
    const updated = [...characters, newChar];
    setCharacters(updated);
    setNewCharName("");
    setNewCharDescription("");
    setNewCharImage(null);
  };

  const handleRemoveCharacter = (idx: number) => {
    if (deleteConfirm !== idx) {
      setDeleteConfirm(idx);
      setTimeout(() => setDeleteConfirm(null), 3000);
      return;
    }
    const updated = characters.filter((_, i) => i !== idx);
    setCharacters(updated);
    setDeleteConfirm(null);
  };

  const handleCharImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setNewCharImage(ev.target?.result as string);
    };
    reader.readAsDataURL(file);
  };

  const handleUpdateCharacter = (idx: number, field: keyof CharacterReference, value: string) => {
    const updated = characters.map((c, i) =>
      i === idx ? { ...c, [field]: value } : c
    );
    setCharacters(updated);
  };

  // ---- Save All ----

  const handleSaveAll = async () => {
    setSaveStatus("saving");
    try {
      await updateProject({
        visual_style: activeStyle,
        accent_color: accentColor,
        custom_accent_color: useCustomColor ? customAccentColor : undefined,
        character_references: characters,
      });
      queryClient.invalidateQueries({ queryKey: ["currentProject"] });
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch {
      setSaveStatus("idle");
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={32} className="animate-spin" style={{ color: "var(--turquoise)" }} />
      </div>
    );
  }

  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item}>
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Visual Profile
        </h1>
        <p className="text-sm mt-2" style={{ color: "var(--text-secondary)" }}>
          Configure your channel&apos;s visual identity, style system, and character consistency.
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
                className="w-full aspect-video rounded-xl flex flex-col items-center justify-center gap-3 transition-all hover:brightness-110 relative overflow-hidden"
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
                      <Sparkles size={20} className="animate-pulse" style={{ color: "var(--purple)" }} />
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
                    // Don't clear analysisResult — saved profile stays
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
                      {project?.visual_profile_json
                        ? "Saved profile loaded"
                        : "JSON profile will appear here"}
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
              {analysisResult && !isAnalyzing && (
                <div className="relative">
                  {isEditingJson ? (
                    <textarea
                      value={editableJson}
                      onChange={(e) => setEditableJson(e.target.value)}
                      className="text-[11px] font-mono p-4 rounded-xl w-full h-64 resize-none outline-none"
                      style={{
                        background: "var(--bg-surface)",
                        color: "var(--turquoise)",
                        border: "1px solid var(--turquoise)",
                      }}
                    />
                  ) : (
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
                  )}
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={handleApplyProfile}
                      disabled={applyStatus === "saving"}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:brightness-110"
                      style={{
                        background: applyStatus === "saved" ? "var(--green)" : "var(--turquoise)",
                        color: "var(--bg-void)",
                      }}
                    >
                      {applyStatus === "saving" ? (
                        <><Loader2 size={14} className="animate-spin" /> Saving...</>
                      ) : applyStatus === "saved" ? (
                        <><CheckCircle2 size={14} /> Saved</>
                      ) : (
                        <><Check size={14} /> Apply Profile</>
                      )}
                    </button>
                    <button
                      onClick={() => {
                        if (isEditingJson) {
                          setIsEditingJson(false);
                        } else {
                          setEditableJson(analysisResult);
                          setIsEditingJson(true);
                        }
                      }}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:brightness-110"
                      style={{
                        background: "transparent",
                        color: "var(--orange)",
                        border: "1px solid var(--orange)",
                      }}
                    >
                      <Pencil size={14} />
                      {isEditingJson ? "Cancel Edit" : "Edit JSON"}
                    </button>
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
          {VISUAL_STYLES.map((style) => {
            const isActive = activeStyle === style.id;
            return (
              <GlassCard
                key={style.id}
                hover
                onClick={() => handleStyleSelect(style.id)}
                className="p-0 cursor-pointer overflow-hidden"
                style={{
                  borderColor: isActive ? "var(--turquoise)" : undefined,
                  borderWidth: isActive ? 2 : undefined,
                }}
              >
                {/* Style preview — colored placeholder with visual description */}
                {/* TODO: Replace with real preview images for each style */}
                <div
                  className="h-28 flex items-center justify-center relative"
                  style={{
                    background: `linear-gradient(135deg, ${style.previewColor} 0%, ${style.previewColor}DD 60%, ${style.previewAccent}40 100%)`,
                  }}
                >
                  <span
                    className="text-xs font-mono px-3 py-1 rounded-full"
                    style={{
                      background: `${style.previewAccent}30`,
                      color: style.previewAccent,
                      border: `1px solid ${style.previewAccent}50`,
                    }}
                  >
                    {style.name}
                  </span>
                  {isActive && (
                    <div className="absolute top-3 right-3">
                      <StatusPill label="Active" color="turquoise" size="sm" />
                    </div>
                  )}
                </div>
                <div className="p-4">
                  <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                    {style.name}
                  </h3>
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
                </div>
              </GlassCard>
            );
          })}
        </div>

        {/* Accent color */}
        <GlassCard className="p-5 mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
            Channel Accent Color
          </h3>
          <div className="flex gap-4 flex-wrap items-end">
            {ACCENT_COLORS.map((c) => {
              const isSelected = !useCustomColor && accentColor === c.value;
              return (
                <button
                  key={c.value}
                  onClick={() => handlePresetColor(c.value)}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg transition-all"
                  style={{
                    background: isSelected ? `${c.value}15` : "var(--bg-elevated)",
                    border: `2px solid ${isSelected ? c.value : "var(--border-subtle)"}`,
                  }}
                >
                  <div className="w-4 h-4 rounded-full" style={{ background: c.value }} />
                  <span className="text-xs font-medium" style={{ color: isSelected ? c.value : "var(--text-secondary)" }}>
                    {c.name}
                  </span>
                </button>
              );
            })}

            {/* Custom color picker */}
            <div className="flex items-center gap-2">
              <div className="relative">
                <input
                  type="color"
                  value={customAccentColor || "#00D4AA"}
                  onChange={(e) => handleCustomColor(e.target.value)}
                  className="w-8 h-8 rounded-lg cursor-pointer border-0 p-0"
                  style={{ background: "transparent" }}
                />
              </div>
              <div className="flex flex-col gap-1">
                <input
                  type="text"
                  value={useCustomColor ? customAccentColor : ""}
                  onChange={(e) => {
                    const val = e.target.value;
                    setCustomAccentColor(val);
                    if (/^#[0-9A-Fa-f]{6}$/.test(val)) {
                      handleCustomColor(val);
                    }
                  }}
                  placeholder="#Custom"
                  className="w-24 px-2 py-1 rounded text-xs font-mono outline-none"
                  style={{
                    background: "var(--bg-elevated)",
                    color: "var(--text-primary)",
                    border: `1px solid ${useCustomColor ? customAccentColor : "var(--border-subtle)"}`,
                  }}
                />
              </div>
            </div>
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
          Define recurring characters to maintain visual identity across all scenes. The pipeline uses these as BYOC (Bring Your Own Character) references.
        </p>

        {/* Character cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {characters.map((char, idx) => (
            <GlassCard key={idx} className="p-0 overflow-hidden">
              {/* Image area */}
              <div
                className="aspect-[4/3] relative flex items-center justify-center"
                style={{
                  background: char.image_url ? undefined : "var(--bg-elevated)",
                  backgroundImage: char.image_url ? `url(${char.image_url})` : undefined,
                  backgroundSize: "cover",
                  backgroundPosition: "center",
                }}
              >
                {!char.image_url && (
                  <User size={40} style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
                )}
                <button
                  onClick={() => handleRemoveCharacter(idx)}
                  className="absolute top-2 right-2 w-7 h-7 rounded-full flex items-center justify-center transition-all"
                  style={{
                    background: deleteConfirm === idx ? "rgba(220,50,50,0.9)" : "rgba(0,0,0,0.6)",
                    color: deleteConfirm === idx ? "#fff" : "var(--text-secondary)",
                  }}
                  title={deleteConfirm === idx ? "Click again to confirm" : "Remove character"}
                >
                  <Trash2 size={12} />
                </button>
              </div>
              <div className="p-4 space-y-2">
                <input
                  type="text"
                  value={char.name}
                  onChange={(e) => handleUpdateCharacter(idx, "name", e.target.value)}
                  className="w-full text-sm font-semibold outline-none bg-transparent"
                  style={{ color: "var(--text-primary)" }}
                  placeholder="Character name..."
                />
                <textarea
                  value={char.description}
                  onChange={(e) => handleUpdateCharacter(idx, "description", e.target.value)}
                  rows={2}
                  className="w-full text-[11px] outline-none bg-transparent resize-none"
                  style={{ color: "var(--text-secondary)" }}
                  placeholder="Describe appearance, clothing, distinguishing features..."
                />
              </div>
            </GlassCard>
          ))}

          {/* Add character card */}
          <GlassCard className="p-0 overflow-hidden">
            <input
              type="file"
              ref={charFileRef}
              onChange={handleCharImageUpload}
              accept="image/*"
              className="hidden"
            />
            <button
              onClick={() => charFileRef.current?.click()}
              className="w-full aspect-[4/3] flex flex-col items-center justify-center gap-3 cursor-pointer transition-all hover:brightness-110"
              style={{
                background: newCharImage ? undefined : "var(--bg-surface)",
                backgroundImage: newCharImage ? `url(${newCharImage})` : undefined,
                backgroundSize: "cover",
                backgroundPosition: "center",
              }}
            >
              {!newCharImage && (
                <>
                  <Plus size={32} style={{ color: "var(--text-tertiary)" }} />
                  <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                    Upload Image (optional)
                  </span>
                </>
              )}
            </button>
            <div className="p-4 space-y-2">
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
              <textarea
                placeholder="Description — appearance, clothing, features..."
                value={newCharDescription}
                onChange={(e) => setNewCharDescription(e.target.value)}
                rows={2}
                className="w-full px-3 py-2 rounded-lg text-xs font-body outline-none resize-none"
                style={{
                  background: "var(--bg-elevated)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              />
              <button
                onClick={handleAddCharacter}
                disabled={!newCharName.trim()}
                className="w-full py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 disabled:opacity-40"
                style={{
                  background: "var(--green)",
                  color: "var(--bg-void)",
                }}
              >
                Add Character
              </button>
            </div>
          </GlassCard>
        </div>
      </motion.div>

      {/* === Save All === */}
      <motion.div variants={item} className="flex justify-center pt-4 pb-8">
        <button
          onClick={handleSaveAll}
          disabled={saveStatus === "saving"}
          className="flex items-center gap-2 px-8 py-3 rounded-xl text-sm font-semibold transition-all hover:brightness-110"
          style={{
            background: saveStatus === "saved" ? "var(--green)" : "var(--turquoise)",
            color: "var(--bg-void)",
          }}
        >
          {saveStatus === "saving" ? (
            <><Loader2 size={16} className="animate-spin" /> Saving...</>
          ) : saveStatus === "saved" ? (
            <><CheckCircle2 size={16} /> All Changes Saved</>
          ) : (
            <><Save size={16} /> Save All Changes</>
          )}
        </button>
      </motion.div>
    </motion.div>
  );
}
