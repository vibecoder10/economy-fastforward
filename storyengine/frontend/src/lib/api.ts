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

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  // Get token from localStorage, fallback to "dev-token" for development
  const storedToken = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const token = storedToken || "dev-token";

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
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

// --- Creator setup + intelligence report (chat-onboarding workspace layer) ---

// The durable brief captured during chat onboarding.
export interface CreatorBrief {
  intent?: string;
  goals?: string[];
  niche_angle?: string;
  channel?: string;
  competitors?: string[];
}

// Subset of /api/onboarding/status we render in the Competitors "Your setup" card.
export interface CreatorSetup {
  channel_name: string;
  youtube_channel_name: string;
  niche: string;
  creator_brief: CreatorBrief;
}

export const getCreatorSetup = () =>
  fetchApi<CreatorSetup>("/api/onboarding/status");

// The onboarding intelligence report (written by onboarding, previously unshown).
export interface IntelTitleIdea {
  title: string;
  pattern?: string;
  reasoning?: string;
  hook_direction?: string;
  source_titles?: string[];
}
export interface IntelInsight {
  pattern?: string;
  strategy?: string;
  reasoning?: string;
}
export interface IntelChannelAnalysis {
  best_pattern?: string;
  weakest_area?: string;
  quick_win?: string;
  opportunity?: string;
}
export interface IntelCreationGuidance {
  research_plan?: string;
  script_plan?: string;
  visual_plan?: string;
  thumbnail_plan?: string;
  modeling_next_step?: string;
}
export interface IntelligenceReport {
  title_ideas: IntelTitleIdea[];
  thumbnail_insights: IntelInsight[];
  hook_ideas: IntelInsight[];
  channel_analysis: IntelChannelAnalysis | null;
  creation_guidance: IntelCreationGuidance | null;
}
export interface IntelligenceReportResponse {
  status: "ok" | "not_generated";
  report: IntelligenceReport | null;
  competitors_analyzed?: number;
  videos_analyzed?: number;
  created_at?: string | null;
}

// The backend stores these report fields as JSONB; without a pool codec asyncpg
// hands them back as JSON strings, so normalize string-or-parsed into real values.
function parseMaybe<T>(v: unknown, fallback: T): T {
  if (v == null) return fallback;
  if (typeof v === "string") {
    try {
      return JSON.parse(v) as T;
    } catch {
      return fallback;
    }
  }
  return v as T;
}

export async function getIntelligenceReport(): Promise<IntelligenceReportResponse> {
  const res = await fetchApi<IntelligenceReportResponse>("/api/onboarding/intelligence-report");
  if (res.report) {
    res.report = {
      title_ideas: parseMaybe(res.report.title_ideas, [] as IntelTitleIdea[]),
      thumbnail_insights: parseMaybe(res.report.thumbnail_insights, [] as IntelInsight[]),
      hook_ideas: parseMaybe(res.report.hook_ideas, [] as IntelInsight[]),
      channel_analysis: parseMaybe(res.report.channel_analysis, null as IntelChannelAnalysis | null),
      creation_guidance: parseMaybe(res.report.creation_guidance, null as IntelCreationGuidance | null),
    };
  }
  return res;
}

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
  candidate_id: string;
  source_title: string;
  source_channel: string;
  source_url?: string | null;
  views: number;
  score: number;
  why: string;
}
export interface CalendarPlan {
  interval_days: number;
  slots: CalendarPlanSlot[];
  note?: string;
}
export const getCalendarPlan = (days?: number) =>
  fetchApi<CalendarPlan>(`/api/dashboard/calendar/plan?days=${days || 30}`);

// Videos
export const getVideos = (status?: string) =>
  fetchApi<VideoSummary[]>(`/api/videos${status ? `?status=${status}` : ""}`);

export const getVideo = (id: string) => fetchApi<VideoDetail>(`/api/videos/${id}`);

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

export const runNextStep = (videoId: string) =>
  fetchApi<PipelineResponse>(`/api/pipeline/run-next/${videoId}`, { method: "POST" });

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

// Niche
export const getNicheConfig = () =>
  fetchApi<NicheConfig>("/api/niche/config");

export const setupNiche = (niche_category: string, sub_niche: string) =>
  fetchApi<{ status: string }>("/api/niche/setup", {
    method: "POST",
    body: JSON.stringify({ niche_category, sub_niche }),
  });

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

// Competitor Videos (niche)
export interface NicheVideo {
  id: string;
  video_id: string;
  title: string;
  url: string | null;
  channel: string;
  channel_url: string | null;
  views: number;
  vph: number;
  hours_old: number;
  published_date: string | null;
  scrape_date: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  likes: number | null;
  description: string | null;
  like_ratio: number | null;
  views_per_sub_ratio: number | null;
  distilled_at: string | null;
  has_dna: boolean;
  hook_type: string | null;
  tone: string | null;
  title_structure: string | null;
  thumbnail_style: string | null;
  face_emotion: string | null;
  distilled_summary: string | null;
}

export interface NicheVideosResponse {
  videos: NicheVideo[];
  total: number;
  limit: number;
  offset: number;
  channels: string[];
}

export const getNicheVideos = (params?: {
  limit?: number;
  offset?: number;
  channel?: string;
  min_vph?: number;
  max_hours_old?: number;
  sort?: string;
}) => {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  if (params?.channel) searchParams.set("channel", params.channel);
  if (params?.min_vph) searchParams.set("min_vph", String(params.min_vph));
  if (params?.max_hours_old) searchParams.set("max_hours_old", String(params.max_hours_old));
  if (params?.sort) searchParams.set("sort", params.sort);
  const qs = searchParams.toString();
  return fetchApi<NicheVideosResponse>(`/api/niche/videos${qs ? `?${qs}` : ""}`);
};

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

// Analytics
export interface AnalyticsOverview {
  total_videos: number;
  total_views: number;
  avg_ctr: number | null;
  avg_retention: number | null;
  published_videos: number;
}

export interface CTRTimelinePoint {
  video_title: string;
  ctr: number | null;
  views: number;
  date: string;
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

export const getCTRTimeline = (limit?: number) =>
  fetchApi<CTRTimelinePoint[]>(`/api/analytics/ctr-timeline${limit ? `?limit=${limit}` : ""}`);

export const getFrameworkPerformance = () =>
  fetchApi<FrameworkPerformance[]>("/api/analytics/framework-performance");

// Topic Performance
export interface TopicPerformance {
  topic: string;
  video_count: number;
  avg_ctr: number | null;
  avg_retention: number | null;
  total_views: number;
}

export const getTopicPerformance = () =>
  fetchApi<TopicPerformance[]>("/api/analytics/topic-performance");

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
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_URL}/api/videos/${videoId}/characters/${charId}/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token || "dev-token"}` },
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
    headers: { Authorization: `Bearer ${token || "dev-token"}` },
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
    headers: { Authorization: `Bearer ${token || "dev-token"}` },
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
  aspect_ratio?: string | null;
  // Per-video pipeline plan: enabled stages (null = full pipeline). The video
  // page hides the tabs for stages that aren't in this list.
  pipeline_stages?: string[] | null;
  skip_voice?: boolean;
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
  created_at: string | null;
}

export interface DialogueMapSegment {
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
export interface NicheConfig {
  niche_category: string | null;
  sub_niche: string | null;
  has_channels: boolean;
}

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
}
export interface ProductionPlan {
  story_concept?: string;
  recommended_titles?: string[];
  thumbnail_concepts?: string[];
  spec?: Record<string, unknown>;
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
export const getSuggestedModels = () =>
  fetchApi<SuggestedModels>("/api/chat/suggested-models");
