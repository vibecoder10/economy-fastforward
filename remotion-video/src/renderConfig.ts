// Load per-video render configuration.
//
// PRIMARY source: getInputProps() — data passed via --props on every render.
// FALLBACK source: static import of public/render_config.json (may be stale
// if Remotion's webpack bundle cache wasn't invalidated between videos).
//
// The static import bakes render_config.json into the webpack bundle at build
// time.  Remotion caches bundles in .remotion/, so switching videos without
// cache invalidation serves the OLD video's caption text.  Using getInputProps()
// avoids this entirely because props are parsed from the CLI on every render.

import { getInputProps } from "remotion";
import renderConfigJson from "../public/render_config.json";

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
 * Replaces the old SegmentText interface from segmentData.ts.
 */
export interface SegmentText {
    text: string;
    duration: number;
}

// Module-level cache for loaded render config
let _cachedConfig: RenderConfig | null = null;

/**
 * Load render configuration, preferring CLI input props over the static import.
 *
 * Input props (--props) are always fresh — they're parsed from the CLI on each
 * render.  The static import of render_config.json is baked into the webpack
 * bundle and can go stale when Remotion's bundle cache persists across videos.
 */
export function loadRenderConfig(): RenderConfig | null {
    if (_cachedConfig) return _cachedConfig;

    // 1. Prefer renderConfig embedded in input props (always fresh)
    try {
        const inputProps = getInputProps() as Record<string, unknown> | undefined;
        const rc = inputProps?.renderConfig as RenderConfig | undefined;
        if (rc?.scenes && rc.scenes.length > 0) {
            _cachedConfig = rc;
            return _cachedConfig;
        }
    } catch {
        // getInputProps() unavailable (e.g. during initial bundling)
    }

    // 2. Fallback to static import (works in Studio preview and when props
    //    don't include renderConfig)
    try {
        _cachedConfig = renderConfigJson as unknown as RenderConfig;
        return _cachedConfig;
    } catch {
        return null;
    }
}

/**
 * Reset cached config — call when input props change between renders.
 * Exposed for testing.
 */
export function resetConfigCache(): void {
    _cachedConfig = null;
}

/**
 * Get the sorted list of unique scene numbers from render config.
 * This is the authoritative list — scene numbers may not be sequential
 * (e.g. if audio_sync skipped a scene due to Whisper failure).
 */
export function getSceneNumbers(): number[] {
    const config = loadRenderConfig();
    if (!config || config.scenes.length === 0) return [];

    const nums = new Set(config.scenes.map((s) => s.scene_number));
    return Array.from(nums).sort((a, b) => a - b);
}

/**
 * Get the number of scenes from render config.
 * Groups render_config scenes by scene_number (multiple images may share a scene).
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
 * Returns null if render_config is unavailable or has no entries for this scene.
 */
export function getSceneDurationFromConfig(sceneNumber: number): number | null {
    const scenes = getRenderScenesForScene(sceneNumber);
    if (scenes.length === 0) return null;
    const total = scenes.reduce((sum, s) => sum + s.display_duration, 0);
    return total > 0 ? total : null;
}

/**
 * Get total video duration from render_config.
 * Returns null if render_config is unavailable.
 */
export function getTotalDurationFromConfig(): number | null {
    const config = loadRenderConfig();
    if (!config || !config.total_duration_seconds) return null;
    return config.total_duration_seconds > 0 ? config.total_duration_seconds : null;
}
