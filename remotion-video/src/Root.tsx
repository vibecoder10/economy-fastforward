import { Composition } from "remotion";
import { Main } from "./Main";
import { EconomyVideoAnimated } from "./compositions/EconomyVideoAnimated";

// Each scene is approximately 60 seconds of audio
const SCENE_DURATION_SECONDS = 60;
const TOTAL_SCENES = 20;
const FPS = 30;

export const RemotionRoot: React.FC = () => {
    return (
        <>
            <Composition
                id="Main"
                component={Main}
                durationInFrames={TOTAL_SCENES * SCENE_DURATION_SECONDS * FPS}
                fps={FPS}
                width={1920}
                height={1080}
                defaultProps={{
                    totalScenes: TOTAL_SCENES,
                }}
            />
            <Composition
                id="Scene1Only"
                component={Main}
                durationInFrames={90 * FPS}
                fps={FPS}
                width={1920}
                height={1080}
                defaultProps={{
                    totalScenes: 1,
                }}
            />

            {/* NEW — Video clip version with transitions and effects */}
            <Composition
                id="EconomyVideoAnimated"
                component={EconomyVideoAnimated}
                durationInFrames={30 * 60 * 8}
                fps={FPS}
                width={1920}
                height={1080}
                defaultProps={{
                    scenes: [],
                    voiceoverUrl: "",
                    musicUrl: "",
                    musicVolume: 0.15,
                }}
            />
        </>
    );
};
