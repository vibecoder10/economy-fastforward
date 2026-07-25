import React from "react";
import {Audio} from "@remotion/media";
import {Sequence, staticFile, useCurrentFrame} from "remotion";
import {
  SHOWCASE_AUDIO_CUES,
  recipeBedGain,
  showcaseBedGain,
} from "./timing";
import type {LayeredSceneRecipe} from "./orchestration";

const ContinuousBed: React.FC<{
  recipes: ReadonlyArray<LayeredSceneRecipe>;
  reference: boolean;
}> = ({recipes, reference}) => {
  const absoluteFrame = useCurrentFrame();
  const recipe = recipes.find(({from, to}) => absoluteFrame >= from && absoluteFrame <= to);
  if (!recipe) throw new Error("Audio frame has no orchestration recipe");
  return (
    <Audio
      loop
      src={staticFile("motion-audio/music-bed.wav")}
      volume={
        reference
          ? showcaseBedGain(absoluteFrame) *
            recipe.audio.bedGain *
            recipe.audio.dialogueDuck
          : recipeBedGain(recipe, absoluteFrame)
      }
    />
  );
};

export const ShowcaseAudio: React.FC<{
  recipes: ReadonlyArray<LayeredSceneRecipe>;
  totalFrames: number;
  fps: number;
  reference: boolean;
}> = ({recipes, totalFrames, fps, reference}) => (
  <>
    <Sequence from={0} durationInFrames={totalFrames} premountFor={fps}>
      <ContinuousBed recipes={recipes} reference={reference} />
    </Sequence>
    {reference ? SHOWCASE_AUDIO_CUES.map((cue) => (
      <Sequence
        key={cue.id}
        name={cue.id}
        from={cue.from}
        durationInFrames={cue.to - cue.from + 1}
        premountFor={fps}
      >
        <Audio
          loop={cue.loop}
          src={staticFile(cue.path)}
          volume={(frame) => {
            const duration = cue.to - cue.from + 1;
            const edge = Math.min(1, frame / 12, (duration - frame) / 12);
            const absoluteFrame = cue.from + frame;
            const recipe = recipes.find(({from, to}) => absoluteFrame >= from && absoluteFrame <= to);
            if (!recipe) return 0;
            const enabled = cue.id.includes("click")
              ? recipe.audio.dataClicks
              : cue.id.includes("boundary")
                ? recipe.audio.transitionEnvelope
                : recipe.audio.pulse;
            return enabled ? Math.max(0, edge) * 0.28 : 0;
          }}
        />
      </Sequence>
    )) : recipes.flatMap((recipe) => {
      if (recipe.audio.silenceDrop) return [];
      const cues: React.ReactNode[] = [];
      const add = (
        id: string,
        path: string,
        enabled: boolean,
        from = recipe.from,
        duration = recipe.durationInFrames,
        loop = true,
      ) => {
        if (!enabled || duration <= 0) return;
        cues.push(
          <Sequence
            key={`${recipe.id}:${id}:${from}`}
            name={`${recipe.id}:${id}`}
            from={from}
            durationInFrames={duration}
            premountFor={fps}
          >
            <Audio
              loop={loop}
              src={staticFile(path)}
              volume={(frame) => {
                const edge = Math.min(
                  1,
                  (frame + 1) / 12,
                  (duration - frame) / 12,
                );
                return Math.max(0, edge) * 0.22;
              }}
            />
          </Sequence>,
        );
      };
      add(
        "pulse",
        "motion-audio/signal-pulse.wav",
        recipe.audio.pulse,
      );
      add(
        "clicks",
        "motion-audio/data-click.wav",
        recipe.audio.dataClicks,
      );
      if (recipe.audio.transitionEnvelope) {
        const edgeFrames = Math.min(12, recipe.durationInFrames);
        add(
          "transition-in",
          "motion-audio/transition-envelope.wav",
          true,
          recipe.from,
          edgeFrames,
          false,
        );
        if (recipe.durationInFrames > edgeFrames) {
          add(
            "transition-out",
            "motion-audio/transition-envelope.wav",
            true,
            recipe.to - edgeFrames + 1,
            edgeFrames,
            false,
          );
        }
      }
      return cues;
    })}
  </>
);
