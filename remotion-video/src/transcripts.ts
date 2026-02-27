// Transcript data for all scenes
// Derives word-level timing from render_config.json (single source of truth)
// instead of static caption file imports which can go stale across videos.

import { getRenderScenesForScene } from "./renderConfig";

/**
 * Build word-level timing for a scene from render_config.json.
 *
 * Each render-config entry has `sentence_text` (the narration for one image)
 * and `narration_start`/`narration_end` (Whisper-aligned boundaries).
 * We split the sentence into words and distribute timing proportionally
 * within those boundaries — accurate enough for 4-word karaoke chunks.
 */
export function getWordsForScene(
    sceneNumber: number,
): Array<{ word: string; start: number; end: number }> {
    const renderScenes = getRenderScenesForScene(sceneNumber);
    if (renderScenes.length === 0) return [];

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
            // Give each word a minimal time slice so karaoke still renders
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
