// Transcript data for all scenes
//
// Derives word-level timing from two sources (in priority order):
// 1. render_config.json via renderConfig.ts (which itself prefers getInputProps()
//    over the static import — see renderConfig.ts for details)
// 2. Input props scenes[].images[].segmentText (direct fallback when
//    render_config has no data for a scene, e.g. standalone render_video.py)

import { getInputProps } from "remotion";
import { getRenderScenesForScene } from "./renderConfig";

interface PropsImage {
    index: number;
    segmentText?: string;
    duration?: number;
}

interface PropsScene {
    sceneNumber: number;
    images?: PropsImage[];
}

/**
 * Build word-level timing for a scene.
 *
 * Tries render_config.json first (most accurate — has Whisper-aligned
 * narration_start/narration_end boundaries).  Falls back to input props
 * segmentText + duration when render_config has no data for this scene.
 */
export function getWordsForScene(
    sceneNumber: number,
): Array<{ word: string; start: number; end: number }> {
    // 1. Try render_config (prefers input props internally, see renderConfig.ts)
    const renderScenes = getRenderScenesForScene(sceneNumber);
    if (renderScenes.length > 0) {
        const words = buildWordsFromRenderScenes(renderScenes);
        if (words.length > 0) return words;
    }

    // 2. Fallback: derive directly from input props segmentText
    return buildWordsFromInputProps(sceneNumber);
}

/**
 * Build words from render_config scenes (existing logic).
 * Each entry has sentence_text and narration_start/narration_end.
 */
function buildWordsFromRenderScenes(
    renderScenes: Array<{ sentence_text?: string; narration_start: number; narration_end: number }>,
): Array<{ word: string; start: number; end: number }> {
    const words: Array<{ word: string; start: number; end: number }> = [];

    for (const scene of renderScenes) {
        const text = scene.sentence_text || "";
        if (!text.trim()) continue;

        const sceneWords = text.split(/\s+/).filter((w) => w.length > 0);
        if (sceneWords.length === 0) continue;

        const start = scene.narration_start;
        const end = scene.narration_end;
        const duration = end - start;

        // Guard against zero/negative duration (degenerate timing)
        if (duration <= 0) {
            for (let i = 0; i < sceneWords.length; i++) {
                words.push({
                    word: sceneWords[i],
                    start: start + i * 0.01,
                    end: start + (i + 1) * 0.01,
                });
            }
            continue;
        }

        const wordDuration = duration / sceneWords.length;

        for (let i = 0; i < sceneWords.length; i++) {
            words.push({
                word: sceneWords[i],
                start: start + i * wordDuration,
                end: start + (i + 1) * wordDuration,
            });
        }
    }

    return words;
}

/**
 * Build words from input props scene data.
 * Uses scenes[].images[].segmentText and duration, with cumulative timing.
 * Less accurate than render_config (no Whisper alignment) but always fresh.
 */
function buildWordsFromInputProps(
    sceneNumber: number,
): Array<{ word: string; start: number; end: number }> {
    try {
        const inputProps = getInputProps() as Record<string, unknown> | undefined;
        const scenes = inputProps?.scenes as PropsScene[] | undefined;
        const scene = scenes?.find((s) => s.sceneNumber === sceneNumber);
        if (!scene?.images?.length) return [];

        const words: Array<{ word: string; start: number; end: number }> = [];
        let cumulativeTime = 0;

        const sortedImages = [...scene.images].sort((a, b) => a.index - b.index);

        for (const image of sortedImages) {
            const text = image.segmentText || "";
            if (!text.trim()) continue;

            const segmentWords = text.split(/\s+/).filter((w) => w.length > 0);
            if (segmentWords.length === 0) continue;

            const duration = image.duration || 5;

            if (duration <= 0) {
                for (let i = 0; i < segmentWords.length; i++) {
                    words.push({
                        word: segmentWords[i],
                        start: cumulativeTime + i * 0.01,
                        end: cumulativeTime + (i + 1) * 0.01,
                    });
                }
                cumulativeTime += 0.01 * segmentWords.length;
                continue;
            }

            const wordDuration = duration / segmentWords.length;

            for (let i = 0; i < segmentWords.length; i++) {
                words.push({
                    word: segmentWords[i],
                    start: cumulativeTime + i * wordDuration,
                    end: cumulativeTime + (i + 1) * wordDuration,
                });
            }

            cumulativeTime += duration;
        }

        return words;
    } catch {
        return [];
    }
}
