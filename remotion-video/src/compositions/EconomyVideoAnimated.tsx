// EconomyVideoAnimated composition - video clip support alongside existing static renderer

import React, { useMemo } from "react";
import {
    AbsoluteFill,
    Sequence,
    useVideoConfig,
    useCurrentFrame,
    staticFile,
} from "remotion";
import { Audio } from "@remotion/media";
import { AnimatedVideoProps, AnimatedVideoScene } from "../types/animated-video";
import { AnimatedSceneRenderer } from "../components/AnimatedSceneRenderer";
import { CaptionsOverlay } from "../components/CaptionsOverlay";
import { GrainOverlay } from "../effects/GrainOverlay";
import { Vignette } from "../effects/Vignette";
import { calculateSceneTimings } from "../lib/playback";

export const EconomyVideoAnimated: React.FC<AnimatedVideoProps> = ({
    scenes = [],
    voiceoverUrl = "",
    musicUrl = "",
    musicVolume = 0.15,
}) => {
    const { fps } = useVideoConfig();
    const frame = useCurrentFrame();
    const currentTimeSeconds = frame / fps;

    // Crossfade overlap duration
    const CROSSFADE_FRAMES = Math.floor(fps * 0.4);

    // Calculate timing for all scenes
    const sceneTimings = useMemo(
        () => calculateSceneTimings(scenes, fps, CROSSFADE_FRAMES),
        [scenes, fps, CROSSFADE_FRAMES]
    );

    // Collect all words from all scenes for captions
    const allWords = useMemo(() => {
        const words: Array<{ word: string; start: number; end: number }> = [];
        let cumulativeTime = 0;

        scenes.forEach((scene) => {
            if (scene.transcript?.words) {
                scene.transcript.words.forEach((word) => {
                    words.push({
                        word: word.word,
                        start: word.start + cumulativeTime,
                        end: word.end + cumulativeTime,
                    });
                });
            }
            cumulativeTime += scene.duration;
        });

        return words;
    }, [scenes]);

    return (
        <AbsoluteFill style={{ backgroundColor: "#000" }}>
            {/* Voiceover audio */}
            {voiceoverUrl && <Audio src={staticFile(voiceoverUrl)} />}

            {/* Background music (optional) */}
            {musicUrl && <Audio src={staticFile(musicUrl)} volume={musicVolume} />}

            {/* Render all scenes in sequences */}
            {sceneTimings.map(({ scene, startFrame, durationFrames }, index) => (
                <Sequence
                    key={`scene-${scene.sceneNumber}-${index}`}
                    from={startFrame}
                    durationInFrames={durationFrames}
                >
                    <AnimatedSceneRenderer
                        scene={scene}
                        durationFrames={durationFrames}
                        sceneIndex={index}
                    />
                </Sequence>
            ))}

            {/* Captions overlay */}
            {allWords.length > 0 && (
                <CaptionsOverlay
                    words={allWords}
                    currentTimeSeconds={currentTimeSeconds}
                />
            )}

            {/* Film grain overlay */}
            <GrainOverlay intensity={0.12} animated={true} />

            {/* Vignette overlay */}
            <Vignette intensity={0.35} size={0.25} />
        </AbsoluteFill>
    );
};
