import {
    AbsoluteFill,
    Img,
    staticFile,
    useCurrentFrame,
    useVideoConfig,
    interpolate,
    OffthreadVideo,
    Sequence,
} from "remotion";
import { Audio } from "@remotion/media";
import { useMemo, useCallback } from "react";
import {
    Segment,
    getCurrentWordIndex,
    getActiveSegment,
    getSegmentsForScene,
} from "./segments";
import { CaptionsOverlay } from "./components/CaptionsOverlay";
import {
    DocumentaryOverlay,
    getRenderScenesForScene,
    RenderScene,
} from "./renderConfig";

interface SceneProps {
    sceneNumber: number;
    audioFile: string;
    images: Array<{ index: number; file: string; sfx?: string; sfxVolume?: number }>;
    transcript?: TranscriptData;
}

interface TranscriptData {
    words: Array<{
        word: string;
        start: number;
        end: number;
    }>;
}


export const Scene: React.FC<SceneProps> = ({
    sceneNumber,
    audioFile,
    images,
    transcript,
}) => {
    const frame = useCurrentFrame();
    const { fps, durationInFrames } = useVideoConfig();

    const currentTimeSeconds = frame / fps;
    // Check if we have transcript data
    const hasTranscript = transcript?.words && transcript.words.length > 0;

    // Build segments from transcript words - images change based on spoken words
    const segments: Segment[] = useMemo(() => {
        if (!hasTranscript) {
            // Fallback: create time-based segments if no transcript
            const segmentDuration = durationInFrames / fps / images.length;
            return images.map((img, index) => ({
                imageFile: img.file,
                text: "",
                duration: segmentDuration,
                wordStartIndex: index,
                wordEndIndex: index,
            }));
        }
        const segs = getSegmentsForScene(sceneNumber, transcript.words, images.length);

        // Debug: log segment boundaries for Scene 1
        if (sceneNumber === 1) {
            console.log(`Scene ${sceneNumber}: ${segs.length} segments, ${transcript.words.length} words`);
            segs.forEach((s, i) => {
                const startWord = transcript.words[s.wordStartIndex]?.word || 'N/A';
                const startTime = transcript.words[s.wordStartIndex]?.start?.toFixed(1) || 'N/A';
                console.log(`  Seg ${i+1}: words ${s.wordStartIndex}-${s.wordEndIndex}, starts "${startWord}" @ ${startTime}s`);
            });
        }

        return segs;
    }, [sceneNumber, hasTranscript, transcript?.words, images.length, durationInFrames, fps]);

    // Find current segment index based on time (for fallback) or word index
    const activeSegmentIndex = useMemo(() => {
        if (!hasTranscript) {
            // Time-based: divide scene duration by number of segments
            const segmentDurationSeconds = (durationInFrames / fps) / images.length;
            const index = Math.floor(currentTimeSeconds / segmentDurationSeconds);
            return Math.min(index, images.length - 1);
        }
        // Word-based
        const currentWordIndex = getCurrentWordIndex(transcript.words, currentTimeSeconds);
        const segment = getActiveSegment(segments, currentWordIndex);
        if (!segment) return 0;
        return segments.findIndex(s => s.imageFile === segment.imageFile);
    }, [hasTranscript, transcript?.words, segments, currentTimeSeconds, durationInFrames, fps, images.length]);

    // Get the active segment
    const activeSegment = segments[activeSegmentIndex] || segments[0];

    // Calculate segment start frame and duration for proper motion timing
    const segmentTiming = useMemo(() => {
        if (!hasTranscript) {
            // Time-based timing
            const segmentDurationSeconds = (durationInFrames / fps) / images.length;
            const startFrame = Math.floor(activeSegmentIndex * segmentDurationSeconds * fps);
            const segmentDuration = Math.floor(segmentDurationSeconds * fps);
            return { startFrame, durationFrames: segmentDuration };
        }
        // Word-based timing
        const startTime = transcript.words[activeSegment.wordStartIndex]?.start || 0;
        const endTime = transcript.words[activeSegment.wordEndIndex]?.end || startTime + 5;
        const startFrame = Math.floor(startTime * fps);
        const segmentDuration = Math.floor((endTime - startTime) * fps);
        return { startFrame, durationFrames: segmentDuration };
    }, [hasTranscript, transcript?.words, activeSegment, activeSegmentIndex, fps, durationInFrames, images.length]);

    // Crossfade overlap duration (in frames) - clips overlap for smooth transitions
    const CROSSFADE_FRAMES = Math.floor(fps * 0.4); // 0.4 second overlap

    // Calculate timing using AIRTABLE DURATIONS (cumulative timing)
    // This is more reliable than word matching since transcription may differ from written text
    const segmentTimings = useMemo(() => {
        let cumulativeStart = 0;

        return segments.map((seg, index) => {
            const startFrame = Math.floor(cumulativeStart * fps);
            const baseDurationFrames = Math.floor(seg.duration * fps);

            // Extend duration for crossfade overlap (except last segment)
            const durationFrames = baseDurationFrames + (index < segments.length - 1 ? CROSSFADE_FRAMES : 0);

            // Accumulate for next segment
            cumulativeStart += seg.duration;

            return {
                imageFile: seg.imageFile,
                startFrame,
                durationFrames,
            };
        });
    }, [segments, fps, CROSSFADE_FRAMES]);

    // SFX fade duration in frames (0.3s)
    const SFX_FADE_FRAMES = Math.floor(fps * 0.3);

    // Load per-image Ken Burns + transition data from render_config
    const renderScenes = useMemo(
        () => getRenderScenesForScene(sceneNumber),
        [sceneNumber],
    );

    return (
        <AbsoluteFill>
            {/* Audio for this scene */}
            <Audio src={staticFile(audioFile)} />

            {/* Render all clips in Sequences - proper Remotion pattern for sequential video */}
            {segmentTimings.map((timing, index) => {
                const img = images[index];
                // Match render_config entry by image_index (1-based)
                const rs = renderScenes[index] as RenderScene | undefined;
                const overlay: DocumentaryOverlay | undefined = rs?.overlay ?? (
                    rs?.caption_title
                        ? {
                            kind: "identity",
                            title: rs.caption_title,
                            body: rs.caption_sub ?? "",
                            position: "bottom_left",
                        }
                        : undefined
                );
                return (
                    <Sequence
                        key={timing.imageFile}
                        from={timing.startFrame}
                        durationInFrames={timing.durationFrames}
                    >
                        <DynamicImage
                            imageFile={timing.imageFile}
                            motionIndex={index}
                            segmentDurationFrames={timing.durationFrames}
                            kenBurns={rs?.ken_burns}
                            transitionIn={rs?.transition_in}
                            transitionOut={rs?.transition_out}
                        />
                        {overlay && (
                            <DocumentaryInfoCard
                                overlay={overlay}
                                segmentDurationFrames={timing.durationFrames}
                                transitionIn={rs?.transition_in}
                                transitionOut={rs?.transition_out}
                            />
                        )}
                        {/* Per-image sound effect — plays for exactly the image duration */}
                        {img?.sfx && (
                            <ImageSfxAudio
                                sfxFile={img.sfx}
                                volume={img.sfxVolume ?? 0.15}
                                durationFrames={timing.durationFrames}
                                fadeFrames={SFX_FADE_FRAMES}
                            />
                        )}
                    </Sequence>
                );
            })}

            {/* Karaoke captions — word-level highlight synced to audio */}
            {/* Uses character-based chunking (max 38 chars) to prevent overflow */}
            {hasTranscript && transcript?.words && transcript.words.length > 0 && (
                <CaptionsOverlay
                    words={transcript.words}
                    currentTimeSeconds={currentTimeSeconds}
                />
            )}
        </AbsoluteFill>
    );
};

