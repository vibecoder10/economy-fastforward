// Types for animated video clip composition

export interface AnimatedVideoScene {
    sceneNumber: number;
    assetType: "video" | "image";
    assetUrl: string;
    duration: number; // in seconds
    shotType?: ShotType;
    isHeroShot?: boolean;
    transcript?: {
        words: Array<{
            word: string;
            start: number;
            end: number;
        }>;
    };
}

export type ShotType =
    | "wide_establishing"
    | "isometric_diorama"
    | "medium_human_story"
    | "close_up_vignette"
    | "data_landscape"
    | "split_screen"
    | "pull_back_reveal"
    | "overhead_map"
    | "journey_shot";

export type TransitionType =
    | "fade"
    | "wipe"
    | "iris"
    | "clockWipe"
    | "slide"
    | "crossfade";

export interface AnimatedVideoProps {
    scenes?: AnimatedVideoScene[];
    voiceoverUrl?: string;
    musicUrl?: string;
    musicVolume?: number;
}

export interface TransitionConfig {
    type: TransitionType;
    duration: number; // in frames
    direction?: "left" | "right" | "up" | "down";
}
