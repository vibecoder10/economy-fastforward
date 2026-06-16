"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Youtube, HardDrive, CheckCircle2, ArrowRight, Loader2, Save, CreditCard, Palette, Bell, FolderOpen, X, ExternalLink } from "lucide-react";
import { useRouter } from "next/navigation";
import { GlassCard } from "@/components/ui/GlassCard";
import { Spinner } from "@/components/ui/spinner";
import { ErrorCard } from "@/components/ui/ErrorCard";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ExampleChannels } from "@/components/channels/ExampleChannels";
import {
  getCurrentProject,
  updateProject,
  getApiKeys,
  getSubscription,
  getChannelProfile,
  updateChannelProfile,
  getNotificationPreferences,
  updateNotificationPreferences,
  getDriveStatus,
  getDriveConnectUrl,
  getDriveAccessToken,
  disconnectDrive as apiDisconnectDrive,
  type Project,
  type ProjectUpdate,
  type NotificationPreferences,
} from "@/lib/api";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

// The 10 canonical frameworks
const ALL_FRAMEWORKS = [
  "Machiavelli",
  "Thucydides Trap",
  "Taleb",
  "Game Theory",
  "Sun Tzu",
  "Brzezinski",
  "Kindleberger Trap",
  "Schelling",
  "Mancur Olson",
  "Joseph Nye",
];

const INTEGRATION_ICONS: Record<string, React.ElementType> = {
  YouTube: Youtube,
  "Google Drive": HardDrive,
};

// Map integration names to the API keys that indicate connectivity
const INTEGRATION_KEY_MAP: Record<string, string[]> = {
  YouTube: ["google_client_id", "google_refresh_token"],
  "Google Drive": ["google_client_id", "google_refresh_token"],
};

