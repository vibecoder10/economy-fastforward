import { API_URL, RUBRIC_URL } from "./env";

// Auto-report failed API calls to RUBRIC dashboard (silent, non-blocking)
function reportError(path: string, status: number, body: string, method: string) {
  if (typeof window === "undefined") return;
  if (!RUBRIC_URL) return; // prod: no RUBRIC endpoint configured, skip silently
  const page = window.location.pathname;
  try {
    fetch(`${RUBRIC_URL}/api/activity-log`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent: "user-browser",
        task: `${method} ${path}`,
        summary: `API error ${status} on ${page}: ${method} ${path} → ${body.substring(0, 200)}`,
        status: "error",
      }),
    }).catch(() => {});
  } catch {}
}

// Command center: the operator's currently-selected client workspace. When set,
// every request carries it as X-Active-Tenant and the backend re-scopes to that
// tenant (after a membership check). Unset for normal users -> no header -> the
// backend behaves exactly as before. Phase 2's switcher writes this key.
export const ACTIVE_TENANT_KEY = "se_active_tenant";

export const getActiveTenant = (): string | null =>
  typeof window !== "undefined" ? localStorage.getItem(ACTIVE_TENANT_KEY) : null;

// Switch the active workspace. Passing null clears it (back to the home tenant).
// A full reload is intentional: it guarantees no stale cross-tenant data lingers
// in memory when re-scoping the whole app to another client channel.
export const setActiveTenant = (tenantId: string | null) => {
  if (typeof window === "undefined") return;
  if (tenantId) localStorage.setItem(ACTIVE_TENANT_KEY, tenantId);
  else localStorage.removeItem(ACTIVE_TENANT_KEY);
  window.location.assign("/");
};

/** Auth + workspace headers for RAW fetch calls (file uploads that can't use
 * fetchApi's JSON Content-Type). Every request must carry X-Active-Tenant or
 * the backend scopes to the login workspace — uploads made while operating a
 * client channel 404'd on lookup (found live: character sheet upload). */
export function uploadHeaders(): Record<string, string> {
  const token = (typeof window !== "undefined" ? localStorage.getItem("token") : null) || "dev-token";
  const activeTenant = typeof window !== "undefined" ? localStorage.getItem(ACTIVE_TENANT_KEY) : null;
  return {
    Authorization: `Bearer ${token}`,
    ...(activeTenant ? { "X-Active-Tenant": activeTenant } : {}),
  };
}

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  // Get token from localStorage, fallback to "dev-token" for development
  const storedToken = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const token = storedToken || "dev-token";
  const activeTenant = typeof window !== "undefined" ? localStorage.getItem(ACTIVE_TENANT_KEY) : null;

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(activeTenant ? { "X-Active-Tenant": activeTenant } : {}),
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text();
    // On 401 (invalid/expired token), clear auth and redirect to login
    if (res.status === 401 && typeof window !== "undefined" && !path.includes("/api/auth/")) {
      localStorage.removeItem("token");
      window.location.href = "/login";
      throw new Error("Session expired — redirecting to login");
    }
    // On 402 (plan limit reached), show upgrade prompt
    if (res.status === 402 && typeof window !== "undefined") {
      try {
        const detail = JSON.parse(body)?.detail || JSON.parse(body);
        if (detail?.error === "plan_limit_reached") {
          const goToPricing = window.confirm(
            `${detail.message}\n\nWould you like to view upgrade options?`
          );
          if (goToPricing) {
            window.location.href = detail.upgrade_url || "/pricing";
          }
        }
      } catch {
        // ignore parse errors
      }
      throw new Error("Plan limit reached");
    }
    // Only report non-auth errors to RUBRIC (skip dev-token and expected auth 401s)
    if (storedToken && storedToken !== "dev-token" && !(res.status === 401 && path.includes("/api/auth/"))) {
      reportError(path, res.status, body, options?.method || "GET");
    }
    // Extract descriptive detail from JSON error responses
    let errorMessage = `API error ${res.status}: ${body}`;
    try {
      const parsed = JSON.parse(body);
      if (parsed?.detail) {
        errorMessage = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      }
    } catch {
      // body wasn't JSON, use raw text
    }
    throw new Error(errorMessage);
  }

  return res.json();
}

// Auth
export interface AuthUser {
  id: string;
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
  plan: string;
  tenant_id?: string | null;
  created_at?: string | null;
  email_verified?: boolean;
}

export const googleLogin = (credential: string) =>
  fetchApi<{ token: string; user: AuthUser }>("/api/auth/google", {
    method: "POST",
    body: JSON.stringify({ credential }),
  });

export const registerUser = (email: string, password: string, display_name: string = "") =>
  fetchApi<{ token: string; user: AuthUser }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name }),
  });

export const loginUser = (email: string, password: string) =>
  fetchApi<{ token: string; user: AuthUser }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const getMe = () => fetchApi<AuthUser>("/api/auth/me");

export const verifyEmail = (token: string) =>
  fetchApi<{ verified: boolean }>("/api/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
  });

export const resendVerification = () =>
  fetchApi<{ sent: boolean; already_verified?: boolean }>("/api/auth/resend-verification", {
    method: "POST",
  });

export const forgotPassword = (email: string) =>
  fetchApi<{ status: string; message: string }>("/api/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });

export const resetPassword = (token: string, new_password: string) =>
  fetchApi<{ status: string; message: string }>("/api/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password }),
  });

// Dashboard
export const getDashboardSummary = () => fetchApi<DashboardSummary>("/api/dashboard/summary");

// Onboarding
export type OnboardingStatus = {
  completed: boolean;
  steps: {
    account_created: boolean;
    channel_configured: boolean;
    api_keys: { configured: number; required: number };
    style_generated: boolean;
    youtube_connected: boolean;
    first_video_created: boolean;
  };
  first_run?: {
    competitor_count: number;
    distilled_count: number;
    video_count: number;
  };
  percent_complete: number;
  display_name: string | null;
};

export const getOnboardingStatus = () =>
  fetchApi<OnboardingStatus>("/api/dashboard/onboarding/status");

export const completeOnboarding = () =>
  fetchApi<{ completed: boolean }>("/api/dashboard/onboarding/complete", {
    method: "POST",
  });

// Calendar
export type CalendarVideo = {
  id: string;
  video_title: string | null;
  status: string | null;
  thumbnail_url: string | null;
  accent_color: string | null;
};

export const getCalendarVideos = (start: string, end: string) =>
  fetchApi<Record<string, CalendarVideo[]>>(`/api/dashboard/calendar?start=${start}&end=${end}`);

export interface CalendarPlanSlot {
  date: string;
  // "queued" = the creator's own production queue (first slots, in their order);
  // "candidate" = a scored competitor winner. Older responses omit kind.
  kind?: "queued" | "candidate";
  candidate_id?: string;
  queue_id?: string;
  position?: number;
  source_title: string;
  source_channel: string;
  source_url?: string | null;
  views?: number;
  score?: number;
  why: string;
}
export interface CalendarPlan {
  interval_days: number;
  slots: CalendarPlanSlot[];
  note?: string;
}
export const getCalendarPlan = (days?: number) =>
  fetchApi<CalendarPlan>(`/api/dashboard/calendar/plan?days=${days || 30}`);

// --- Production queue (the creator's own ordered "build these" list) ---
export interface QueueItem {
  id: string;
  position: number;
  title: string;
  framework_angle?: string | null;
  status: "queued" | "launched" | "skipped";
  video_id?: string | null;
  launched_at?: string | null;
  created_at: string;
}
export const getQueue = () => fetchApi<{ items: QueueItem[] }>("/api/queue");
export const addToQueue = (items: { title: string }[]) =>
  fetchApi<{ status: string; count: number }>("/api/queue", {
    method: "POST",
    body: JSON.stringify({ items }),
  });
export const patchQueueItem = (id: string, data: { title?: string; position?: number; status?: string }) =>
  fetchApi<{ status: string }>(`/api/queue/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
export const deleteQueueItem = (id: string) =>
  fetchApi<{ status: string }>(`/api/queue/${id}`, { method: "DELETE" });
// --- Channel cast (locked brand identity) ---
export interface ChannelCastMember {
  name: string;
  description?: string;
  reference_url: string;
  always?: boolean;
}
export const getChannelCast = () =>
  fetchApi<{ characters: ChannelCastMember[]; cast_locked: boolean }>("/api/projects/current/cast");
export const lockChannelCast = () =>
  fetchApi<{ status: string }>("/api/projects/current/cast/lock", {
    method: "POST",
    body: JSON.stringify({}),
  });
export const unlockChannelCast = () =>
  fetchApi<{ status: string }>("/api/projects/current/cast/lock", { method: "DELETE" });
export const generateChannelCastMember = (name: string, description: string, always = true) =>
  fetchApi<{ status: string; characters: ChannelCastMember[] }>(
    "/api/projects/current/cast/generate",
    { method: "POST", body: JSON.stringify({ name, description, always }) }
  );
export const updateChannelCastMember = (name: string, patch: { always?: boolean; new_name?: string }) =>
  fetchApi<{ status: string; characters: ChannelCastMember[] }>(
    `/api/projects/current/cast/${encodeURIComponent(name)}`,
    { method: "PATCH", body: JSON.stringify(patch) }
  );
export const deleteChannelCastMember = (name: string) =>
  fetchApi<{ status: string; characters: ChannelCastMember[] }>(
    `/api/projects/current/cast/${encodeURIComponent(name)}`,
    { method: "DELETE" }
  );

// --- House script format (one template per channel) ---
export interface ScriptTemplate {
  id: string;
  name: string;
  structure: string;
  example_excerpt?: string | null;
  is_default: boolean;
  created_at: string;
}
export const getScriptTemplates = () =>
  fetchApi<{ templates: ScriptTemplate[] }>("/api/script-templates");
export const deleteScriptTemplate = (id: string) =>
  fetchApi<{ status: string }>(`/api/script-templates/${id}`, { method: "DELETE" });

export const launchQueueItem = (id: string) =>
  fetchApi<{ status: string; queue_id: string; video_id: string; video_title: string }>(
    `/api/queue/${id}/launch`,
    { method: "POST" }
  );

// Videos
export const getVideos = (status?: string) =>
  fetchApi<VideoSummary[]>(`/api/videos${status ? `?status=${status}` : ""}`);

export const getVideo = (id: string) => fetchApi<VideoDetail>(`/api/videos/${id}`);

export const rewriteSceneText = (videoId: string, scene: number) =>
  fetchApi<{ scene: number; text: string; word_count: number }>(
    `/api/videos/${videoId}/scenes/${scene}/rewrite`,
    { method: "POST" },
  );

export const getDefaultVideoMotionPrompt = () =>
  fetchApi<{ prompt: string }>("/api/videos/defaults/video-motion-prompt");

export const getDefaultScriptPrompt = () =>
  fetchApi<{ prompt: string }>("/api/videos/defaults/script-prompt");

export const getDefaultThumbnailPrompt = () =>
  fetchApi<{ prompt: string }>("/api/videos/defaults/thumbnail-prompt");

export const getDefaultSoundCurationPrompt = () =>
  fetchApi<{ prompt: string }>("/api/videos/defaults/sound-curation-prompt");

export const getDefaultSoundGenerationPrompt = () =>
  fetchApi<{ prompt: string }>("/api/videos/defaults/sound-generation-prompt");

export const getDefaultResearchPrompt = () =>
  fetchApi<{ prompt: string }>("/api/videos/defaults/research-prompt");

// System Prompts (tenant-level defaults)
export interface SystemPromptItem {
  key: string;
  label: string;
  description: string;
  prompt: string;
  is_custom: boolean;
}

export const getSystemPrompts = () =>
  fetchApi<SystemPromptItem[]>("/api/system-prompts");

export const updateSystemPrompt = (key: string, promptText: string) =>
  fetchApi<{ status: string; key: string }>(`/api/system-prompts/${key}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt_text: promptText }),
  });

export const resetSystemPrompt = (key: string) =>
  fetchApi<{ status: string; key: string; prompt: string }>(`/api/system-prompts/${key}`, {
    method: "DELETE",
  });

