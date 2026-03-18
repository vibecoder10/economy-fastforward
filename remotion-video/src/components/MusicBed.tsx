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

	// Determine first and last act numbers
	const firstAct = actBoundaries[0]?.act ?? 1;
	const lastAct = actBoundaries[actBoundaries.length - 1]?.act ?? 1;

	// Crossfade timing: 3 seconds = 90 frames at 30fps
	const CROSSFADE_FRAMES = 90;
	// Fade in/out timing: 2 seconds for fade in, 3 seconds for fade out
	const FADE_IN_FRAMES = 60; // 2 seconds at 30fps
	const FADE_OUT_FRAMES = 90; // 3 seconds at 30fps

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
				const isLastAct = actNum === lastAct;
				const durationFrames = isLastAct
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
							volume={musicBed.volume || 0.08}
							isFirstAct={actNum === firstAct}
							isLastAct={isLastAct}
							actStartFrame={startFrame}
							actEndFrame={boundary.endFrame}
							videoEndFrame={totalDurationFrames}
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
	isFirstAct: boolean;
	isLastAct: boolean;
	actStartFrame: number;
	actEndFrame: number;
	videoEndFrame: number;
	fadeInFrames: number;
	fadeOutFrames: number;
}

/**
 * Internal component for a single act's music with volume control.
 *
 * Handles fade in/out and volume interpolation based on act position.
 */
const ActMusic: React.FC<ActMusicProps> = ({
	musicFile,
	volume,
	isFirstAct,
	isLastAct,
	actStartFrame,
	actEndFrame,
	videoEndFrame,
	fadeInFrames,
	fadeOutFrames,
}) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();

	// Calculate effective volume with fade in/out
	const effectiveVolume = useMemo(() => {
		let vol = volume;

		if (isFirstAct) {
			// Fade in from 0 to baseVolume over first fadeInFrames of VIDEO (not act)
			if (frame < fadeInFrames) {
				vol = interpolate(frame, [0, fadeInFrames], [0, volume]);
			}
		} else {
			// Non-first acts: fade in over fadeOutFrames at act start
			const framesSinceActStart = frame - actStartFrame;
			if (framesSinceActStart < fadeOutFrames) {
				vol = interpolate(framesSinceActStart, [0, fadeOutFrames], [0, volume]);
			}
		}

		if (isLastAct) {
			// Fade out from baseVolume to 0 over last fadeOutFrames of VIDEO
			const framesUntilEnd = videoEndFrame - frame;
			if (framesUntilEnd < fadeOutFrames) {
				vol = interpolate(framesUntilEnd, [0, fadeOutFrames], [0, volume]);
			}
		} else {
			// Non-last acts: fade out over fadeOutFrames at act end
			const framesUntilActEnd = actEndFrame - frame;
			if (framesUntilActEnd < fadeOutFrames) {
				vol = interpolate(framesUntilActEnd, [0, fadeOutFrames], [0, volume]);
			}
		}

		return vol;
	}, [
		frame,
		volume,
		isFirstAct,
		isLastAct,
		actStartFrame,
		actEndFrame,
		videoEndFrame,
		fadeInFrames,
		fadeOutFrames,
	]);

	return (
		<Audio
			src={staticFile(`music/${musicFile}`)}
			volume={effectiveVolume}
			loop
		/>
	);
};
