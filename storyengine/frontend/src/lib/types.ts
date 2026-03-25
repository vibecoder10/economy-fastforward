export type PipelineStatus =
  | "idea_logged"
  | "researching"
  | "scripting"
  | "voice"
  | "visuals"
  | "storyboard_review"
  | "rendering"
  | "uploaded"
  | "published"
  | "done";

export type Verdict = "hit" | "steady" | "underperformed";

export interface Video {
  id: string;
  title: string;
  status: PipelineStatus;
  framework?: string;
  videoLengthMin?: number;
  wordCount?: number;
  sceneCount?: number;
  estimatedCost?: number;
  views?: number;
  ctr?: number;
  retention?: number;
  watchTimeHrs?: number;
  verdict?: Verdict;
  uploadDate?: string;
  thumbnailUrl?: string;
  progress?: number;
  updatedAt?: string;
}

export interface ScriptScene {
  sceneNumber: number;
  actNumber: number;
  narrationText: string;
  visualStyle: string;
  composition: string;
  sources?: string[];
  imageGenerated?: boolean;
}

export interface StoryboardScene {
  sceneNumber: number;
  narrationText: string;
  panels: StoryboardPanel[];
  approved?: boolean;
  selectedPanel?: number;
}

export interface StoryboardPanel {
  id: string;
  imageUrl?: string;
  selected?: boolean;
  approved?: boolean;
}

export interface ActivityItem {
  id: string;
  message: string;
  timestamp: string;
  type: "success" | "warning" | "info" | "error";
  videoTitle?: string;
}

export interface AnalyticsDataPoint {
  date: string;
  views: number;
  ctr: number;
}

export interface Insight {
  category: string;
  title: string;
  description: string;
  stat: string;
  statLabel: string;
  color: string;
}

export interface RenderState {
  progress: number;
  resolution: string;
  fps: number;
  duration: string;
  musicTrack: string;
  exportFormat: string;
  ramUsage: string;
  cpuLoad: string;
  timeRemaining: string;
  scenes: RenderSceneBlock[];
}

export interface RenderSceneBlock {
  type: "image" | "video" | "voice" | "sound";
  label: string;
  color: string;
}

export interface SettingsData {
  channelName: string;
  niche: string;
  targetAudience: string;
  visualStyle: string;
  accentColor: string;
  frameworks: { name: string; enabled: boolean }[];
  integrations: { name: string; icon: string; connected: boolean }[];
}

export interface VoiceSegment {
  id: string;
  sceneNumber: number;
  narrationText: string;
  duration: string;
  panels: { id: string; imageUrl?: string }[];
  selectedPanel?: number;
  approved?: boolean;
}

export interface ImageGenItem {
  id: string;
  segmentId: string;
  prompt: string;
  progress: number;
  completed: boolean;
  imageUrl?: string;
}

export interface VisualSegment {
  id: string;
  sentenceText: string;
  imagePrompt: string;
  imageUrl?: string;
  status: "pending" | "generating" | "done";
  segmentId: string;
}

export interface SceneVisualGroup {
  sceneNumber: number;
  actNumber: number;
  narrationText: string;
  visualStyle: string;
  composition: string;
  duration: string;
  segments: VisualSegment[];
  storyboardPanels?: StoryboardPanel[];
  storyboardApproved?: boolean;
  selectedStoryboardPanel?: number;
}
