import { Composition } from "remotion";
import { Main } from "./Main";
import { EconomyVideoAnimated } from "./compositions/EconomyVideoAnimated";
import { getSceneDurationFromConfig, getTotalDurationFromConfig, getSceneNumbers } from "./renderConfig";

const FPS = 24;
// Buffer after last spoken word to let audio trail off naturally
const SCENE_END_BUFFER_SECONDS = 1;

/**
 * Total video duration from render_config.json.
 * Uses total_duration_seconds when available, otherwise sums per-scene
 * durations using the ACTUAL scene numbers from render_config (not 1..N).
 */
function getTotalDurationFrames(fps: number): number {
    const sceneNums = getSceneNumbers();
    const sceneCount = sceneNums.length || 20;

    const configTotal = getTotalDurationFromConfig();
    if (configTotal !== null) {
        // Add buffer per scene for audio trail-off
        return Math.ceil((configTotal + sceneCount * SCENE_END_BUFFER_SECONDS) * fps);
    }

    // Sum per-scene durations using actual scene numbers from render_config
    let total = 0;
    for (const sceneNum of sceneNums) {
        const dur = getSceneDurationFromConfig(sceneNum);
        if (dur !== null) {
            total += Math.ceil((dur + SCENE_END_BUFFER_SECONDS) * fps);
        }
    }
    // Fallback: 25 minutes if render_config has no data at all
    return total || Math.ceil(25 * 60 * fps);
}

/**
 * Duration for a single scene (Scene1Only composition).
 */
function getScene1DurationFrames(fps: number): number {
    const dur = getSceneDurationFromConfig(1);
    if (dur !== null) return Math.ceil((dur + SCENE_END_BUFFER_SECONDS) * fps);
    // Fallback: 2 minutes for preview
    return Math.ceil(2 * 60 * fps);
}

export const RemotionRoot: React.FC = () => {
    return (
        <>
            <Composition
                id="Main"
                component={Main}
                durationInFrames={getTotalDurationFrames(FPS)}
                fps={FPS}
                width={1920}
                height={1080}
            />
            <Composition
                id="Scene1Only"
                component={Main}
                durationInFrames={getScene1DurationFrames(FPS)}
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
