import {
    AbsoluteFill,
    Img,
    staticFile,
    useCurrentFrame,
    useVideoConfig,
    interpolate,
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
        weight: 800,
        size: 72,
        letterSpacing: "0.02em",
        wordGap: 24,
    },
    colors: {
        current: "#FFD700", // Golden Yellow
        past: "#FFFFFF",
        future: "rgba(255, 255, 255, 0.5)",
        glow: "0 0 20px #FFD700, 0 0 40px #FFD700",
        textStroke: "2px #000000", // Black outline
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

    // Build segments from transcript words - images change based on spoken words
    const segments: Segment[] = useMemo(() => {
        if (!transcript?.words || transcript.words.length === 0) {
            // Fallback: create even segments if no transcript
            return images.map((img, index) => ({
                imageFile: img.file,
                text: "",
                duration: 10,
                wordStartIndex: 0,
                wordEndIndex: 0,
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
    }, [sceneNumber, transcript?.words, images.length]);

    // Find current word index based on time
    const currentWordIndex = useMemo(() => {
        if (!transcript?.words || transcript.words.length === 0) return 0;
        return getCurrentWordIndex(transcript.words, currentTimeSeconds);
    }, [transcript?.words, currentTimeSeconds]);

    // Get the active segment (and thus image) based on current word
    const activeSegment = useMemo(() => {
        return getActiveSegment(segments, currentWordIndex);
    }, [segments, currentWordIndex]);

    // Find the index of the active segment for motion variation
    const activeSegmentIndex = useMemo(() => {
        if (!activeSegment) return 0;
        return segments.findIndex(s => s.imageFile === activeSegment.imageFile);
    }, [segments, activeSegment]);

    return (
        <AbsoluteFill>
            {/* Audio for this scene */}
            <Audio src={staticFile(audioFile)} />

            {/* Single image that changes based on spoken words */}
            {activeSegment && (
                <DynamicImage
                    key={activeSegment.imageFile}
                    imageFile={activeSegment.imageFile}
                    motionIndex={activeSegmentIndex}
                    durationFrames={durationInFrames}
                />
            )}

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
    // Chunk words into groups of 4
    const chunks: Array<Array<{ word: string; start: number; end: number }>> = [];
    for (let i = 0; i < words.length; i += STYLE.chunking.wordsPerChunk) {
        chunks.push(words.slice(i, i + STYLE.chunking.wordsPerChunk));
    }

    // Find current chunk based on time
    const currentChunkIndex = chunks.findIndex((chunk) => {
        const chunkStart = chunk[0].start * 1000;
        const chunkEnd = chunk[chunk.length - 1].end * 1000;
        return currentTimeMs >= chunkStart && currentTimeMs <= chunkEnd;
    });

    const currentChunk = chunks[currentChunkIndex] || chunks[0];

    if (!currentChunk) return null;

    return (
        <>
            {currentChunk.map((wordData, index) => {
                const wordStartMs = wordData.start * 1000;
                const wordEndMs = wordData.end * 1000;

                const isPast = currentTimeMs > wordEndMs;
                const isCurrent = currentTimeMs >= wordStartMs && currentTimeMs <= wordEndMs;
                const isFuture = currentTimeMs < wordStartMs;

                // Clean word (remove trailing punctuation but preserve contractions)
                const cleanWord = wordData.word.replace(/[.,!?;:]$/, "");

                let color = STYLE.colors.future;
                let textShadow = "none";
                let transform = "scale(1)";

                if (isCurrent) {
                    color = STYLE.colors.current;
                    textShadow = STYLE.colors.glow;
                    transform = "scale(1.1)";
                } else if (isPast) {
                    color = STYLE.colors.past;
                }

                return (
                    <span
                        key={`${wordData.start}-${index}`}
                        style={{
                            color,
                            textShadow,
                            transform,
                            WebkitTextStroke: STYLE.colors.textStroke,
                            paintOrder: "stroke fill",
                            transition: "none", // Remotion requires no CSS transitions
                            display: "inline-block",
                        }}
                    >
                        {cleanWord}
                    </span>
                );
            })}
        </>
    );
};

// Dynamic camera motion types
type MotionType = "dollyIn" | "panRight" | "dollyOut" | "panLeft";

// Camera motion component with varied effects
const DynamicImage: React.FC<{
    imageFile: string;
    motionIndex: number;
    durationFrames?: number;
}> = ({ imageFile, motionIndex, durationFrames }) => {
    const frame = useCurrentFrame();
    const { durationInFrames, fps } = useVideoConfig();

    // Cycle through motion types: dolly in, pan right, dolly out, pan left
    const motionTypes: MotionType[] = ["dollyIn", "panRight", "dollyOut", "panLeft"];
    const motionType = motionTypes[motionIndex % 4];

    // Motion lasts the full scene duration (slow continuous motion)
    const motionDuration = durationFrames || durationInFrames;

    let scale = 1;
    let translateX = 0;
    let translateY = 0;

    switch (motionType) {
        case "dollyIn":
            // Zoom in from 100% to 120% (faster, more dramatic)
            scale = interpolate(frame, [0, motionDuration], [1, 1.2], {
                extrapolateRight: "clamp",
            });
            break;
        case "panRight":
            // Zoom + pan right (increased motion)
            scale = interpolate(frame, [0, motionDuration], [1.05, 1.15], {
                extrapolateRight: "clamp",
            });
            translateX = interpolate(frame, [0, motionDuration], [50, -50], {
                extrapolateRight: "clamp",
            });
            break;
        case "dollyOut":
            // Zoom out from 120% to 100% (faster, more dramatic)
            scale = interpolate(frame, [0, motionDuration], [1.2, 1], {
                extrapolateRight: "clamp",
            });
            break;
        case "panLeft":
            // Zoom + pan left (increased motion)
            scale = interpolate(frame, [0, motionDuration], [1.05, 1.15], {
                extrapolateRight: "clamp",
            });
            translateX = interpolate(frame, [0, motionDuration], [-50, 50], {
                extrapolateRight: "clamp",
            });
            break;
    }

    return (
        <AbsoluteFill>
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
