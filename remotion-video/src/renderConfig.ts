// Load per-video render configuration from CLI input props ONLY.
//
// CRITICAL: This file previously used a static `import` of
// public/render_config.json.  That import gets baked into the webpack bundle
// at build time.  Remotion caches bundles in .remotion/, so switching to a
// new video WITHOUT clearing the cache served the OLD video's caption text.
// This caused "Optimus They" captions to appear over El Mencho images.
//
// The static import has been REMOVED.  All data now flows through
// getInputProps() which reads --props from the CLI on every render.
// If no props are available (e.g. Studio preview), all functions return
// null/empty — never stale data from a previous video.

import { getInputProps } from "remotion";

// For Studio preview: try to load render_config.json statically
// This is safe because Studio preview is local-only development
let _staticConfig: RenderConfig | null = null;

// Try to load static config at module initialization (Studio preview)
try {
    // Use synchronous XHR for initial load (works in browser/Studio)
    if (typeof XMLHttpRequest !== "undefined" && typeof window !== "undefined") {
        // Remotion serves static files with a hash prefix
        const staticBase = (window as unknown as Record<string, unknown>).remotion_staticBase as string || "";
        const configUrl = staticBase ? `${staticBase}/render_config.json` : "/render_config.json";

        const xhr = new XMLHttpRequest();
        xhr.open("GET", configUrl, false); // synchronous
        xhr.send();
        if (xhr.status === 200) {
            const data = JSON.parse(xhr.responseText) as RenderConfig;
            if (data?.scenes && data.scenes.length > 0) {
                _staticConfig = data;
            }
        }
    }
} catch {
    // Static file not available or XHR not supported
}

export interface WordTimestamp {
    word: string;
    start: number;
    end: number;
}

export interface RenderScene {
    scene_number: number;
    image_path: string;
    display_start: number;
    display_end: number;
    display_duration: number;
    narration_start: number;
    narration_end: number;
    style: string;
    composition: string;
    act: number;
    ken_burns: Record<string, unknown>;
    transition_in: Record<string, unknown>;
    transition_out: Record<string, unknown>;
    sentence_text?: string;
    image_index?: number;
    type?: "image" | "video";
    video_clip_path?: string;
    words?: WordTimestamp[];
    // Static-documentary caption, rendered as a FIXED overlay (does not move
    // with the Ken Burns motion): name + operator/service years + 1–2 specs.
    caption_title?: string;
    caption_sub?: string;
    caption_specs?: string[];
}

export interface ActMusicBed {
    scope?: "act";
    act: number;
    file: string;
    mood: string;
    volume: number;
}

export interface FullVideoMusicBed {
    scope: "video";
    file: string;
    volume: number;
    trim_before_seconds: number;
    loop: boolean;
}

export type MusicBed = ActMusicBed | FullVideoMusicBed;

export interface RenderConfig {
    video_id: string;
    audio_path: string;
    total_duration_seconds: number;
    fps: number;
    resolution: {
        width: number;
        height: number;
    };
    scenes: RenderScene[];
    music_beds?: MusicBed[];
}

/**
 * Segment text data derived from render_config scenes.
 */
export interface SegmentText {
    text: string;
    duration: number;
}

// Module-level cache (lives only for this render process)
let _cachedConfig: RenderConfig | null = null;

/**
 * Load render config from CLI input props (--props).
 *
 * Returns the renderConfig object embedded in props.json by pipeline.py,
 * or null if unavailable.  NEVER returns stale data from a previous video.
 *
 * For Studio preview: falls back to public/render_config.json if no CLI props.
 */
export function loadRenderConfig(): RenderConfig | null {
    if (_cachedConfig) return _cachedConfig;

    // 1. Try CLI input props first (production render path)
    try {
        const inputProps = getInputProps() as Record<string, unknown>;
        const rc = inputProps?.renderConfig as RenderConfig | undefined;
        if (rc?.scenes && rc.scenes.length > 0) {
            _cachedConfig = rc;
            return _cachedConfig;
        }
    } catch {
        // getInputProps() unavailable (e.g. during initial bundling)
    }

    // 2. Fallback: return cached static config for Studio preview
    return _staticConfig;
}

/**
 * Reset cached config.  Exposed for testing.
 */
export function resetConfigCache(): void {
    _cachedConfig = null;
}

/**
 * Get the sorted list of unique scene numbers from render config.
 */
export function getSceneNumbers(): number[] {
    const config = loadRenderConfig();
    if (!config || config.scenes.length === 0) return [];

    const nums = new Set(config.scenes.map((s) => s.scene_number));
    return Array.from(nums).sort((a, b) => a - b);
}

/**
 * Get the number of scenes from render config.
 */
export function getSceneCount(): number {
    return getSceneNumbers().length;
}

/**
 * Get render_config scenes for a specific scene number.
 * Each returned entry represents one image with its display timing.
 */
export function getRenderScenesForScene(sceneNumber: number): RenderScene[] {
    const config = loadRenderConfig();
    if (!config) return [];

    return config.scenes.filter((s) => s.scene_number === sceneNumber);
}

/**
 * Get image count for a scene from render config.
 */
export function getImageCountForScene(sceneNumber: number): number {
    return getRenderScenesForScene(sceneNumber).length;
}

/**
 * Get scene duration from render_config (sum of per-image display_duration).
 * Returns null if unavailable.
 */
export function getSceneDurationFromConfig(sceneNumber: number): number | null {
    const scenes = getRenderScenesForScene(sceneNumber);
    if (scenes.length === 0) return null;
    const total = scenes.reduce((sum, s) => sum + s.display_duration, 0);
    return total > 0 ? total : null;
}

/**
 * Get total video duration from render_config.
 * Returns null if unavailable.
 */
export function getTotalDurationFromConfig(): number | null {
    const config = loadRenderConfig();
    if (!config || !config.total_duration_seconds) return null;
    return config.total_duration_seconds > 0 ? config.total_duration_seconds : null;
}

/**
 * Get music beds from render_config.
 * Returns empty array if unavailable.
 */
export function getMusicBeds(): MusicBed[] {
    const config = loadRenderConfig();
    if (!config || !config.music_beds) return [];
    return config.music_beds;
}

/**
 * Calculate act boundaries (start/end frames) from scene data.
 * Returns array sorted by act number.
 */
export function getActBoundaries(
    fps: number
): Array<{ act: number; startFrame: number; endFrame: number }> {
    const config = loadRenderConfig();
    if (!config || !config.scenes || config.scenes.length === 0) return [];

    const actMap = new Map<number, { start: number; end: number }>();

    for (const scene of config.scenes) {
        const act = scene.act || 0;
        if (act === 0) continue;

        const existing = actMap.get(act);
        if (existing) {
            existing.start = Math.min(existing.start, scene.display_start);
            existing.end = Math.max(existing.end, scene.display_end);
        } else {
            actMap.set(act, { start: scene.display_start, end: scene.display_end });
        }
    }

    const result: Array<{ act: number; startFrame: number; endFrame: number }> = [];
    for (const [act, bounds] of Array.from(actMap.entries()).sort(
        (a, b) => a[0] - b[0]
    )) {
        result.push({
            act,
            startFrame: Math.floor(bounds.start * fps),
            endFrame: Math.floor(bounds.end * fps),
        });
    }

    return result;
}