export default function SettingsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  // Saved indicator state
  const [savedField, setSavedField] = useState<string | null>(null);
  const [saveAllStatus, setSaveAllStatus] = useState<"idle" | "saving" | "saved">("idle");
  const savedTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch project (replaces channel profile)
  const { data: project, isLoading: projectLoading, error: projectError } = useQuery({
    queryKey: ["currentProject"],
    queryFn: getCurrentProject,
  });

  // Fetch API keys for integration status
  const { data: keysData } = useQuery({
    queryKey: ["apiKeys"],
    queryFn: getApiKeys,
  });

  // Fetch subscription status (used for billing link card)
  const { data: subscription } = useQuery({
    queryKey: ["subscription"],
    queryFn: getSubscription,
  });

  // Brand Kit
  const { data: channelProfile } = useQuery({
    queryKey: ["channelProfile"],
    queryFn: getChannelProfile,
  });
  const [brandAccent, setBrandAccent] = useState("");
  const [brandLogo, setBrandLogo] = useState("");
  const [brandSaving, setBrandSaving] = useState(false);
  const [brandSaved, setBrandSaved] = useState(false);

  // Google Drive connection
  const [driveSaving, setDriveSaving] = useState(false);
  const [driveSaved, setDriveSaved] = useState(false);
  const [pickerLoaded, setPickerLoaded] = useState(false);

  // Fetch Drive connection status
  const { data: driveStatus, refetch: refetchDriveStatus } = useQuery({
    queryKey: ["driveStatus"],
    queryFn: getDriveStatus,
    refetchOnWindowFocus: true,
  });

  // Load Google Picker API script
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (document.getElementById("google-picker-script")) {
      setPickerLoaded(true);
      return;
    }
    const script = document.createElement("script");
    script.id = "google-picker-script";
    script.src = "https://apis.google.com/js/api.js";
    script.onload = () => setPickerLoaded(true);
    document.head.appendChild(script);
  }, []);

  const connectGoogleDrive = useCallback(async () => {
    const { auth_url } = await getDriveConnectUrl();
    window.location.href = auth_url;
  }, []);

  const openDrivePicker = useCallback(async () => {
    // Get a fresh access token from our backend (uses stored refresh token)
    let accessToken: string;
    try {
      const resp = await getDriveAccessToken();
      accessToken = resp.access_token;
    } catch {
      alert("Failed to get Drive access. Try reconnecting Google Drive.");
      return;
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const gapi = (window as any).gapi;
    if (!gapi) return;

    gapi.load("picker", () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const google = (window as any).google;
      if (!google?.picker) return;

      const view = new google.picker.DocsView(google.picker.ViewId.FOLDERS);
      view.setSelectFolderEnabled(true);
      view.setMimeTypes("application/vnd.google-apps.folder");

      const picker = new google.picker.PickerBuilder()
        .addView(view)
        .setOAuthToken(accessToken)
        .setTitle("Select a folder for StoryEngine assets")
        .setCallback(async (data: { action: string; docs?: { id: string; name: string }[] }) => {
          if (data.action === google.picker.Action.PICKED && data.docs?.[0]) {
            const folder = data.docs[0];
            setDriveSaving(true);
            try {
              await updateChannelProfile({
                google_drive_folder_id: folder.id,
                google_drive_folder_name: folder.name,
              });
              queryClient.invalidateQueries({ queryKey: ["channelProfile"] });
              refetchDriveStatus();
              setDriveSaved(true);
              setTimeout(() => setDriveSaved(false), 2000);
            } finally {
              setDriveSaving(false);
            }
          }
        })
        .build();
      picker.setVisible(true);
    });
  }, [queryClient, refetchDriveStatus]);

  const disconnectDrive = useCallback(async () => {
    setDriveSaving(true);
    try {
      await apiDisconnectDrive();
      refetchDriveStatus();
    } finally {
      setDriveSaving(false);
    }
  }, [refetchDriveStatus]);

  // Notification preferences
  const { data: notifPrefs } = useQuery({
    queryKey: ["notificationPrefs"],
    queryFn: getNotificationPreferences,
  });

  // Local form state
  const [channelName, setChannelName] = useState("");
  const [niche, setNiche] = useState("Geopolitics");
  const [targetAudience, setTargetAudience] = useState("");
  const [enabledFrameworks, setEnabledFrameworks] = useState<string[]>([]);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  // Sync from server data
  useEffect(() => {
    if (project) {
      setChannelName(project.name);
      setNiche(project.niche || "Geopolitics");
      setTargetAudience(project.target_audience);
      setEnabledFrameworks(project.frameworks || []);
    }
  }, [project]);

  // Sync brand kit from channel profile
  useEffect(() => {
    if (channelProfile) {
      setBrandAccent(channelProfile.accent_color || "#00D4AA");
      setBrandLogo(channelProfile.logo_url || "");
    }
  }, [channelProfile]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (data: ProjectUpdate) => updateProject(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["currentProject"] });
    },
  });

  // Show "Saved" indicator for 2s
  const showSaved = useCallback((field: string) => {
    if (savedTimeoutRef.current) clearTimeout(savedTimeoutRef.current);
    setSavedField(field);
    savedTimeoutRef.current = setTimeout(() => setSavedField(null), 2000);
  }, []);

  // Auto-save handlers (on blur)
  const saveField = useCallback(
    (field: keyof ProjectUpdate, value: string | string[]) => {
      saveMutation.mutate({ [field]: value });
      showSaved(field);
      setHasUnsavedChanges(false);
    },
    [saveMutation, showSaved]
  );

  const handleChannelNameBlur = () => {
    if (channelName !== (project?.name ?? "")) {
      saveField("name", channelName);
    }
  };

  const handleNicheChange = (value: string) => {
    setNiche(value);
    saveField("niche", value);
  };

  const handleTargetAudienceBlur = () => {
    if (targetAudience !== (project?.target_audience ?? "")) {
      saveField("target_audience", targetAudience);
    }
  };

  const toggleFramework = (name: string) => {
    const next = enabledFrameworks.includes(name)
      ? enabledFrameworks.filter((f) => f !== name)
      : [...enabledFrameworks, name];
    setEnabledFrameworks(next);
    setHasUnsavedChanges(true);
  };

  // Save All handler
  const handleSaveAll = async () => {
    setSaveAllStatus("saving");
    try {
      await updateProject({
        name: channelName,
        niche,
        target_audience: targetAudience,
        frameworks: enabledFrameworks,
      });
      queryClient.invalidateQueries({ queryKey: ["currentProject"] });
      setSaveAllStatus("saved");
      setHasUnsavedChanges(false);
      setTimeout(() => setSaveAllStatus("idle"), 2000);
    } catch {
      setSaveAllStatus("idle");
    }
  };

  // Compute integration statuses from API keys data
  const integrationStatuses = Object.entries(INTEGRATION_KEY_MAP).map(([name, keys]) => {
    const connected = keys.every((keyName) => {
      const keyStatus = keysData?.keys.find((k) => k.name === keyName);
      return keyStatus?.configured ?? false;
    });
    return { name, connected };
  });

  if (projectLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }

  if (projectError) {
    return (
      <div className="py-12">
        <ErrorCard message={(projectError as Error).message || "Failed to load settings"} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  return (
    <motion.div className="space-y-8 max-w-3xl mx-auto" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item}>
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Profile
        </h1>
      </motion.div>

      {/* Example channels — the channels your videos are modeled on */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-1" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Example channels
          </h2>
        </div>
        <p className="text-xs mb-4" style={{ paddingLeft: 19, color: "var(--text-tertiary)" }}>
          Channels you want your videos modeled on. These power the title ideas in New Video. Add, remove, or re-sync them here.
        </p>
        <GlassCard className="p-6">
          <ExampleChannels variant="full" />
        </GlassCard>
      </motion.div>

      {/* Channel Profile */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Channel Profile
          </h2>
          <SavedIndicator visible={savedField === "name" || savedField === "niche" || savedField === "target_audience"} />
        </div>
        <GlassCard className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-secondary)" }}>
                Channel name
              </label>
              <input
                type="text"
                value={channelName}
                onChange={(e) => { setChannelName(e.target.value); setHasUnsavedChanges(true); }}
                onBlur={handleChannelNameBlur}
                className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none"
                style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                placeholder="Your channel name"
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
                onChange={handleNicheChange}
              />
            </div>
            <div>
              <label className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-secondary)" }}>
                Target audience
              </label>
              <textarea
                value={targetAudience}
                onChange={(e) => { setTargetAudience(e.target.value); setHasUnsavedChanges(true); }}
                onBlur={handleTargetAudienceBlur}
                rows={3}
                className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none resize-none"
                style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                placeholder="Describe your target audience..."
              />
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
          <SavedIndicator visible={savedField === "frameworks"} />
        </div>
        <GlassCard className="p-6">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {ALL_FRAMEWORKS.map((fw) => {
              const enabled = enabledFrameworks.includes(fw);
              return (
                <button
                  key={fw}
                  onClick={() => toggleFramework(fw)}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg transition-all text-sm"
                  style={{
                    background: enabled ? "var(--turquoise-dim)" : "var(--bg-elevated)",
                    border: `1px solid ${enabled ? "var(--turquoise)" : "var(--border-subtle)"}`,
                    color: enabled ? "var(--turquoise)" : "var(--text-secondary)",
                  }}
                >
                  {/* Toggle pill */}
                  <div
                    className="w-8 h-4 rounded-full relative transition-all shrink-0"
                    style={{ background: enabled ? "var(--turquoise)" : "var(--bg-surface)" }}
                  >
                    <div
                      className="w-3 h-3 rounded-full absolute top-0.5 transition-all"
                      style={{
                        background: enabled ? "var(--bg-void)" : "var(--text-tertiary)",
                        left: enabled ? "calc(100% - 14px)" : "2px",
                      }}
                    />
                  </div>
                  <span className="text-xs font-medium truncate">{fw}</span>
                </button>
              );
            })}
          </div>
        </GlassCard>
      </motion.div>

      {/* Visual Identity — Link to /profile */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Visual Identity
          </h2>
        </div>
        <GlassCard className="p-6">
          <div className="flex items-center justify-between">
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Visual styles, accent colors, and image profiles are configured on the Visual Profile page.
            </p>
            <button
              onClick={() => router.push("/profile")}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all hover:brightness-110"
              style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)", border: "1px solid var(--turquoise)" }}
            >
              Configure Visual Identity
              <ArrowRight size={16} />
            </button>
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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {integrationStatuses.map((integration) => {
            const Icon = INTEGRATION_ICONS[integration.name] || HardDrive;
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
                  onClick={() => router.push("/settings/keys")}
                  className="w-full py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110"
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

      {/* Brand Kit */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--gold)", paddingLeft: 16 }}>
          <Palette size={18} style={{ color: "var(--gold)" }} />
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Brand Kit
          </h2>
          {brandSaved && <SavedIndicator visible />}
        </div>
        <GlassCard className="p-6">
          <div className="space-y-5">
            {/* Accent Color */}
            <div>
              <label className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-secondary)" }}>
                Accent Color
              </label>
              <div className="flex items-center gap-2 flex-wrap">
                {[
                  { label: "Teal", value: "#00D4AA" },
                  { label: "Amber", value: "#FFB800" },
                  { label: "Crimson", value: "#C44545" },
                  { label: "Purple", value: "#8B5CF6" },
                ].map((c) => (
                  <button
                    key={c.value}
                    onClick={() => setBrandAccent(c.value)}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all"
                    style={{
                      background: brandAccent === c.value ? `${c.value}22` : "transparent",
                      border: `1px solid ${brandAccent === c.value ? c.value : "var(--border-subtle)"}`,
                    }}
                  >
                    <span className="w-4 h-4 rounded-full" style={{ background: c.value }} />
                    <span className="text-[10px] font-medium" style={{ color: brandAccent === c.value ? c.value : "var(--text-secondary)" }}>
                      {c.label}
                    </span>
                  </button>
                ))}
                <div className="flex items-center gap-1.5">
                  <input
                    type="text"
                    value={brandAccent}
                    onChange={(e) => setBrandAccent(e.target.value)}
                    maxLength={7}
                    className="w-20 px-2 py-1.5 rounded-lg text-xs font-mono outline-none"
                    style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                    placeholder="#hex"
                  />
                  <span className="w-5 h-5 rounded" style={{ background: brandAccent, border: "1px solid var(--border-subtle)" }} />
                </div>
              </div>
            </div>

            {/* Logo URL */}
            <div>
              <label className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-secondary)" }}>
                Logo URL
              </label>
              <div className="flex items-center gap-3">
                <input
                  type="text"
                  value={brandLogo}
                  onChange={(e) => setBrandLogo(e.target.value)}
                  className="flex-1 px-3 py-2 rounded-lg text-sm font-body outline-none"
                  style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                  placeholder="https://example.com/logo.png"
                />
                {brandLogo && (
                  <img src={brandLogo} alt="Logo preview" className="w-8 h-8 rounded object-contain" style={{ background: "var(--bg-elevated)" }} onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                )}
              </div>
            </div>

            {/* Save */}
            <button
              onClick={async () => {
                setBrandSaving(true);
                try {
                  await updateChannelProfile({ accent_color: brandAccent, logo_url: brandLogo });
                  queryClient.invalidateQueries({ queryKey: ["channelProfile"] });
                  setBrandSaved(true);
                  setTimeout(() => setBrandSaved(false), 2000);
                } finally {
                  setBrandSaving(false);
                }
              }}
              disabled={brandSaving}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110"
              style={{ background: "var(--gold-dim)", color: "var(--gold)", border: "1px solid var(--gold)" }}
            >
              {brandSaving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              {brandSaving ? "Saving..." : "Save Brand Kit"}
            </button>
          </div>
        </GlassCard>
      </motion.div>

      {/* Google Drive Storage */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--green)", paddingLeft: 16 }}>
          <HardDrive size={18} style={{ color: "var(--green)" }} />
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Google Drive Storage
          </h2>
          {driveSaved && <SavedIndicator visible />}
        </div>
        <GlassCard className="p-6">
          <p className="text-xs mb-4" style={{ color: "var(--text-tertiary)" }}>
            Connect your Google Drive to store pipeline assets — voice files, renders, thumbnails, and more. One click, no API keys needed.
          </p>

          {driveStatus?.connected ? (
            <div className="space-y-3">
              {/* Connected state */}
              <div
                className="flex items-center gap-3 px-4 py-3 rounded-lg"
                style={{ background: "rgba(34, 197, 94, 0.08)", border: "1px solid rgba(34, 197, 94, 0.2)" }}
              >
                <CheckCircle2 size={20} style={{ color: "var(--green)" }} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                    Google Drive Connected
                  </p>
                  <p className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                    Assets will be saved to your Drive
                  </p>
                </div>
              </div>

              {/* Folder selection */}
              {driveStatus.folder_id ? (
                <div
                  className="flex items-center gap-3 px-4 py-3 rounded-lg"
                  style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                >
                  <FolderOpen size={18} style={{ color: "var(--turquoise)" }} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                      {driveStatus.folder_name || "Selected Folder"}
                    </p>
                  </div>
                  <a
                    href={`https://drive.google.com/drive/folders/${driveStatus.folder_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-1.5 rounded-lg transition-colors hover:bg-[var(--bg-surface)]"
                    title="Open in Google Drive"
                  >
                    <ExternalLink size={14} style={{ color: "var(--text-secondary)" }} />
                  </a>
                </div>
              ) : (
                <p className="text-xs px-1" style={{ color: "var(--amber, #eab308)" }}>
                  No folder selected yet — choose where to store your assets.
                </p>
              )}

              {/* Actions */}
              <div className="flex items-center gap-2">
                <button
                  onClick={openDrivePicker}
                  disabled={!pickerLoaded || driveSaving}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110"
                  style={{ background: "var(--turquoise-dim, rgba(0,212,170,0.1))", color: "var(--turquoise)", border: "1px solid rgba(0, 212, 170, 0.3)" }}
                >
                  {driveSaving ? <Loader2 size={12} className="animate-spin" /> : <FolderOpen size={12} />}
                  {driveStatus.folder_id ? "Change Folder" : "Choose Folder"}
                </button>
                <button
                  onClick={disconnectDrive}
                  disabled={driveSaving}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110"
                  style={{ background: "rgba(239, 68, 68, 0.08)", color: "#ef4444", border: "1px solid rgba(239, 68, 68, 0.2)" }}
                >
                  <X size={12} />
                  Disconnect
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={connectGoogleDrive}
              className="flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all hover:brightness-110 w-full justify-center"
              style={{ background: "var(--green-dim, rgba(34,197,94,0.1))", color: "var(--green)", border: "1px solid rgba(34, 197, 94, 0.3)" }}
            >
              <HardDrive size={16} />
              Connect Google Drive
            </button>
          )}
        </GlassCard>
      </motion.div>

      {/* Notification Preferences */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--turquoise)", paddingLeft: 16 }}>
          <Bell size={18} style={{ color: "var(--turquoise)" }} />
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Notifications
          </h2>
        </div>
        <GlassCard className="p-6">
          <div className="space-y-4">
            {([
              { key: "email_video_complete" as const, label: "Pipeline Complete", desc: "When a video finishes rendering" },
              { key: "email_weekly_digest" as const, label: "Weekly Digest", desc: "Performance summary every Monday" },
              { key: "email_error_alerts" as const, label: "Error Alerts", desc: "When a pipeline step fails" },
              { key: "email_ctr_alerts" as const, label: "CTR Alerts", desc: "CTR drops or surges after publish" },
            ] as const).map((item) => (
              <div key={item.key} className="flex items-center justify-between py-1">
                <div>
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{item.label}</p>
                  <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>{item.desc}</p>
                </div>
                <button
                  data-testid={`notif-toggle-${item.key}`}
                  onClick={async () => {
                    const current = notifPrefs?.[item.key] ?? true;
                    // Optimistic update
                    queryClient.setQueryData(["notificationPrefs"], (old: NotificationPreferences | undefined) =>
                      old ? { ...old, [item.key]: !current } : old
                    );
                    try {
                      await updateNotificationPreferences({ [item.key]: !current });
                    } catch {
                      // Revert on failure
                      queryClient.invalidateQueries({ queryKey: ["notificationPrefs"] });
                    }
                  }}
                  className="w-10 h-5 rounded-full relative transition-all shrink-0"
                  style={{ background: (notifPrefs?.[item.key] ?? true) ? "var(--turquoise)" : "var(--bg-surface)" }}
                >
                  <div
                    className="w-4 h-4 rounded-full absolute top-0.5 transition-all"
                    style={{
                      background: (notifPrefs?.[item.key] ?? true) ? "var(--bg-void)" : "var(--text-tertiary)",
                      left: (notifPrefs?.[item.key] ?? true) ? "calc(100% - 18px)" : "2px",
                    }}
                  />
                </button>
              </div>
            ))}
          </div>
        </GlassCard>
      </motion.div>

      {/* Billing & Plan — link to dedicated page */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--gold)", paddingLeft: 16 }}>
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Billing & Plan
          </h2>
        </div>
        <GlassCard className="p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: "var(--gold-dim)" }}>
                <CreditCard size={20} style={{ color: "var(--gold)" }} />
              </div>
              <div>
                <p className="text-sm font-semibold capitalize" style={{ color: "var(--text-primary)" }}>
                  {subscription ? `${subscription.plan} Plan` : "Loading..."}
                </p>
                <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                  Manage your plan, usage, and payment
                </p>
              </div>
            </div>
            <button
              onClick={() => router.push("/billing")}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              <ArrowRight size={14} />
              Manage Billing
            </button>
          </div>
        </GlassCard>
      </motion.div>

      {/* Save Button */}
      <motion.div variants={item} className="flex justify-end pb-8">
        <button
          onClick={handleSaveAll}
          disabled={saveAllStatus === "saving"}
          className="flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold transition-all hover:brightness-110"
          style={{
            background: saveAllStatus === "saved" ? "var(--green)" : "var(--turquoise)",
            color: "var(--bg-void)",
          }}
        >
          {saveAllStatus === "saving" ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Saving...
            </>
          ) : saveAllStatus === "saved" ? (
            <>
              <CheckCircle2 size={16} />
              Saved
            </>
          ) : (
            <>
              <Save size={16} />
              Save Changes
            </>
          )}
        </button>
      </motion.div>
    </motion.div>
  );
}

/** Green checkmark that fades after 2s */
function SavedIndicator({ visible }: { visible: boolean }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: visible ? 1 : 0, scale: visible ? 1 : 0.8 }}
      transition={{ duration: 0.2 }}
      className="flex items-center gap-1"
    >
      <CheckCircle2 size={14} className="text-green-500" />
      <span className="text-xs text-green-500 font-medium">Saved</span>
    </motion.div>
  );
}
