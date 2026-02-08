// Light leak overlay effect for hero shots

import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";

interface LightLeakProps {
    duration: number; // in frames
    color?: string;
    position?: "left" | "right" | "top" | "bottom";
}

export const LightLeak: React.FC<LightLeakProps> = ({
    duration,
    color = "#FFE135",
    position = "right",
}) => {
    const frame = useCurrentFrame();

    // Light leak appears for first 30% of duration, then fades
    const leakDuration = Math.floor(duration * 0.3);

    const opacity = interpolate(
        frame,
        [0, leakDuration * 0.3, leakDuration * 0.7, leakDuration],
        [0, 0.4, 0.3, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );

    // Animate the position slightly
    const drift = interpolate(frame, [0, leakDuration], [0, 20], {
        extrapolateRight: "clamp",
    });

    const positionStyles: Record<string, React.CSSProperties> = {
        right: {
            background: `linear-gradient(to left, ${color}88, transparent 60%)`,
            transform: `translateX(${drift}px)`,
        },
        left: {
            background: `linear-gradient(to right, ${color}88, transparent 60%)`,
            transform: `translateX(-${drift}px)`,
        },
        top: {
            background: `linear-gradient(to bottom, ${color}88, transparent 60%)`,
            transform: `translateY(-${drift}px)`,
        },
        bottom: {
            background: `linear-gradient(to top, ${color}88, transparent 60%)`,
            transform: `translateY(${drift}px)`,
        },
    };

    if (frame > leakDuration) return null;

    return (
        <AbsoluteFill
            style={{
                pointerEvents: "none",
                mixBlendMode: "screen",
                opacity,
                ...positionStyles[position],
            }}
        />
    );
};
