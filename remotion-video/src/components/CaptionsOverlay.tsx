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
        size: 72,
        letterSpacing: "0.02em",
        wordGap: 16,
    },
    colors: {
        current: "#FFE135", // Bright yellow - currently spoken word
        default: "#FFFFFF", // White - all other words (past and future)
        textStroke: "6px #000000", // Black outline
    },
    position: {
        bottom: 100,
        gradientHeight: "35%",
    },
};

export const CaptionsOverlay: React.FC<CaptionsOverlayProps> = ({
    words,
    currentTimeSeconds,
    wordsPerChunk = 6,
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

    // Find which word is currently being spoken (or most recently spoken)
    // First try exact match
    let currentWordIndex = words.findIndex(
        (w) => currentTimeSeconds >= w.start && currentTimeSeconds <= w.end
    );

    // If no exact match (in a gap between words), find the most recent word
    // This reduces perceived lag by "sticking" to the last spoken word
    if (currentWordIndex === -1) {
        // Find the last word whose end time has passed
        for (let i = words.length - 1; i >= 0; i--) {
            if (currentTimeSeconds >= words[i].end) {
                currentWordIndex = i;
                break;
            }
        }
        // If still -1, we're before the first word - highlight nothing
    }

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
                    flexWrap: "nowrap",
                    justifyContent: "center",
                    gap: STYLE.font.wordGap,
                    maxWidth: "92%",
                    fontFamily: STYLE.font.family,
                    fontWeight: STYLE.font.weight,
                    fontSize: STYLE.font.size,
                    letterSpacing: STYLE.font.letterSpacing,
                    whiteSpace: "nowrap",
                }}
            >
                {currentChunk.map((wordData) => {
                    // Current word is yellow, all others are white
                    const isCurrentWord = wordData.originalIndex === currentWordIndex;
                    const color = isCurrentWord ? STYLE.colors.current : STYLE.colors.default;

                    return (
                        <span
                            key={`${wordData.start}-${wordData.originalIndex}`}
                            style={{
                                color,
                                WebkitTextStroke: STYLE.colors.textStroke,
                                paintOrder: "stroke fill",
                                display: "inline-block",
                            }}
                        >
                            {wordData.word}
                        </span>
                    );
                })}
            </div>
        </AbsoluteFill>
    );
};
