// Animated scene renderer for video clips

import React from "react";
import {
    AbsoluteFill,
    Img,
    OffthreadVideo,
    staticFile,
    useCurrentFrame,
    useVideoConfig,
    interpolate,
} from "remotion";
import { AnimatedVideoScene } from "../types/animated-video";
import { getTransitionForScene, getFadeOpacity } from "../lib/transitions";
import { LightLeak } from "../effects/LightLeak";

interface AnimatedSceneRendererProps {
    scene: AnimatedVideoScene;
    durationFrames: number;
    sceneIndex: number;
}

export const AnimatedSceneRenderer: React.FC<AnimatedSceneRendererProps> = ({
    scene,
    durationFrames,
    sceneIndex,
}) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();

    // Get transition config based on shot type
    const transition = getTransitionForScene(
        scene.shotType,
        scene.isHeroShot || false,
        fps
    );

    // Calculate opacity for crossfade
    const opacity = getFadeOpacity(
        frame,
        durationFrames,
        transition.duration,
        transition.duration
    );

    // Ken Burns effect for images
    const getKenBurnsTransform = () => {
        const progress = frame / durationFrames;
        const pattern = sceneIndex % 6;

        let scale = 1;
        let translateX = 0;
        let translateY = 0;

        const baseZoom = 1.0 + progress * 0.25;

        switch (pattern) {
            case 0:
                scale = baseZoom;
                translateX = -progress * 80;
                translateY = -progress * 30;
                break;
            case 1:
                scale = 1.25 - progress * 0.2;
                translateX = progress * 80;
                translateY = progress * 20;
                break;
            case 2:
                scale = 1.05 + progress * 0.2;
                translateX = 50 - progress * 100;
                break;
            case 3:
                scale = 1.05 + progress * 0.2;
                translateX = -50 + progress * 100;
                break;
            case 4:
                scale = baseZoom;
                translateY = 60 - progress * 120;
                translateX = -progress * 30;
                break;
            case 5:
                scale = 1.25 - progress * 0.15;
                translateY = -50 + progress * 100;
                translateX = progress * 25;
                break;
        }

        // Breathing motion
        const breathe = Math.sin(frame * 0.08) * 3;
        translateX += breathe;
        translateY += breathe * 0.6;

        return `scale(${scale}) translate(${translateX}px, ${translateY}px)`;
    };

    const renderContent = () => {
        if (scene.assetType === "video") {
            return (
                <OffthreadVideo
                    src={staticFile(scene.assetUrl)}
                    muted
                    style={{
                        width: "100%",
                        height: "100%",
                        objectFit: "cover",
                    }}
                />
            );
        }

        // Fallback to image with Ken Burns
        return (
            <Img
                src={staticFile(scene.assetUrl)}
                style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    transform: getKenBurnsTransform(),
                }}
            />
        );
    };

    return (
        <AbsoluteFill style={{ opacity }}>
            {renderContent()}

            {/* Light leak effect for hero shots */}
            {scene.isHeroShot && (
                <LightLeak
                    duration={durationFrames}
                    color="#FFE135"
                    position={sceneIndex % 2 === 0 ? "right" : "left"}
                />
            )}
        </AbsoluteFill>
    );
};
