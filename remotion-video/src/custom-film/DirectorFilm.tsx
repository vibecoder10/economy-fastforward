import React from "react";
import {Audio, Video} from "@remotion/media";
import {
  AbsoluteFill,
  Easing,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {
  type DirectorRemotionProps,
  validateDirectorRemotionProps,
} from "./directorSchema";

const source = (path: string): string =>
  /^https?:\/\//.test(path) ? path : staticFile(path);

const gain = (decibels: number): number => 10 ** (decibels / 20);

const MeasuredCaption: React.FC<{
  line: DirectorRemotionProps["shots"][number]["spoken_lines"][number];
}> = ({line}) => {
  const localFrame = useCurrentFrame();
  const absoluteFrame = line.start_frame + localFrame;
  return (
    <div
      data-caption-speaker={line.speaker_id}
      data-caption-line={line.line_index}
      style={{
        position: "absolute",
        left: "19%",
        right: "19%",
        bottom: 92,
        boxSizing: "border-box",
        padding: "18px 24px",
        borderRadius: 14,
        border: "1px solid rgba(255,255,255,.28)",
        background: "rgba(5,8,12,.82)",
        boxShadow: "0 20px 60px rgba(0,0,0,.5)",
        color: "#f6f1e7",
        fontFamily: "Noto Sans, Arial, sans-serif",
        fontSize: 42,
        fontWeight: 700,
        lineHeight: 1.22,
        textAlign: "center",
        whiteSpace: "pre-wrap",
      }}
    >
      {line.measured_words.map((word, index) => {
        const active =
          word.from_frame <= absoluteFrame && word.to_frame > absoluteFrame;
        return (
          <span
            key={`${word.from_frame}:${index}`}
            style={{
              color: active ? "#41e3d2" : "#f6f1e7",
              textShadow: active ? "0 0 24px rgba(65,227,210,.45)" : "none",
            }}
          >
            {word.text}
          </span>
        );
      })}
    </div>
  );
};

const DirectorShot: React.FC<{
  shot: DirectorRemotionProps["shots"][number];
}> = ({shot}) => {
  const localFrame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const transitionOpacity =
    shot.transition_duration_frames > 0
      ? interpolate(
          localFrame,
          [0, shot.transition_duration_frames],
          [0.58, 0],
          {
            easing: Easing.inOut(Easing.quad),
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          },
        )
      : 0;
  return (
    <AbsoluteFill
      data-director-shot-id={shot.shot_id}
      data-director-shot-key={shot.shot_key}
      data-director-technique={shot.technique}
      style={{backgroundColor: "#030508"}}
    >
      <Video
        muted
        src={source(shot.clip.local_path)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
        }}
      />
      {shot.sound_layers.map((layer) => (
        <Sequence
          key={layer.layer_id}
          name={`sound:${layer.kind}:${layer.layer_id}`}
          from={layer.start_frame - shot.start_frame}
          durationInFrames={layer.end_frame - layer.start_frame}
          premountFor={fps}
        >
          <Audio
            loop={layer.loop}
            src={source(layer.source.local_path)}
            volume={gain(layer.gain_db)}
          />
        </Sequence>
      ))}
      {shot.spoken_lines.map((line) => (
        <React.Fragment key={`${shot.shot_id}:${line.line_index}`}>
          <Sequence
            name={`voice:${line.speaker_id}:${line.line_index}`}
            from={line.start_frame - shot.start_frame}
            durationInFrames={line.end_frame - line.start_frame}
            premountFor={fps}
          >
            <Audio src={source(line.source.local_path)} />
          </Sequence>
          <Sequence
            name={`caption:${line.speaker_id}:${line.line_index}`}
            from={line.start_frame - shot.start_frame}
            durationInFrames={line.end_frame - line.start_frame}
            premountFor={fps}
          >
            <MeasuredCaption line={line} />
          </Sequence>
        </React.Fragment>
      ))}
      {transitionOpacity > 0 ? (
        <AbsoluteFill
          data-transition={shot.transition_from_previous}
          style={{
            backgroundColor: "#030508",
            opacity: transitionOpacity,
            pointerEvents: "none",
          }}
        />
      ) : null}
    </AbsoluteFill>
  );
};

export const StoryEngineDirectorFilm: React.FC<DirectorRemotionProps> = (
  rawProps,
) => {
  const props = validateDirectorRemotionProps(rawProps);
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{backgroundColor: "#030508"}}>
      {props.shots.map((shot) => (
        <Sequence
          key={shot.shot_id}
          name={`${shot.order_index + 1}:${shot.shot_key}`}
          from={shot.start_frame}
          durationInFrames={shot.duration_frames}
          premountFor={fps}
        >
          <DirectorShot shot={shot} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