const DocumentaryInfoCard: React.FC<{
    overlay: DocumentaryOverlay;
    segmentDurationFrames: number;
    transitionIn?: Record<string, unknown>;
    transitionOut?: Record<string, unknown>;
}> = ({ overlay, segmentDurationFrames, transitionIn, transitionOut }) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();

    const fadeInSeconds = (transitionIn?.duration as number) ?? 0.4;
    const fadeOutSeconds = (transitionOut?.duration as number) ?? 0.4;
    const fadeInFrames = Math.max(1, Math.floor(fps * fadeInSeconds));
    const fadeOutFrames = Math.max(1, Math.floor(fps * fadeOutSeconds));
    const fadeOutStart = Math.max(
        fadeInFrames,
        segmentDurationFrames - fadeOutFrames,
    );
    const fadeIn = interpolate(frame, [0, fadeInFrames], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
    });
    const fadeOut = interpolate(
        frame,
        [fadeOutStart, segmentDurationFrames],
        [1, 0],
        {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
        },
    );
    const transitionInType = (transitionIn?.type as string) ?? "crossfade";
    const transitionOutType = (transitionOut?.type as string) ?? "crossfade";
    const opacity = Math.min(
        transitionInType === "cut" ? 1 : fadeIn,
        transitionOutType === "cut" ? 1 : fadeOut,
    );

    return (
        <div
            style={{
                position: "absolute",
                left: overlay.position === "bottom_left" ? 76 : undefined,
                right: overlay.position === "bottom_right" ? 76 : undefined,
                bottom: 68,
                width: 940,
                height: 230,
                boxSizing: "border-box",
                padding: "22px 30px 23px 28px",
                background: "rgba(250, 249, 246, 0.92)",
                borderLeft: "7px solid #a88345",
                boxShadow: "0 16px 40px rgba(0, 0, 0, 0.16)",
                color: "#252525",
                opacity,
                fontFamily: "Georgia, 'Times New Roman', serif",
                overflow: "hidden",
            }}
        >
            <div
                style={{
                    fontFamily: "Arial, Helvetica, sans-serif",
                    fontSize: 22,
                    fontWeight: 800,
                    letterSpacing: 1.4,
                    lineHeight: 1.1,
                    color: overlay.kind === "spec" ? "#765b2e" : "#54504a",
                    textTransform: overlay.kind === "spec" ? "uppercase" : "none",
                }}
            >
                {overlay.title}
            </div>
            <div
                style={{
                    display: "-webkit-box",
                    WebkitBoxOrient: "vertical",
                    WebkitLineClamp: overlay.kind === "script" ? 3 : 2,
                    overflow: "hidden",
                    fontSize: overlay.kind === "script" ? 34 : 43,
                    fontWeight: overlay.kind === "script" ? 500 : 600,
                    letterSpacing: 0.25,
                    lineHeight: overlay.kind === "script" ? 1.18 : 1.12,
                    marginTop: 13,
                }}
            >
                {overlay.body.slice(0, 150)}
            </div>
        </div>
    );
};

