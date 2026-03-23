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
