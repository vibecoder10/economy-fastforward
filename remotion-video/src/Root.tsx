import { Composition } from "remotion";
import { Main } from "./Main";
import { EconomyVideoAnimated } from "./compositions/EconomyVideoAnimated";
import { getWordsForScene } from "./transcripts";

const TOTAL_SCENES = 20;
const FPS = 24;
// Buffer after last spoken word to let audio trail off naturally
const SCENE_END_BUFFER_SECONDS = 1;
// Fallback when transcript data is unavailable
const FALLBACK_SCENE_DURATION_SECONDS = 60;

/**
 * Compute actual scene duration from Whisper transcript word timestamps.
 */
function getSceneDurationSeconds(sceneNumber: number): number {
    const words = getWordsForScene(sceneNumber);
    if (words.length === 0) return FALLBACK_SCENE_DURATION_SECONDS;
    return words[words.length - 1].end + SCENE_END_BUFFER_SECONDS;
}

/**
 * Sum actual durations across all scenes for total video length.
 */
function getTotalDurationFrames(sceneCount: number, fps: number): number {
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
