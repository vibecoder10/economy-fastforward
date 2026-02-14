// Film grain overlay effect

import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";

interface GrainOverlayProps {
    intensity?: number; // 0-1, default 0.15
    animated?: boolean;
}

export const GrainOverlay: React.FC<GrainOverlayProps> = ({
    intensity = 0.15,
    animated = true,
}) => {
    const frame = useCurrentFrame();

    // Animate grain by shifting the SVG pattern
    const offset = animated ? (frame % 100) * 0.5 : 0;

    // Subtle flicker for organic feel
    const flicker = animated
        ? interpolate(Math.sin(frame * 0.3), [-1, 1], [0.8, 1.2])
        : 1;

    const adjustedIntensity = intensity * flicker;

    return (
        <AbsoluteFill
            style={{
                pointerEvents: "none",
                mixBlendMode: "overlay",
                opacity: adjustedIntensity,
            }}
        >
            <svg
                width="100%"
                height="100%"
                xmlns="http://www.w3.org/2000/svg"
                style={{
                    transform: `translate(${offset}px, ${offset}px)`,
                }}
            >
                <defs>
                    <filter id="grain" x="0%" y="0%" width="100%" height="100%">
                        <feTurbulence
                            type="fractalNoise"
                            baseFrequency="0.8"
                            numOctaves="4"
                            seed={frame % 10}
                            stitchTiles="stitch"
                        />
                        <feColorMatrix type="saturate" values="0" />
                    </filter>
                </defs>
                <rect
                    width="100%"
                    height="100%"
                    filter="url(#grain)"
                    opacity="1"
                />
            </svg>
        </AbsoluteFill>
    );
};
