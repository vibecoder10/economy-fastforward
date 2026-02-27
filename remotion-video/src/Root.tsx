import { Composition } from "remotion";
import { Main } from "./Main";
import { EconomyVideoAnimated } from "./compositions/EconomyVideoAnimated";
import { getSceneCount, getSceneDurationFromConfig, getTotalDurationFromConfig } from "./renderConfig";

const TOTAL_SCENES = getSceneCount() || 6;
const FPS = 24;
// Buffer after last spoken word to let audio trail off naturally
const SCENE_END_BUFFER_SECONDS = 1;

/**
 * Get scene duration from render_config.json (the single source of truth).
 * Throws if render_config is missing — the pipeline MUST run audio sync
 * before rendering.
 */
function getSceneDurationSeconds(sceneNumber: number): number {
    const configDuration = getSceneDurationFromConfig(sceneNumber);
    if (configDuration !== null) return configDuration + SCENE_END_BUFFER_SECONDS;

    throw new Error(
        `render_config.json has no timing data for scene ${sceneNumber}. ` +
        `Audio sync must run before rendering.`
    );
}

/**
 * Total video duration from render_config.json.
 * Falls back to summing per-scene durations (still from render_config).
 */
function getTotalDurationFrames(sceneCount: number, fps: number): number {
    const configTotal = getTotalDurationFromConfig();
    if (configTotal !== null) {
        // Add buffer per scene for audio trail-off
        return Math.ceil((configTotal + sceneCount * SCENE_END_BUFFER_SECONDS) * fps);
    }

    // Sum per-scene durations (each reads from render_config)
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