// Per-image sound effect — simple fade in/out at the image's volume
const ImageSfxAudio: React.FC<{
    sfxFile: string;
    volume: number;
    durationFrames: number;
    fadeFrames: number;
}> = ({ sfxFile, volume, durationFrames, fadeFrames }) => {
    const getVolume = useCallback(
        (f: number) => {
            if (durationFrames < fadeFrames * 2 + 2) {
                return volume;
            }
            return interpolate(
                f,
                [0, fadeFrames, durationFrames - fadeFrames, durationFrames],
                [0, volume, volume, 0],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
            );
        },
        [durationFrames, fadeFrames, volume],
    );

    return <Audio src={staticFile(sfxFile)} volume={getVolume} />;
};

// Check if a video file was explicitly provided for this segment
// Returns non-null only when the imageFile is already an .mp4 path
// For PNG-only projects, this will always return null
const getVideoFile = (imageFile: string): string | null => {
    if (imageFile.endsWith('.mp4')) {
        return imageFile;
    }
    return null;
};

// Video clip component - plays within a Sequence
// In Remotion 4.0+, videos inside Sequences automatically sync to Sequence timeline
const VideoClip: React.FC<{
    videoFile: string;
    durationFrames: number;
}> = ({ videoFile, durationFrames }) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();

    // Crossfade transition: fade in at start, fade out at end
    const FADE_FRAMES = Math.floor(fps * 0.4); // 0.4 second fade

    // Safety: ensure we have enough frames for the fade curve
    const safeDuration = Math.max(durationFrames, FADE_FRAMES * 2 + 1);
    const fadeOutStart = Math.max(FADE_FRAMES + 1, safeDuration - FADE_FRAMES);

    const opacity = interpolate(
        frame,
        [0, FADE_FRAMES, fadeOutStart, safeDuration],
        [0, 1, 1, 0],
        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
    );

    return (
        <AbsoluteFill style={{ opacity }}>
            <OffthreadVideo
                src={staticFile(videoFile)}
                muted
                style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                }}
            />
        </AbsoluteFill>
    );
};

