import {
    AbsoluteFill,
    Img,
    staticFile,
    useCurrentFrame,
    useVideoConfig,
    interpolate,
    Sequence,
} from "remotion";
import { Audio } from "@remotion/media";

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

// Duration each image is shown (in seconds)
const IMAGE_DURATION_SECONDS = 10;

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
    const { fps } = useVideoConfig();

    const imageDurationFrames = IMAGE_DURATION_SECONDS * fps;
    const currentTimeMs = (frame / fps) * 1000;

    return (
        <AbsoluteFill>
            {/* Audio for this scene */}
            <Audio src={staticFile(audioFile)} />

            {/* Images with dynamic camera motion */}
            {images.map((image, index) => {
                const startFrame = index * imageDurationFrames;

                return (
                    <Sequence
                        key={image.index}
                        from={startFrame}
                        durationInFrames={imageDurationFrames}
                    >
                        <DynamicImage imageFile={image.file} motionIndex={index} />
                    </Sequence>
                );
            })}

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
const DynamicImage: React.FC<{ imageFile: string; motionIndex: number }> = ({ imageFile, motionIndex }) => {
    const frame = useCurrentFrame();
    const { durationInFrames } = useVideoConfig();

    // Cycle through motion types: dolly in, pan right, dolly out, pan left
    const motionTypes: MotionType[] = ["dollyIn", "panRight", "dollyOut", "panLeft"];
    const motionType = motionTypes[motionIndex % 4];

    // Motion lasts the full image duration
    const motionDuration = durationInFrames;

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
