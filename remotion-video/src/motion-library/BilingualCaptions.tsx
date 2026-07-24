import React from "react";
import {useCurrentFrame} from "remotion";
import {activeWordIndex, type TimedWord} from "./contracts";
import {PrimitiveFrame} from "./PrimitiveFrame";
import {SignalPulse} from "./SignalPulse";
import {COLORS} from "./theme";
import {CropSafeColumn} from "./CropSafe";

const WORDS: TimedWord[] = [
  {text: "La", startFrame: 8, endFrame: 22},
  {text: "ciudad", startFrame: 22, endFrame: 40},
  {text: "todavía", startFrame: 40, endFrame: 60},
  {text: "respira.", startFrame: 60, endFrame: 88},
];

export const BilingualCaptions: React.FC = () => {
  const frame = useCurrentFrame();
  const active = activeWordIndex(WORDS, frame);
  return <PrimitiveFrame kicker="Measured word timing" title="Bilingual captions">
    <CropSafeColumn top={300} bottom={340} style={{boxSizing: "border-box", padding: 34, borderLeft: `5px solid ${COLORS.turquoise}`, background: "rgba(8,20,25,.86)"}}>
      <div style={{fontSize: 25, color: COLORS.turquoise, fontWeight: 700, marginBottom: 22}}>MARA · ES</div>
      <div style={{fontSize: 42, fontWeight: 600, lineHeight: 1.35}}>{WORDS.map((word, index) => <span key={`${word.text}-${word.startFrame}`} style={{display: "inline-block", marginRight: 13, color: index === active ? COLORS.amber : COLORS.cream, transform: `translateY(${index === active ? -5 : 0}px)`}}>{word.text}</span>)}</div>
      <div style={{fontSize: 25, marginTop: 24, color: COLORS.blue}}>The city is still breathing.</div>
    </CropSafeColumn>
    <div style={{position: "absolute", left: 680, top: 705, width: 560, fontSize: 18, color: "#82979e"}}>Unicode-safe · translated · measured emphasis</div>
    <SignalPulse compact phase={5} />
  </PrimitiveFrame>;
};
