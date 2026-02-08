// Playback calculations for video clips

import { AnimatedVideoScene } from "../types/animated-video";

export interface PlaybackTiming {
    startFrame: number;
    durationFrames: number;
    playbackRate: number;
}

// Calculate playback timing for a scene
export function calculatePlayback(
    scene: AnimatedVideoScene,
    fps: number,
    videoDurationSeconds: number,
    crossfadeFrames: number
): PlaybackTiming {
    const targetDurationFrames = Math.floor(scene.duration * fps);

    // If video is shorter than target duration, calculate playback rate to stretch
    // If video is longer, we'll trim it
    let playbackRate = 1.0;

    if (videoDurationSeconds > 0 && videoDurationSeconds < scene.duration) {
        // Video is shorter - slow it down slightly (min 0.8x)
        playbackRate = Math.max(0.8, videoDurationSeconds / scene.duration);
    } else if (videoDurationSeconds > scene.duration) {
        // Video is longer - speed it up slightly (max 1.2x)
        playbackRate = Math.min(1.2, videoDurationSeconds / scene.duration);
    }

    return {
        startFrame: 0,
        durationFrames: targetDurationFrames + crossfadeFrames,
        playbackRate,
    };
}

// Calculate cumulative timing for all scenes
export function calculateSceneTimings(
    scenes: AnimatedVideoScene[],
    fps: number,
    crossfadeFrames: number
): Array<{ scene: AnimatedVideoScene; startFrame: number; durationFrames: number }> {
    let cumulativeFrame = 0;

    return scenes.map((scene) => {
        const startFrame = cumulativeFrame;
        const baseDurationFrames = Math.floor(scene.duration * fps);
        const durationFrames = baseDurationFrames + crossfadeFrames;

        // Next scene starts at the end of this scene's base duration (overlap for crossfade)
        cumulativeFrame += baseDurationFrames;

        return {
            scene,
            startFrame,
            durationFrames,
        };
    });
}

// Get total composition duration
export function getTotalDuration(
    scenes: AnimatedVideoScene[],
    fps: number
): number {
    return scenes.reduce((total, scene) => total + Math.floor(scene.duration * fps), 0);
}
