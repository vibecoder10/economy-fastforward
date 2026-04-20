"use client";

import { useState, useRef, useCallback } from "react";
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
  CheckCircle2,
  Trash2,
  Pencil,
  Zap,
  Image as ImageIcon,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import {
  getVisualStyles,
  createVisualStyle,
  activateVisualStyle,
  deleteVisualStyle,
  createStyleCharacter,
  deleteStyleCharacter,
  generateCharacterImage,
  analyzeStyleImage,
  getProfile,
  updateProfile,
  type VisualStyle,
  type StyleCharacter,
} from "@/lib/api";
import { humanizeError } from "@/lib/errors";
import { useToast } from "@/components/ui/toast";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

export default function ProfilePage() {
  const queryClient = useQueryClient();
  const toast = useToast();

  // --- User Profile ---
  const { data: profile, isLoading: profileLoading, error: profileError } = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
  });
  const [editingProfile, setEditingProfile] = useState(false);
  const [profileName, setProfileName] = useState("");
  const [profileEmail, setProfileEmail] = useState("");
  const profileMutation = useMutation({
    mutationFn: updateProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profile"] });
      setEditingProfile(false);
    },
  });

  // Fetch all visual styles (includes characters per style)
  const { data: styles, isLoading } = useQuery({
    queryKey: ["visualStyles"],
    queryFn: getVisualStyles,
  });

  const activeStyle = styles?.find((s) => s.is_active) ?? null;

  // --- AI Generator state ---
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [isEditingJson, setIsEditingJson] = useState(false);
  const [editableJson, setEditableJson] = useState("");
  const [newStyleName, setNewStyleName] = useState("");
  const [saveStyleStatus, setSaveStyleStatus] = useState<"idle" | "saving" | "saved">("idle");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // --- Style management ---
  const [deleteStyleConfirm, setDeleteStyleConfirm] = useState<string | null>(null);
  const [expandedPromptId, setExpandedPromptId] = useState<string | null>(null);

  // --- Character state ---
  const [newCharName, setNewCharName] = useState("");
  const [newCharImage, setNewCharImage] = useState<string | null>(null);
  const [charSaveStatus, setCharSaveStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [deleteCharConfirm, setDeleteCharConfirm] = useState<string | null>(null);
  const charFileRef = useRef<HTMLInputElement>(null);
  // Generate tab
  const [charTab, setCharTab] = useState<"upload" | "generate">("upload");
  const [generatePrompt, setGeneratePrompt] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedImageUrl, setGeneratedImageUrl] = useState<string | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [genCharName, setGenCharName] = useState("");

  // --- Mutations ---
  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["visualStyles"] });
  }, [queryClient]);

  const activateMutation = useMutation({
    mutationFn: activateVisualStyle,
    onSuccess: (data) => {
      queryClient.setQueryData(["visualStyles"], data);
    },
  });

  const deleteStyleMutation = useMutation({
    mutationFn: deleteVisualStyle,
    onMutate: async (styleId) => {
      await queryClient.cancelQueries({ queryKey: ["visualStyles"] });
      const previous = queryClient.getQueryData<VisualStyle[]>(["visualStyles"]);
      queryClient.setQueryData<VisualStyle[]>(["visualStyles"], (old) =>
        old?.filter((s) => s.id !== styleId) ?? []
      );
      return { previous };
    },
    onError: (_err, _styleId, context) => {
      if (context?.previous) queryClient.setQueryData(["visualStyles"], context.previous);
      toast.error("Failed to delete style. It has been restored.");
    },
    onSettled: () => invalidate(),
  });

  const createCharMutation = useMutation({
    mutationFn: ({ styleId, name, image_url }: { styleId: string; name: string; image_url: string }) =>
      createStyleCharacter(styleId, { name, image_url }),
    onSuccess: invalidate,
  });

  const deleteCharMutation = useMutation({
    mutationFn: ({ styleId, charId }: { styleId: string; charId: string }) =>
      deleteStyleCharacter(styleId, charId),
    onMutate: async ({ styleId, charId }) => {
      await queryClient.cancelQueries({ queryKey: ["visualStyles"] });
      const previous = queryClient.getQueryData<VisualStyle[]>(["visualStyles"]);
      queryClient.setQueryData<VisualStyle[]>(["visualStyles"], (old) =>
        old?.map((s) =>
          s.id === styleId ? { ...s, characters: s.characters.filter((c) => c.id !== charId) } : s
        ) ?? []
      );
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(["visualStyles"], context.previous);
      toast.error("Failed to delete character. It has been restored.");
    },
    onSettled: () => invalidate(),
  });

  // --- AI Upload handler ---
  const runAnalysis = useCallback((imageData: string) => {
    setIsAnalyzing(true);
    setAnalysisResult(null);
    setAnalysisError(null);
    setIsEditingJson(false);

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("Analysis timed out after 30 seconds")), 30000)
    );

    Promise.race([analyzeStyleImage(imageData), timeout])
      .then((data) => {
        console.log("[StyleAnalysis] Raw response:", data);
        if (!data || !data.profile) {
          throw new Error("Analysis returned empty result. Try again with a different image.");
        }
        let result: string;
        try {
          result = JSON.stringify(data.profile, null, 2);
        } catch {
          throw new Error("Analysis returned unparseable data. Try again with a different image.");
        }
        setAnalysisResult(result);
        setEditableJson(result);
        setAnalysisError(null);
      })
      .catch((err) => {
        console.error("[StyleAnalysis] Error:", err);
        setAnalysisResult(null);
        const raw = err instanceof Error ? err.message : "";
        if (raw.includes("timed out")) {
          setAnalysisError("Analysis timed out. Try again with a different image.");
        } else {
          setAnalysisError(humanizeError(err, "We couldn't analyze that image. Try another one."));
        }
      })
      .finally(() => {
        setIsAnalyzing(false);
      });
  }, []);

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const imageData = ev.target?.result as string;
      setUploadedImage(imageData);
      runAnalysis(imageData);
    };
    reader.readAsDataURL(file);
  };

  // --- Save as new style ---
  const handleSaveAsNewStyle = async () => {
    const jsonStr = isEditingJson ? editableJson : analysisResult;
    if (!jsonStr || !newStyleName.trim()) return;
    try {
      const parsed = JSON.parse(jsonStr);
      setSaveStyleStatus("saving");
      await createVisualStyle({
        name: newStyleName.trim(),
        style_profile: parsed,
        reference_image_url: uploadedImage || undefined,
      });
      invalidate();
      setSaveStyleStatus("saved");
      setNewStyleName("");
      setAnalysisResult(null);
      setUploadedImage(null);
      setIsEditingJson(false);
      setTimeout(() => setSaveStyleStatus("idle"), 2000);
    } catch {
      setSaveStyleStatus("idle");
    }
  };

  // --- Style activation ---
  const handleActivate = (styleId: string) => {
    activateMutation.mutate(styleId);
  };

  // --- Style deletion ---
  const handleDeleteStyle = (styleId: string) => {
    if (deleteStyleConfirm !== styleId) {
      setDeleteStyleConfirm(styleId);
      setTimeout(() => setDeleteStyleConfirm(null), 3000);
      return;
    }
    deleteStyleMutation.mutate(styleId);
    setDeleteStyleConfirm(null);
  };

  // --- Character upload ---
  const handleCharImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setNewCharImage(ev.target?.result as string);
    };
    reader.readAsDataURL(file);
  };

  const handleAddCharacter = async () => {
    if (!activeStyle || !newCharName.trim() || !newCharImage) return;
    setCharSaveStatus("saving");
    try {
      await createStyleCharacter(activeStyle.id, {
        name: newCharName.trim(),
        image_url: newCharImage,
      });
      await queryClient.invalidateQueries({ queryKey: ["visualStyles"] });
      setNewCharName("");
      setNewCharImage(null);
      setCharSaveStatus("saved");
      setTimeout(() => setCharSaveStatus("idle"), 2000);
    } catch (err) {
      setCharSaveStatus("idle");
      toast.error(`Character save failed: ${humanizeError(err, "We couldn't save your character. Try again.")}`);
    }
  };

  // --- Character generation ---
  const handleGenerateCharacter = async () => {
    if (!activeStyle || !generatePrompt.trim()) return;
    setIsGenerating(true);
    setGenerateError(null);
    setGeneratedImageUrl(null);
    try {
      const result = await generateCharacterImage(generatePrompt.trim(), activeStyle.id);
      setGeneratedImageUrl(result.image_url);
    } catch (err) {
      const raw = err instanceof Error ? err.message : "";
      if (raw.includes("Kie.ai API key not configured") || raw.includes("400")) {
        setGenerateError("Configure your Kie.ai API key in Settings → API Keys to generate characters.");
      } else {
        setGenerateError(humanizeError(err, "We couldn't generate that character. Try again."));
      }
    } finally {
      setIsGenerating(false);
    }
  };

  const handleUseGeneratedImage = async () => {
    if (!generatedImageUrl || !activeStyle || !genCharName.trim()) return;
    setCharSaveStatus("saving");
    try {
      await createStyleCharacter(activeStyle.id, {
        name: genCharName.trim(),
        image_url: generatedImageUrl,
      });
      await queryClient.invalidateQueries({ queryKey: ["visualStyles"] });
      setGeneratedImageUrl(null);
      setGeneratePrompt("");
      setGenCharName("");
      setCharSaveStatus("saved");
      setTimeout(() => setCharSaveStatus("idle"), 2000);
    } catch (err) {
      setCharSaveStatus("idle");
      toast.error(`Character save failed: ${humanizeError(err, "We couldn't save your character. Try again.")}`);
    }
  };

  // --- Character deletion ---
  const handleDeleteChar = (charId: string) => {
    if (!activeStyle) return;
    if (deleteCharConfirm !== charId) {
      setDeleteCharConfirm(charId);
      setTimeout(() => setDeleteCharConfirm(null), 3000);
      return;
    }
    deleteCharMutation.mutate({ styleId: activeStyle.id, charId });
    setDeleteCharConfirm(null);
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
      {/* Page Header */}
      <motion.div variants={item}>
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Profile
        </h1>
        <p className="text-sm mt-2" style={{ color: "var(--text-secondary)" }}>
          Your account and visual style settings.
        </p>
      </motion.div>

      {/* Account Section */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <User size={18} style={{ color: "var(--turquoise)" }} />
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Account
          </h2>
        </div>

        <GlassCard className="p-6">
          {profileLoading ? (
            <div className="flex items-center gap-2">
              <Loader2 size={16} className="animate-spin" style={{ color: "var(--turquoise)" }} />
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>Loading profile...</span>
            </div>
          ) : profileError ? (
            <div className="text-sm" style={{ color: "var(--red)" }}>
              Unable to load profile. The server may need to be restarted.
            </div>
          ) : profile ? (
            editingProfile ? (
              <div className="space-y-4 max-w-md">
                <div>
                  <label className="text-[11px] uppercase tracking-wider block mb-1" style={{ color: "var(--text-secondary)" }}>
                    Display Name
                  </label>
                  <input
                    type="text"
                    value={profileName}
                    onChange={(e) => setProfileName(e.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-sm"
                    style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
                  />
                </div>
                <div>
                  <label className="text-[11px] uppercase tracking-wider block mb-1" style={{ color: "var(--text-secondary)" }}>
                    Email
                  </label>
                  <input
                    type="email"
                    value={profileEmail}
                    onChange={(e) => setProfileEmail(e.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-sm"
                    style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
                  />
                </div>
                <div className="flex gap-2">
                  <ActionButton
                    variant="filled"
                    icon={profileMutation.isPending ? Loader2 : Check}
                    disabled={profileMutation.isPending}
                    onClick={() => profileMutation.mutate({ display_name: profileName, email: profileEmail })}
                  >
                    Save
                  </ActionButton>
                  <ActionButton variant="outline" icon={X} onClick={() => setEditingProfile(false)}>
                    Cancel
                  </ActionButton>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-x-8 gap-y-3 max-w-md">
                  <div>
                    <span className="text-[11px] uppercase tracking-wider block" style={{ color: "var(--text-secondary)" }}>Name</span>
                    <span className="text-sm" style={{ color: "var(--text-primary)" }}>{profile.display_name || "—"}</span>
                  </div>
                  <div>
                    <span className="text-[11px] uppercase tracking-wider block" style={{ color: "var(--text-secondary)" }}>Email</span>
                    <span className="text-sm" style={{ color: "var(--text-primary)" }}>{profile.email || "—"}</span>
                  </div>
                  <div>
                    <span className="text-[11px] uppercase tracking-wider block" style={{ color: "var(--text-secondary)" }}>Plan</span>
                    <StatusPill label={profile.plan} color={profile.plan === "free" ? "gold" : "turquoise"} />
                  </div>
                  <div>
                    <span className="text-[11px] uppercase tracking-wider block" style={{ color: "var(--text-secondary)" }}>Member Since</span>
                    <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                      {profile.created_at ? new Date(profile.created_at).toLocaleDateString() : "—"}
                    </span>
                  </div>
                </div>
                <ActionButton
                  variant="outline"
                  icon={Pencil}
                  onClick={() => {
                    setProfileName(profile.display_name || "");
                    setProfileEmail(profile.email || "");
                    setEditingProfile(true);
                  }}
                >
                  Edit Profile
                </ActionButton>
              </div>
            )
          ) : (
            <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>Unable to load profile.</p>
          )}
        </GlassCard>
      </motion.div>

      {/* === SECTION 1: AI Visual Profile Generator === */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--purple)", paddingLeft: 16 }}>
          <Wand2 size={18} style={{ color: "var(--purple)" }} />
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            AI Visual Profile Generator
          </h2>
        </div>

        <GlassCard className="p-6">
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            Upload a reference image and AI will extract colors, lighting, composition, texture, and mood into a reusable style profile.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Upload area — object-fit: contain */}
            <div>
              <input type="file" ref={fileInputRef} onChange={handleImageUpload} accept="image/*" className="hidden" />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full aspect-video rounded-xl flex flex-col items-center justify-center gap-3 transition-all hover:brightness-110 relative overflow-hidden"
                style={{
                  background: "var(--bg-surface)",
                  border: `2px dashed ${uploadedImage ? "var(--purple)" : "var(--border)"}`,
                }}
              >
                {uploadedImage ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={uploadedImage}
                    alt="Reference"
                    className="w-full h-full rounded-xl"
                    style={{ objectFit: "contain" }}
                  />
                ) : (
                  <>
                    <Upload size={32} style={{ color: "var(--text-tertiary)" }} />
                    <span className="text-sm" style={{ color: "var(--text-secondary)" }}>Drop image or click to upload</span>
                    <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>PNG, JPG up to 10MB</span>
                  </>
                )}
                {uploadedImage && isAnalyzing && (
                  <div className="absolute inset-0 bg-black/60 rounded-xl flex items-center justify-center">
                    <div className="flex items-center gap-3">
                      <Loader2 size={20} className="animate-spin" style={{ color: "var(--purple)" }} />
                      <span className="text-sm font-medium" style={{ color: "var(--purple)" }}>Analyzing style...</span>
                    </div>
                  </div>
                )}
              </button>
              {uploadedImage && (
                <button onClick={() => setUploadedImage(null)} className="mt-2 text-xs flex items-center gap-1" style={{ color: "var(--text-tertiary)" }}>
                  <X size={12} /> Clear image
                </button>
              )}
            </div>

            {/* JSON output + save controls */}
            <div>
              {!analysisResult && !isAnalyzing && !analysisError && (
                <div className="w-full aspect-video rounded-xl flex items-center justify-center" style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                  <div className="text-center">
                    <Eye size={24} style={{ color: "var(--text-tertiary)" }} className="mx-auto mb-2" />
                    <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>JSON profile will appear here</p>
                  </div>
                </div>
              )}
              {analysisError && !isAnalyzing && (
                <div className="w-full aspect-video rounded-xl flex items-center justify-center" style={{ background: "var(--bg-surface)", border: "1px solid var(--red, #e94560)" }}>
                  <div className="text-center px-4 space-y-3">
                    <X size={24} style={{ color: "var(--red, #e94560)" }} className="mx-auto" />
                    <p className="text-xs" style={{ color: "var(--red, #e94560)" }}>{analysisError}</p>
                    {uploadedImage && (
                      <button
                        onClick={() => runAnalysis(uploadedImage)}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110"
                        style={{ background: "var(--purple)", color: "#fff" }}
                      >
                        <Loader2 size={12} /> Try Again
                      </button>
                    )}
                  </div>
                </div>
              )}
              {isAnalyzing && (
                <div className="w-full aspect-video rounded-xl flex items-center justify-center" style={{ background: "var(--bg-surface)", border: "1px solid var(--purple-dim)" }}>
                  <div className="space-y-2 w-3/4">
                    {[80, 60, 90, 45, 70].map((w, i) => (
                      <div key={i} className="h-2 rounded animate-pulse" style={{ width: `${w}%`, background: "var(--purple-dim)" }} />
                    ))}
                  </div>
                </div>
              )}
              {analysisResult && !isAnalyzing && (
                <div className="space-y-3">
                  {/* Prompt prefix highlight */}
                  {(() => {
                    try {
                      const parsed = JSON.parse(isEditingJson ? editableJson : analysisResult);
                      if (parsed.prompt_prefix) {
                        return (
                          <div className="p-3 rounded-lg" style={{ background: "var(--turquoise-dim)", border: "1px solid var(--turquoise)" }}>
                            <p className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: "var(--turquoise)" }}>
                              Prompt Prefix (injected into every image)
                            </p>
                            <p className="text-xs font-mono" style={{ color: "var(--text-primary)" }}>
                              {parsed.prompt_prefix}
                            </p>
                          </div>
                        );
                      }
                    } catch { /* ignore parse errors */ }
                    return null;
                  })()}
                  {isEditingJson ? (
                    <textarea
                      value={editableJson}
                      onChange={(e) => setEditableJson(e.target.value)}
                      className="text-[11px] font-mono p-4 rounded-xl w-full h-64 resize-none outline-none"
                      style={{ background: "var(--bg-surface)", color: "var(--turquoise)", border: "1px solid var(--turquoise)" }}
                    />
                  ) : (
                    <pre
                      className="text-[11px] font-mono p-4 rounded-xl overflow-auto max-h-64"
                      style={{ background: "var(--bg-surface)", color: "var(--turquoise)", border: "1px solid var(--turquoise-dim)" }}
                    >
                      {analysisResult}
                    </pre>
                  )}

                  <button
                    onClick={() => { if (isEditingJson) setIsEditingJson(false); else { setEditableJson(analysisResult); setIsEditingJson(true); } }}
                    className="text-xs flex items-center gap-1" style={{ color: "var(--orange)" }}
                  >
                    <Pencil size={12} /> {isEditingJson ? "Cancel Edit" : "Edit JSON"}
                  </button>

                  {/* Style name + save */}
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={newStyleName}
                      onChange={(e) => setNewStyleName(e.target.value)}
                      placeholder="Give your style a name..."
                      className="flex-1 px-3 py-2 rounded-lg text-sm font-body outline-none"
                      style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                    />
                    <button
                      onClick={handleSaveAsNewStyle}
                      disabled={!newStyleName.trim() || saveStyleStatus === "saving"}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-40 shrink-0"
                      style={{
                        background: saveStyleStatus === "saved" ? "var(--green)" : "var(--green)",
                        color: "var(--bg-void)",
                      }}
                    >
                      {saveStyleStatus === "saving" ? (
                        <><Loader2 size={14} className="animate-spin" /> Saving...</>
                      ) : saveStyleStatus === "saved" ? (
                        <><CheckCircle2 size={14} /> Saved</>
                      ) : (
                        <><Plus size={14} /> Save as New Style</>
                      )}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </GlassCard>
      </motion.div>

      {/* === SECTION 2: Your Visual Styles === */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <Palette size={18} style={{ color: "var(--turquoise)" }} />
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Your Visual Styles
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {styles?.map((style) => {
            const isActive = style.is_active;
            const palette = style.style_profile?.color_palette;
            const primary = palette?.primary || "#1A1A2E";
            const accent = palette?.accent || "#E94560";
            // Build tags from detailed schema fields, fallback to keywords
            const sp = style.style_profile || {} as Record<string, unknown>;
            const tags: string[] = [];
            const artMedium = sp.art_medium as string | undefined;
            const renderStyle = sp.rendering_style as string | undefined;
            const eraInfluence = sp.era_influence as string | undefined;
            if (artMedium) tags.push(artMedium.split(",")[0].split("with")[0].trim());
            if (renderStyle) tags.push(renderStyle.split(",")[0].trim());
            if (eraInfluence) tags.push(eraInfluence.split(",")[0].trim());
            // Fallback to keywords if no detailed fields
            if (tags.length === 0 && Array.isArray(sp.keywords)) {
              tags.push(...(sp.keywords as string[]).slice(0, 3));
            }

            return (
              <GlassCard
                key={style.id}
                hover
                onClick={() => handleActivate(style.id)}
                className="p-0 cursor-pointer overflow-hidden relative"
                style={{
                  borderColor: isActive ? "var(--turquoise)" : undefined,
                  borderWidth: isActive ? 2 : undefined,
                }}
              >
                {/* Preview area */}
                <div className="h-28 flex items-center justify-center relative" style={{
                  background: style.reference_image_url
                    ? undefined
                    : `linear-gradient(135deg, ${primary} 0%, ${primary}DD 60%, ${accent}40 100%)`,
                }}>
                  {style.reference_image_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={style.reference_image_url}
                      alt={style.name}
                      className="w-full h-full"
                      style={{ objectFit: "cover" }}
                    />
                  ) : (
                    <span className="text-xs font-mono px-3 py-1 rounded-full" style={{
                      background: `${accent}30`, color: accent, border: `1px solid ${accent}50`,
                    }}>
                      {style.name}
                    </span>
                  )}
                  {isActive && (
                    <div className="absolute top-3 right-3">
                      <StatusPill label="Active" color="turquoise" size="sm" />
                    </div>
                  )}
                  {/* Delete button — only for non-default styles */}
                  {!style.is_default && (
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDeleteStyle(style.id); }}
                      className="absolute top-3 left-3 w-7 h-7 rounded-full flex items-center justify-center transition-all"
                      style={{
                        background: deleteStyleConfirm === style.id ? "rgba(220,50,50,0.9)" : "rgba(0,0,0,0.5)",
                        color: deleteStyleConfirm === style.id ? "#fff" : "var(--text-secondary)",
                      }}
                      title={deleteStyleConfirm === style.id ? "Click again to confirm" : "Delete style"}
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>

                {/* Info */}
                <div className="p-4">
                  <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                    {style.name}
                  </h3>
                  {style.style_profile?.mood && (
                    <p className="text-xs mb-2 truncate" style={{ color: "var(--text-secondary)" }}>
                      {style.style_profile.mood}
                    </p>
                  )}
                  <div className="flex gap-1.5 flex-wrap">
                    {tags.slice(0, 3).map((tag) => (
                      <span key={tag} className="text-[10px] font-mono px-2 py-0.5 rounded" style={{ background: "var(--bg-elevated)", color: "var(--text-tertiary)" }}>
                        {tag}
                      </span>
                    ))}
                    {style.characters.length > 0 && (
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded" style={{ background: "var(--green-dim, var(--bg-elevated))", color: "var(--green)" }}>
                        {style.characters.length} character{style.characters.length !== 1 ? "s" : ""}
                      </span>
                    )}
                  </div>
                  {/* View Prompt toggle */}
                  {typeof style.style_profile?.prompt_prefix === "string" && style.style_profile.prompt_prefix && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedPromptId(expandedPromptId === style.id ? null : style.id);
                      }}
                      className="mt-2 text-[10px] font-medium flex items-center gap-1 transition-all"
                      style={{ color: "var(--purple)" }}
                    >
                      <Eye size={10} />
                      {expandedPromptId === style.id ? "Hide Prompt" : "View Prompt"}
                    </button>
                  )}
                  {expandedPromptId === style.id && typeof style.style_profile?.prompt_prefix === "string" && style.style_profile.prompt_prefix && (
                    <div className="mt-2 p-2.5 rounded-lg" style={{ background: "var(--bg-elevated)", border: "1px solid var(--purple-dim)" }}
                      onClick={(e) => e.stopPropagation()}>
                      <p className="text-[10px] font-mono leading-relaxed mb-2" style={{ color: "var(--text-secondary)" }}>
                        {style.style_profile.prompt_prefix}
                      </p>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          navigator.clipboard.writeText(style.style_profile.prompt_prefix as string);
                        }}
                        className="text-[9px] font-medium px-2 py-0.5 rounded transition-all hover:brightness-110"
                        style={{ background: "var(--purple-dim)", color: "var(--purple)" }}
                      >
                        Copy to Clipboard
                      </button>
                    </div>
                  )}
                </div>
              </GlassCard>
            );
          })}
        </div>
      </motion.div>

      {/* === SECTION 3: Characters for Active Style === */}
      {activeStyle && (
        <motion.div variants={item}>
          <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--green)", paddingLeft: 16 }}>
            <User size={18} style={{ color: "var(--green)" }} />
            <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
              Characters — {activeStyle.name}
            </h2>
          </div>

          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            These characters will be used as visual references for all videos using this style.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* Existing characters */}
            {activeStyle.characters.map((char) => (
              <GlassCard key={char.id} className="p-0 overflow-hidden">
                <div className="aspect-square relative flex items-center justify-center" style={{ background: "var(--bg-elevated)" }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={char.image_url} alt={char.name} className="w-full h-full" style={{ objectFit: "contain" }} />
                  <button
                    onClick={() => handleDeleteChar(char.id)}
                    className="absolute top-2 right-2 w-7 h-7 rounded-full flex items-center justify-center transition-all"
                    style={{
                      background: deleteCharConfirm === char.id ? "rgba(220,50,50,0.9)" : "rgba(0,0,0,0.6)",
                      color: deleteCharConfirm === char.id ? "#fff" : "var(--text-secondary)",
                    }}
                    title={deleteCharConfirm === char.id ? "Click again to confirm" : "Remove character"}
                  >
                    <X size={12} />
                  </button>
                </div>
                <div className="p-3">
                  <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{char.name}</p>
                </div>
              </GlassCard>
            ))}

            {/* Add character card */}
            <GlassCard className="p-0 overflow-hidden">
              {/* Tab bar */}
              <div className="flex border-b" style={{ borderColor: "var(--border-subtle)" }}>
                <button
                  onClick={() => setCharTab("upload")}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-all"
                  style={{
                    color: charTab === "upload" ? "var(--turquoise)" : "var(--text-tertiary)",
                    borderBottom: charTab === "upload" ? "2px solid var(--turquoise)" : "2px solid transparent",
                  }}
                >
                  <ImageIcon size={13} /> Upload
                </button>
                <button
                  onClick={() => setCharTab("generate")}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-all"
                  style={{
                    color: charTab === "generate" ? "var(--purple)" : "var(--text-tertiary)",
                    borderBottom: charTab === "generate" ? "2px solid var(--purple)" : "2px solid transparent",
                  }}
                >
                  <Zap size={13} /> Generate
                </button>
              </div>

              {charTab === "upload" ? (
                <>
                  <input type="file" ref={charFileRef} onChange={handleCharImageUpload} accept="image/*" className="hidden" />
                  <button
                    onClick={() => charFileRef.current?.click()}
                    className="w-full aspect-square flex flex-col items-center justify-center gap-3 cursor-pointer transition-all hover:brightness-110"
                    style={{ background: "var(--bg-surface)" }}
                  >
                    {newCharImage ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={newCharImage} alt="Preview" className="w-full h-full" style={{ objectFit: "contain" }} />
                    ) : (
                      <>
                        <Plus size={32} style={{ color: "var(--text-tertiary)" }} />
                        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Upload Image</span>
                      </>
                    )}
                  </button>
                </>
              ) : (
                /* Generate tab */
                <div className="aspect-square flex flex-col" style={{ background: "var(--bg-surface)" }}>
                  {generatedImageUrl ? (
                    <div className="flex-1 relative">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={generatedImageUrl} alt="Generated" className="w-full h-full" style={{ objectFit: "contain" }} />
                      <input
                        type="text"
                        placeholder="Character name..."
                        value={genCharName}
                        onChange={(e) => setGenCharName(e.target.value)}
                        className="absolute bottom-14 left-2 right-2 px-3 py-1.5 rounded-lg text-xs font-body outline-none"
                        style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                      />
                      <div className="absolute bottom-2 left-2 right-2 flex gap-2">
                        <button
                          onClick={handleUseGeneratedImage}
                          disabled={!genCharName.trim() || charSaveStatus === "saving"}
                          className="flex-1 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-40"
                          style={{ background: "var(--green)", color: "var(--bg-void)" }}
                        >
                          {charSaveStatus === "saving" ? "Saving..." : "Use This"}
                        </button>
                        <button
                          onClick={handleGenerateCharacter}
                          className="flex-1 py-1.5 rounded-lg text-xs font-semibold"
                          style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
                        >
                          Regenerate
                        </button>
                      </div>
                    </div>
                  ) : isGenerating ? (
                    <div className="flex-1 flex items-center justify-center">
                      <div className="text-center">
                        <Loader2 size={24} className="animate-spin mx-auto mb-2" style={{ color: "var(--purple)" }} />
                        <p className="text-xs" style={{ color: "var(--purple)" }}>Generating character...</p>
                      </div>
                    </div>
                  ) : (
                    <div className="flex-1 flex flex-col p-3 gap-2">
                      <textarea
                        value={generatePrompt}
                        onChange={(e) => setGeneratePrompt(e.target.value)}
                        placeholder="Male figure in dark tactical suit, silver hair, commanding posture..."
                        rows={4}
                        className="flex-1 px-3 py-2 rounded-lg text-xs font-body outline-none resize-none"
                        style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                      />
                      {generateError && (
                        <p className="text-[10px] px-1" style={{ color: "var(--red)" }}>{generateError}</p>
                      )}
                      <button
                        onClick={handleGenerateCharacter}
                        disabled={!generatePrompt.trim()}
                        className="w-full py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 disabled:opacity-40"
                        style={{ background: "var(--purple)", color: "#fff" }}
                      >
                        Generate
                      </button>
                      <p className="text-[9px] text-center" style={{ color: "var(--text-tertiary)" }}>
                        Uses 1 Nano Banana 2 credit (~$0.045)
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* Name input + save */}
              <div className="p-3 space-y-2">
                <input
                  type="text"
                  placeholder="Character name..."
                  value={newCharName}
                  onChange={(e) => setNewCharName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none"
                  style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                />
                <button
                  onClick={handleAddCharacter}
                  disabled={!newCharName.trim() || !newCharImage || charSaveStatus === "saving"}
                  className="w-full py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 disabled:opacity-40"
                  style={{
                    background: charSaveStatus === "saved" ? "var(--green)" : "var(--green)",
                    color: "var(--bg-void)",
                  }}
                >
                  {charSaveStatus === "saving" ? (
                    "Saving..."
                  ) : charSaveStatus === "saved" ? (
                    "Saved"
                  ) : (
                    "Add Character"
                  )}
                </button>
              </div>
            </GlassCard>
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}
