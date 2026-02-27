import { AbsoluteFill, Sequence, staticFile, useVideoConfig } from "remotion";
import { Audio } from "@remotion/media";
import { Scene } from "./Scene";
import { useMemo } from "react";
import { getWordsForScene } from "./transcripts";
import { getSceneNumbers, getImageCountForScene, getSceneDurationFromConfig } from "./renderConfig";

interface MainProps {
    totalScenes?: number;
}

// Buffer after last spoken word to let audio trail off naturally
const SCENE_END_BUFFER_SECONDS = 1;

/**
 * Get scene duration from render_config.json (the single source of truth).
 * Returns null if render_config has no data for this scene (scene was
 * skipped during audio_sync — e.g. Whisper failure or missing audio).
 */
function getSceneDurationSeconds(sceneNumber: number): number | null {
    const configDuration = getSceneDurationFromConfig(sceneNumber);
    if (configDuration !== null) return configDuration + SCENE_END_BUFFER_SECONDS;
    return null;
}

export const Main: React.FC<MainProps> = ({ totalScenes }) => {
    const { fps } = useVideoConfig();

    // Get actual scene numbers from render_config.json.
    // When totalScenes is passed (e.g. Scene1Only preview), use sequential 1..N.
    // Otherwise use the real scene numbers — they may not be sequential if
    // audio_sync skipped a scene.
    const sceneNumberList = useMemo(() => {
        if (totalScenes) {
            return Array.from({ length: totalScenes }, (_, i) => i + 1);
        }
        const nums = getSceneNumbers();
        return nums.length > 0 ? nums : Array.from({ length: 20 }, (_, i) => i + 1);
    }, [totalScenes]);

    // Generate scene data with transcripts - image count is dynamic per scene
    const scenes = useMemo(() => {
        return sceneNumberList.map((sceneNumber) => {
            // Get image count from render_config.json, fallback to 6
            const imageCount = getImageCountForScene(sceneNumber) || 6;

            return {
                sceneNumber,
                audioFile: `Scene ${sceneNumber}.mp3`,
                images: Array.from({ length: imageCount }, (_, j) => ({
                    index: j + 1,
                    file: `Scene_${String(sceneNumber).padStart(2, "0")}_${String(j + 1).padStart(2, "0")}.png`,
                })),
                transcript: {
                    words: getWordsForScene(sceneNumber),
                },
            };
        });
    }, [sceneNumberList]);

    // Calculate cumulative start frames using actual audio durations per scene.
    // Scenes missing from render_config are skipped (they had no audio data).
    const scenesWithTiming = useMemo(() => {
        let cumulativeFrames = 0;
        const result: Array<typeof scenes[number] & { startFrame: number; durationFrames: number }> = [];
        for (const scene of scenes) {
            const sceneDuration = getSceneDurationSeconds(scene.sceneNumber);
            if (sceneDuration === null) {
                console.warn(
                    `Scene ${scene.sceneNumber}: no timing data in render_config.json, skipping`
                );
                continue;
            }
            const startFrame = cumulativeFrames;
            const durationFrames = Math.ceil(sceneDuration * fps);
            cumulativeFrames += durationFrames;
            result.push({ ...scene, startFrame, durationFrames });
        }
        return result;
    }, [scenes, fps]);

    return (
        <AbsoluteFill style={{ backgroundColor: "#000" }}>
            {scenesWithTiming.map((scene) => (
                <Sequence
                    key={scene.sceneNumber}
                    from={scene.startFrame}
                    durationInFrames={scene.durationFrames}
                >
                    <Scene
                        sceneNumber={scene.sceneNumber}
                        audioFile={scene.audioFile}
                        images={scene.images}
                        transcript={scene.transcript}
                    />
                </Sequence>
            ))}
        </AbsoluteFill>
    );
};

