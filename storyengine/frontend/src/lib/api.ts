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
  video_length_minutes: number | null;
  youtube_url: string | null;
  avg_retention: number | null;
  impressions: number;
  likes: number;
  comments: number;
  performance_verdict: string | null;
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
