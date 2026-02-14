// Transition logic for animated video clips

import { interpolate } from "remotion";
import { ShotType, TransitionType, TransitionConfig } from "../types/animated-video";

// Map shot types to preferred transition styles
const SHOT_TRANSITION_MAP: Record<ShotType, TransitionType> = {
    wide_establishing: "fade",
    isometric_diorama: "crossfade",
    medium_human_story: "crossfade",
    close_up_vignette: "iris",
    data_landscape: "wipe",
    split_screen: "slide",
    pull_back_reveal: "fade",
    overhead_map: "clockWipe",
    journey_shot: "slide",
};

// Get transition config based on shot type
export function getTransitionForScene(
    shotType: ShotType | undefined,
    isHeroShot: boolean,
    fps: number
): TransitionConfig {
    const type = shotType ? SHOT_TRANSITION_MAP[shotType] : "crossfade";

    // Hero shots get longer transitions
    const baseDuration = isHeroShot ? 0.6 : 0.4;
    const duration = Math.floor(baseDuration * fps);

    return {
        type,
        duration,
        direction: type === "slide" ? "left" : undefined,
    };
}

// Calculate opacity for crossfade/fade transitions
export function getFadeOpacity(
    frame: number,
    durationFrames: number,
    fadeInFrames: number,
    fadeOutFrames: number
): number {
    const fadeOutStart = Math.max(fadeInFrames + 1, durationFrames - fadeOutFrames);

    return interpolate(
        frame,
        [0, fadeInFrames, fadeOutStart, durationFrames],
        [0, 1, 1, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );
}

// Calculate wipe progress (0 to 1)
export function getWipeProgress(
    frame: number,
    durationFrames: number,
    transitionFrames: number,
    isEntrance: boolean
): number {
    if (isEntrance) {
        return interpolate(
            frame,
            [0, transitionFrames],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
        );
    } else {
        const exitStart = durationFrames - transitionFrames;
        return interpolate(
            frame,
            [exitStart, durationFrames],
            [1, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
        );
    }
}

// Calculate iris (circular reveal) progress
export function getIrisProgress(
    frame: number,
    durationFrames: number,
    transitionFrames: number,
    isEntrance: boolean
): number {
    const maxRadius = 150; // percentage of viewport diagonal

    if (isEntrance) {
        return interpolate(
            frame,
            [0, transitionFrames],
            [0, maxRadius],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
        );
    } else {
        const exitStart = durationFrames - transitionFrames;
        return interpolate(
            frame,
            [exitStart, durationFrames],
            [maxRadius, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
        );
    }
}

// Calculate slide offset
export function getSlideOffset(
    frame: number,
    durationFrames: number,
    transitionFrames: number,
    direction: "left" | "right" | "up" | "down",
    isEntrance: boolean
): { x: number; y: number } {
    const offset = 100; // percentage

    const directionMap = {
        left: { x: -offset, y: 0 },
        right: { x: offset, y: 0 },
        up: { x: 0, y: -offset },
        down: { x: 0, y: offset },
    };

    const targetOffset = directionMap[direction];

    if (isEntrance) {
        const progress = interpolate(
            frame,
            [0, transitionFrames],
            [1, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
        );
        return {
            x: targetOffset.x * progress,
            y: targetOffset.y * progress,
        };
    } else {
        const exitStart = durationFrames - transitionFrames;
        const progress = interpolate(
            frame,
            [exitStart, durationFrames],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
        );
        return {
            x: -targetOffset.x * progress,
            y: -targetOffset.y * progress,
        };
    }
}
