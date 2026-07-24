export type FrameSection = {
  readonly order_index: number;
  readonly start_frame: number;
  readonly duration_frames: number;
  readonly assets: ReadonlyArray<{
    readonly start_frame: number;
    readonly duration_frames: number;
  }>;
  readonly captions: ReadonlyArray<{
    readonly start_frame: number;
    readonly end_frame: number;
  }>;
  readonly transition_in: {
    readonly duration_frames: number;
    readonly overlap_frames: number;
    readonly accounting: string;
  };
  readonly transition_out: {
    readonly duration_frames: number;
    readonly overlap_frames: number;
    readonly accounting: string;
  };
};

export const secondsToFrames = (seconds: number, fps: number): number => {
  if (
    !Number.isInteger(seconds) ||
    seconds < 0 ||
    !Number.isInteger(fps) ||
    fps <= 0
  ) {
    throw new Error("Custom Film seconds and fps must be exact integers");
  }
  return seconds * fps;
};

export const assertExactFrameLayout = (
  sections: ReadonlyArray<FrameSection>,
  totalFrames: number,
): void => {
  if (!Number.isInteger(totalFrames) || totalFrames <= 0) {
    throw new Error("Custom Film total frames must be a positive integer");
  }
  let filmFrame = 0;
  sections.forEach((section, orderIndex) => {
    if (
      section.order_index !== orderIndex ||
      section.start_frame !== filmFrame ||
      !Number.isInteger(section.duration_frames) ||
      section.duration_frames <= 0
    ) {
      throw new Error("Custom Film section order or frame boundary changed");
    }
    for (const transition of [
      section.transition_in,
      section.transition_out,
    ]) {
      if (
        transition.overlap_frames !== 0 ||
        transition.accounting !== "inside_section" ||
        transition.duration_frames < 0 ||
        transition.duration_frames > section.duration_frames
      ) {
        throw new Error("Custom Film transition accounting changed");
      }
    }
    let assetFrame = 0;
    for (const asset of section.assets) {
      if (
        asset.start_frame !== assetFrame ||
        !Number.isInteger(asset.duration_frames) ||
        asset.duration_frames <= 0
      ) {
        throw new Error("Custom Film asset order or frame boundary changed");
      }
      assetFrame += asset.duration_frames;
    }
    if (assetFrame !== section.duration_frames) {
      throw new Error("Custom Film assets do not exactly fill their section");
    }
    let captionEnd = section.start_frame;
    for (const caption of section.captions) {
      if (
        caption.start_frame !== captionEnd ||
        caption.end_frame <= caption.start_frame ||
        caption.end_frame > section.start_frame + section.duration_frames
      ) {
        throw new Error("Custom Film caption order or frame boundary changed");
      }
      captionEnd = caption.end_frame;
    }
    if (captionEnd !== section.start_frame + section.duration_frames) {
      throw new Error("Custom Film captions do not exactly fill their section");
    }
    filmFrame += section.duration_frames;
  });
  if (filmFrame !== totalFrames) {
    throw new Error("Custom Film sections do not exactly fill the film");
  }
};