export const createVideo = (data: {
  title: string;
  source_url?: string;
  framework_angle?: string;
  video_length_minutes?: number;
  writer_guidance?: string;
  accent_color?: string;
  aspect_ratio?: "16:9" | "9:16";
  video_resolution?: "480p" | "720p";
  skip_research?: boolean;
  skip_voice?: boolean;
  // Which pipeline stages to run (research, script, voice, images, sound,
  // video, thumbnail, render, upload). Omit for the full pipeline.
  pipeline_stages?: string[];
  // Per-video LOOK the generator front-loads (from a preset or a custom
  // description). Omit to let the clone or the channel default decide.
  image_style_override?: string;
  // Save the chosen look as the channel's active visual identity.
  lock_in_identity?: boolean;
  // Human-readable label for the chosen look (e.g. "Pixar 3D", "Custom").
  visual_style_label?: string;
  // Optional YouTube link to copy the style of (onto the creator's own topic,
  // scoped to the switched-on stages).
  reference_url?: string;
  // Optional catalog pick from the 5 rich Python visual-profile engines
  // (checklist §2.1, C20/C21) — a style_presets.id, e.g. "holographic_hud".
  // A DIFFERENT axis from image_style_override above: this picks the
  // structural image-generation ENGINE, that picks a free-text aesthetic
  // OVERLAY on top of it. Either, both, or neither may be set.
  style_preset_id?: string;
  // Optional editorial-voice engine pick (checklist §2.3, C24) — a
  // shared.profiles.script profile id, e.g. "power_doctrine_v2". Omit for
  // the neutral default; opt-in only.
  script_profile?: string;
}) =>
  fetchApi<VideoSummary>("/api/videos", {
    method: "POST",
    body: JSON.stringify(data),
  });

export interface ModelVideoResponse {
  video_id: string;
  status: string;
  message?: string | null;
}

export const modelVideo = (videoUrl: string) =>
  fetchApi<ModelVideoResponse>("/api/model-video", {
    method: "POST",
    body: JSON.stringify({ video_url: videoUrl }),
  });

export const retryModelVideo = (videoId: string) =>
  fetchApi<ModelVideoResponse>(`/api/model-video/${videoId}/retry`, {
    method: "POST",
  });

export const advanceVideo = (id: string, to?: string) =>
  fetchApi<{ status: string }>(`/api/videos/${id}/advance${to ? `?to=${encodeURIComponent(to)}` : ""}`, { method: "PATCH" });

