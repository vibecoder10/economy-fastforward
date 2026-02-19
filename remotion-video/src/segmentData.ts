// Segment timing data for word-synced image display
// This file contains video-specific timing data.
// When empty, the system falls back to even distribution of words across images.

export interface SegmentText {
    text: string;
    duration: number;
}

// Video-specific segment data - populated per project
// When empty, getSegmentsForScene() uses createEvenSegments() as fallback
export const sceneSegmentData: Record<number, SegmentText[]> = {};
