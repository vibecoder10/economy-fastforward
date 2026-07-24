// Per-act background music component with looping and crossfades

import React, { useMemo } from 'react';
import { Audio } from '@remotion/media';
import { staticFile, useCurrentFrame, useVideoConfig, interpolate, Sequence } from 'remotion';
import { getMusicBeds, getActBoundaries, MusicBed as MusicBedType, getTotalDurationFromConfig } from '../renderConfig';

/**
 * Per-act background music component with looping and crossfades.
 *
 * Features:
 * - One music track per act
 * - Automatic looping (tracks are ~1:33, acts are 2-3 min)
 * - Crossfade between acts (3 second overlap = 90 frames at 30fps)
 * - Fade in at video start (2 seconds = 60 frames)
 * - Fade out at video end (3 seconds = 90 frames)
 * - Default volume: 8% (0.08)
 *
 * Returns null if no music beds available (backward compatible).
 */
export const MusicBed: React.FC = () => {
	const { fps } = useVideoConfig();

	// Get music beds and act boundaries
	const musicBeds = useMemo(() => getMusicBeds(), []);
	const actBoundaries = useMemo(() => getActBoundaries(fps), [fps]);
	const totalDurationSeconds = useMemo(() => getTotalDurationFromConfig(), []);
	const totalDurationFrames = useMemo(() => {
		return totalDurationSeconds ? Math.ceil(totalDurationSeconds * fps) : null;
	}, [totalDurationSeconds, fps]);

	// Backward compatibility: if no music beds, render nothing
	if (musicBeds.length === 0 || actBoundaries.length === 0 || !totalDurationFrames) {
		return null;
	}

	// Create a map of act -> music bed for quick lookup
	const musicByAct = useMemo(() => {
		const map = new Map<number, MusicBedType>();
		for (const bed of musicBeds) {
			map.set(bed.act, bed);
		}
		return map;
	}, [musicBeds]);

	// Determine last act for crossfade logic
	const lastAct = actBoundaries[actBoundaries.length - 1]?.act ?? 1;

	// Crossfade timing: 3 seconds overlap between acts
	const CROSSFADE_FRAMES = Math.floor(fps * 3);
	// Fade in/out timing: 2 seconds for fade in, 3 seconds for fade out
	const FADE_IN_FRAMES = Math.floor(fps * 2);
	const FADE_OUT_FRAMES = Math.floor(fps * 3);

	return (
		<>
			{actBoundaries.map((boundary) => {
				const actNum = boundary.act;
				const musicBed = musicByAct.get(actNum);

				if (!musicBed) {
					return null;
				}

				const startFrame = boundary.startFrame;
				// Add crossfade overlap if not the last act
				const isLastActFlag = actNum === lastAct;
				const durationFrames = isLastActFlag
					? boundary.endFrame - startFrame
					: boundary.endFrame - startFrame + CROSSFADE_FRAMES;

				return (
					<Sequence
						key={`music-act-${actNum}`}
						from={startFrame}
						durationInFrames={durationFrames}
					>
						<ActMusic
							musicFile={musicBed.file}
							volume={Math.min(musicBed.volume || 0.03, 0.03)}
							sequenceDuration={durationFrames}
							fadeInFrames={FADE_IN_FRAMES}
							fadeOutFrames={FADE_OUT_FRAMES}
						/>
					</Sequence>
				);
			})}
		</>
	);
};

interface ActMusicProps {
	musicFile: string;
	volume: number;
	sequenceDuration: number;  // Duration of this Sequence in frames
	fadeInFrames: number;
	fadeOutFrames: number;
}

/**
 * Internal component for a single act's music with volume control.
 *
 * Handles fade in/out and volume interpolation based on act position.
 *
 * IMPORTANT: This component runs inside a <Sequence>, so useCurrentFrame()
 * returns SEQUENCE-RELATIVE frames (starting at 0), not absolute video frames.
 */
const ActMusic: React.FC<ActMusicProps> = ({
	musicFile,
	volume,
	sequenceDuration,
	fadeInFrames,
	fadeOutFrames,
}) => {
	// frame is SEQUENCE-RELATIVE (starts at 0 for each act's Sequence)
	const frame = useCurrentFrame();

	// Calculate effective volume with fade in/out
	const effectiveVolume = useMemo(() => {
		let vol = volume;

		// Fade in at start of sequence (all acts fade in)
		if (frame < fadeInFrames) {
			vol = interpolate(frame, [0, fadeInFrames], [0, volume]);
		}

		// Fade out at end of sequence
		const framesUntilEnd = sequenceDuration - frame;
		if (framesUntilEnd < fadeOutFrames) {
			// Use minimum of fade-in and fade-out volumes to handle overlap
			const fadeOutVol = interpolate(framesUntilEnd, [0, fadeOutFrames], [0, volume]);
			vol = Math.min(vol, fadeOutVol);
		}

		// Ensure volume is never negative or above 1
		return Math.max(0, Math.min(1, vol));
	}, [
		frame,
		volume,
		sequenceDuration,
		fadeInFrames,
		fadeOutFrames,
	]);

	const { fps } = useVideoConfig();
	// Skip the first 30 seconds of each track (avoid slow intros)
	const MUSIC_START_FROM_FRAMES = Math.floor(30 * fps);

	return (
		<Audio
			src={staticFile(`music/${musicFile}`)}
			volume={effectiveVolume}
			trimBefore={MUSIC_START_FROM_FRAMES}
			loop
		/>
	);
};
