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
import { useMemo } from "react";
import {
    Segment,
    getCurrentWordIndex,
    getActiveSegment,
    getSegmentsForScene,
} from "./segments";

interface SceneProps {
    sceneNumber: number;
    audioFile: string;
    images: Array<{ index: number; file: string }>;
    transcript?: TranscriptData;
}

interface TranscriptData {
    words: Array<{
        word: string;
        start: number;
        end: number;
    }>;
}

// Style constants from user preferences
const STYLE = {
    font: {
        family: "Inter",
        weight: 900,
        size: 80,
        letterSpacing: "0.01em",
        wordGap: 20,
    },
    colors: {
        current: "#FFE135", // Bright yellow - currently spoken word
        past: "#FFFFFF", // White - already spoken
        future: "#888888", // Gray - not yet spoken
        glow: "none",
        textStroke: "8px #000000", // Thick black outline
    },
    position: {
        bottom: 120,
        gradientHeight: "40%",
    },
    chunking: {
        wordsPerChunk: 4,
    },
};

export const Scene: React.FC<SceneProps> = ({
    sceneNumber,
    audioFile,
    images,
    transcript,
}) => {
    const frame = useCurrentFrame();
    const { fps, durationInFrames } = useVideoConfig();

    const currentTimeSeconds = frame / fps;
    const currentTimeMs = currentTimeSeconds * 1000;

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

    return (
        <AbsoluteFill>
            {/* Audio for this scene */}
            <Audio src={staticFile(audioFile)} />

            {/* Render all clips in Sequences - proper Remotion pattern for sequential video */}
            {segmentTimings.map((timing, index) => (
                <Sequence
                    key={timing.imageFile}
                    from={timing.startFrame}
                    durationInFrames={timing.durationFrames}
                >
                    <DynamicImage
                        imageFile={timing.imageFile}
                        motionIndex={index}
                        segmentDurationFrames={timing.durationFrames}
                    />
                </Sequence>
            ))}

            {/* Gradient overlay for caption readability */}
            <AbsoluteFill
                style={{
                    display: "flex",
                    background: `linear-gradient(to top, rgba(0,0,0,0.85) 0%, transparent ${STYLE.position.gradientHeight})`,
                    justifyContent: "flex-end",
                    alignItems: "center",
                    paddingBottom: STYLE.position.bottom,
                }}
            >
                {/* Caption display */}
                <div
                    style={{
                        display: "flex",
                        flexWrap: "wrap",
                        justifyContent: "center",
                        gap: STYLE.font.wordGap,
                        maxWidth: "80%",
                        fontFamily: STYLE.font.family,
                        fontWeight: STYLE.font.weight,
                        fontSize: STYLE.font.size,
                        letterSpacing: STYLE.font.letterSpacing,
                    }}
                >
                    {transcript?.words ? (
                        <KaraokeCaption words={transcript.words} currentTimeMs={currentTimeMs} />
                    ) : (
                        <span style={{ color: STYLE.colors.past }}>Scene {sceneNumber}</span>
                    )}
                </div>
            </AbsoluteFill>
        </AbsoluteFill>
    );
};

