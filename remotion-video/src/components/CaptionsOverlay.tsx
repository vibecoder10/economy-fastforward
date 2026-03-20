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
    maxCharsPerChunk?: number;
}

// Maximum characters per chunk - fits 92% of 1920px at 72px Inter Bold
// Calculated: (1920 * 0.92 - 5 * 16px gap) / ~43px per char ≈ 39 chars
const MAX_CHARS_PER_CHUNK = 38;

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
    maxCharsPerChunk = MAX_CHARS_PER_CHUNK,
}) => {
    if (!words || words.length === 0) return null;

    // Chunk words by character count (not word count) to prevent overflow
    // This creates adaptive chunks: short words → more per chunk, long words → fewer
    const chunks: Array<Array<Word & { originalIndex: number }>> = [];
    let buildingChunk: Array<Word & { originalIndex: number }> = [];
    let buildingChunkChars = 0;

    for (let i = 0; i < words.length; i++) {
        const word = words[i];
        // Calculate chars if we add this word (+1 for space between words)
        const wordChars = word.word.length + (buildingChunk.length > 0 ? 1 : 0);

        // If adding this word would exceed limit AND we have at least one word, start new chunk
        if (buildingChunkChars + wordChars > maxCharsPerChunk && buildingChunk.length > 0) {
            chunks.push(buildingChunk);
            buildingChunk = [];
            buildingChunkChars = 0;
        }

        buildingChunk.push({ ...word, originalIndex: i });
        buildingChunkChars += word.word.length + (buildingChunk.length > 1 ? 1 : 0);
    }

    // Don't forget the last chunk
    if (buildingChunk.length > 0) {
        chunks.push(buildingChunk);
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
