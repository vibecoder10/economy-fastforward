"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Key,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Eye,
  Trash2,
  RefreshCw,
  Server,
  Cloud,
} from "lucide-react";
import { Card, Modal, Spinner, Tabs, TabPanel } from "@/components/ui";
import { PasswordInput } from "@/components/forms";
import {
  getApiKeys,
  setApiKey,
  deleteApiKey,
  testApiKey,
  revealApiKey,
  type ApiKeyStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// Human-readable key names
const KEY_LABELS: Record<string, { name: string; description: string }> = {
  anthropic_api_key: { name: "Anthropic (Claude)", description: "AI for scripts, prompts, and analysis" },
  elevenlabs_api_key: { name: "ElevenLabs", description: "Voice synthesis for narration" },
  elevenlabs_voice_id: { name: "ElevenLabs Voice ID", description: "Voice ID for narration" },
  kie_ai_api_key: { name: "Kie.ai", description: "Image and video generation" },
  openai_api_key: { name: "OpenAI", description: "Whisper transcription" },
  gemini_api_key: { name: "Gemini", description: "Vision analysis for thumbnails" },
  tavily_api_key: { name: "Tavily", description: "Web search for research" },
  airtable_api_key: { name: "Airtable (Legacy)", description: "Legacy database - being migrated" },
  airtable_base_id: { name: "Airtable Base ID", description: "Legacy database ID" },
  google_client_id: { name: "Google Client ID", description: "OAuth for Drive and Docs" },
  google_client_secret: { name: "Google Client Secret", description: "OAuth secret" },
  google_refresh_token: { name: "Google Refresh Token", description: "OAuth refresh token" },
  slack_bot_token: { name: "Slack Bot Token", description: "Pipeline notifications" },
  slack_app_token: { name: "Slack App Token", description: "Slack socket mode" },
};

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState("keys");
  const queryClient = useQueryClient();

  // Modal state
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [keyValue, setKeyValue] = useState("");
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [revealedValue, setRevealedValue] = useState<string | null>(null);

  // Fetch all keys
  const { data: keysData, isLoading } = useQuery({
    queryKey: ["apiKeys"],
    queryFn: getApiKeys,
  });

  // Test key mutation
  const testMutation = useMutation({
    mutationFn: testApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["apiKeys"] });
    },
  });

  // Set key mutation
  const setMutation = useMutation({
    mutationFn: ({ name, value }: { name: string; value: string }) => setApiKey(name, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["apiKeys"] });
      setEditingKey(null);
      setKeyValue("");
    },
  });

  // Delete key mutation
  const deleteMutation = useMutation({
    mutationFn: deleteApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["apiKeys"] });
    },
  });

  // Reveal key
  const handleReveal = async (name: string) => {
    try {
      const result = await revealApiKey(name);
      setRevealedKey(name);
      setRevealedValue(result.value);
    } catch {
      // Handle error silently
    }
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
        <div className="space-y-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Spinner size="lg" />
            </div>
          ) : (
            keysData?.keys.map((key) => (
              <ApiKeyCard
                key={key.name}
                apiKey={key}
                label={KEY_LABELS[key.name]?.name || key.name}
                description={KEY_LABELS[key.name]?.description || ""}
                onConfigure={() => {
                  setEditingKey(key.name);
                  setKeyValue("");
                }}
                onTest={() => testMutation.mutate(key.name)}
                onReveal={() => handleReveal(key.name)}
                onDelete={() => deleteMutation.mutate(key.name)}
                isTesting={testMutation.isPending && testMutation.variables === key.name}
                testResult={
                  testMutation.data && testMutation.variables === key.name
                    ? testMutation.data
                    : null
                }
              />
            ))
          )}
        </div>
      </TabPanel>

      <TabPanel active={activeTab === "autopilot"}>
        <Card>
          <div className="p-4">
            <h3 className="mb-4 font-semibold">Autopilot Control</h3>
            <div className="flex flex-col items-center justify-center gap-4 py-8 text-center">
              <AlertCircle size={40} className="text-[var(--text-secondary)]" />
              <div>
                <p className="font-medium">Autopilot controls coming soon</p>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  ON/OFF toggle, cadence settings, confidence weights
                </p>
              </div>
            </div>
          </div>
        </Card>
      </TabPanel>

      <TabPanel active={activeTab === "preferences"}>
        <Card>
          <div className="p-4">
            <h3 className="mb-4 font-semibold">Preferences</h3>
            <div className="flex flex-col items-center justify-center gap-4 py-8 text-center">
              <AlertCircle size={40} className="text-[var(--text-secondary)]" />
              <div>
                <p className="font-medium">Preferences coming soon</p>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  Default visual styles, notification settings
                </p>
              </div>
            </div>
          </div>
        </Card>
      </TabPanel>

      {/* Edit Key Modal */}
      <Modal
        open={editingKey !== null}
        onClose={() => {
          setEditingKey(null);
          setKeyValue("");
        }}
        title={`Configure ${KEY_LABELS[editingKey || ""]?.name || editingKey}`}
        size="md"
      >
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
          />
          <p className="text-xs text-[var(--text-secondary)]">
            {KEY_LABELS[editingKey || ""]?.description}
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setEditingKey(null);
                setKeyValue("");
              }}
              className="rounded-lg px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!keyValue || setMutation.isPending}
              className="flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-black disabled:opacity-50"
            >
              {setMutation.isPending && <Spinner size="sm" className="text-black" />}
              Save Key
            </button>
          </div>
        </form>
      </Modal>

      {/* Reveal Key Modal */}
      <Modal
        open={revealedKey !== null}
        onClose={() => {
          setRevealedKey(null);
          setRevealedValue(null);
        }}
        title={`${KEY_LABELS[revealedKey || ""]?.name || revealedKey} - Full Value`}
        size="md"
      >
        <div className="space-y-4">
          <div className="rounded-lg bg-[var(--background)] p-3">
            <code className="break-all text-sm">{revealedValue}</code>
          </div>
          <p className="text-xs text-[var(--error)]">
            Keep this key secret. Do not share it publicly.
          </p>
          <div className="flex justify-end">
            <button
              onClick={() => {
                setRevealedKey(null);
                setRevealedValue(null);
              }}
              className="rounded-lg bg-[var(--surface-elevated)] px-4 py-2 text-sm font-medium"
            >
              Close
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// Individual API Key Card component
interface ApiKeyCardProps {
  apiKey: ApiKeyStatus;
  label: string;
  description: string;
  onConfigure: () => void;
  onTest: () => void;
  onReveal: () => void;
  onDelete: () => void;
  isTesting: boolean;
  testResult: { success: boolean | null; message: string } | null;
}

