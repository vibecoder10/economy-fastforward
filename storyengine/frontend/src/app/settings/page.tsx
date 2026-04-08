"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Youtube, HardDrive, CheckCircle2, ArrowRight, Loader2, Save, CreditCard, Crown, Zap, Building2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { GlassCard } from "@/components/ui/GlassCard";
import { FilterSelect } from "@/components/ui/FilterSelect";
import {
  getCurrentProject,
  updateProject,
  getApiKeys,
  getSubscription,
  createCheckout,
  createBillingPortal,
  getUsage,
  type Project,
  type ProjectUpdate,
} from "@/lib/api";

const TRUSTED_STRIPE_DOMAINS = [
  "https://checkout.stripe.com",
  "https://billing.stripe.com",
];

function isStripeUrl(url: string): boolean {
  return TRUSTED_STRIPE_DOMAINS.some((domain) => url.startsWith(domain));
}

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
  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ["currentProject"],
    queryFn: getCurrentProject,
  });

  // Fetch API keys for integration status
  const { data: keysData } = useQuery({
    queryKey: ["apiKeys"],
    queryFn: getApiKeys,
  });

  // Fetch subscription status
  const { data: subscription, isLoading: subLoading } = useQuery({
    queryKey: ["subscription"],
    queryFn: getSubscription,
  });

  const { data: usage } = useQuery({
    queryKey: ["usage"],
    queryFn: getUsage,
  });

  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);

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
        <Loader2 size={32} className="animate-spin" style={{ color: "var(--turquoise)" }} />
      </div>
    );
  }

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

      {/* Billing & Plan */}
      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-4" style={{ borderLeft: "3px solid var(--gold)", paddingLeft: 16 }}>
          <h2 className="text-lg font-semibold font-body" style={{ color: "var(--text-primary)" }}>
            Billing & Plan
          </h2>
        </div>

        {/* Current plan banner */}
        {subscription && (
          <GlassCard className="p-5 mb-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: "var(--gold-dim)" }}>
                  <Crown size={20} style={{ color: "var(--gold)" }} />
                </div>
                <div>
                  <p className="text-sm font-semibold capitalize" style={{ color: "var(--text-primary)" }}>
                    {subscription.plan} Plan
                  </p>
                  {subscription.stripe_status && (
                    <span className="text-[10px] font-mono" style={{ color: subscription.stripe_status === "active" ? "var(--green)" : "var(--gold)" }}>
                      {subscription.stripe_status}
                    </span>
                  )}
                </div>
              </div>
              {subscription.has_subscription && (
                <button
                  onClick={async () => {
                    setPortalLoading(true);
                    try {
                      const res = await createBillingPortal();
                      if (!isStripeUrl(res.portal_url)) {
                        alert("Invalid billing portal URL. Please contact support.");
                        setPortalLoading(false);
                        return;
                      }
                      window.location.href = res.portal_url;
                    } catch { setPortalLoading(false); }
                  }}
                  disabled={portalLoading}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110"
                  style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
                >
                  {portalLoading ? <Loader2 size={14} className="animate-spin" /> : <CreditCard size={14} />}
                  Manage Subscription
                </button>
              )}
            </div>
          </GlassCard>
        )}

        {/* Usage stats */}
        {usage && (
          <GlassCard className="p-5 mb-4">
            <h3
              className="text-[11px] font-semibold uppercase tracking-wider mb-3"
              style={{ color: "var(--text-secondary)" }}
            >
              This Month&apos;s Usage
            </h3>
            {[
              { label: "Videos", used: usage.usage.videos_created, limit: usage.limits.videos_per_month },
              { label: "Render Minutes", used: Math.round(usage.usage.render_minutes), limit: usage.limits.render_minutes },
            ].map(({ label, used, limit }) => {
              const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
              const barColor = pct >= 90 ? "var(--red)" : pct >= 70 ? "var(--gold)" : "var(--turquoise)";
              return (
                <div key={label} className="mb-3 last:mb-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{label}</span>
                    <span className="text-xs font-mono" style={{ color: barColor }}>{used}/{limit}</span>
                  </div>
                  <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: barColor }} />
                  </div>
                </div>
              );
            })}
          </GlassCard>
        )}

        {/* Plan selection cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {([
            { key: "starter", name: "Starter", price: "$25", icon: Zap, features: ["Pipeline access", "1 channel", "Manual mode"] },
            { key: "pro", name: "Pro", price: "$40", icon: Crown, features: ["Autopilot", "Analytics", "Competitor scraping", "Learnings"] },
            { key: "agency", name: "Agency", price: "$75", icon: Building2, features: ["Multi-channel", "Team management", "Priority rendering"] },
          ] as const).map((plan) => {
            const isCurrent = subscription?.plan === plan.key || (subscription?.stripe_plan === plan.key);
            const Icon = plan.icon;
            return (
              <GlassCard key={plan.key} className="p-5" style={isCurrent ? { border: "1px solid var(--gold)" } : undefined}>
                <div className="flex items-center gap-2 mb-3">
                  <Icon size={18} style={{ color: isCurrent ? "var(--gold)" : "var(--text-secondary)" }} />
                  <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{plan.name}</span>
                </div>
                <p className="text-2xl font-display mb-1" style={{ color: "var(--text-primary)" }}>
                  {plan.price}<span className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>/mo</span>
                </p>
                <ul className="space-y-1.5 mt-3 mb-4">
                  {plan.features.map((f) => (
                    <li key={f} className="text-xs flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
                      <CheckCircle2 size={12} style={{ color: "var(--turquoise)" }} />
                      {f}
                    </li>
                  ))}
                </ul>
                {isCurrent ? (
                  <div className="text-center text-xs font-medium py-2 rounded-lg" style={{ background: "var(--gold-dim)", color: "var(--gold)" }}>
                    Current Plan
                  </div>
                ) : (
                  <button
                    onClick={async () => {
                      setCheckoutLoading(plan.key);
                      try {
                        const res = await createCheckout(plan.key);
                        if (!isStripeUrl(res.checkout_url)) {
                          alert("Invalid checkout URL. Please contact support.");
                          setCheckoutLoading(null);
                          return;
                        }
                        window.location.href = res.checkout_url;
                      } catch { setCheckoutLoading(null); }
                    }}
                    disabled={checkoutLoading !== null}
                    className="w-full py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110"
                    style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                  >
                    {checkoutLoading === plan.key ? (
                      <Loader2 size={14} className="animate-spin inline" />
                    ) : (
                      "Subscribe"
                    )}
                  </button>
                )}
              </GlassCard>
            );
          })}
        </div>
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
