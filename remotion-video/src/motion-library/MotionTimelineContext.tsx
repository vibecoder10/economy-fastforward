import React, {createContext, useContext} from "react";

const MotionTimelineContext = createContext<number | null>(null);

export const MotionTimelineProvider = MotionTimelineContext.Provider;

export const useMotionTimelineFrame = (): number | null =>
  useContext(MotionTimelineContext);