function ApiKeyCard({
  apiKey,
  label,
  description,
  onConfigure,
  onTest,
  onReveal,
  onDelete,
  isTesting,
  testResult,
}: ApiKeyCardProps) {
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
            <h3 className="font-medium">{label}</h3>
            <p className="mt-0.5 text-xs text-[var(--text-secondary)]">{description}</p>
            {apiKey.configured && (
              <div className="mt-2 flex items-center gap-2">
                <code className="rounded bg-[var(--background)] px-2 py-0.5 text-xs">
                  {apiKey.masked_value}
                </code>
                {apiKey.source && (
                  <span className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                    {apiKey.source === "vault" ? (
                      <>
                        <Cloud size={12} />
                        Vault
                      </>
                    ) : (
                      <>
                        <Server size={12} />
                        Environment
                      </>
                    )}
                  </span>
                )}
              </div>
            )}
            {testResult && (
              <div
                className={cn(
                  "mt-2 flex items-center gap-1.5 text-xs",
                  testResult.success ? "text-green-500" : "text-[var(--error)]"
                )}
              >
                {testResult.success ? (
                  <CheckCircle2 size={14} />
                ) : (
                  <XCircle size={14} />
                )}
                {testResult.message}
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
                className="rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--text-primary)] disabled:opacity-50"
                title="Test key"
              >
                {isTesting ? <Spinner size="sm" /> : <RefreshCw size={16} />}
              </button>
              <button
                onClick={onReveal}
                className="rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--text-primary)]"
                title="Reveal key"
              >
                <Eye size={16} />
              </button>
              <button
                onClick={onConfigure}
                className="rounded-lg px-3 py-1.5 text-sm font-medium text-[var(--accent)] hover:bg-[var(--accent)]/10"
              >
                Update
              </button>
              {apiKey.source === "vault" && (
                <button
                  onClick={onDelete}
                  className="rounded-lg p-2 text-[var(--error)] hover:bg-[var(--error)]/10"
                  title="Delete from vault"
                >
                  <Trash2 size={16} />
                </button>
              )}
            </>
          ) : (
            <button
              onClick={onConfigure}
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
