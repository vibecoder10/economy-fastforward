import { Composition } from "remotion";
import { Main } from "./Main";
import {StoryEngineDirectorFilm} from "./custom-film/DirectorFilm";
import {DIRECTOR_FILM_DEFAULT_PROPS} from "./custom-film/directorFixture";
import {DIRECTOR_SCENE_CONTROL_PROOF_PROPS} from "./custom-film/directorSceneControlFixture";
import {validateDirectorRemotionProps} from "./custom-film/directorSchema";
import { getSceneDurationFromConfig, getTotalDurationFromConfig, getSceneNumbers } from "./renderConfig";
import {MotionLibraryPreview} from "./motion-library/MotionLibraryPreview";
import {PREVIEW_PRIMITIVES, PREVIEW_SECONDS_PER_PRIMITIVE} from "./motion-library/contracts";
import {StoryEngineCustomFilmShowcase} from "./showcase/StoryEngineCustomFilmShowcase";
import {
    STORYENGINE_SHOWCASE_DEFAULT_PROPS,
    STORYENGINE_SHOWCASE_SOURCE_CLIP_PROOF_PROPS,
    STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS,
} from "./showcase/fixture";
import {validateLayeredCustomFilmProps, validateStoryEngineShowcaseProps} from "./showcase/manifest";

const FPS = 24;
// Buffer after last spoken word to let audio trail off naturally
const SCENE_END_BUFFER_SECONDS = 1;

/**
 * Total video duration from render_config.json.
 * Uses total_duration_seconds when available, otherwise sums per-scene
 * durations using the ACTUAL scene numbers from render_config (not 1..N).
 */
function getTotalDurationFrames(fps: number): number {
    const sceneNums = getSceneNumbers();
    const sceneCount = sceneNums.length || 20;

    const configTotal = getTotalDurationFromConfig();
    if (configTotal !== null) {
        // Add buffer per scene for audio trail-off
        return Math.ceil((configTotal + sceneCount * SCENE_END_BUFFER_SECONDS) * fps);
    }

    // Sum per-scene durations using actual scene numbers from render_config
    let total = 0;
    for (const sceneNum of sceneNums) {
        const dur = getSceneDurationFromConfig(sceneNum);
        if (dur !== null) {
            total += Math.ceil((dur + SCENE_END_BUFFER_SECONDS) * fps);
        }
    }
    // Fallback: 25 minutes if render_config has no data at all
    return total || Math.ceil(25 * 60 * fps);
}

/**
 * Duration for a single scene (Scene1Only composition).
 */
function getScene1DurationFrames(fps: number): number {
    const dur = getSceneDurationFromConfig(1);
    if (dur !== null) return Math.ceil((dur + SCENE_END_BUFFER_SECONDS) * fps);
    // Fallback: 2 minutes for preview
    return Math.ceil(2 * 60 * fps);
}

export const RemotionRoot: React.FC = () => {
    return (
        <>
            <Composition
                id="Main"
                component={Main}
                durationInFrames={getTotalDurationFrames(FPS)}
                fps={FPS}
                width={1920}
                height={1080}
            />
            <Composition
                id="Scene1Only"
                component={Main}
                durationInFrames={getScene1DurationFrames(FPS)}
                fps={FPS}
                width={1920}
                height={1080}
                defaultProps={{
                    totalScenes: 1,
                }}
            />
            <Composition
                id="MotionLibraryPreview"
                component={MotionLibraryPreview}
                durationInFrames={PREVIEW_PRIMITIVES.length * PREVIEW_SECONDS_PER_PRIMITIVE * FPS}
                fps={FPS}
                width={1920}
                height={1080}
            />
            <Composition
                id="StoryEngineCustomFilmShowcase"
                component={StoryEngineCustomFilmShowcase}
                durationInFrames={7200}
                fps={24}
                width={1920}
                height={1080}
                defaultProps={STORYENGINE_SHOWCASE_DEFAULT_PROPS}
                calculateMetadata={({props}) => {
                    const approved = validateLayeredCustomFilmProps(props);
                    return {
                        durationInFrames: approved.video.total_frames,
                        fps: approved.video.fps,
                        width: approved.video.width,
                        height: approved.video.height,
                    };
                }}
            />
            <Composition
                id="StoryEngineDirectorFilm"
                component={StoryEngineDirectorFilm}
                durationInFrames={72}
                fps={24}
                width={1920}
                height={1080}
                defaultProps={DIRECTOR_FILM_DEFAULT_PROPS}
                calculateMetadata={({props}) => {
                    const approved = validateDirectorRemotionProps(props);
                    return {
                        durationInFrames: approved.video.total_frames,
                        fps: approved.video.fps,
                        width: approved.video.width,
                        height: approved.video.height,
                    };
                }}
            />
            <Composition
                id="StoryEngineDirectorSceneControlProof"
                component={StoryEngineDirectorFilm}
                durationInFrames={432}
                fps={24}
                width={1920}
                height={1080}
                defaultProps={DIRECTOR_SCENE_CONTROL_PROOF_PROPS}
                calculateMetadata={({props}) => {
                    const approved = validateDirectorRemotionProps(props);
                    return {
                        durationInFrames: approved.video.total_frames,
                        fps: approved.video.fps,
                        width: approved.video.width,
                        height: approved.video.height,
                    };
                }}
            />
            <Composition
                id="StoryEngineCustomFilmShowcaseStagedProof"
                component={StoryEngineCustomFilmShowcase}
                durationInFrames={7200}
                fps={24}
                width={1920}
                height={1080}
                defaultProps={STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS}
                calculateMetadata={({props}) => {
                    validateStoryEngineShowcaseProps(props);
                    return {durationInFrames: 7200, fps: 24, width: 1920, height: 1080};
                }}
            />
            <Composition
                id="StoryEngineCustomFilmShowcaseSourceClipProof"
                component={StoryEngineCustomFilmShowcase}
                durationInFrames={7200}
                fps={24}
                width={1920}
                height={1080}
                defaultProps={STORYENGINE_SHOWCASE_SOURCE_CLIP_PROOF_PROPS}
                calculateMetadata={({props}) => {
                    validateStoryEngineShowcaseProps(props);
                    return {durationInFrames: 7200, fps: 24, width: 1920, height: 1080};
                }}
            />
        </>
    );
};
