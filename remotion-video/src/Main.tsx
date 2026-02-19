import { AbsoluteFill, Sequence, staticFile, useVideoConfig } from "remotion";
import { Audio } from "@remotion/media";
import { Scene } from "./Scene";
import { useMemo } from "react";
import { getWordsForScene } from "./transcripts";
import { getSceneCount, getImageCountForScene } from "./renderConfig";

interface MainProps {
    totalScenes?: number;
}

// Approximate duration per scene in seconds (will be refined with audio duration)
const SCENE_DURATION_SECONDS = 60;

export const Main: React.FC<MainProps> = ({ totalScenes }) => {
    const { fps } = useVideoConfig();

    // Derive total scenes from render_config.json, then props, then default
    const sceneCount = totalScenes ?? getSceneCount() || 20;

    // Generate scene data with transcripts - image count is dynamic per scene
    const scenes = useMemo(() => {
        return Array.from({ length: sceneCount }, (_, i) => {
            const sceneNumber = i + 1;
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
    }, [sceneCount]);

    // Calculate cumulative start frames for each scene
    const scenesWithTiming = useMemo(() => {
        let cumulativeFrames = 0;
        return scenes.map((scene) => {
            const startFrame = cumulativeFrames;
            const durationFrames = SCENE_DURATION_SECONDS * fps;
            cumulativeFrames += durationFrames;
            return { ...scene, startFrame, durationFrames };
        });
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

