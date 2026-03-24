const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

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
    throw new Error(`API error ${res.status}: ${body}`);
  }

  return res.json();
}

// Dashboard
export const getDashboardSummary = () => fetchApi<DashboardSummary>("/api/dashboard/summary");

// Videos
export const getVideos = (status?: string) =>
  fetchApi<VideoSummary[]>(`/api/videos${status ? `?status=${status}` : ""}`);

export const getVideo = (id: string) => fetchApi<VideoDetail>(`/api/videos/${id}`);

export const advanceVideo = (id: string) =>
  fetchApi<{ status: string }>(`/api/videos/${id}/advance`, { method: "PATCH" });

export const rejectVideo = (id: string, reason?: string) =>
  fetchApi<{ status: string }>(`/api/videos/${id}/reject`, {
    method: "PATCH",
    body: JSON.stringify({ reason }),
  });

export const getVideoAssets = (id: string) => fetchApi<Asset[]>(`/api/videos/${id}/assets`);

export const getVideoScript = (id: string) => fetchApi<ScriptScene[]>(`/api/videos/${id}/script`);

// Assets
export const approveAsset = (id: string) =>
  fetchApi<{ status: string }>(`/api/assets/${id}/approve`, { method: "PATCH" });

export const rejectAsset = (id: string) =>
  fetchApi<{ status: string }>(`/api/assets/${id}/reject`, { method: "PATCH" });

export const batchApproveAssets = (assetIds: string[], status: "approved" | "rejected") =>
  fetchApi<{ updated: number }>("/api/assets/batch-approve", {
    method: "POST",
    body: JSON.stringify({ asset_ids: assetIds, status }),
  });

// Review
export const getPendingReview = () => fetchApi<PendingReview>("/api/review/pending");

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
  fetchApi<{ value: string }>(`/api/settings/keys/${name}/reveal`);

// Pipeline - Stage Triggers
export const createIdea = (topic: string, source?: string) =>
  fetchApi<PipelineResponse>("/api/pipeline/create-idea", {
    method: "POST",
    body: JSON.stringify({ topic, source: source || "storyengine" }),
  });

export const runPipelineStage = (videoId: string, stage: string) =>
  fetchApi<PipelineResponse>(`/api/pipeline/${stage}/${videoId}`, { method: "POST" });

export const runNextStep = (videoId: string) =>
  fetchApi<PipelineResponse>(`/api/pipeline/run-next/${videoId}`, { method: "POST" });

export const getPipelineStatus = (videoId: string) =>
  fetchApi<PipelineStatus>(`/api/pipeline/status/${videoId}`);

export const getPipelineTaskStatus = (videoId: string) =>
  fetchApi<TaskStatus>(`/api/pipeline/task/${videoId}`);

// Video Style Updates
export const updateVideoStyles = (
  videoId: string,
  styles: { visual_style?: string; accent_color?: string; image_model_override?: string }
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

export const getAutopilotLearnings = (category?: string, limit?: number) =>
  fetchApi<Learning[]>(
    `/api/autopilot/learnings?limit=${limit || 20}${category ? `&category=${category}` : ""}`
  );

export const toggleAutopilot = (enabled: boolean) =>
  fetchApi<{ status: string; enabled: boolean }>("/api/autopilot/toggle", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });

export const updateAutopilotConfig = (videosPerMonth: number) =>
  fetchApi<{ status: string; config: AutopilotConfig }>("/api/autopilot/config", {
    method: "POST",
    body: JSON.stringify({ videos_per_month: videosPerMonth }),
  });

export const launchCandidate = (candidateId: string) =>
  fetchApi<{ status: string; candidate_id: string; message: string }>(
    `/api/autopilot/launch/${candidateId}`,
    { method: "POST" }
  );

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
  airtable_record_id: string | null;
  headline: string | null;
  source: string | null;
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
  story_bible: string | null;
  thumbnail_prompt: string | null;
  thumbnail_style_override: string | null;
  visual_style: string | null;
  image_style_override: string | null;
  image_model_override: string | null;
  video_length_minutes: number | null;
  youtube_url: string | null;
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
  // Cost
  total_cost: number | null;
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
  created_at: string | null;
}

export interface ScriptScene {
  id: string;
  video_id: string | null;
  scene: number | null;
  scene_text: string | null;
  voice_over_url: string | null;
  voice_status: string | null;
  script_status: string | null;
  sources: string | null;
  storyboard_on_off: string | null;
  // Storyboard
  storyboard_1_url: string | null;
  storyboard_2_url: string | null;
  storyboard_3_url: string | null;
  storyboard_prompts: string | null;
  storyboard_beat_count: number | null;
  storyboard_status: string | null;
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
  weights: Record<string, number>;
  thresholds: Record<string, number>;
}

export interface ConfidenceBreakdown {
  vph_score: number;
  vph_reasoning: string;
  freshness_score: number;
  freshness_reasoning: string;
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
