import { AbsoluteFill, Sequence, staticFile, useVideoConfig, getInputProps } from "remotion";
import { Audio } from "@remotion/media";
import { Scene } from "./Scene";
import { useMemo } from "react";
import { getWordsForScene } from "./transcripts";
import { getSceneNumbers, getImageCountForScene, getSceneDurationFromConfig, getRenderScenesForScene } from "./renderConfig";
import { MusicBed } from "./components/MusicBed";

interface MainProps {
    totalScenes?: number;
}

// Buffer after last spoken word to let audio trail off naturally
const SCENE_END_BUFFER_SECONDS = 1;

/**
 * Get scene duration from render_config.json (the single source of truth).
 * Returns null if render_config has no data for this scene (scene was
 * skipped during audio_sync — e.g. Whisper failure or missing audio).
 */
function getSceneDurationSeconds(sceneNumber: number): number | null {
    const configDuration = getSceneDurationFromConfig(sceneNumber);
    if (configDuration !== null) return configDuration + SCENE_END_BUFFER_SECONDS;
    return null;
}

// Per-image SFX data from pipeline props
interface ImageSfxData {
    sfx?: string;       // e.g. "sfx/sfx_1_1.mp3"
    sfxVolume?: number;  // 0.0-1.0, default 0.15
}

interface PropsImage {
    index: number;
    sfx?: string;
    sfxVolume?: number;
}

interface PropsScene {
    sceneNumber: number;
    images?: PropsImage[];
}

export const Main: React.FC<MainProps> = ({ totalScenes }) => {
    const { fps } = useVideoConfig();

    // Load per-image SFX data from inputProps (embedded by pipeline.py)
    const sfxByScene = useMemo(() => {
        const map: Record<number, Record<number, ImageSfxData>> = {};
        try {
            const inputProps = getInputProps() as Record<string, unknown>;
            const propsScenes = (inputProps?.scenes ?? []) as PropsScene[];
            for (const s of propsScenes) {
                if (!s.sceneNumber || !s.images) continue;
                const imageMap: Record<number, ImageSfxData> = {};
                for (const img of s.images) {
                    if (img.sfx) {
                        imageMap[img.index] = { sfx: img.sfx, sfxVolume: img.sfxVolume ?? 0.15 };
                    }
                }
                if (Object.keys(imageMap).length > 0) {
                    map[s.sceneNumber] = imageMap;
                }
            }
        } catch {
            // No input props available (studio preview)
        }
        return map;
    }, []);

    // Get actual scene numbers from render_config.json.
    // When totalScenes is passed (e.g. Scene1Only preview), use sequential 1..N.
    // Otherwise use the real scene numbers — they may not be sequential if
    // audio_sync skipped a scene.
    const sceneNumberList = useMemo(() => {
        if (totalScenes) {
            return Array.from({ length: totalScenes }, (_, i) => i + 1);
        }
        const nums = getSceneNumbers();
        return nums.length > 0 ? nums : Array.from({ length: 20 }, (_, i) => i + 1);
    }, [totalScenes]);

    // Generate scene data with transcripts - image count is dynamic per scene
    const scenes = useMemo(() => {
        return sceneNumberList.map((sceneNumber) => {
            // Get image count from render_config.json, fallback to 6
            const imageCount = getImageCountForScene(sceneNumber) || 6;
            const sceneSfx = sfxByScene[sceneNumber] ?? {};

            // Get render_config entries for this scene to detect video clips
            const renderScenes = getRenderScenesForScene(sceneNumber);

            return {
                sceneNumber,
                audioFile: `Scene ${sceneNumber}.mp3`,
                images: Array.from({ length: imageCount }, (_, j) => {
                    const imgIndex = j + 1;
                    const sfxData = sceneSfx[imgIndex];
                    const padScene = String(sceneNumber).padStart(2, "0");
                    const padIndex = String(imgIndex).padStart(2, "0");
                    // Use .mp4 extension if render_config marks this entry as a video clip
                    const rs = renderScenes.find(
                        (s) => s.scene_number === sceneNumber && s.image_index === imgIndex,
                    );
                    const ext = rs?.type === "video" && rs.video_clip_path ? "mp4" : "png";
                    return {
                        index: imgIndex,
                        file: `Scene_${padScene}_${padIndex}.${ext}`,
                        sfx: sfxData?.sfx,
                        sfxVolume: sfxData?.sfxVolume,
                    };
                }),
                transcript: {
                    words: getWordsForScene(sceneNumber),
                },
            };
        });
    }, [sceneNumberList, sfxByScene]);

    // Calculate cumulative start frames using actual audio durations per scene.
    // Scenes missing from render_config are skipped (they had no audio data).
    const scenesWithTiming = useMemo(() => {
        let cumulativeFrames = 0;
        const result: Array<typeof scenes[number] & { startFrame: number; durationFrames: number }> = [];
        for (const scene of scenes) {
            const sceneDuration = getSceneDurationSeconds(scene.sceneNumber);
            if (sceneDuration === null) {
                console.warn(
                    `Scene ${scene.sceneNumber}: no timing data in render_config.json, skipping`
                );
                continue;
            }
            const startFrame = cumulativeFrames;
            const durationFrames = Math.ceil(sceneDuration * fps);
            cumulativeFrames += durationFrames;
            result.push({ ...scene, startFrame, durationFrames });
        }
        return result;
    }, [scenes, fps]);

    return (
        <AbsoluteFill style={{ backgroundColor: "#000" }}>
            {/* Background music bed - spans full video, manages its own timing */}
            <MusicBed />

            {scenesWithTiming.map((scene) => (
                <Sequence
                    key={scene.sceneNumber}
                    from={scene.startFrame}
                    durationInFrames={scene.durationFrames}
                >
                    <Scene
                        sceneNumber={scene.sceneNumber}
                        audioFile={scene.audioFile}
                        images={scene.images}
                        transcript={scene.transcript}
                    />
                </Sequence>
            ))}
        </AbsoluteFill>
    );
};