export const updateVideo = (id: string, data: Record<string, unknown>) =>
  fetchApi<{ status: string }>(`/api/videos/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const rejectVideo = (id: string, reason?: string) =>
  fetchApi<{ status: string }>(`/api/videos/${id}/reject`, {
    method: "PATCH",
    body: JSON.stringify({ reason }),
  });

export const generateVideoSeo = (id: string) =>
  fetchApi<{ description: string; tags: string[]; hashtags: string[]; channel?: string }>(
    `/api/videos/${id}/generate-seo`, { method: "POST" });

export const saveVideoSeo = (
  id: string,
  data: { title?: string; description?: string; tags?: string[] | string },
) =>
  fetchApi<{ status: string }>(`/api/videos/${id}/seo`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const getVideoAssets = (id: string) => fetchApi<Asset[]>(`/api/videos/${id}/assets`);

export const getImageVariants = (videoId: string, scene: number, index: number) =>
  fetchApi<ImageVariant[]>(
    `/api/videos/${videoId}/assets/variants?scene=${scene}&index=${index}`
  );

export const getVideoScript = (id: string) => fetchApi<ScriptScene[]>(`/api/videos/${id}/script`);

export const getAudioToken = (videoId: string) =>
  fetchApi<{ token: string }>(`/api/videos/${videoId}/audio-token`, { method: "POST" });

// Script <-> Google Drive sync
export interface DriveScriptStatus {
  connected: boolean;
  doc_id: string | null;
  doc_url: string | null;
  synced_at: string | null;
  drive_modified_at: string | null;
  drive_newer: boolean;
}
export interface DrivePushResult {
  doc_id: string;
  doc_url: string;
  status: string;
}
export interface DrivePullResult {
  changed: boolean;
  scenes_changed: number[];
  conflict?: boolean;
  message?: string;
}
export const getDriveScriptStatus = (videoId: string) =>
  fetchApi<DriveScriptStatus>(`/api/videos/${videoId}/script/drive-status`);

export const pushScriptToDrive = (videoId: string) =>
  fetchApi<DrivePushResult>(`/api/videos/${videoId}/script/push-to-drive`, { method: "POST" });

export const syncScriptFromDrive = (videoId: string, force = false) =>
  fetchApi<DrivePullResult>(
    `/api/videos/${videoId}/script/sync-from-drive${force ? "?force=true" : ""}`,
    { method: "POST" }
  );

// Assets
export const approveAsset = (id: string) =>
  fetchApi<{ status: string }>(`/api/assets/${id}/approve`, { method: "PATCH" });

export const rejectAsset = (id: string) =>
  fetchApi<{ status: string }>(`/api/assets/${id}/reject`, { method: "PATCH" });

export const updateVideoPrompt = (id: string, video_prompt: string) =>
  fetchApi<{ status: string }>(`/api/assets/${id}/video-prompt`, {
    method: "PATCH",
    body: JSON.stringify({ video_prompt }),
  });

export const updateImagePrompt = (id: string, image_prompt: string) =>
  fetchApi<{ status: string }>(`/api/assets/${id}/image-prompt`, {
    method: "PATCH",
    body: JSON.stringify({ image_prompt }),
  });

/** Set (or clear, with `null`) this scene's manual clip-model override — the
 * C14 badge's override sheet. Wins over the automatic routed_model at both
 * quote time and generation time (shared.model_router.resolve_clip_model). */
export const updateAssetModelOverride = (id: string, model_override: string | null) =>
  fetchApi<{ status: string; model_override: string | null }>(`/api/assets/${id}/model-override`, {
    method: "PATCH",
    body: JSON.stringify({ model_override }),
  });

export const batchApproveAssets = (assetIds: string[], status: "approved" | "rejected") =>
  fetchApi<{ updated: number }>("/api/assets/batch-approve", {
    method: "POST",
    body: JSON.stringify({ asset_ids: assetIds, status }),
  });

// Review
export const getPendingReview = () => fetchApi<PendingReview>("/api/review/pending");

export const approveStoryboard = (scriptId: string) =>
  fetchApi<{ status: string; script_id: string }>(`/api/review/storyboard/${scriptId}/approve`, {
    method: "POST",
  });

export const rejectStoryboard = (scriptId: string, reason?: string) =>
  fetchApi<{ status: string; script_id: string }>(`/api/review/storyboard/${scriptId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const bulkApproveStoryboards = (scriptIds: string[]) =>
  fetchApi<{ status: string; approved_count: number; script_ids: string[] }>(
    "/api/review/storyboard/approve-all",
    { method: "POST", body: JSON.stringify({ script_ids: scriptIds }) }
  );

export const deleteVideo = (id: string) =>
  fetchApi<{ status: string; video_id: string }>(`/api/videos/${id}`, { method: "DELETE" });

export const generateVideoPrompts = (videoId: string) =>
  fetchApi<PipelineResponse>(`/api/pipeline/generate-video-prompts/${videoId}`, { method: "POST" });

// User Preferences
export const getUserPreferences = () =>
  fetchApi<Record<string, unknown>>("/api/user/preferences");

export const setUserPreference = (key: string, value: unknown) =>
  fetchApi<{ status: string; key: string }>(`/api/user/preferences/${key}`, {
    method: "PUT",
    body: JSON.stringify({ value }),
  });

// Activity
export const getActivity = (status?: string) =>
  fetchApi<ActivityEntry[]>(`/api/activity${status ? `?status=${status}` : ""}`);

export const getActivityStats = () => fetchApi<ActivityStats>("/api/activity/stats");

// Settings - API Key Management
export const getApiKeys = () => fetchApi<ApiKeyList>("/api/settings/keys");

export const getApiKeyStatus = (name: string) =>
  fetchApi<ApiKeyStatus>(`/api/settings/keys/${name}`);

export const setApiKey = (name: string, value: string) =>
  fetchApi<{ status: string; message: string }>(`/api/settings/keys/${name}`, {
    method: "POST",
    body: JSON.stringify({ value }),
  });

export const deleteApiKey = (name: string) =>
  fetchApi<{ status: string; message: string }>(`/api/settings/keys/${name}`, {
    method: "DELETE",
  });

export const testApiKey = (name: string) =>
  fetchApi<TestKeyResponse>(`/api/settings/keys/${name}/test`, { method: "POST" });

export const revealApiKey = (name: string) =>
  fetchApi<{ value: string }>(`/api/settings/keys/${name}/reveal`, { method: "POST" });

export const validateAllApiKeys = () =>
  fetchApi<{ results: { key: string; success: boolean; message: string }[] }>("/api/settings/keys/validate", { method: "POST" });

// Agent access tokens (checklist P2.4a/c, chunks C26/C28) — mint/list/revoke
// for connecting an external MCP client (Claude, etc). Routes are
// session-authed (routes/agent_access.py); minting an agent token requires a
// real logged-in session, never an agent token itself.
export interface AgentToken {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

// The plaintext `token` field is returned ONLY by createAgentToken, and only
// on this one response — routes/agent_access.py never stores or re-serves it
// (only its hash). Never persist this value beyond in-memory component state.
export interface AgentTokenCreated {
  id: string;
  name: string;
  token: string;
  created_at: string;
}

export const getAgentTokens = () =>
  fetchApi<AgentToken[]>("/api/agent-tokens");

export const createAgentToken = (name: string) =>
  fetchApi<AgentTokenCreated>("/api/agent-tokens", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const revokeAgentToken = (id: string) =>
  fetchApi<{ revoked: boolean }>(`/api/agent-tokens/${id}`, { method: "DELETE" });

// Channel Profile (legacy — redirects to projects)
export const getChannelProfile = () =>
  fetchApi<ChannelProfile>("/api/channel-profile");

export const updateChannelProfile = (data: ChannelProfileUpdate) =>
  fetchApi<ChannelProfile>("/api/channel-profile", {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const getIntegrationStatuses = () =>
  fetchApi<IntegrationStatusItem[]>("/api/channel-profile/integrations");

// User Profile
export const getProfile = () =>
  fetchApi<UserProfile>("/api/profile");

export const updateProfile = (data: UserProfileUpdate) =>
  fetchApi<UserProfile>("/api/profile", {
    method: "PUT",
    body: JSON.stringify(data),
  });

// Projects (new — replaces channel_profiles)
export const getCurrentProject = () =>
  fetchApi<Project>("/api/projects/current");

export const updateProject = (data: ProjectUpdate) =>
  fetchApi<Project>("/api/projects/current", {
    method: "PUT",
    body: JSON.stringify(data),
  });

// Visual Styles
export const getVisualStyles = () =>
  fetchApi<VisualStyle[]>("/api/visual-styles");

export const createVisualStyle = (data: CreateVisualStyleRequest) =>
  fetchApi<VisualStyle>("/api/visual-styles", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const activateVisualStyle = (styleId: string) =>
  fetchApi<VisualStyle[]>(`/api/visual-styles/${styleId}/activate`, {
    method: "PUT",
  });

export const deleteVisualStyle = (styleId: string) =>
  fetchApi<{ status: string }>(`/api/visual-styles/${styleId}`, {
    method: "DELETE",
  });

export const createStyleCharacter = (styleId: string, data: { name: string; image_url: string }) =>
  fetchApi<StyleCharacter>(`/api/visual-styles/${styleId}/characters`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const deleteStyleCharacter = (styleId: string, characterId: string) =>
  fetchApi<{ status: string }>(`/api/visual-styles/${styleId}/characters/${characterId}`, {
    method: "DELETE",
  });

export const generateCharacterImage = (prompt: string, styleId: string) =>
  fetchApi<{ status: string; image_url: string; prompt: string }>(
    "/api/visual-styles/characters/generate",
    { method: "POST", body: JSON.stringify({ prompt, style_id: styleId }) }
  );

export const analyzeStyleImage = (imageData: string) =>
  fetchApi<{ status: string; profile: Record<string, unknown> }>(
    "/api/visual-styles/analyze-image",
    { method: "POST", body: JSON.stringify({ image_data: imageData }) }
  );

// Pipeline - Stage Triggers
export const createIdea = (topic: string, source?: string) =>
  fetchApi<PipelineResponse>("/api/pipeline/create-idea", {
    method: "POST",
    body: JSON.stringify({ topic, source: source || "storyengine" }),
  });

export const runPipelineStage = (videoId: string, stage: string, params?: Record<string, string | number>) => {
  const queryString = params
    ? "?" + Object.entries(params).map(([k, v]) => `${k}=${v}`).join("&")
    : "";
  return fetchApi<PipelineResponse>(`/api/pipeline/${stage}/${videoId}${queryString}`, { method: "POST" });
};

export type MachineScriptPreview = {
  machine: string;
  scene: number;
  paragraph: string;
  word_count: number;
  passed: boolean;
  warnings: string[];
  onscreen_label?: string;
  research_source?: string;
  story_plan?: Record<string, unknown>;
  quality_audit?: {
    passed?: boolean;
    summary?: string;
    checks?: Array<{
      name?: string;
      label?: string;
      passed?: boolean;
      detail?: string;
      advisory?: boolean;
    }>;
  };
  claim_bundle?: {
    editorial_thesis?: string;
    formula_sentences?: string[];
    paragraph?: string;
    onscreen_label?: string;
    claim_map?: Array<{
      span?: string;
      slot?: string;
      used_evidence_ids?: string[];
      evidence_ids?: string[];
    }>;
  };
};

export type MachineScriptPreviewReadiness = {
  status: string;
  ready: boolean;
  video_id: string;
  machine: string;
  scene?: number;
  summary?: string;
  warnings?: string[];
  next_action?: string;
  research_payload?: Record<string, unknown>;
};

export const checkMachineScriptPreviewReadiness = (videoId: string, machine: string) =>
  fetchApi<MachineScriptPreviewReadiness>(
    `/api/pipeline/machine-script-preview-readiness/${videoId}`,
    { method: "POST", body: JSON.stringify({ machine }) },
  );

export const runMachineScriptPreview = (videoId: string, machine: string, confirmedPaidRun: true) =>
  fetchApi<{ status: string; preview: MachineScriptPreview; research_payload?: Record<string, unknown> }>(
    `/api/pipeline/machine-script-preview/${videoId}`,
    { method: "POST", body: JSON.stringify({ machine, confirmed_paid_run: confirmedPaidRun }) },
  );

export type OneMachineResearchResult = {
  status: string;
  video_id: string;
  machine: string;
  research_card?: Record<string, unknown>;
  research_payload?: Record<string, unknown>;
  summary?: string;
  warnings?: string[];
  error?: string;
  next_action?: string;
};

export const runOneMachineResearch = (videoId: string, machine: string, confirmedPaidRun: true) =>
  fetchApi<OneMachineResearchResult>(
    `/api/pipeline/machine-research-one/${videoId}`,
    { method: "POST", body: JSON.stringify({ machine, confirmed_paid_run: confirmedPaidRun }) },
  );

// --- Roster orchestrator: surgical repair verbs (cheapest first) ---

export type MachineRepairResult = {
  status: string;
  machine: string;
  verb: string;
  passed: boolean;
  warnings: string[];
  actions?: Array<{ verb: string; status?: string; detail?: string; reason?: string; est_cost_usd?: number }>;
  est_spend_usd?: number;
  research_payload?: Record<string, unknown>;
  error?: string;
};

export const runMachineRepair = (
  videoId: string,
  machine: string,
  options: {
    verb?: "auto" | "promote_excerpt" | "rewrite_field" | "targeted_fetch" | "mark_bare";
    excerptId?: string;
    kind?: string;
    field?: string;
    focus?: string;
    confirmedPaidRun?: boolean;
  } = {},
) =>
  fetchApi<MachineRepairResult>(`/api/pipeline/machine-repair/${videoId}`, {
    method: "POST",
    body: JSON.stringify({
      machine,
      verb: options.verb || "auto",
      excerpt_id: options.excerptId,
      kind: options.kind,
      field: options.field,
      focus: options.focus,
      confirmed_paid_run: options.confirmedPaidRun ?? false,
    }),
  });

export const runRosterOrchestrator = (
  videoId: string,
  confirmedPaidRun: true,
  options: { machines?: string[]; budgetUsd?: number; allowFullRerun?: boolean } = {},
) =>
  fetchApi<PipelineResponse>(`/api/pipeline/roster-orchestrate/${videoId}`, {
    method: "POST",
    body: JSON.stringify({
      machines: options.machines,
      budget_usd: options.budgetUsd ?? 5.0,
      allow_full_rerun: options.allowFullRerun ?? true,
      confirmed_paid_run: confirmedPaidRun,
    }),
  });

export type RosterDashboard = {
  status: string;
  video_id: string;
  ready: number;
  total: number;
  est_spend_usd_total: number;
  last_run?: {
    ran_at?: string;
    attempted?: number;
    cleared?: number;
    alerts?: string[];
    budget_breached?: boolean;
  } | null;
  units: Array<{
    machine: string;
    state: "ready" | "needs_repair" | "needs_research";
    warnings: string[];
    suggested_action?: { verb: string; excerpt_id?: string; kind?: string; field?: string; focus?: string; reason?: string } | null;
    preview?: { passed: boolean; word_count?: number } | null;
  }>;
};

export const getRosterDashboard = (videoId: string) =>
  fetchApi<RosterDashboard>(`/api/pipeline/roster-dashboard/${videoId}`);

export const runNextStep = (videoId: string) =>
  fetchApi<PipelineResponse>(`/api/pipeline/run-next/${videoId}`, { method: "POST" });

// The shared action layer (PARITY-PLAN): one source of truth for what can run,
// what it costs, and why something is blocked. Chat's confirm cards and the
// page's buttons/costs both read THIS.
export interface VideoActionInfo {
  verb: string;
  label: string;
  paid: boolean;
  needs: string | null;
  accepts_edit: boolean;
  /** Plain-English reason it can't run yet; null = runnable now */
  blocked: string | null;
  cost: number;
  cost_text: string;
  /** Itemized per-model/tier quote (C18, checklist §1.3) — the SAME shape
   * chat's confirm cards carry (ChatCostBreakdown below). null when there's
   * nothing real to itemize yet (e.g. before pictures exist). */
  breakdown: ChatCostBreakdown | null;
}

export interface VideoActions {
  video_id: string;
  summary: {
    title: string; status: string; length_min: number | null; model: string;
    scenes: number; boards: number; voiced: number; max_scene: number;
    pics: number; clips: number; cast: number; spent: number; validation: string;
  };
  build_target: "pictures" | "finish";
  actions: VideoActionInfo[];
  prices: { clip: Record<string, number>; picture: number };
}

export const getVideoActions = (videoId: string) =>
  fetchApi<VideoActions>(`/api/pipeline/actions/${videoId}`);

// C18 (checklist §1.3 [U]) — the clickable doors for C17's draft_pass/finalize
// verbs (GuidedNextStep's "Draft the whole video" / "Finalize N approved
// scenes" buttons) and C15b's scene-scoped approve, which was chat-only until
// now. All three call the SAME actions.py runner chat already uses.
export const runDraftPass = (videoId: string) =>
  fetchApi<PipelineResponse>(`/api/pipeline/actions/${videoId}/draft-pass`, { method: "POST" });

export const runFinalize = (videoId: string) =>
  fetchApi<PipelineResponse>(`/api/pipeline/actions/${videoId}/finalize`, { method: "POST" });

export const approveScene = (videoId: string, scene: number) =>
  fetchApi<{ scene: number; message: string }>(`/api/pipeline/actions/${videoId}/approve-scene`, {
    method: "POST",
    body: JSON.stringify({ scene }),
  });

// Cost ledger (checklist §0.3d / C10) — the receipts behind videos.total_cost.
// `total_cost` here is the SAME rollup VideoDetail.total_cost carries (both
// read the videos row); `by_stage` and `rows` are the drawer's breakdown.
// No local price table — every dollar figure here came from the server.
export interface LedgerRow {
  stage: string;
  model: string | null;
  units: number;
  unit_cost: number;
  actual_cost: number;
  kie_task_id: string | null;
  created_at: string | null;
}

export interface VideoLedger {
  video_id: string;
  total_cost: number;
  by_stage: Record<string, number>;
  rows: LedgerRow[];
}

export const getVideoLedger = (videoId: string) =>
  fetchApi<VideoLedger>(`/api/videos/${videoId}/ledger`);

export const runBuild = (videoId: string, target: "pictures" | "finish") =>
  fetchApi<PipelineResponse>(`/api/pipeline/build/${videoId}`, {
    method: "POST",
    body: JSON.stringify({ target }),
  });

export const improvePrompt = (
  videoId: string,
  surface: "image" | "motion" | "thumbnail" | "script",
  current: string,
  direction?: string
) =>
  fetchApi<{ prompt: string }>(`/api/pipeline/improve-prompt/${videoId}`, {
    method: "POST",
    body: JSON.stringify({ surface, current, direction: direction || null }),
  });

export const getPipelineStatus = (videoId: string) =>
  fetchApi<PipelineStatus>(`/api/pipeline/status/${videoId}`);

export const cancelPipelineTask = (videoId: string) =>
  fetchApi<{ status: string; message: string }>(`/api/pipeline/cancel/${videoId}`, {
    method: "POST",
  });

export const getPipelineTaskStatus = (videoId: string) =>
  fetchApi<TaskStatus>(`/api/pipeline/task/${videoId}`);

// Video Style Updates
export const updateVideoStyles = (
  videoId: string,
  styles: { visual_style?: string; accent_color?: string; image_model_override?: string; video_model?: string }
) =>
  fetchApi<StyleUpdateResponse>(`/api/videos/${videoId}/styles?${new URLSearchParams(
    Object.entries(styles).filter(([, v]) => v !== undefined) as [string, string][]
  ).toString()}`, { method: "PATCH" });

// Autopilot
export const getAutopilotSummary = () => fetchApi<AutopilotSummary>("/api/autopilot/summary");

export const getAutopilotCandidates = (limit?: number, minVph?: number) =>
  fetchApi<CompetitorCandidate[]>(
    `/api/autopilot/candidates?limit=${limit || 20}&min_vph=${minVph || 50}`
  );

export const getCandidateDetail = (id: string) =>
  fetchApi<CandidateDetail>(`/api/autopilot/candidates/${id}`);

export const getAutopilotLearnings = (category?: string, limit?: number) =>
  fetchApi<Learning[]>(
    `/api/autopilot/learnings?limit=${limit || 20}${category ? `&category=${category}` : ""}`
  );

export const toggleAutopilot = (enabled: boolean) =>
  fetchApi<{ status: string; enabled: boolean }>("/api/autopilot/toggle", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });

export const updateAutopilotConfig = (config: { videos_per_month?: number; videos_per_scrape?: number; weights?: Record<string, number>; thresholds?: Record<string, number> }) =>
  fetchApi<{ status: string; config: AutopilotConfig }>("/api/autopilot/config", {
    method: "POST",
    body: JSON.stringify(config),
  });

export interface BackgroundTaskStatus {
  last_run: string | null;
  is_running: boolean;
  last_error: string | null;
}

export interface AutopilotTasks {
  scrape: BackgroundTaskStatus;
  youtube_sync: BackgroundTaskStatus;
  learning_extraction: BackgroundTaskStatus;
  title_analysis: BackgroundTaskStatus;
}

export const getAutopilotTasks = () => fetchApi<AutopilotTasks>("/api/autopilot/tasks");

export interface ScorecardLesson {
  component: string;
  state: "win" | "weak" | "pending";
  text: string;
}
export interface VideoScorecard {
  video_id: string;
  title: string;
  thumbnail_url?: string | null;
  status: string;
  youtube_url?: string | null;
  views?: number | null;
  ctr?: number | null;
  impressions?: number | null;
  avg_retention?: number | null;
  synced: boolean;
  applied: string[];
  lessons: ScorecardLesson[];
}
export const getAutopilotScorecards = (limit?: number) =>
  fetchApi<VideoScorecard[]>(`/api/autopilot/scorecards?limit=${limit || 12}`);

export const launchCandidate = (candidateId: string) =>
  fetchApi<{ status: string; candidate_id: string; video_id: string; video_title: string; message: string }>(
    `/api/autopilot/launch/${candidateId}`,
    { method: "POST" }
  );

// Pipeline task management
export const clearStaleTask = (videoId: string) =>
  fetchApi<{ status: string }>(`/api/pipeline/task/${videoId}/clear`);

// Pipeline reset
export const resetPipeline = (videoId: string, resetTo: string) =>
  fetchApi<{ status: string; video_id: string; reset_to: string; deleted: { scripts: number; assets: number } }>(
    `/api/pipeline/reset/${videoId}`,
    { method: "POST", body: JSON.stringify({ reset_to: resetTo }) }
  );

// Agent Quality Pipeline
export const getAgentStats = () =>
  fetchApi<AgentStats>("/api/agents/stats");

export const getAgentVideos = () =>
  fetchApi<AgentVideoResult[]>("/api/agents/videos");

export const getAgentResults = (videoId: string) =>
  fetchApi<AgentVideoResult>(`/api/agents/videos/${videoId}`);

export const runAgentPipeline = (videoId: string, tier: string = "standard") =>
  fetchApi<{ status: string; message: string }>(`/api/agents/videos/${videoId}/run`, {
    method: "POST",
    body: JSON.stringify({ quality_tier: tier }),
  });

export const getAgentTaskStatus = (videoId: string) =>
  fetchApi<{ status: string; message: string }>(`/api/agents/videos/${videoId}/task`);

// Suggestion Accept/Reject
export const acceptSuggestion = (videoId: string, fields: string[]) =>
  fetchApi<{ status: string; video_id: string; accepted: string[] }>(
    `/api/videos/${videoId}/accept-suggestion`,
    { method: "POST", body: JSON.stringify({ accept: fields }) }
  );

export const rejectSuggestion = (videoId: string) =>
  fetchApi<{ status: string; video_id: string }>(
    `/api/videos/${videoId}/reject-suggestion`,
    { method: "POST" }
  );

// Channel's current visual style (locked format, else most recent video)
export const getStyleDefault = () =>
  fetchApi<{ preset_id: string | null; source: "locked_format" | "recent_video" | null }>(
    "/api/videos/style-default"
  );

// Discovery Ideas
export const getDiscoveryIdeas = (status?: string, limit?: number) =>
  fetchApi<DiscoveryIdea[]>(
    `/api/discovery/ideas?status=${status || "fresh"}&limit=${limit || 20}`
  );

export const getDiscoveryStatus = () =>
  fetchApi<DiscoveryStatus>("/api/discovery/status");

export const refreshDiscoveryIdeas = () =>
  fetchApi<{ status: string; batch_id: string; message: string }>(
    "/api/discovery/refresh",
    { method: "POST" }
  );

export const launchIdea = (ideaId: string, titleIndex: number, videoLengthMinutes: number = 15) =>
  fetchApi<{ status: string; video_id: string; video_title: string; message: string }>(
    `/api/discovery/ideas/${ideaId}/launch`,
    {
      method: "POST",
      body: JSON.stringify({ title_index: titleIndex, video_length_minutes: videoLengthMinutes }),
    }
  );

export const dismissIdea = (ideaId: string) =>
  fetchApi<{ status: string; idea_id: string }>(
    `/api/discovery/ideas/${ideaId}/dismiss`,
    { method: "POST" }
  );

// Learning Extraction
export interface LearningRecord {
  id: string;
  category: string;
  pattern: string;
  confidence: number;
  sample_size: number;
  avg_ctr: number | null;
  avg_retention: number | null;
  source_videos: string | null;
  active: boolean;
}

export interface ExtractionResult {
  videos_analyzed: number;
  patterns_extracted: number;
  patterns_new: number;
  patterns_updated: number;
}

export const getLearnings = (category?: string, activeOnly: boolean = true) =>
  fetchApi<LearningRecord[]>(
    `/api/learnings?active_only=${activeOnly}${category ? `&category=${category}` : ""}`
  );

export const extractLearnings = () =>
  fetchApi<ExtractionResult>("/api/learnings/extract", { method: "POST" });

export const extractLearningsForVideo = (videoId: string) =>
  fetchApi<ExtractionResult>(`/api/learnings/extract/${videoId}`, { method: "POST" });

export const analyzeCompetitorTitles = () =>
  fetchApi<{ status: string; patterns_found: number; insights_saved: number; videos_analyzed: number }>(
    "/api/learnings/analyze-titles",
    { method: "POST" }
  );

export const analyzeTranscripts = () =>
  fetchApi<{ status: string; patterns_found: number; insights_saved: number; videos_analyzed: number }>(
    "/api/learnings/analyze-transcripts",
    { method: "POST" }
  );

export const toggleLearning = (learningId: string) =>
  fetchApi<{ id: string; active: boolean }>(`/api/learnings/${learningId}/toggle`, {
    method: "PATCH",
  });

// Niche (competitor/example channels)
export const getNicheChannels = () =>
  fetchApi<CompetitorChannel[]>("/api/niche/channels");

export const addNicheChannel = (channel_name: string, channel_url: string) =>
  fetchApi<{ status: string }>("/api/niche/channels", {
    method: "POST",
    body: JSON.stringify({ channel_name, channel_url }),
  });

export const removeNicheChannel = (channelId: string) =>
  fetchApi<{ status: string }>(`/api/niche/channels/${channelId}`, {
    method: "DELETE",
  });

export interface ScrapeStatus {
  is_running: boolean;
  videos_found: number;
  videos_saved: number;
  channels_total: number;
  channels_done: number;
  current_channel: string | null;
  channel_progress: Record<string, number>;
  error: string | null;
  last_run: string | null;
}

export const scrapeCompetitorChannels = () =>
  fetchApi<{ status: string; message: string }>("/api/niche/scrape", {
    method: "POST",
  });

export const getScrapeStatus = () =>
  fetchApi<ScrapeStatus>("/api/niche/scrape/status");

export const cancelScrape = () =>
  fetchApi<{ status: string; message: string }>("/api/niche/scrape/cancel", {
    method: "POST",
  });

// YouTube Metrics Sync
export interface YouTubeSyncError {
  video_id: string;
  error_type: string;
  message: string;
}

export interface YouTubeSyncStatus {
  is_running: boolean;
  videos_synced: number;
  videos_total: number;
  videos_failed: number;
  videos_retried: number;
  matched_internal?: number;
  channel_synced?: boolean;
  errors: YouTubeSyncError[];
  error: string | null;
  error_type: string | null;
  last_run: string | null;
}

export const syncYouTubeMetrics = () =>
  fetchApi<{ status: string; message: string }>("/api/youtube/sync", {
    method: "POST",
  });

export const getYouTubeSyncStatus = () =>
  fetchApi<YouTubeSyncStatus>("/api/youtube/sync/status");

// Billing
export interface Subscription {
  plan: string;
  stripe_plan: string | null;
  stripe_status: string | null;
  has_subscription: boolean;
  trial_active: boolean;
  trial_days_remaining: number;
}

export const getSubscription = () =>
  fetchApi<Subscription>("/api/billing/subscription");

export const createCheckout = (plan: string, successUrl?: string, cancelUrl?: string) =>
  fetchApi<{ checkout_url: string; session_id: string }>("/api/billing/create-checkout", {
    method: "POST",
    body: JSON.stringify({ plan, success_url: successUrl, cancel_url: cancelUrl }),
  });

export const createBillingPortal = (returnUrl?: string) =>
  fetchApi<{ portal_url: string }>("/api/billing/portal", {
    method: "POST",
    body: JSON.stringify({ return_url: returnUrl }),
  });

// Usage tracking
export interface UsageLimits {
  plan: string;
  limits: {
    videos_per_month: number;
    render_minutes: number;
    concurrent_jobs: number;
  };
  usage: {
    videos_created: number;
    api_calls: number;
    render_minutes: number;
    storage_bytes: number;
  };
  period_start: string;
}

export const getUsage = () =>
  fetchApi<UsageLimits>("/api/billing/usage");

// Analytics — real channel data from the YouTube sync
export interface AnalyticsChannel {
  channel_id: string | null;
  name: string | null;
  thumbnail: string | null;
  subscribers: number;
  total_views: number;
  video_count: number;
  last_synced: string | null;
}

export interface AnalyticsOverview {
  connected: boolean;
  channel: AnalyticsChannel | null;
  published_videos: number;
  total_views: number;
  avg_ctr: number | null;
  avg_view_duration_seconds: number | null;
  avg_retention: number | null;
  views_28d: number;
  watch_time_hours_28d: number | null;
  subscribers_gained_28d: number;
  avg_ctr_28d: number | null;
}

export interface AnalyticsTimelinePoint {
  date: string;
  views: number;
  impressions: number | null;
  ctr: number | null;
  watch_time_minutes: number | null;
  subscribers_gained: number | null;
}

export interface ChannelVideo {
  id: string;
  youtube_video_id: string;
  internal_video_id: string | null;
  title: string | null;
  thumbnail_url: string | null;
  published_at: string | null;
  duration_seconds: number | null;
  privacy_status: string | null;
  views: number;
  likes: number;
  comments: number;
  impressions: number | null;
  ctr: number | null;
  avg_view_duration_seconds: number | null;
  avg_view_percentage: number | null;
  watch_url: string;
  last_synced_at: string | null;
}

export interface FrameworkPerformance {
  framework: string;
  video_count: number;
  avg_ctr: number | null;
  avg_retention: number | null;
  total_views: number;
}

export const getAnalyticsOverview = () =>
  fetchApi<AnalyticsOverview>("/api/analytics/overview");

export const getAnalyticsTimeline = (days: number = 28) =>
  fetchApi<AnalyticsTimelinePoint[]>(`/api/analytics/timeline?days=${days}`);

export const getAnalyticsVideos = (limit: number = 50) =>
  fetchApi<ChannelVideo[]>(`/api/analytics/videos?limit=${limit}`);

export const getFrameworkPerformance = () =>
  fetchApi<FrameworkPerformance[]>("/api/analytics/framework-performance");

// Style/model performance — checklist §3.1 [U] / C31 (data layer shipped C30).
// Field names copied verbatim from backend/models.py's StyleChoiceAggregate /
// StylePerformanceResponse — don't retype.
export interface StyleChoiceAggregate {
  dimension: string;
  choice: string;
  video_count: number;
  synced_count: number;
  avg_ctr: number | null;
  avg_retention: number | null;
  total_views: number;
  total_spend: number;
}

export interface StylePerformanceResponse {
  by_style_preset: StyleChoiceAggregate[];
  by_render_style: StyleChoiceAggregate[];
  by_script_profile: StyleChoiceAggregate[];
  by_clip_model: StyleChoiceAggregate[];
}

export const getStylePerformance = () =>
  fetchApi<StylePerformanceResponse>("/api/analytics/by-style");

// Competitor Benchmark
export interface CompetitorBenchmark {
  channel_avg_ctr: number | null;
  channel_avg_retention: number | null;
  channel_total_views: number;
  channel_videos_with_ctr: number;
  competitors: {
    channel: string;
    video_count: number;
    avg_vph: number | null;
    total_views: number;
  }[];
}

export const getCompetitorBenchmark = () =>
  fetchApi<CompetitorBenchmark>("/api/analytics/competitor-benchmark");

// Scene Editing
export const updateSceneText = (videoId: string, scene: number, text: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/scenes/${scene}/text`, {
    method: "PATCH",
    body: JSON.stringify({ text }),
  });

export const updateSceneTone = (videoId: string, scene: number, tone: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/scenes/${scene}/tone`, {
    method: "PATCH",
    body: JSON.stringify({ tone }),
  });

export const getSceneSegments = (videoId: string, scene: number) =>
  fetchApi<SegmentResponse>(`/api/videos/${videoId}/scenes/${scene}/segments`);

export interface SplitResult {
  status: string;
  video_id: string;
  total_segments: number;
  scenes: { scene: number; segments: number }[];
}

export const runSplit = (videoId: string) =>
  fetchApi<SplitResult>(`/api/pipeline/split/${videoId}`, { method: "POST" });

export const updateSceneSegments = (
  videoId: string, scene: number,
  segments: { image_index: number; sentence_text: string }[]
) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/scenes/${scene}/segments`, {
    method: "PUT",
    body: JSON.stringify({ segments }),
  });

export const updateStoryboardMode = (videoId: string, enabled: boolean) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/storyboard-mode`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });

export const clearSceneStoryboard = (videoId: string, scene: number) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/storyboards/${scene}`, {
    method: "DELETE",
  });

/** Remove ONE storyboard grid image — prompts and other boards stay. */
export const clearStoryboardSlot = (videoId: string, scene: number, beat: number) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/storyboards/${scene}/${beat}`, {
    method: "DELETE",
  });

export const clearAllStoryboards = (videoId: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/storyboards`, {
    method: "DELETE",
  });

export const clearAllExtractedPanels = (videoId: string) =>
  fetchApi<{ status: string; cleared_count: number }>(`/api/videos/${videoId}/extracted-panels`, {
    method: "DELETE",
  });

export const clearExtractedPanel = (videoId: string, assetId: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/extracted-panels/${assetId}`, {
    method: "DELETE",
  });

// --- Video characters (per-video character design) ---

export interface VideoCharacter {
  id: string;
  name: string;
  description?: string | null;
  reference_url?: string | null;
  status: "draft" | "approved";
  source: "generated" | "uploaded" | "project";
  sort: number;
}

export const lockStory = (videoId: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/lock-story`, { method: "POST" });

export const unlockStory = (videoId: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/unlock-story`, { method: "POST" });

export const getVideoCharacters = (videoId: string) =>
  fetchApi<{ characters: VideoCharacter[]; approved_at: string | null }>(
    `/api/videos/${videoId}/characters`
  );

export const designCharacters = (videoId: string) =>
  fetchApi<{ status: string; message: string }>(`/api/videos/${videoId}/characters/generate`, {
    method: "POST",
  });

export const regenerateCharacter = (videoId: string, charId: string) =>
  fetchApi<{ status: string; message: string }>(
    `/api/videos/${videoId}/characters/${charId}/regenerate`,
    { method: "POST" }
  );

export const updateCharacter = (videoId: string, charId: string, data: { name?: string; description?: string }) =>
  fetchApi<VideoCharacter>(`/api/videos/${videoId}/characters/${charId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteCharacter = (videoId: string, charId: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/characters/${charId}`, {
    method: "DELETE",
  });

export const approveCast = (videoId: string) =>
  fetchApi<{ status: string; message?: string; count?: number }>(`/api/videos/${videoId}/characters/approve`, {
    method: "POST",
  });

export const saveCastToProject = (videoId: string) =>
  fetchApi<{ status: string; count: number }>(`/api/videos/${videoId}/characters/save-to-project`, {
    method: "POST",
  });

export interface ProjectCastMember {
  name: string;
  description: string;
  reference_url: string;
  already_in_video: boolean;
}

export const getProjectCast = (videoId: string) =>
  fetchApi<{ characters: ProjectCastMember[]; has_project: boolean }>(
    `/api/videos/${videoId}/characters/project-cast`
  );

export const importCastFromProject = (videoId: string, names?: string[]) =>
  fetchApi<{ status: string; count: number }>(`/api/videos/${videoId}/characters/import-from-project`, {
    method: "POST",
    body: JSON.stringify({ names: names ?? null }),
  });

export const uploadCharacterImage = async (
  videoId: string,
  charId: string,
  file: File,
): Promise<{ status: string; reference_url: string }> => {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_URL}/api/videos/${videoId}/characters/${charId}/upload`, {
    method: "POST",
    headers: uploadHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
};

// --- Video environments (per-video location/environment locking) ---

export interface VideoEnvironment {
  id: string;
  name: string;
  description?: string | null;
  reference_url?: string | null;
  status: "draft" | "approved";
  source: "generated" | "uploaded" | "project";
  sort: number;
}

export const getEnvironments = (videoId: string) =>
  fetchApi<{ environments: VideoEnvironment[]; approved_at: string | null }>(
    `/api/videos/${videoId}/environments`
  );

export const designEnvironments = (videoId: string) =>
  fetchApi<{ status: string; message: string }>(`/api/videos/${videoId}/environments/design`, {
    method: "POST",
  });

export const regenerateEnvironment = (videoId: string, envId: string) =>
  fetchApi<{ status: string; message: string }>(
    `/api/videos/${videoId}/environments/${envId}/regenerate`,
    { method: "POST" }
  );

export const updateEnvironment = (videoId: string, envId: string, data: { name?: string; description?: string }) =>
  fetchApi<VideoEnvironment>(`/api/videos/${videoId}/environments/${envId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteEnvironment = (videoId: string, envId: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/environments/${envId}`, {
    method: "DELETE",
  });

export const approveEnvironments = (videoId: string) =>
  fetchApi<{ status: string; message?: string; count?: number }>(`/api/videos/${videoId}/environments/approve`, {
    method: "POST",
  });

export const skipEnvironments = (videoId: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/environments/skip`, {
    method: "POST",
  });

export const uploadEnvironmentImage = async (
  videoId: string,
  envId: string,
  file: File,
): Promise<{ status: string; reference_url: string }> => {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_URL}/api/videos/${videoId}/environments/${envId}/upload`, {
    method: "POST",
    headers: uploadHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
};

export const uploadStoryboardGrid = async (
  videoId: string,
  scene: number,
  beat: number,
  file: File,
): Promise<{ status: string; url: string; all_grids_complete: boolean }> => {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const formData = new FormData();
  formData.append("scene", String(scene));
  formData.append("beat", String(beat));
  formData.append("file", file);
  const res = await fetch(`${API_URL}/api/videos/${videoId}/storyboard-grid-upload`, {
    method: "POST",
    headers: uploadHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
};

// Targeted regeneration (single scene/image, bypasses status gate)
export const runVoiceForScene = (videoId: string, scene: number) =>
  fetchApi<PipelineResponse>(`/api/pipeline/voice/${videoId}?scene=${scene}`, {
    method: "POST",
  });


// Types
export interface DashboardSummary {
  active_bots: number;
  pending_review: number;
  pipeline_distribution: Record<string, number>;
  cost_today: number;
  cost_week: number[];
  errors: number;
  latest_video: VideoSummary | null;
  total_videos: number;
  avg_ctr: number | null;
  total_views: number;
  videos_this_week: number;
  recent_videos: VideoSummary[];
}

export interface VideoSummary {
  id: string;
  video_title: string | null;
  status: string | null;
  thumbnail_url: string | null;
  accent_color: string;
  total_cost: number;
  views: number;
  ctr: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface VideoDetail extends VideoSummary {
  characters_approved_at?: string | null;
  story_locked_at?: string | null;
  dialogue_audio?: string | null;
  // null = normal (clip stitch / narrator). 'static_docu' = static-image
  // documentary: images held over the narration, no animate stage.
  render_mode?: string | null;
  // Channel-style routing guardrail (C13b/C14): 'animated' | 'realistic' |
  // null (undeclared — "Auto", the router's money-safe default). Drives
  // the Scenes workspace's "Channel look" control.
  render_style?: string | null;
  aspect_ratio?: string | null;
  // Per-video pipeline plan: enabled stages (null = full pipeline). The video
  // page hides the tabs for stages that aren't in this list.
  pipeline_stages?: string[] | null;
  skip_voice?: boolean;
  // True when the default autobuild chain skipped the optional research
  // stage (script wrote straight from the topic). Drives the "Research:
  // skipped — Run research" transparency chip. Clears once research runs.
  research_skipped?: boolean;
  airtable_record_id: string | null;
  headline: string | null;
  source: string | null;
  source_views: number | null;
  source_channel: string | null;
  source_urls: string | null;
  framework_angle: string | null;
  thematic_framework: string | null;
  hook_script: string | null;
  past_context: string | null;
  present_parallel: string | null;
  future_prediction: string | null;
  writer_guidance: string | null;
  thesis: string | null;
  executive_hook: string | null;
  research_payload: Record<string, unknown> | null;
  original_dna: Record<string, unknown> | null;
  script: string | null;
  script_validation: string | null;
  story_bible: string | null;
  thumbnail_prompt: string | null;
  thumbnail_style_override: string | null;
  visual_style: string | null;
  image_style_override: string | null;
  image_model_override: string | null;
  video_model: string | null;
  video_length_minutes: number | null;
  youtube_url: string | null;
  final_video_url: string | null;
  avg_retention: number | null;
  impressions: number;
  likes: number;
  comments: number;
  performance_verdict: string | null;
  // Performance snapshots
  avg_view_duration_seconds: number | null;
  views_24h: number | null;
  views_48h: number | null;
  views_7d: number | null;
  views_30d: number | null;
  ctr_12h: number | null;
  ctr_24h: number | null;
  ctr_48h: number | null;
  retention_48h: number | null;
  // Post-mortem
  post_mortem_48h: string | null;
  post_mortem_7d: string | null;
  // total_cost already defined in VideoSummary
  // Agent quality
  agent_paper_trail: Record<string, unknown> | null;
  agent_hook_score: number | null;
  agent_body_score: number | null;
  agent_tier: string | null;
  agent_cost: number | null;
  // Suggestions
  suggested_script: string | null;
  suggested_title: string | null;
  suggested_thumbnail_prompt: string | null;
  suggested_thumbnail_urls: { url: string; approach: string }[] | null;
  // Editable system prompts
  video_motion_system_prompt: string | null;
  script_system_prompt: string | null;
  thumbnail_system_prompt: string | null;
  sound_system_prompt: string | null;
  suggestion_source: string | null;
  suggestion_scores: { hook?: number; body?: number; reasoning?: string } | null;
  suggestion_status: string | null;
}

export interface Asset {
  id: string;
  video_id: string;
  scene: number | null;
  image_index: number | null;
  image_url: string | null;
  image_prompt: string | null;
  status: string | null;
  shot_type: string | null;
  hero_shot: boolean;
  sentence_text: string | null;
  video_clip_url: string | null;
  video_prompt: string | null;
  sound_prompt: string | null;
  sound_effect_url: string | null;
  sound_volume: number | null;
  duration_seconds?: number | null;
  /** Bad-crop validation flags from extraction: 'label_leak', 'gutter_split' */
  extraction_flags?: string[] | null;
  /** Which image model ACTUALLY drew this picture ('gpt-image-2' | 'nano-banana-2' |
   * 'z-image'), independent of the video's current image_model_override — a mismatch
   * means the override wasn't honored when this picture was made, or a fallback fired. */
  image_model?: string | null;
  /** Per-scene clip-model routing (checklist §1.2/C12-C14). `routed_model` is
   * shared.model_router's automatic recommendation computed at shot-plan time;
   * `routing_reason` is the human-readable "why" behind it; `model_used` is
   * whichever model ACTUALLY generated the clip (may differ from routed_model
   * if an override or a fallback fired); `model_override` is the creator's own
   * manual pick from the C14 override sheet, which wins over routed_model. All
   * null for assets that predate C12, or a fresh scene with no clip yet. */
  routed_model?: string | null;
  routing_reason?: string | null;
  model_used?: string | null;
  model_override?: string | null;
  /** Camera-move data (checklist §2.2/C23). `camera_movement` is the AUTO/
   * "earned" pick camera_selector.py stamped at shot-plan time — raw shape
   * "move_id|PURPOSE" or "static" (see coverage_to_app.py's _camera_tag).
   * `camera_preset_id` is the creator's own manual pick from the Scenes
   * chip/sheet or the copilot, which wins over the auto pick at clip-
   * generation time. Both null for assets that predate C23. */
  camera_movement?: string | null;
  camera_preset_id?: string | null;
  created_at: string | null;
}

export interface DialogueMapSegment {
  /** Position in the scene's dialogue_segments — keys the per-line audio route. */
  index: number;
  type: "narration" | "dialogue";
  speaker?: string | null;
  text: string;
  duration?: number | null;
  voiced: boolean;
}

export interface DialogueMap {
  dialogue_mode: string | null;
  scenes: { scene: number; segments: DialogueMapSegment[] }[];
}

export const getDialogueMap = (videoId: string) =>
  fetchApi<DialogueMap>(`/api/videos/${videoId}/dialogue-map`);

export const deleteClip = (videoId: string, assetId: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/clips/${assetId}`, { method: "DELETE" });

/** One-tap fix for a red "bad crop" badge: re-crops the picture's whole
 * storyboard beat (free), then auto re-animates any clips the new pictures
 * made stale (~$0.10 each). Background task — watch the task pill. */
export const recropAsset = (videoId: string, assetId: string) =>
  fetchApi<{ status: string; message: string }>(
    `/api/videos/${videoId}/assets/${assetId}/recrop`, { method: "POST" });

export const fixTextAsset = (videoId: string, assetId: string) =>
  fetchApi<{ status: string; message: string }>(
    `/api/videos/${videoId}/assets/${assetId}/fix-text`, { method: "POST" });

export interface ImageVariant {
  id: string;
  video_id: string | null;
  scene: number | null;
  image_index: number | null;
  image_url: string | null;
  drive_image_url?: string | null;
  image_prompt: string | null;
  status: string | null;
  shot_type: string | null;
  hero_shot: boolean;
  sentence_text: string | null;
  panel_position?: number | null;
  generation_method?: string | null;
  image_model?: string | null;
  created_at: string | null;
}

export interface ScriptScene {
  id: string;
  video_id: string | null;
  scene: number | null;
  scene_text: string | null;
  voice_over_url: string | null;
  scene_video_url: string | null;
  voice_status: string | null;
  script_status: string | null;
  sources: string | null;
  storyboard_on_off: string | null;
  // Storyboard
  storyboard_1_url: string | null;
  storyboard_2_url: string | null;
  storyboard_3_url: string | null;
  storyboard_4_url: string | null;
  storyboard_5_url: string | null;
  storyboard_prompts: string | null;
  storyboard_beat_count: number | null;
  storyboard_status: string | null;
  coverage_directive: string | null; // the saved shot plan the boards + pictures draw from
  tone: string | null; // serious | conversational | urgent | concise
  updated_at?: string | null; // bumps when a board is (re)generated — used to cache-bust grid images
}

export interface ActivityEntry {
  id: string;
  bot_name: string;
  video_id: string | null;
  video_title: string | null;
  status: string;
  message: string | null;
  cost: number;
  created_at: string | null;
}

export interface ActivityStats {
  bots_running: number;
  errors_today: number;
  cost_today: number;
}

export interface PendingReview {
  scripts: ReviewItem[];
  storyboards: ReviewItem[];
  thumbnails: ReviewItem[];
  images: ReviewItem[];
}

export interface ReviewItem {
  asset_id?: string;
  script_id?: string;
  video_id: string;
  title: string | null;
  url?: string;
  storyboard_1_url?: string;
  storyboard_2_url?: string;
  storyboard_3_url?: string;
  word_count?: number;
  scene?: number;
  image_index?: number;
  prompt?: string;
  type: string;
}

// Settings Types
export interface ApiKeyStatus {
  name: string;
  configured: boolean;
  source: "vault" | "env" | null;
  masked_value: string | null;
}

export interface ApiKeyList {
  keys: ApiKeyStatus[];
}

export interface TestKeyResponse {
  success: boolean | null;
  message: string;
}

// Pipeline Types
export interface PipelineResponse {
  video_id: string;
  status: string;
  message: string;
  error?: string;
}

export interface PipelineStatus {
  video_id: string;
  current_status: string;
  next_action: string | null;
  airtable_synced: boolean;
}

export interface TaskStatus {
  status: "pending" | "running" | "completed" | "failed";
  message: string | null;
  error?: string;
  // C28: additive attribution — the agent's display name when the running
  // task's claim is agent-held (generation_claims.claimed_by starts with
  // "agent:"), null/absent otherwise. Optional so older cached responses or
  // any other endpoint returning a TaskStatus-shaped object without this
  // field still type-check — absence must always mean "no chip".
  via_agent?: string | null;
}

export interface StyleUpdateResponse {
  status: string;
  video_id: string;
  updated_fields: {
    visual_style: string | null;
    accent_color: string | null;
    image_model_override: string | null;
  };
}

// Autopilot Types
export interface AutopilotState {
  enabled: boolean;
  last_cycle: string | null;
  videos_produced: number;
  channel_avg_ctr: number;
  next_production_date: string | null;
  days_until_next: number;
}

export interface AutopilotConfig {
  videos_per_month: number;
  production_interval_days: number;
  videos_per_scrape: number;
  weights: Record<string, number>;
  thresholds: Record<string, number>;
}

export interface ConfidenceBreakdown {
  vph_score: number;
  vph_reasoning: string;
  freshness_score: number;
  freshness_reasoning: string;
  intelligence_score: number;
  intelligence_reasoning: string;
  total_score: number;
}

export interface CompetitorCandidate {
  id: string;
  title: string;
  source: string;
  url: string | null;
  vph: number;
  hours_old: number;
  confidence: number;
  confidence_breakdown?: ConfidenceBreakdown;
  published_date: string | null;
  modeled: boolean;
}

export interface CandidateIntelligence {
  summary: string;
  metadata: {
    hook_dna?: { type?: string; opening_line?: string; technique?: string };
    content_dna?: { tone?: string; topic_tags?: string[]; complexity?: string };
    title_dna?: { structure?: string; curiosity_mechanism?: string; power_words?: string[] };
    thumbnail_dna?: {
      face_present?: boolean; face_emotion?: string; overall_style?: string;
      text_overlay?: { present?: boolean; text?: string };
      composition?: { layout?: string };
      colors?: { dominant?: string; mood?: string };
    };
    retention_dna?: { first_hook_seconds?: number; key_retention_moments?: number[] };
    engagement_signals?: { controversy_level?: string; shareability?: string };
    villain_dna?: { villain_type?: string; villain_entity?: string };
  };
}

export interface CandidateDetail extends CompetitorCandidate {
  transcript: string | null;
  thumbnail_url: string | null;
  description: string | null;
  duration_seconds: number | null;
  likes: number | null;
  has_intelligence: boolean;
  has_transcript: boolean;
  intelligence: CandidateIntelligence | null;
}

export interface Learning {
  id: string;
  pattern: string;
  category: string;
  effect: string;
  confidence: number;
  sample_size: number;
  avg_ctr: number | null;
}

export interface AutopilotSummary {
  state: AutopilotState;
  config: AutopilotConfig;
  candidates: CompetitorCandidate[];
  learnings: Learning[];
}

// Agent Quality Pipeline
export interface AgentStats {
  total_scripts: number;
  avg_hook_score: number;
  avg_body_score: number;
  avg_cost: number;
  total_cost: number;
}

export interface AgentVideoResult {
  video_id: string;
  video_title: string;
  tier: string;
  hook_score: number | null;
  body_score: number | null;
  cost: number | null;
  paper_trail: Record<string, unknown> | null;
}

// Niche
export interface CompetitorChannel {
  id: string;
  channel_name: string;
  channel_url: string;
  category: string | null;
  active: boolean;
  last_scraped: string | null;
}

export interface ThumbnailVersion {
  prompt: string;
  image_url: string | null;
  created_at: string;
}

export interface Segment {
  id: string;
  image_index: number;
  sentence_text: string;
  shot_type: string | null;
  status: string | null;
  word_count: number;
  duration_seconds: number;
  cumulative_start: number;
  image_prompt: string | null;
}

export interface SegmentResponse {
  scene: number;
  segments: Segment[];
}

// Channel Profile
export interface ChannelProfile {
  channel_name: string;
  niche: string;
  target_audience: string;
  frameworks: string[];
  accent_color?: string;
  logo_url?: string;
  google_drive_folder_id?: string;
  google_drive_folder_name?: string;
  user_type: string;
  style_description: string;
  youtube_channel_id: string;
  youtube_channel_name: string;
  onboarding_completed_at: string | null;
}

export interface ChannelProfileUpdate {
  channel_name?: string;
  niche?: string;
  target_audience?: string;
  frameworks?: string[];
  accent_color?: string;
  logo_url?: string;
  google_drive_folder_id?: string;
  google_drive_folder_name?: string;
  user_type?: string;
  style_description?: string;
  youtube_channel_id?: string;
  youtube_channel_name?: string;
}

export interface IntegrationStatusItem {
  name: string;
  connected: boolean;
}

// User Profile
export interface UserProfile {
  id: string;
  email: string | null;
  display_name: string | null;
  plan: string;
  created_at: string | null;
}

export interface UserProfileUpdate {
  display_name?: string;
  email?: string;
}

// Project (replaces ChannelProfile)
export interface CharacterReference {
  name: string;
  description: string;
  image_url?: string;
}

export interface Project {
  id: string;
  name: string;
  niche: string;
  target_audience: string;
  visual_style: string;
  visual_profile_json: Record<string, unknown> | null;
  accent_color: string;
  custom_accent_color: string | null;
  frameworks: string[];
  character_references: CharacterReference[];
}

export interface ProjectUpdate {
  name?: string;
  niche?: string;
  target_audience?: string;
  visual_style?: string;
  visual_profile_json?: Record<string, unknown>;
  accent_color?: string;
  custom_accent_color?: string | null;
  frameworks?: string[];
  character_references?: CharacterReference[];
}

// Visual Styles
export interface StyleCharacter {
  id: string;
  name: string;
  image_url: string;
  sort_order: number;
}

export interface VisualStyle {
  id: string;
  name: string;
  style_profile: {
    mood?: string;
    lighting?: string;
    composition?: string;
    texture?: string;
    color_palette?: { primary?: string; secondary?: string; accent?: string; highlight?: string };
    keywords?: string[];
    [key: string]: unknown;
  };
  reference_image_url: string | null;
  is_active: boolean;
  is_default: boolean;
  characters: StyleCharacter[];
}

export interface CreateVisualStyleRequest {
  name: string;
  style_profile: Record<string, unknown>;
  reference_image_url?: string;
}

// Discovery Ideas
export interface DiscoveryIdea {
  id: string;
  source_type: string;
  competitor_title: string | null;
  competitor_channel: string | null;
  competitor_url: string | null;
  competitor_vph: number | null;
  competitor_views: number | null;
  competitor_published_date: string | null;
  competitor_thumbnail_url: string | null;
  our_angle: string;
  hook: string | null;
  framework: string | null;
  estimated_appeal: number | null;
  appeal_breakdown: Record<string, number> | null;
  title_options: TitleOption[];
  status: string;
  batch_date: string | null;
  created_at: string | null;
  hook_type: string | null;
  tone: string | null;
  title_structure: string | null;
  thumbnail_style: string | null;
}

export interface TitleOption {
  title: string;
  formula_id: string;
  thumbnail_text: string;
  score: number;
}

export interface DiscoveryStatus {
  is_refreshing: boolean;
  last_batch_date: string | null;
  idea_count: number;
  fresh_count: number;
  learnings_applied: number;
  error: string | null;
}

// --- Pipeline Readiness ---
export interface ReadinessKey {
  key: string;
  label: string;
  reason: string;
  url: string;
}

export interface ReadinessStatus {
  ready: boolean;
  missing_keys: ReadinessKey[];
  configured_keys: string[];
  warnings: ReadinessKey[];
}

export const getReadinessStatus = () =>
  fetchApi<ReadinessStatus>("/api/pipeline/readiness");

// --- System Prompts Generate ---
export interface GenerateStyleRequest {
  style_description: string;
  channel_name?: string;
  niche?: string;
  target_audience?: string;
}

export interface GenerateStyleResponse {
  status: string;
  summary: string;
  prompts: Record<string, { label: string; text: string }>;
}

export const generateSystemPrompts = (data: GenerateStyleRequest) =>
  fetchApi<GenerateStyleResponse>("/api/system-prompts/generate", {
    method: "POST",
    body: JSON.stringify(data),
  });

// --- YouTube OAuth ---
export const getYouTubeConnectUrl = () =>
  fetchApi<{ auth_url: string }>("/api/auth/youtube/connect");

export const youtubeOAuthCallback = (code: string) =>
  fetchApi<{ status: string; channel_id: string | null; channel_name: string | null; channel_description: string | null }>("/api/auth/youtube/callback", {
    method: "POST",
    body: JSON.stringify({ code }),
  });

export const getYouTubeStatus = () =>
  fetchApi<{ connected: boolean; channel_id: string | null; channel_name: string | null }>("/api/auth/youtube/status");

export const disconnectYouTube = () =>
  fetchApi<{ status: string }>("/api/auth/youtube/disconnect", { method: "POST" });

// --- User's own channel videos (Flow B onboarding) ---
export interface MyYouTubeVideo {
  video_id: string;
  title: string;
  description: string;
  published_at: string;
  thumbnail: string;
  views: number;
  likes: number;
  comments: number;
}

export const getMyYouTubeVideos = (limit = 5, sort: "views" | "recent" = "views") =>
  fetchApi<{ videos: MyYouTubeVideo[]; channel_id: string; total_scanned: number }>(
    `/api/youtube/my-videos?limit=${limit}&sort=${sort}`,
  );

export interface VoiceLearnSource {
  video_id: string;
  title: string;
  views: number;
  has_transcript?: boolean;
}

export const learnVoiceFromYouTube = () =>
  fetchApi<{
    status: string;
    style_description: string;
    transcript_count?: number;
    source_videos: VoiceLearnSource[];
  }>("/api/youtube/learn-voice", { method: "POST" });

// --- Suggest Titles ---
export interface TitleSuggestion {
  title: string;
  thumbnail_text: string;
  score: number;
}

export const suggestTitles = async (topic: string) => {
  // The backend may return either plain title strings or full objects depending
  // on what the model emits. Normalize to TitleSuggestion so callers always get
  // a renderable {title, thumbnail_text, score}.
  const res = await fetchApi<{ titles: (string | Partial<TitleSuggestion>)[] }>(
    "/api/videos/suggest-titles",
    {
      method: "POST",
      body: JSON.stringify({ topic }),
    },
  );
  const titles: TitleSuggestion[] = (res.titles ?? []).map((t) =>
    typeof t === "string"
      ? { title: t, thumbnail_text: "", score: 0 }
      : { title: t.title ?? "", thumbnail_text: t.thumbnail_text ?? "", score: t.score ?? 0 },
  );
  return { titles };
};

// Export Manifest
export interface ExportManifestFile {
  type: string;
  label: string;
  url?: string;
  content?: string | Record<string, unknown>;
  format?: string;
  size_hint?: string | null;
}

export interface ExportManifest {
  video_id: string;
  video_title: string;
  status: string;
  final_video_url: string | null;
  thumbnail_url: string | null;
  drive_folder_link: string | null;
  youtube_url: string | null;
  assets: { scene: number; image_url: string; image_prompt: string }[];
  voice_tracks: { scene: number; voice_over_url: string }[];
}

export const getExportManifest = (videoId: string) =>
  fetchApi<ExportManifest>(`/api/videos/${videoId}/export-manifest`);

// Notification Preferences
export interface NotificationPreferences {
  email_weekly_digest: boolean;
  email_video_complete: boolean;
  email_error_alerts: boolean;
  email_ctr_alerts: boolean;
}

export const getNotificationPreferences = () =>
  fetchApi<NotificationPreferences>("/api/preferences/notifications");

export const updateNotificationPreferences = (data: Partial<NotificationPreferences>) =>
  fetchApi<NotificationPreferences>("/api/preferences/notifications", {
    method: "PATCH",
    body: JSON.stringify(data),
  });

// Google Drive connection
export interface DriveStatus {
  connected: boolean;
  folder_id: string | null;
  folder_name: string | null;
}

export const getDriveStatus = () =>
  fetchApi<DriveStatus>("/api/auth/google-drive/status");

export const getDriveConnectUrl = () =>
  fetchApi<{ auth_url: string }>("/api/auth/google-drive/connect");

export const postDriveCallback = (code: string) =>
  fetchApi<{ status: string; access_token: string }>("/api/auth/google-drive/callback", {
    method: "POST",
    body: JSON.stringify({ code }),
  });

export const disconnectDrive = () =>
  fetchApi<{ status: string }>("/api/auth/google-drive/disconnect", { method: "POST" });

export const getDriveAccessToken = () =>
  fetchApi<{ access_token: string }>("/api/auth/google-drive/access-token", { method: "POST" });

// Health Check
export interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy";
  service: string;
  database: boolean;
  active_tasks: number;
  storage: boolean;
}

export const getHealthStatus = () =>
  fetchApi<HealthStatus>("/api/health");

// ── Content Intelligence ─────────────────────────────────────────

export interface IntelligenceStats {
  distilled: number;
  total_with_transcript: number;
  pending: number;
  progress_pct: number;
  raw_bytes_processed: number;
  distilled_bytes: number;
  compression_ratio: number;
  estimated_savings_mb: number;
}

export interface IntelligenceSearchResult {
  id: string;
  source_type: string;
  source_id: string;
  summary: string;
  metadata: Record<string, unknown>;
  similarity: number | null;
  source_title: string | null;
  source_vph: number | null;
  source_channel: string | null;
  source_url: string | null;
  source_thumbnail_url: string | null;
  raw_char_count: number | null;
}

export interface TopicInsight {
  topic: string;
  count: number;
  avg_vph: number;
}

export interface HookInsight {
  hook_type: string;
  count: number;
  avg_vph: number;
  avg_like_ratio: number;
}

export interface ThumbnailInsights {
  layouts: Array<{ layout: string; count: number; avg_vph: number }>;
  face_emotions: Array<{ emotion: string; count: number; avg_vph: number }>;
  face_present: Array<{ face_present: boolean; count: number; avg_vph: number }>;
  styles: Array<{ style: string; count: number; avg_vph: number }>;
}

export interface TimingInsights {
  by_day: Array<{ day: number; day_name: string; count: number; avg_vph: number; avg_like_ratio?: number }>;
  by_hour: Array<{ hour: number; count: number; avg_vph: number }>;
}

export interface ViralVideo {
  id: string;
  title: string;
  channel: string;
  views: number;
  vph: number;
  views_per_sub_ratio: number;
  channel_subscriber_count: number;
  like_ratio: number;
  comment_ratio: number;
  thumbnail_url: string | null;
  summary: string | null;
  hook_type: string | null;
  tone: string | null;
  thumb_layout: string | null;
  title_structure: string | null;
}

export const getIntelligenceStats = () =>
  fetchApi<IntelligenceStats>("/api/intelligence/stats");

export const searchIntelligence = (q: string, limit = 20, sourceType?: string) => {
  const params = new URLSearchParams({ q, limit: String(limit) });
  if (sourceType) params.set("source_type", sourceType);
  return fetchApi<{ query: string; results: IntelligenceSearchResult[]; count: number }>(
    `/api/intelligence/search?${params}`
  );
};

export const getTopicInsights = (limit = 20) =>
  fetchApi<{ topics: TopicInsight[] }>(`/api/intelligence/insights/topics?limit=${limit}`);

export const getHookInsights = () =>
  fetchApi<{ hooks: HookInsight[] }>("/api/intelligence/insights/hooks");

export const getThumbnailInsights = () =>
  fetchApi<ThumbnailInsights>("/api/intelligence/insights/thumbnails");

export const getTimingInsights = () =>
  fetchApi<TimingInsights>("/api/intelligence/insights/timing");

export const getViralityInsights = (limit = 20) =>
  fetchApi<{ viral_videos: ViralVideo[]; count: number }>(`/api/intelligence/insights/virality?limit=${limit}`);

export const triggerBackfill = (batchSize = 50) =>
  fetchApi<{ status: string; batch_size?: number }>("/api/intelligence/backfill", {
    method: "POST",
    body: JSON.stringify({}),
  });

export const getBackfillStatus = () =>
  fetchApi<{ running: boolean; processed?: number; failed?: number; status?: string }>(
    "/api/intelligence/backfill/status"
  );

export interface DistillURLResult {
  status: string;
  video_id: string;
  title?: string;
  channel?: string;
  views?: number;
  vph?: number;
  has_transcript?: boolean;
  transcript_chars?: number;
  summary?: string;
  dna?: Record<string, unknown>;
  distillation_result?: Record<string, unknown>;
  error?: string;
}

export const distillFromURL = (url: string) =>
  fetchApi<DistillURLResult>("/api/intelligence/distill-url", {
    method: "POST",
    body: JSON.stringify({ url }),
  });

// ── Intelligence Recommendations & Meta-Insights ─────────────────

export interface IntelligenceRecommendations {
  sample_size: number;
  confidence: number;
  hook: { type: string; avg_vph: number; count: number; avg_like_ratio: number } | null;
  thumbnail: {
    layout: string | null; layout_avg_vph: number;
    style: string | null; style_avg_vph: number;
    face_emotion: string | null; face_emotion_avg_vph: number;
    face_present: boolean | null; face_present_avg_vph: number;
  } | null;
  title_structure: { structure: string; avg_vph: number } | null;
  timing: {
    best_day: number | null; best_day_name: string | null; best_day_avg_vph: number;
    best_hour: number | null; best_hour_avg_vph: number;
  } | null;
  top_topics: Array<{ topic: string; avg_vph: number }>;
}

export interface NicheMetaInsights {
  generated_at: string | null;
  sample_size: number;
  meta_report: string | null;
  insights: {
    niche_summary?: string;
    top_patterns?: Array<{
      pattern: string; performance: string; recommendation: string; confidence: string;
    }>;
    combination_insights?: string[];
    timing_strategy?: { best_days: string[]; best_hours: number[]; reasoning: string };
    contrarian_findings?: string[];
    niche_signature?: {
      audience_type: string; content_preference: string;
      visual_language: string; emotional_drivers: string[];
    };
  } | null;
  top_hook_types: Array<{ hook_type: string; count: number; avg_vph: number }> | null;
  top_thumbnail_patterns: Array<{ layout?: string; style?: string; count: number; avg_vph: number }> | null;
  top_title_structures: Array<{ structure: string; count: number; avg_vph: number }> | null;
  optimal_timing: Record<string, unknown> | null;
  niche_signature: Record<string, unknown> | null;
}

export const getIntelligenceRecommendations = () =>
  fetchApi<{ status: string; recommendations: IntelligenceRecommendations | null }>(
    "/api/intelligence/recommendations"
  );

export const getNicheMetaInsights = () =>
  fetchApi<{ status: string; insights: NicheMetaInsights["insights"] } & Partial<NicheMetaInsights>>(
    "/api/intelligence/meta-insights"
  );

export const triggerMetaAnalysis = () =>
  fetchApi<{ status: string; message: string }>("/api/intelligence/meta-insights/generate", {
    method: "POST",
  });

export const getAutopilotRecommendations = () =>
  fetchApi<{ status: string; recommendations: IntelligenceRecommendations | null }>(
    "/api/autopilot/recommendations"
  );

// --- Chat (chat-first creative producer) ---

export interface ChatCardOption {
  value: string;
  label: string;
  hint?: string;
}
// Confirm-action card (id "confirm_action") itemized quote (C15, checklist §1.2):
// one line per model/tier actually resolved for this quote — additive only, the
// SAME numbers actions.cost_breakdown() grouped from the routed per-row prices
// (backend/actions.py). Absent entirely on any quote with nothing to itemize
// (e.g. a build quote before pictures exist) or on any pre-C15 payload.
export interface ChatCostBreakdownLine {
  model_id: string;
  display_name: string;
  tier: string;
  count: number;
  subtotal: number;
}
export interface ChatCostBreakdown {
  lines: ChatCostBreakdownLine[];
  total: number;
  all_premium_total: number | null;
  hero_scenes: { scene: number | null; model_id: string; display_name: string; reason: string }[];
  /** Distinct scene count behind this itemization (C18, checklist §1.3) —
   * "Draft the whole video" / "Finalize N approved scenes" reads N from
   * here, never from counting asset rows (a scene has multiple). */
  scene_count: number;
}
// Inline storyboards/keyframes card (id "scene_boards", C15b — director review
// loop part 1, tasks/storyengine-copilot-ux-map.md): every url is already a
// tenant-authorized media-proxy URL (/api/media/drive/{id}), never a raw Drive
// or external link — the backend builds these, the frontend only displays them.
export interface ChatCardImage {
  url: string;
  label: string;
  asset_id: string;
  scene: number;
  index: number | null;
}
export interface ChatCard {
  id: string;
  label: string;
  type: "single" | "multi";
  options: ChatCardOption[];
  // Proposed-prompt cards (id "prompt_apply") carry the full draft here so the dock
  // can show it in an editable box; Apply sends back the edited text as prompt_text.
  body?: string;
  // Style card: the option value the system recommends (e.g. the reference video's
  // detected look) so the UI can badge it. The creator can still pick any option.
  recommended_value?: string;
  recommended_hint?: string;
  // Secure key card (id "secure_key"): the input placeholder, so each step names
  // the exact key being asked for (e.g. "Paste your Kie.ai API key…").
  placeholder?: string;
  // Confirm-action card only (C15) — see ChatCostBreakdown above. Optional and
  // additive: an older frontend build simply never reads this key.
  breakdown?: ChatCostBreakdown;
  // Scene-boards card only (C15b). Optional and additive: absent on every
  // other card and on any pre-C15b payload, so older/newer builds render
  // exactly as before when it's missing.
  images?: ChatCardImage[];
}
export interface ProductionPlan {
  story_concept?: string;
  recommended_titles?: string[];
  thumbnail_concepts?: string[];
  spec?: Record<string, unknown>;
  // C15a — pre-creation cost quote for the "Make it" tap, stamped server-side
  // from actions.estimate_cost's own rough pre-pictures guess (before "Make it"
  // ever fires the paid autobuild). Optional and additive: an older backend
  // build never sends these, and the plan card renders exactly as before.
  estimated_cost?: number;
  estimated_cost_text?: string;
}
export interface ChatTurnRequest {
  conversation_id?: string | null;
  message?: string | null;
  selections?: Record<string, unknown> | null;
  approve?: boolean;
  start_onboarding?: boolean;
  // The in-pipeline chat dock sends the video it's scoped to on every turn. Its
  // presence tells the backend this is the co-pilot dock: find-or-create one
  // conversation per video AND hold paid/destructive actions behind a confirm card.
  video_id?: string | null;
  // What the creator is looking at, so "this image" resolves without naming it.
  ui_context?: { tab?: string; scene?: number; index?: number } | null;
  // Files dropped into the chat this turn: chat_assets ids from uploadChatAsset.
  attachments?: string[];
}
export interface ChatTurnResponse {
  conversation_id: string;
  assistant_text: string;
  cards?: ChatCard[] | null;
  plan?: ProductionPlan | null;
  ready_to_create: boolean;
  video_id?: string | null;
  phase: string; // asking | plan | created
}

export const sendChatTurn = (body: ChatTurnRequest) =>
  fetchApi<ChatTurnResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });

// A file dropped into the chat: uploaded + parsed server-side, then referenced
// by id on the next chat turn via ChatTurnRequest.attachments.
export interface ChatAssetInfo {
  id: string;
  kind: "csv" | "pdf" | "text" | "image";
  filename?: string | null;
  summary: string;
  preview?: unknown;
}
export const uploadChatAsset = async (
  file: File,
  conversationId?: string | null,
  // Set when dropped into a video's docked co-pilot, so the backend stamps the
  // asset with that video from the moment it lands. Omitted by the home chat.
  videoId?: string | null,
): Promise<{ asset: ChatAssetInfo }> => {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const formData = new FormData();
  formData.append("file", file);
  if (conversationId) formData.append("conversation_id", conversationId);
  if (videoId) formData.append("video_id", videoId);
  const res = await fetch(`${API_URL}/api/chat/upload`, {
    method: "POST",
    headers: uploadHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
};

// Onboarding secure key box: posts the pasted key straight to the vault path so
// it never rides in as a chat message. Returns which provider it detected.
export interface OnboardingKeyResponse {
  ok: boolean;
  provider?: "kie" | "claude" | null;
  message: string;
}
export const setOnboardingKey = (value: string) =>
  fetchApi<OnboardingKeyResponse>("/api/chat/onboarding-key", {
    method: "POST",
    body: JSON.stringify({ value }),
  });

// --- Workspaces (command center) ---
export interface Workspace {
  tenant_id: string;
  name: string;
  role: string;
  channel_name?: string | null;
  youtube_connected: boolean;
}
export interface WorkspacesResponse {
  is_operator: boolean;
  workspaces: Workspace[];
}
export const getWorkspaces = () =>
  fetchApi<WorkspacesResponse>("/api/workspaces");
export const createWorkspace = (name: string) =>
  fetchApi<Workspace>("/api/workspaces", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
// Non-destructive: unlinks the workspace from the operator's switcher; the
// channel's tenant + data are preserved.
export const removeWorkspace = (tenantId: string) =>
  fetchApi<{ status: string }>(`/api/workspaces/${tenantId}`, { method: "DELETE" });

// One prior message of a video's co-pilot conversation, flattened for the dock.
export interface ChatHistoryMessage {
  role: "user" | "assistant";
  text: string;
  cards?: ChatCard[] | null;
  plan?: ProductionPlan | null;
}
export interface ChatConversation {
  conversation_id: string | null;
  messages: ChatHistoryMessage[];
  phase: string;
}

// Hydrate the in-pipeline chat dock on open with this video's conversation so it
// resumes the whole backstory. Empty (conversation_id null) when none exists yet.
export const getChatConversation = (videoId: string) =>
  fetchApi<ChatConversation>(`/api/chat/conversation?video_id=${encodeURIComponent(videoId)}`);

export interface ChatConversationSummary {
  conversation_id: string;
  title: string;
  preview: string;
  phase: string;
  video_id?: string | null;
  updated_at?: string | null;
}
export const listChatConversations = (limit?: number) =>
  fetchApi<ChatConversationSummary[]>(`/api/chat/conversations?limit=${limit || 20}`);
export const getChatConversationById = (conversationId: string) =>
  fetchApi<ChatConversation & { video_id?: string | null }>(
    `/api/chat/conversation/${encodeURIComponent(conversationId)}`
  );

// "Worth modeling" — the real top videos from the channel the creator is modeling,
// with metrics + an AI 'why model this'. Empty when they have no competitor data.
export interface SuggestedModelVideo {
  video_id: string;
  title: string;
  url?: string | null;
  channel?: string | null;
  views: number;
  vph: number;
  posted: string;
  thumbnail: string;
  why: string;
}
export interface SuggestedModels {
  channel: string | null;
  videos: SuggestedModelVideo[];
}
// --- Video generation models (single source of truth: shared.channel_profile
// .MODEL_REGISTRY, storyengine-wiring-fix-checklist.md §0.2). The Scenes
// clip-model dropdown derives its selectable list from this endpoint instead
// of a hand-copied constant — `wired` mirrors pipeline_executor's own gate. ---
export interface VideoModelInfo {
  id: string;
  name: string;
  kind: string; // "video" today — the registry may grow other kinds later
  wired: boolean;
  /** $/clip at the model's cheapest tier, or null if unwired. Single price
   * source: backend shared.channel_profile.CLIP_PRICE_BY_MODEL. */
  cost_per_clip: number | null;
}
export interface ModelsResponse {
  models: VideoModelInfo[];
  default_video_model: string;
}
export const getModels = () => fetchApi<ModelsResponse>("/api/models");

export const getSuggestedModels = () =>
  fetchApi<SuggestedModels>("/api/chat/suggested-models");

// --- Camera-move presets (checklist §2.2, C23) — a curated subset of the
// 40+-move catalog (image_prompts.engine.camera_moves.py), read-only, same
// "global catalog behind auth" posture as getModels() above. ---
export interface CameraPresetInfo {
  id: string;
  name: string;
  motion_prompt: string;
  best_for: string[];
  category: string;
  /** The catalog's own `image_setup` text — the closest honest thing to a
   * preview (no preview images exist for camera moves). Null for
   * static_locked (no composition contract). */
  preview: string | null;
}
export interface CameraPresetsResponse {
  presets: CameraPresetInfo[];
}
export const getCameraPresets = () => fetchApi<CameraPresetsResponse>("/api/camera-presets");

/** Set (or clear, with null = "Auto") one shot's manual camera-move
 * override. Wins over the auto/"earned" camera_movement at clip-generation
 * time — invalidate video-assets so the chip refreshes immediately. */
export const updateAssetCameraPreset = (assetId: string, camera_preset_id: string | null) =>
  fetchApi<{ status: string; camera_preset_id: string | null }>(
    `/api/assets/${assetId}/camera-preset`, {
      method: "PATCH",
      body: JSON.stringify({ camera_preset_id }),
    });

// --- Style presets (checklist §2.1, C20 backend / C21a frontend gallery) ---
// The 5 rich Python visual-profile ENGINES (shared.profiles.visual/*.py),
// backed by GET /api/style-presets. A DIFFERENT axis from the free-text
// image_style_override "look" above — see CreateVideoRequest's style_preset_id
// comment and docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S9-5
// for the full reconciliation note. Single fetcher — shared via the
// ["style-presets"] query key by both the New Video gallery and (C21b) the
// chat LOOK card, so React Query dedupes the request instead of each door
// fetching its own copy.
export interface StylePreset {
  id: string;
  display_name: string;
  description: string | null;
  tags: string[];
  best_for: string[];
  cost_tier: string | null;
  preview_url: string | null;
  source: string;
  sort: number;
}
export interface StylePresetsResponse {
  presets: StylePreset[];
}
export const getStylePresets = () =>
  fetchApi<StylePresetsResponse>("/api/style-presets");

// --- Style descriptions (checklist §2.1, C21b) ---
// The six style-DESCRIPTION ids (pixar_3d/flat_2d/realistic/anime/watercolor/
// comic) — a free-text aesthetic-overlay axis, DIFFERENT from StylePreset's
// 5-row structural engine catalog above. Backed by GET /api/style-descriptions,
// a thin view over the backend's channel_format.STYLE_DESCRIPTIONS (a static
// Python dict, not a DB table) — the ONE source shared by the reference-video
// vision classifier, the chat LOOK card, and the New Video "Style description"
// grid, replacing the two hardcoded copies this used to have (producer_prompt.
// VISUAL_PRESETS backend-side, lib/visual-presets.ts frontend-side — both
// deleted this chunk).
export interface StyleDescription {
  id: string;
  label: string;
  look: string;
}
export interface StyleDescriptionsResponse {
  descriptions: StyleDescription[];
}
export const getStyleDescriptions = () =>
  fetchApi<StyleDescriptionsResponse>("/api/style-descriptions");

// --- Script profiles (checklist §2.3, C24) ---
// The editorial-voice engines in shared.profiles.script (neutral_v1 default,
// power_doctrine_v2/v1 opt-in) — backed by GET /api/script-profiles. A
// DIFFERENT axis from StylePreset above: this picks the SCRIPT's tone/act
// structure/voice, not the image-generation engine. Copy (display_name/
// description/best_for) is pulled server-side from each profile's own
// template_metadata — never hand-written here.
export interface ScriptProfile {
  id: string;
  display_name: string;
  description: string;
  best_for: string[];
  is_default: boolean;
}
export interface ScriptProfilesResponse {
  profiles: ScriptProfile[];
}
export const getScriptProfiles = () =>
  fetchApi<ScriptProfilesResponse>("/api/script-profiles");
