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
}

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
 */
export function loadRenderConfig(): RenderConfig | null {
    if (_cachedConfig) return _cachedConfig;

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

    return null;
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
