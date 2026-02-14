// Shared captions overlay component

import React from "react";
import { AbsoluteFill } from "remotion";

interface Word {
    word: string;
    start: number;
    end: number;
}

interface CaptionsOverlayProps {
    words: Word[];
    currentTimeSeconds: number;
    wordsPerChunk?: number;
}

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
        textStroke: "8px #000000", // Thick black outline
    },
    position: {
        bottom: 120,
        gradientHeight: "40%",
    },
};

export const CaptionsOverlay: React.FC<CaptionsOverlayProps> = ({
    words,
    currentTimeSeconds,
    wordsPerChunk = 4,
}) => {
    if (!words || words.length === 0) return null;

    // Chunk words into groups
    const chunks: Array<Array<Word & { originalIndex: number }>> = [];
    for (let i = 0; i < words.length; i += wordsPerChunk) {
        chunks.push(
            words.slice(i, i + wordsPerChunk).map((w, idx) => ({
                ...w,
                originalIndex: i + idx,
            }))
        );
    }

    // Find current chunk based on time
    const currentChunkIndex = chunks.findIndex((chunk) => {
        const chunkStart = chunk[0].start;
        const chunkEnd = chunk[chunk.length - 1].end;
        return currentTimeSeconds >= chunkStart && currentTimeSeconds <= chunkEnd;
    });

    // If between chunks, show the next chunk
    let activeChunkIndex = currentChunkIndex;
    if (activeChunkIndex === -1) {
        activeChunkIndex = chunks.findIndex(
            (chunk) => chunk[0].start > currentTimeSeconds
        );
        if (activeChunkIndex === -1) activeChunkIndex = chunks.length - 1;
    }

    const currentChunk = chunks[activeChunkIndex];
    if (!currentChunk) return null;

    // Find which word is currently being spoken
    const currentWordIndex = words.findIndex(
        (w) => currentTimeSeconds >= w.start && currentTimeSeconds <= w.end
    );

    return (
        <AbsoluteFill
            style={{
                display: "flex",
                background: `linear-gradient(to top, rgba(0,0,0,0.85) 0%, transparent ${STYLE.position.gradientHeight})`,
                justifyContent: "flex-end",
                alignItems: "center",
                paddingBottom: STYLE.position.bottom,
            }}
        >
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
                {currentChunk.map((wordData) => {
                    // Clean word (remove trailing punctuation)
                    const cleanWord = wordData.word.replace(/[.,!?;:]$/, "");

                    // Determine word state
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
                                color,
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
            </div>
        </AbsoluteFill>
    );
};
