import { Composition } from "remotion";
import { Main } from "./Main";
import { EconomyVideoAnimated } from "./compositions/EconomyVideoAnimated";
import { getWordsForScene } from "./transcripts";
import { getSceneDurationFromConfig, getTotalDurationFromConfig } from "./renderConfig";

const TOTAL_SCENES = 20;
const FPS = 24;
// Buffer after last spoken word to let audio trail off naturally
const SCENE_END_BUFFER_SECONDS = 1;
// Fallback when transcript data is unavailable
const FALLBACK_SCENE_DURATION_SECONDS = 60;

/**
 * Get scene duration from the best available source:
 * 1. render_config.json (audio-synced per-image timing) — most accurate
 * 2. Whisper transcript word timestamps (caption files) — fallback
 * 3. Hardcoded 60s — last resort
 */
function getSceneDurationSeconds(sceneNumber: number): number {
    const configDuration = getSceneDurationFromConfig(sceneNumber);
    if (configDuration !== null) return configDuration + SCENE_END_BUFFER_SECONDS;

    const words = getWordsForScene(sceneNumber);
    if (words.length === 0) return FALLBACK_SCENE_DURATION_SECONDS;
    return words[words.length - 1].end + SCENE_END_BUFFER_SECONDS;
}

/**
 * Total video duration. Prefers render_config's total_duration_seconds,
 * falls back to summing per-scene durations.
 */
function getTotalDurationFrames(sceneCount: number, fps: number): number {
    const configTotal = getTotalDurationFromConfig();
    if (configTotal !== null) {
        // Add buffer per scene for audio trail-off
        return Math.ceil((configTotal + sceneCount * SCENE_END_BUFFER_SECONDS) * fps);
    }

    let total = 0;
    for (let i = 1; i <= sceneCount; i++) {
        total += Math.ceil(getSceneDurationSeconds(i) * fps);
    }
    return total;
}

export const RemotionRoot: React.FC = () => {
    return (
        <>
            <Composition
                id="Main"
                component={Main}
                durationInFrames={getTotalDurationFrames(TOTAL_SCENES, FPS)}
                fps={FPS}
                width={1920}
                height={1080}
                defaultProps={{
                    totalScenes: TOTAL_SCENES,
                }}
            />
            <Composition
                id="Scene1Only"
                component={Main}
                durationInFrames={Math.ceil(getSceneDurationSeconds(1) * FPS)}
                fps={FPS}
                width={1920}
                height={1080}
                defaultProps={{
                    totalScenes: 1,
                }}
            />

            {/* NEW — Video clip version with transitions and effects */}
            <Composition
                id="EconomyVideoAnimated"
                component={EconomyVideoAnimated}
                durationInFrames={30 * 60 * 8}
                fps={FPS}
                width={1920}
                height={1080}
                defaultProps={{
                    scenes: [],
                    voiceoverUrl: "",
                    musicUrl: "",
                    musicVolume: 0.15,
                }}
            />
        </>
    );
};