// Camera motion component - CONTINUOUS motion, never stops
// When inside a Sequence, useCurrentFrame() returns frame relative to Sequence start
const DynamicImage: React.FC<{
    imageFile: string;
    motionIndex: number;
    segmentDurationFrames: number;
    kenBurns?: Record<string, unknown>;
    transitionIn?: Record<string, unknown>;
    transitionOut?: Record<string, unknown>;
}> = ({ imageFile, motionIndex, segmentDurationFrames, kenBurns, transitionIn, transitionOut }) => {
    // Inside Sequence: frame is already relative to segment start
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();

    // Check if this segment has a video clip
    const videoFile = getVideoFile(imageFile);
    if (videoFile) {
        return <VideoClip videoFile={videoFile} durationFrames={segmentDurationFrames} />;
    }

    // Frame is relative to Sequence start (0-based)
    const localFrame = frame;

    // Transition durations from render_config (fall back to 0.4s crossfade)
    const fadeInDuration = (transitionIn?.duration as number) ?? 0.4;
    const fadeOutDuration = (transitionOut?.duration as number) ?? 0.4;
    const FADE_IN_FRAMES = Math.floor(fps * fadeInDuration);
    const FADE_OUT_FRAMES = Math.floor(fps * fadeOutDuration);

    // Transition type determines opacity curve
    const transInType = (transitionIn?.type as string) ?? "crossfade";
    const transOutType = (transitionOut?.type as string) ?? "crossfade";

    // Safety: ensure we have enough frames for the fade curve
    const safeDuration = Math.max(segmentDurationFrames, FADE_IN_FRAMES + FADE_OUT_FRAMES + 1);
    const fadeOutStart = Math.max(FADE_IN_FRAMES + 1, safeDuration - FADE_OUT_FRAMES);

    // "cut" transitions are instant (no fade), "dip_to_black" uses full fade
    const fadeInTarget = transInType === "cut" ? 0 : FADE_IN_FRAMES;
    const fadeOutTarget = transOutType === "cut" ? 0 : FADE_OUT_FRAMES;

    const opacity = interpolate(
        localFrame,
        [0, Math.max(fadeInTarget, 1), fadeOutStart, fadeOutStart + Math.max(fadeOutTarget, 1)],
        [transInType === "cut" ? 1 : 0, 1, 1, transOutType === "fade_to_black" || transOutType === "dip_to_black" ? 0 : 0],
        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
    );

    // Progress through FULL segment - motion NEVER stops
    const progress = Math.min(
        localFrame / Math.max(segmentDurationFrames - 1, 1),
        1,
    );

    let scale = 1;
    let translateX = 0;
    let translateY = 0;

    // Use Ken Burns data from render_config if available
    const direction = kenBurns?.direction as string | undefined;
    const speedMultiplier = (kenBurns?.speed_multiplier as number) ?? 1.0;

    if (direction && kenBurns) {
        // Profile-aware Ken Burns from render_config
        const startScale = (kenBurns.start_scale as number) ?? 1.0;
        const endScale = (kenBurns.end_scale as number) ?? startScale;
        const startXOffset = (kenBurns.start_x_offset as number) ?? 0;
        const endXOffset = (kenBurns.end_x_offset as number) ?? 0;
        const startYOffset = (kenBurns.start_y_offset as number) ?? 0;
        const endYOffset = (kenBurns.end_y_offset as number) ?? 0;

        // DvsU motion uses a full-duration smoothstep: zero velocity at both
        // ends, monotonic in between, and exactly complete on the last frame.
        // Legacy configs retain their previous speed-multiplier behavior.
        const motionCurve = kenBurns.motion_curve as string | undefined;
        const adjustedProgress = motionCurve === "cinematic_smoothstep"
            ? progress * progress * (3 - 2 * progress)
            : Math.min(progress * speedMultiplier, 1);

        // Scale interpolation
        scale = startScale + (endScale - startScale) * adjustedProgress;

        // Pan/tilt interpolation
        translateX = startXOffset + (endXOffset - startXOffset) * adjustedProgress;
        translateY = startYOffset + (endYOffset - startYOffset) * adjustedProgress;
    } else {
        // Fallback: 6 hardcoded patterns (for Studio preview or missing config)
        const pattern = motionIndex % 6;
        const baseZoom = 1.0 + progress * 0.25;

        switch (pattern) {
            case 0:
                scale = baseZoom;
                translateX = -progress * 80;
                translateY = -progress * 30;
                break;
            case 1:
                scale = 1.25 - progress * 0.20;
                translateX = progress * 80;
                translateY = progress * 20;
                break;
            case 2:
                scale = 1.05 + progress * 0.20;
                translateX = 50 - progress * 100;
                break;
            case 3:
                scale = 1.05 + progress * 0.20;
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
    }

    if (!kenBurns?.disable_breathe) {
        // Legacy non-static compositions keep their existing organic motion.
        const breathe = Math.sin(localFrame * 0.08) * 3;
        translateX += breathe;
        translateY += breathe * 0.6;
    }

    return (
        <AbsoluteFill style={{ opacity }}>
            <Img
                src={staticFile(imageFile)}
                style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    transform: `scale(${scale}) translate(${translateX}px, ${translateY}px)`,
                    transformOrigin: "center center",
                }}
            />
        </AbsoluteFill>
    );
};
