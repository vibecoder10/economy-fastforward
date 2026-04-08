"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Key,
  CheckCircle2,
  XCircle,
  AlertCircle,
  RefreshCw,
  Check,
  Clock,
} from "lucide-react";
import { Card, Modal, Spinner, Tabs, TabPanel } from "@/components/ui";
import { PasswordInput } from "@/components/forms";
import {
  getApiKeys,
  setApiKey,
  testApiKey,
  validateAllApiKeys,
  type ApiKeyStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// Ordered integration list per requirements
const INTEGRATION_ORDER = [
  "anthropic_api_key",
  "elevenlabs_api_key",
  "elevenlabs_voice_id",
  "kie_ai_api_key",
  "openai_api_key",
  "gemini_api_key",
  "google_client_id",
  "google_refresh_token",
];

// Human-readable key names and descriptions
const KEY_LABELS: Record<string, { name: string; description: string; group?: string; required?: boolean }> = {
  anthropic_api_key: { name: "Anthropic (Claude)", description: "AI for scripts, prompts, and analysis", required: true },
  elevenlabs_api_key: { name: "ElevenLabs API Key", description: "Voice synthesis for narration", group: "ElevenLabs", required: true },
  elevenlabs_voice_id: { name: "ElevenLabs Voice ID", description: "Voice ID for narration", group: "ElevenLabs" },
  kie_ai_api_key: { name: "Kie.ai", description: "Image and video generation", required: true },
  openai_api_key: { name: "OpenAI", description: "Whisper transcription" },
  gemini_api_key: { name: "Gemini", description: "Vision analysis for thumbnails" },
  google_client_id: { name: "YouTube Data API", description: "Upload and analytics", group: "Google" },
  google_refresh_token: { name: "Google Drive", description: "Asset storage", group: "Google" },
};

export default function ApiKeysPage() {
  const [activeTab, setActiveTab] = useState("keys");
  const queryClient = useQueryClient();

  // Modal state
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [keyValue, setKeyValue] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  // Per-key test results (persisted across renders)
  const [testResults, setTestResults] = useState<Record<string, { success: boolean | null; message: string; timestamp: string }>>({});
  const [testingKey, setTestingKey] = useState<string | null>(null);

  // Fetch all keys
  const { data: keysData, isLoading, error: fetchError } = useQuery({
    queryKey: ["apiKeys"],
    queryFn: getApiKeys,
  });

  // Test key mutation
  const testMutation = useMutation({
    mutationFn: testApiKey,
    onMutate: (keyName: string) => {
      setTestingKey(keyName);
    },
    onSuccess: (result, keyName) => {
      setTestResults((prev) => ({
        ...prev,
        [keyName]: {
          success: result.success,
          message: result.message,
          timestamp: new Date().toLocaleTimeString(),
        },
      }));
      setTestingKey(null);
      queryClient.invalidateQueries({ queryKey: ["apiKeys"] });
    },
    onError: (_error, keyName) => {
      setTestResults((prev) => ({
        ...prev,
        [keyName]: {
          success: false,
          message: "Connection test failed",
          timestamp: new Date().toLocaleTimeString(),
        },
      }));
      setTestingKey(null);
    },
  });

  // Set key mutation
  const setMutation = useMutation({
    mutationFn: ({ name, value }: { name: string; value: string }) => setApiKey(name, value),
    onMutate: () => {
      setSaveStatus("saving");
      setSaveError(null);
    },
    onSuccess: () => {
      setSaveStatus("success");
      queryClient.invalidateQueries({ queryKey: ["apiKeys"] });
      setTimeout(() => {
        setEditingKey(null);
        setKeyValue("");
        setSaveStatus("idle");
      }, 1500);
    },
    onError: (error: Error) => {
      setSaveStatus("error");
      setSaveError(error.message || "Failed to save API key");
    },
  });

  // Validate all keys mutation
  const validateAllMutation = useMutation({
    mutationFn: validateAllApiKeys,
    onSuccess: (data) => {
      const results: Record<string, { success: boolean | null; message: string; timestamp: string }> = {};
      const ts = new Date().toLocaleTimeString();
      for (const r of data.results) {
        results[r.key] = { success: r.success, message: r.message, timestamp: ts };
      }
      setTestResults((prev) => ({ ...prev, ...results }));
      queryClient.invalidateQueries({ queryKey: ["apiKeys"] });
    },
  });

  const closeEditModal = () => {
    setEditingKey(null);
    setKeyValue("");
    setSaveStatus("idle");
    setSaveError(null);
  };

  // Filter keys to only show the ones we want, in order
  const orderedKeys = INTEGRATION_ORDER.map((name) => {
    const keyData = keysData?.keys.find((k) => k.name === name);
    return keyData || { name, configured: false, source: null, masked_value: null };
  });

  // Group keys by group header
  const renderKeys = () => {
    let lastGroup: string | undefined;
    const elements: React.ReactNode[] = [];

    orderedKeys.forEach((key) => {
      const label = KEY_LABELS[key.name];
      if (!label) return;

      // Render group header if needed
      if (label.group && label.group !== lastGroup) {
        elements.push(
          <div key={`group-${label.group}`} className="pt-4 pb-1 first:pt-0">
            <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
              {label.group}
            </p>
          </div>
        );
        lastGroup = label.group;
      } else if (!label.group && lastGroup) {
        lastGroup = undefined;
      }

      elements.push(
        <ApiKeyCard
          key={key.name}
          apiKey={key}
          label={label.name}
          description={label.description}
          required={label.required ?? false}
          onUpdate={() => {
            setEditingKey(key.name);
            setKeyValue("");
            setSaveStatus("idle");
            setSaveError(null);
          }}
          onTest={() => testMutation.mutate(key.name)}
          isTesting={testingKey === key.name}
          testResult={testResults[key.name] || null}
        />
      );
    });

    return elements;
  };

  const tabs = [
    { id: "keys", label: "API Keys" },
    { id: "autopilot", label: "Autopilot" },
    { id: "preferences", label: "Preferences" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Settings</h1>

      <Tabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      <TabPanel active={activeTab === "keys"}>
        <div className="space-y-3">
          {/* Validate All button */}
          {!isLoading && !fetchError && (
            <div className="flex justify-end">
              <button
                onClick={() => validateAllMutation.mutate()}
                disabled={validateAllMutation.isPending}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
                style={{
                  border: "1px solid var(--border)",
                  color: validateAllMutation.isPending ? "var(--text-tertiary)" : "var(--text-secondary)",
                }}
              >
                {validateAllMutation.isPending ? (
                  <Spinner size="sm" />
                ) : (
                  <RefreshCw size={14} />
                )}
                {validateAllMutation.isPending ? "Validating..." : "Validate All"}
              </button>
            </div>
          )}
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Spinner size="lg" />
            </div>
          ) : fetchError ? (
            <div className="flex items-center gap-2 rounded-lg bg-[var(--error)]/10 p-4 text-sm text-[var(--error)]">
              <AlertCircle size={16} />
              Failed to load API keys: {fetchError.message}
            </div>
          ) : (
            renderKeys()
          )}
        </div>
      </TabPanel>

      <TabPanel active={activeTab === "autopilot"}>
        <Card>
          <div className="p-4">
            <div className="flex flex-col items-center justify-center gap-4 py-8 text-center">
              <AlertCircle size={40} className="text-[var(--text-secondary)]" />
              <div>
                <p className="font-medium">Autopilot configuration coming soon</p>
              </div>
            </div>
          </div>
        </Card>
      </TabPanel>

      <TabPanel active={activeTab === "preferences"}>
        <Card>
          <div className="p-4">
            <div className="flex flex-col items-center justify-center gap-4 py-8 text-center">
              <AlertCircle size={40} className="text-[var(--text-secondary)]" />
              <div>
                <p className="font-medium">Preferences coming soon</p>
              </div>
            </div>
          </div>
        </Card>
      </TabPanel>

      {/* Edit Key Modal */}
      <Modal
        open={editingKey !== null}
        onClose={closeEditModal}
        title={`${editingKey && KEY_LABELS[editingKey] ? (keysData?.keys.find((k) => k.name === editingKey)?.configured ? "Update" : "Configure") : "Configure"} ${KEY_LABELS[editingKey || ""]?.name || editingKey}`}
        size="md"
      >
        {saveStatus === "success" ? (
          <div className="flex flex-col items-center justify-center gap-3 py-6">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-500/10">
              <Check size={24} className="text-green-500" />
            </div>
            <p className="font-medium text-green-500">API Key Saved Successfully!</p>
            <p className="text-sm text-[var(--text-secondary)]">
              The key is now stored securely.
            </p>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (editingKey && keyValue) {
                setMutation.mutate({ name: editingKey, value: keyValue });
              }
            }}
            className="space-y-4"
          >
            <PasswordInput
              label="API Key"
              value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
              placeholder="Enter your API key..."
              autoFocus
              disabled={saveStatus === "saving"}
            />
            <p className="text-xs text-[var(--text-secondary)]">
              {KEY_LABELS[editingKey || ""]?.description}
            </p>

            {saveStatus === "error" && saveError && (
              <div className="flex items-center gap-2 rounded-lg bg-[var(--error)]/10 p-3 text-xs text-[var(--error)]">
                <XCircle size={14} />
                {saveError}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeEditModal}
                disabled={saveStatus === "saving"}
                className="rounded-lg px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!keyValue || saveStatus === "saving"}
                className="flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-black disabled:opacity-50"
              >
                {saveStatus === "saving" && <Spinner size="sm" className="text-black" />}
                {saveStatus === "saving" ? "Saving..." : "Save Key"}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}

// Integration status dot — shows connection state at a glance
function StatusDot({ status }: { status: "connected" | "not_configured" | "failed" }) {
  const colors = {
    connected: "var(--green)",
    not_configured: "var(--text-tertiary)",
    failed: "var(--red)",
  };
  return (
    <span
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
      style={{ backgroundColor: colors[status] }}
      title={status === "connected" ? "Connected" : status === "failed" ? "Connection failed" : "Not configured"}
    />
  );
}

// Individual API Key Card component
interface ApiKeyCardProps {
  apiKey: ApiKeyStatus;
  label: string;
  description: string;
  required: boolean;
  onUpdate: () => void;
  onTest: () => void;
  isTesting: boolean;
  testResult: { success: boolean | null; message: string; timestamp: string } | null;
}

function ApiKeyCard({
  apiKey,
  label,
  description,
  required,
  onUpdate,
  onTest,
  isTesting,
  testResult,
}: ApiKeyCardProps) {
  // Derive integration status from configured state + test results
  const integrationStatus: "connected" | "not_configured" | "failed" =
    testResult?.success === false ? "failed" :
    testResult?.success === true ? "connected" :
    apiKey.configured ? "connected" : "not_configured";

  return (
    <Card>
      <div className="flex items-start justify-between p-4">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-10 w-10 items-center justify-center rounded-lg",
              apiKey.configured ? "bg-green-500/10" : "bg-[var(--surface-elevated)]"
            )}
          >
            <Key
              size={20}
              className={apiKey.configured ? "text-green-500" : "text-[var(--text-secondary)]"}
            />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-medium">{label}</h3>
              <span
                className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                style={{
                  color: required ? "var(--orange)" : "var(--text-tertiary)",
                  backgroundColor: required ? "var(--orange-dim)" : "rgba(255,255,255,0.05)",
                }}
              >
                {required ? "Required" : "Optional"}
              </span>
              <StatusDot status={integrationStatus} />
            </div>
            <p className="mt-0.5 text-xs text-[var(--text-secondary)]">{description}</p>
            {apiKey.configured && apiKey.masked_value && (
              <div className="mt-2">
                <code className="rounded bg-[var(--background)] px-2 py-0.5 text-xs">
                  {apiKey.masked_value}
                </code>
              </div>
            )}
            {testResult && (
              <div className="mt-2 flex items-center gap-1.5">
                {testResult.success ? (
                  <span className="flex items-center gap-1 text-xs text-green-500">
                    <CheckCircle2 size={14} />
                    Connected
                  </span>
                ) : testResult.success === false ? (
                  <span className="flex items-center gap-1 text-xs text-[var(--error)]">
                    <XCircle size={14} />
                    Invalid Key
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                    <AlertCircle size={14} />
                    {testResult.message}
                  </span>
                )}
                <span className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)]">
                  <Clock size={10} />
                  {testResult.timestamp}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1">
          {apiKey.configured ? (
            <>
              <button
                onClick={onTest}
                disabled={isTesting}
                className="rounded-lg px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--text-primary)] disabled:opacity-50"
                title="Test connection"
              >
                {isTesting ? <Spinner size="sm" /> : (
                  <span className="flex items-center gap-1">
                    <RefreshCw size={14} />
                    Test
                  </span>
                )}
              </button>
              <button
                onClick={onUpdate}
                className="rounded-lg px-3 py-1.5 text-sm font-medium text-[var(--accent)] hover:bg-[var(--accent)]/10"
              >
                Update
              </button>
            </>
          ) : (
            <button
              onClick={onUpdate}
              className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black"
            >
              Configure
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
