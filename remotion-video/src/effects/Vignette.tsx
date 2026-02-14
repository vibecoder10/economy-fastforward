// Vignette overlay effect

import React from "react";
import { AbsoluteFill } from "remotion";

interface VignetteProps {
    intensity?: number; // 0-1, default 0.4
    size?: number; // 0-1, how far the vignette extends, default 0.3
}

export const Vignette: React.FC<VignetteProps> = ({
    intensity = 0.4,
    size = 0.3,
}) => {
    // Calculate gradient stops based on size
    const innerStop = Math.floor((1 - size) * 100);
    const outerStop = 100;

    return (
        <AbsoluteFill
            style={{
                pointerEvents: "none",
                background: `radial-gradient(
                    ellipse at center,
                    transparent ${innerStop}%,
                    rgba(0, 0, 0, ${intensity}) ${outerStop}%
                )`,
            }}
        />
    );
};
