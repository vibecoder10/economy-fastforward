// Transcript data for all scenes
// Auto-generated from Whisper transcriptions

interface WhisperWord {
    word: string;
    start: number;
    end: number;
    probability: number;
}

interface WhisperSegment {
    id: number;
    start: number;
    end: number;
    text: string;
    words: WhisperWord[];
}

interface WhisperTranscript {
    text: string;
    segments: WhisperSegment[];
    language: string;
}

// Import all transcripts
import scene1 from "./captions/Scene 1.json";
import scene2 from "./captions/Scene 2.json";
import scene3 from "./captions/Scene 3.json";
import scene4 from "./captions/Scene 4.json";
import scene5 from "./captions/Scene 5.json";
import scene6 from "./captions/Scene 6.json";
import scene7 from "./captions/Scene 7.json";
import scene8 from "./captions/Scene 8.json";
import scene9 from "./captions/Scene 9.json";
import scene10 from "./captions/Scene 10.json";
import scene11 from "./captions/Scene 11.json";
import scene12 from "./captions/Scene 12.json";
import scene13 from "./captions/Scene 13.json";
import scene14 from "./captions/Scene 14.json";
import scene15 from "./captions/Scene 15.json";
import scene16 from "./captions/Scene 16.json";
import scene17 from "./captions/Scene 17.json";
import scene18 from "./captions/Scene 18.json";
import scene19 from "./captions/Scene 19.json";
import scene20 from "./captions/Scene 20.json";

const transcripts: WhisperTranscript[] = [
    scene1 as WhisperTranscript,
    scene2 as WhisperTranscript,
    scene3 as WhisperTranscript,
    scene4 as WhisperTranscript,
    scene5 as WhisperTranscript,
    scene6 as WhisperTranscript,
    scene7 as WhisperTranscript,
    scene8 as WhisperTranscript,
    scene9 as WhisperTranscript,
    scene10 as WhisperTranscript,
    scene11 as WhisperTranscript,
    scene12 as WhisperTranscript,
    scene13 as WhisperTranscript,
    scene14 as WhisperTranscript,
    scene15 as WhisperTranscript,
    scene16 as WhisperTranscript,
    scene17 as WhisperTranscript,
    scene18 as WhisperTranscript,
    scene19 as WhisperTranscript,
    scene20 as WhisperTranscript,
];

// Export all words from a transcript for karaoke display
export function getWordsForScene(sceneNumber: number): Array<{ word: string; start: number; end: number }> {
    const transcript = transcripts[sceneNumber - 1];
    if (!transcript) return [];

    const words: Array<{ word: string; start: number; end: number }> = [];
    for (const segment of transcript.segments) {
        if (segment.words) {
            for (const w of segment.words) {
                words.push({
                    word: w.word,
                    start: w.start,
                    end: w.end,
                });
            }
        }
    }
    return words;
}

export { transcripts };
