export interface DocumentaryTransition {
    type?: unknown;
    duration?: unknown;
}

export interface DocumentaryTimingSegment {
    imageFile: string;
    duration: number;
}

export interface DocumentaryTimingScene {
    transition_in?: DocumentaryTransition;
    transition_out?: DocumentaryTransition;
}

export interface DocumentarySequenceTiming {
    imageFile: string;
    startFrame: number;
    durationFrames: number;
}

const DEFAULT_TRANSITION_SECONDS = 0.4;

export const documentaryTransitionFrames = (
    transition: DocumentaryTransition | undefined,
    fps: number,
): number => {
    if (transition?.type === "cut") return 0;
    const rawDuration = transition?.duration;
    const duration = typeof rawDuration === "number" && Number.isFinite(rawDuration)
        ? rawDuration
        : DEFAULT_TRANSITION_SECONDS;
    if (duration <= 0) return 0;
    return Math.max(1, Math.floor(duration * fps));
};

export const buildDocumentarySequenceTimings = (
    segments: DocumentaryTimingSegment[],
    scenes: DocumentaryTimingScene[],
    fps: number,
): DocumentarySequenceTiming[] => {
    let cumulativeStart = 0;
    return segments.map((segment, index) => {
        const startFrame = Math.floor(cumulativeStart * fps);
        const baseDurationFrames = Math.floor(segment.duration * fps);
        const overlapFrames = index < segments.length - 1
            ? documentaryTransitionFrames(scenes[index]?.transition_out, fps)
            : 0;
        cumulativeStart += segment.duration;
        return {
            imageFile: segment.imageFile,
            startFrame,
            durationFrames: baseDurationFrames + overlapFrames,
        };
    });
};

export const activeDocumentaryOverlay = <Overlay>(
    absoluteFrame: number,
    timings: DocumentarySequenceTiming[],
    overlays: Array<Overlay | undefined>,
    sceneEndFrame: number,
): Overlay | undefined => {
    if (
        absoluteFrame < 0
        || absoluteFrame >= sceneEndFrame
        || timings.length === 0
        || absoluteFrame < timings[0].startFrame
    ) {
        return undefined;
    }

    let activeIndex = -1;
    for (let index = 0; index < timings.length; index += 1) {
        const timing = timings[index];
        if (index === 0) {
            activeIndex = 0;
            continue;
        }

        const previousTiming = timings[index - 1];
        const previousEndFrame = previousTiming.startFrame + previousTiming.durationFrames;
        const overlapFrames = Math.max(0, previousEndFrame - timing.startFrame);
        const crossoverFrame = timing.startFrame + Math.ceil(overlapFrames / 2);
        if (absoluteFrame < crossoverFrame) break;
        activeIndex = index;
    }
    return activeIndex >= 0 ? overlays[activeIndex] : undefined;
};

const clampUnit = (value: number): number => Math.max(0, Math.min(1, value));

export const documentaryTransitionOpacity = (
    localFrame: number,
    sequenceDurationFrames: number,
    transitionIn: DocumentaryTransition | undefined,
    transitionOut: DocumentaryTransition | undefined,
    fps: number,
): number => {
    const fadeInFrames = documentaryTransitionFrames(transitionIn, fps);
    const fadeOutFrames = documentaryTransitionFrames(transitionOut, fps);
    const fadeIn = fadeInFrames > 0
        ? clampUnit(localFrame / fadeInFrames)
        : 1;
    const fadeOutStart = sequenceDurationFrames - fadeOutFrames;
    const fadeOut = fadeOutFrames > 0
        ? clampUnit((sequenceDurationFrames - localFrame) / fadeOutFrames)
        : 1;
    return Math.min(fadeIn, localFrame >= fadeOutStart ? fadeOut : 1);
};
