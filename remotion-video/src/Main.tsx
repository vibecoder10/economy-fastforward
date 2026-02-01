import { AbsoluteFill, Sequence, staticFile, useVideoConfig } from "remotion";
import { Audio } from "@remotion/media";
import { Scene } from "./Scene";
import { useMemo } from "react";
import { getWordsForScene } from "./transcripts";

interface MainProps {
    totalScenes?: number;
}

// Approximate duration per scene in seconds (will be refined with audio duration)
const SCENE_DURATION_SECONDS = 60;

export const Main: React.FC<MainProps> = ({ totalScenes = 20 }) => {
    const { fps } = useVideoConfig();

    // Generate scene data with transcripts
    const scenes = useMemo(() => {
        return Array.from({ length: totalScenes }, (_, i) => ({
            sceneNumber: i + 1,
            audioFile: `Scene ${i + 1}.mp3`,
            images: Array.from({ length: 6 }, (_, j) => ({
                index: j + 1,
                file: `Scene_${String(i + 1).padStart(2, "0")}_${String(j + 1).padStart(2, "0")}.png`,
            })),
            transcript: {
                words: getWordsForScene(i + 1),
            },
        }));
    }, [totalScenes]);

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