// Karaoke caption component with word-by-word highlighting
const KaraokeCaption: React.FC<{
    words: Array<{ word: string; start: number; end: number }>;
    currentTimeMs: number;
}> = ({ words, currentTimeMs }) => {
    const currentTimeSec = currentTimeMs / 1000;

    // Chunk words into groups of 4
    const chunks: Array<Array<{ word: string; start: number; end: number; originalIndex: number }>> = [];
    for (let i = 0; i < words.length; i += STYLE.chunking.wordsPerChunk) {
        chunks.push(words.slice(i, i + STYLE.chunking.wordsPerChunk).map((w, idx) => ({
            ...w,
            originalIndex: i + idx,
        })));
    }

    // Find current chunk based on time
    const currentChunkIndex = chunks.findIndex((chunk) => {
        const chunkStart = chunk[0].start;
        const chunkEnd = chunk[chunk.length - 1].end;
        return currentTimeSec >= chunkStart && currentTimeSec <= chunkEnd;
    });

    // If between chunks, show the next chunk
    let activeChunkIndex = currentChunkIndex;
    if (activeChunkIndex === -1) {
        // Find the next upcoming chunk
        activeChunkIndex = chunks.findIndex((chunk) => chunk[0].start > currentTimeSec);
        if (activeChunkIndex === -1) activeChunkIndex = chunks.length - 1;
    }

    const currentChunk = chunks[activeChunkIndex];

    if (!currentChunk) return null;

    // Find which word is currently being spoken
    const currentWordIndex = words.findIndex(
        (w) => currentTimeSec >= w.start && currentTimeSec <= w.end
    );

    return (
        <>
            {currentChunk.map((wordData) => {
                // Clean word (remove trailing punctuation but preserve contractions)
                const cleanWord = wordData.word.replace(/[.,!?;:]$/, "");

                // Determine word state: past, current, or future
                let color = STYLE.colors.future;
                if (wordData.originalIndex < currentWordIndex) {
                    color = STYLE.colors.past;
                } else if (wordData.originalIndex === currentWordIndex) {
                    color = STYLE.colors.current;
                }

                return (
                    <span
                        key={`${wordData.start}-${wordData.originalIndex}`}
                        style={{
                            color: color,
                            WebkitTextStroke: STYLE.colors.textStroke,
                            paintOrder: "stroke fill",
                            display: "inline-block",
                            transition: "color 0.1s ease-out",
                        }}
                    >
                        {cleanWord}
                    </span>
                );
            })}
        </>
    );
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
}> = ({ imageFile, motionIndex, segmentDurationFrames }) => {
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

    // Crossfade transition: fade in at start, fade out at end
    const FADE_FRAMES = Math.floor(fps * 0.4); // 0.4 second fade

    // Safety: ensure we have enough frames for the fade curve
    const safeDuration = Math.max(segmentDurationFrames, FADE_FRAMES * 2 + 1);
    const fadeOutStart = Math.max(FADE_FRAMES + 1, safeDuration - FADE_FRAMES);

    const opacity = interpolate(
        localFrame,
        [0, FADE_FRAMES, fadeOutStart, safeDuration],
        [0, 1, 1, 0],
        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
    );

    // Progress through FULL segment - motion NEVER stops
    const progress = Math.min(localFrame / segmentDurationFrames, 1);

    // 6 continuous motion patterns that run the entire duration
    const pattern = motionIndex % 6;

    let scale = 1;
    let translateX = 0;
    let translateY = 0;

    // Base zoom that's always happening (100% to 125% over segment)
    const baseZoom = 1.0 + progress * 0.25;

    // Layered motion - zoom + pan + drift all happening together
    switch (pattern) {
        case 0:
            // Push in + drift right - continuous diagonal movement
            scale = baseZoom;
            translateX = -progress * 80; // Drifts right (negative moves image left, view goes right)
            translateY = -progress * 30; // Slight upward drift
            break;

        case 1:
            // Pull out + drift left - reverse energy
            scale = 1.25 - progress * 0.20; // 125% down to 105%
            translateX = progress * 80; // Drifts left
            translateY = progress * 20; // Slight downward
            break;

        case 2:
            // Continuous pan right with steady zoom
            scale = 1.05 + progress * 0.20;
            translateX = 50 - progress * 100; // 50 to -50
            break;

        case 3:
            // Continuous pan left with steady zoom
            scale = 1.05 + progress * 0.20;
            translateX = -50 + progress * 100; // -50 to 50
            break;

        case 4:
            // Rise up throughout - reveals and builds
            scale = baseZoom;
            translateY = 60 - progress * 120; // 60 to -60 (continuous rise)
            translateX = -progress * 30; // Subtle side drift
            break;

        case 5:
            // Sink down with zoom - weight and gravity
            scale = 1.25 - progress * 0.15;
            translateY = -50 + progress * 100; // -50 to 50 (continuous fall)
            translateX = progress * 25;
            break;
    }

    // Add subtle organic "breathing" motion on top of everything
    const breathe = Math.sin(localFrame * 0.08) * 3;
    translateX += breathe;
    translateY += breathe * 0.6;

    return (
        <AbsoluteFill style={{ opacity }}>
            <Img
                src={staticFile(imageFile)}
                style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    transform: `scale(${scale}) translate(${translateX}px, ${translateY}px)`,
                }}
            />
        </AbsoluteFill>
    );
};
