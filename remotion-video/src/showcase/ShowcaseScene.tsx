import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {EvidenceBoard} from "../motion-library/EvidenceBoard";
import {PrimitiveFrame} from "../motion-library/PrimitiveFrame";
import {RadioWaveform} from "../motion-library/RadioWaveform";
import {SignalPulse} from "../motion-library/SignalPulse";
import {CropSafeColumn} from "../motion-library/CropSafe";
import {COLORS, FONT_FAMILY} from "../motion-library/theme";
import {signalPulseCycleFrame, signalPulseEnergy} from "../motion-library/contracts";
import {SHOWCASE_REQUEST} from "./manifest";
import type {LayeredSceneRecipe} from "./orchestration";
import {MARA_MEASURED_WORDS, MARA_RESPONSE_WORDS, activeAbsoluteWord, showcasePulseFrame} from "./timing";

type Cue = LayeredSceneRecipe;

const clamp = (value: number) => Math.max(0, Math.min(1, value));

const MotionIngredient: React.FC<{
  layer: LayeredSceneRecipe["motionLayers"][number];
  recipe: LayeredSceneRecipe;
  progress: number;
}> = ({layer, recipe, progress}) => {
  const energy = recipe.signals.energy / 3;
  const safeInset = layer.safeZone === "center-critical" ? 150 : 0;
  const shell: React.CSSProperties = {
    position: "absolute",
    inset: `0 ${safeInset}px`,
    zIndex: layer.zIndex,
    mixBlendMode: layer.blend,
    opacity: layer.intensity,
  };
  if (layer.primitive === "SignalPulse") {
    return <div data-motion-ingredient={layer.primitive} style={shell}><SignalPulse compact phase={recipe.sectionIndex}/></div>;
  }
  if (layer.primitive === "MotionAudioSystem") {
    return <div data-motion-ingredient={layer.primitive} style={shell}><div style={{position:"absolute",right:4,top:72,display:"flex",alignItems:"end",gap:3,height:26}}>{[.35,.7,.48,1,.62,.82].map((height,index)=><div key={index} style={{width:3,height:`${Math.max(8,height*energy*26)}px`,background:recipe.audio.silenceDrop?"#263238":COLORS.turquoise}}/>)}</div></div>;
  }
  if (layer.primitive === "MediaKinetics") {
    return (
      <div data-motion-ingredient={layer.primitive} style={shell}>
        <div
          style={{
            position: "absolute",
            inset: 70,
            border: `1px solid rgba(45,226,208,${0.12 + energy * 0.16})`,
            transform: `scale(${0.985 + progress * 0.015})`,
            transformOrigin: "center",
          }}
        />
      </div>
    );
  }
  const common = {position: "absolute" as const, inset: 0};
  if (layer.primitive === "OutageMap") {
    return <div data-motion-ingredient={layer.primitive} style={shell}><svg width="100%" height="100%" viewBox="0 0 1620 1080" style={common}><path d="M130 650 C370 420 570 720 810 490 S1170 690 1460 440" fill="none" stroke={COLORS.turquoise} strokeWidth={3+energy*3} pathLength="1" strokeDasharray="1" strokeDashoffset={1-progress}/></svg></div>;
  }
  if (layer.primitive === "EvidenceBoard") {
    return <div data-motion-ingredient={layer.primitive} style={shell}><svg width="100%" height="100%" viewBox="0 0 1620 1080" style={common}>{[0,1,2].map(index=><g key={index}><rect x={1170+index*105} y={250+index*70} width="94" height="68" fill="#0b191e" stroke={COLORS.amber}/><path d={`M810 530 L${1170+index*105} ${284+index*70}`} stroke={COLORS.amber} strokeWidth="2"/></g>)}</svg></div>;
  }
  if (layer.primitive === "IncidentTimeline") {
    return <div data-motion-ingredient={layer.primitive} style={shell}><svg width="100%" height="100%" viewBox="0 0 1620 1080" style={common}><path d="M280 790 H1340" stroke={COLORS.turquoise} strokeWidth="3"/>{[370,810,1250].map(x=><circle key={x} cx={x} cy="790" r={8+progress*7} fill={COLORS.turquoise}/>)}</svg></div>;
  }
  if (layer.primitive === "RadioWaveform") {
    return <div data-motion-ingredient={layer.primitive} style={shell}><svg width="100%" height="100%" viewBox="0 0 1620 1080" style={common}><path d="M200 540 L270 540 300 470 340 640 380 505 420 575 460 540 H610" fill="none" stroke={COLORS.turquoise} strokeWidth={3+energy*3}/></svg></div>;
  }
  if (layer.primitive === "NetworkExplainer") {
    const productSafeNodes = recipe.signals.intents.includes("product")
      ? [[90,230],[1530,230],[90,790],[1530,790]]
      : [[570,400],[810,310],[1050,400],[810,600]];
    return <div data-motion-ingredient={layer.primitive} data-product-safe={recipe.signals.intents.includes("product")} style={shell}><svg width="100%" height="100%" viewBox="0 0 1620 1080" style={common}>{productSafeNodes.map(([x,y],index)=><circle key={index} cx={x} cy={y} r="14" fill={recipe.signals.intents.includes("product")?COLORS.turquoise:progress>=index/4?COLORS.turquoise:COLORS.red}/>)}</svg></div>;
  }
  if (layer.primitive === "StoryEngineReveal") {
    return <div data-motion-ingredient={layer.primitive} style={shell}><svg width="100%" height="100%" viewBox="0 0 1620 1080" style={common}><path d="M270 835 C550 835 610 900 810 900 S1070 835 1350 835" fill="none" stroke={COLORS.turquoise} strokeWidth={3+progress*5}/></svg></div>;
  }
  if (layer.primitive === "BilingualCaptions") {
    return <div data-motion-ingredient={layer.primitive} style={shell}><div style={{position:"absolute",left:520,right:520,bottom:120,height:3,background:COLORS.amber,transform:`scaleX(${.4+.6*progress})`}}/></div>;
  }
  return null;
};

const TransformationThread: React.FC<{
  recipe: LayeredSceneRecipe;
  absoluteFrame: number;
}> = ({recipe, absoluteFrame}) => {
  const progress = clamp(
    (absoluteFrame - recipe.from) / Math.max(1, recipe.durationInFrames - 1),
  );
  const energy = recipe.signals.energy / 3;
  const handoffColor = recipe.signals.handoff.includes("network")
    ? COLORS.amber
    : COLORS.turquoise;
  return (
    <AbsoluteFill
      data-layered-recipe={recipe.id}
      data-layer-count={recipe.motionLayers.length}
      data-media-primary={recipe.media.primary}
      data-media-secondary={recipe.media.secondary}
      data-camera={recipe.camera.mode}
      data-audio-treatment={JSON.stringify(recipe.audio)}
      style={{pointerEvents: "none", zIndex: 70}}
    >
      <svg width="1920" height="1080" viewBox="0 0 1920 1080" style={{position:"absolute",inset:0,zIndex:1,mixBlendMode:"screen"}}>
        <path
          d="M 150 94 C 470 94, 510 188, 790 188 S 1110 94, 1450 94 S 1670 188, 1770 188"
          fill="none"
          stroke={handoffColor}
          strokeWidth={2 + energy * 3}
          pathLength="1"
          strokeDasharray="1"
          strokeDashoffset={1 - progress}
          opacity={0.34 + energy * 0.35}
        />
      </svg>
      {[...recipe.motionLayers]
        .sort((left, right) => left.zIndex - right.zIndex)
        .map((layer) => <MotionIngredient key={layer.primitive} layer={layer} recipe={recipe} progress={progress}/>)}
    </AbsoluteFill>
  );
};

const BoundaryView: React.FC<{cue: Cue}> = ({cue}) => {
  const local = useCurrentFrame();
  const isFade = cue.transition.mode === "fade";
  const section = cue.id.split("-")[0].toUpperCase();
  const blackOpacity = isFade ? 1 - local / 11 : local / 11;
  return (
    <AbsoluteFill style={{background: COLORS.panel, color: COLORS.cream, fontFamily: FONT_FAMILY}}>
      <CropSafeColumn top={420} bottom={420} style={{display: "grid", placeItems: "center", color: COLORS.turquoise, fontSize: 25, letterSpacing: 5}}>
        {section}
      </CropSafeColumn>
      <AbsoluteFill style={{background: "#000", opacity: clamp(blackOpacity)}} />
    </AbsoluteFill>
  );
};

const OpeningView: React.FC<{cue: Cue; absoluteFrame: number}> = ({cue, absoluteFrame}) => {
  const local = absoluteFrame - cue.from;
  if (cue.id === "opening-clock") {
    const clock = local >= 95 ? "09:17:00" : `09:16:${String(56 + Math.floor(local / 24)).padStart(2, "0")}`;
    return <PrimitiveFrame kicker="09:16 → 09:17" title="The last connected seconds"><CropSafeColumn top={350} bottom={350} style={{fontSize: 94, textAlign: "center", letterSpacing: 8, fontWeight: 700}}>{clock}</CropSafeColumn></PrimitiveFrame>;
  }
  if (cue.id === "opening-failure-cascade") {
    const labels = ["PHONE", "TRANSIT", "HOSPITAL", "TRAFFIC", "NEWS"];
    return <PrimitiveFrame kicker="09:17:00" title="The city forgets how to speak">
      <div style={{position: "absolute", left: 300, right: 300, top: 300, display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 18}}>{labels.map((label, index) => {
        const failed = local >= index * 34;
        return <div key={label} style={{height: 260, display: "grid", placeItems: "center", border: `2px solid ${failed ? COLORS.red : COLORS.turquoise}`, color: failed ? COLORS.red : COLORS.cream, background: failed ? "#090909" : COLORS.panel, fontSize: 20}}>{failed ? "NO SIGNAL" : label}</div>;
      })}</div>
    </PrimitiveFrame>;
  }
  if (cue.id === "opening-hard-silence") {
    return <AbsoluteFill style={{background: "#000", color: "#425158", fontFamily: FONT_FAMILY, display: "grid", placeItems: "center", fontSize: 26, letterSpacing: 8}}>NO CARRIER</AbsoluteFill>;
  }
  if (cue.id === "opening-first-pulse") {
    return <PrimitiveFrame kicker="One analog signal remains" title="Seven bursts. Eleven seconds."><SignalPulse /></PrimitiveFrame>;
  }
  if (cue.id === "opening-frozen-city") {
    return <PrimitiveFrame kicker="Citywide outage" title="Every screen is dark">
      <div style={{position: "absolute", left: 330, right: 330, top: 240, bottom: 250, display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 18}}>{Array.from({length: 12}, (_, index) => <div key={index} style={{border: "1px solid #23353b", background: index === 6 ? "radial-gradient(circle,#134d4c,#071114 55%)" : "#050708"}} />)}</div>
      <SignalPulse compact />
    </PrimitiveFrame>;
  }
  if (cue.id === "opening-tower") {
    const flash = clamp(local / 80);
    return <PrimitiveFrame kicker="Obsolete emergency band" title="Something old is still transmitting">
      <svg style={{position: "absolute", left: 680, top: 220}} width="560" height="600" viewBox="0 0 560 600">
        <path d="M280 55 L150 560 M280 55 L410 560 M190 410 H370 M215 310 H345 M240 205 H320" stroke={COLORS.cream} strokeWidth="8" fill="none" />
        <circle cx="280" cy="70" r={24 + flash * 110} fill="none" stroke={COLORS.turquoise} opacity={1 - flash * .7} />
        <circle cx="280" cy="70" r="10" fill={COLORS.turquoise} />
      </svg>
      <SignalPulse compact />
    </PrimitiveFrame>;
  }
  if (cue.id === "opening-title") {
    const reveal = 0.35 + clamp(local / 60) * 0.65;
    const pulseFrame = showcasePulseFrame(absoluteFrame);
    const titlePulse = signalPulseEnergy(pulseFrame, 24);
    const pulseTravel = signalPulseCycleFrame(pulseFrame, 24) / 264;
    return <AbsoluteFill style={{background: COLORS.ink, fontFamily: FONT_FAMILY, color: COLORS.cream, display: "grid", placeItems: "center"}}>
      <div style={{width: 560, textAlign: "center", opacity: reveal}}>
        <div data-title-pulse-energy={titlePulse.toFixed(4)} style={{height: 5, width: `${reveal * 100}%`, background: COLORS.turquoise, marginBottom: 30, position: "relative", boxShadow: `0 0 ${8 + titlePulse * 55}px ${COLORS.turquoise}`}}>
          <div style={{position: "absolute", left: `${pulseTravel * 100}%`, top: -5, width: 14, height: 14, borderRadius: 9, background: COLORS.turquoise, boxShadow: `0 0 ${18 + titlePulse * 32}px ${COLORS.turquoise}`}} />
        </div>
        <div style={{fontSize: 65, lineHeight: 1.05, fontWeight: 700}}>THE DAY THE INTERNET WENT DARK</div>
      </div>
    </AbsoluteFill>;
  }
  return <AbsoluteFill style={{background: "#000"}} />;
};

const MAP_PINS = [[180,350],[340,210],[500,380],[680,170],[820,330],[1040,220],[1160,410]] as const;
const ShowcaseMap: React.FC<{absoluteFrame: number}> = ({absoluteFrame}) => {
  const pinProgress = clamp((absoluteFrame - 1248) / (1679 - 1248));
  const rewind = clamp((absoluteFrame - 1680) / (2111 - 1680));
  const route = absoluteFrame < 1680 ? pinProgress : 1 - rewind * .62;
  return <PrimitiveFrame kicker={absoluteFrame >= 1680 ? "Timestamp rewind · 2012 → 1998" : "Seven decommissioned relays"} title="Follow the signal">
    <svg style={{position: "absolute", left: 260, top: 185}} width="1400" height="650" viewBox="0 0 1400 650">
      <rect width="1400" height="650" rx="25" fill="#071419" stroke="#1a3439" />
      {Array.from({length: 13}, (_, index) => <path key={index} d={`M${20 + index * 110} 0 C${80 + index * 90} 220 ${index * 120} 420 ${100 + index * 95} 650`} fill="none" stroke="#17323a" strokeWidth="2" />)}
      <path d="M180 350 C330 80 480 420 680 170 S950 390 1160 410" fill="none" stroke={COLORS.turquoise} strokeWidth="8" pathLength="1" strokeDasharray="1" strokeDashoffset={1-route} />
      {MAP_PINS.map(([x,y], index) => <g key={x} opacity={pinProgress >= index / 7 ? 1 : .12}><circle cx={x} cy={y} r="11" fill={index < 4 ? COLORS.red : COLORS.turquoise} /><text x={x+18} y={y-12} fill={COLORS.cream} fontSize="18">RELAY {index+1}</text></g>)}
    </svg>
    <div style={{position: "absolute", left: 700, top: 690, width: 520, textAlign: "center", color: COLORS.turquoise, fontSize: 22}}>{absoluteFrame >= 1680 ? `REWIND ${Math.round(rewind * 14)} YEARS` : `${Math.min(7, Math.max(1, Math.ceil(pinProgress * 7)))} / 7 PINS VERIFIED`}</div>
    <SignalPulse compact />
  </PrimitiveFrame>;
};

const VoicePacket: React.FC = () => <PrimitiveFrame kicker="Evidence threshold crossed" title="The signal stops behaving like data"><CropSafeColumn top={350} bottom={350} style={{padding: 28, boxSizing: "border-box", border: `2px solid ${COLORS.turquoise}`, textAlign: "center"}}><div style={{fontSize: 20, letterSpacing: 3, color: COLORS.turquoise}}>VOICE PACKET DETECTED</div><div style={{fontSize: 42, marginTop: 22}}>MARA · CHANNEL 07</div></CropSafeColumn><SignalPulse compact /></PrimitiveFrame>;

const ShowcaseTimeline: React.FC<{absoluteFrame:number}> = ({absoluteFrame}) => {
  const events = [
    {date:"1998",label:"BLACKOUT DRILL"},
    {date:"2012",label:"STORM FAILURE"},
    {date:"NOW",label:"CURRENT OUTAGE"},
  ];
  const progress=clamp((absoluteFrame-3072)/(3431-3072));
  const eventLeft=[330,650,950];
  return <PrimitiveFrame kicker="Three decades · one hidden sequence" title="Incident timeline"><div style={{position:"absolute",left:300,right:300,top:470,height:4,background:"#254047"}}><div style={{height:"100%",width:`${progress*100}%`,background:COLORS.turquoise}}/></div>{events.map((event,index)=><div key={event.date} style={{position:"absolute",left:eventLeft[index],top:340,width:220,opacity:progress>=index/3?1:.18}}><div style={{fontSize:38,fontWeight:700,color:index===2?COLORS.turquoise:COLORS.amber}}>{event.date}</div><div style={{marginTop:115,fontSize:20}}>{event.label}</div></div>)}<div style={{position:"absolute",left:700,width:520,top:690,textAlign:"center",color:COLORS.turquoise,fontSize:22}}>SAME SEVEN-BURST SEQUENCE</div><SignalPulse compact/></PrimitiveFrame>;
};

const MaraPortrait: React.FC<{label: string; sub: string}> = ({label, sub}) => <PrimitiveFrame kicker="Emergency operations · channel 07" title={label}>
  <CropSafeColumn top={205} bottom={230}>
    <div style={{height: 470, background: "radial-gradient(circle at 50% 36%,#31515a 0 14%,#152b33 15% 28%,#081217 29%)", border: "1px solid #244149", position: "relative"}}>
      <div style={{position: "absolute", left: 24, bottom: 24, right: 24, padding: 18, background: "rgba(3,8,11,.78)"}}><b style={{color: COLORS.turquoise}}>MARA</b><div style={{marginTop: 7, fontSize: 18}}>{sub}</div></div>
    </div>
  </CropSafeColumn>
  <SignalPulse compact />
</PrimitiveFrame>;

const MeasuredCaption: React.FC<{absoluteFrame: number; response?: boolean}> = ({absoluteFrame, response = false}) => {
  const words = response ? MARA_RESPONSE_WORDS : MARA_MEASURED_WORDS;
  const active = activeAbsoluteWord(words, absoluteFrame);
  return <PrimitiveFrame kicker={response ? "Mara · EN" : "Voice in signal · ES"} title={response ? "Listen to the last word." : "A voice inside the carrier"}>
    <CropSafeColumn top={300} bottom={325} style={{padding: 34, boxSizing: "border-box", background: "rgba(8,20,25,.92)", borderLeft: `5px solid ${response ? COLORS.amber : COLORS.turquoise}`}}>
      <div style={{fontSize: 37, lineHeight: 1.45}}>{words.map((word,index) => <span key={word.startFrame} style={{display: "inline-block", marginRight: 12, color: index === active ? COLORS.amber : COLORS.cream, transform: `translateY(${index === active ? -4 : 0}px)`}}>{word.text}</span>)}</div>
      <div style={{fontSize: 23, marginTop: 22, color: COLORS.blue}}>{response ? "No. He always swallowed the last word when he was afraid." : "Mara, if you can hear me, do not restart the network."}</div>
    </CropSafeColumn>
    <SignalPulse compact />
  </PrimitiveFrame>;
};

const RecoveryKey: React.FC = () => <PrimitiveFrame kicker="The voice is carrying the key" title="Ordered recovery sequence"><CropSafeColumn top={340} bottom={340} style={{display: "grid", placeItems: "center", border: `2px solid ${COLORS.turquoise}`, color: COLORS.turquoise, fontSize: 45, fontWeight: 700}}>09 · 04 · 21 · 16</CropSafeColumn><SignalPulse /></PrimitiveFrame>;

const NetworkState: React.FC<{absoluteFrame: number; reconnect: boolean}> = ({absoluteFrame,reconnect}) => {
  const start = reconnect ? 6048 : 5772;
  const progress = clamp((absoluteFrame-start)/(reconnect ? 280 : 220));
  const nodes = reconnect ? ["HOSPITAL","TRANSIT","EMERGENCY LINES","PUBLIC SCREENS"] : ["GRID","RELAY","RADIO","CITY"];
  const reconnectStarts = [6048,6132,6216,6300];
  return <PrimitiveFrame kicker={reconnect ? "One recovery pulse · ordered speech" : "Every part recovers at once"} title={reconnect ? "Reconnect in sequence" : "The new network collapses"}>
    <div style={{position: "absolute", left: 720, width: 480, top: 250, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 32}}>{nodes.map((node,index) => {
      const on = reconnect ? absoluteFrame >= reconnectStarts[index] : progress < 1-index/4;
      return <div key={node} style={{width: 190,height:190,padding:14,boxSizing:"border-box",textAlign:"center",justifySelf:index%2===0?"start":"end",borderRadius:100,display:"grid",placeItems:"center",border:`3px solid ${on?COLORS.turquoise:COLORS.red}`,color:on?COLORS.turquoise:COLORS.red,background:on?"rgba(45,226,208,.1)":"rgba(255,97,95,.08)",fontWeight:700}}>{node}</div>;
    })}</div>
    <div style={{position:"absolute",left:700,width:520,top:700,textAlign:"center",color:COLORS.turquoise,fontSize:21}}>{reconnect ? `${reconnectStarts.filter((value)=>absoluteFrame>=value).length} / 4 ONLINE` : "CASCADE FAILURE"}</div>
    <SignalPulse compact />
  </PrimitiveFrame>;
};

const CityReturn: React.FC<{absoluteFrame:number}> = ({absoluteFrame}) => {
  const progress=clamp((absoluteFrame-6384)/(6623-6384));
  const layers=["HOSPITAL","TRANSIT","EMERGENCY LINES","PUBLIC SCREENS"];
  return <PrimitiveFrame kicker="The city returns one layer at a time" title="Recovery"><CropSafeColumn top={250} bottom={260}>{layers.map((label,index)=><div key={label} style={{height:85,marginBottom:16,display:"flex",alignItems:"center",padding:"0 24px",background:progress>=(index+1)/4?COLORS.panelSoft:"#080b0d",borderLeft:`5px solid ${progress>=(index+1)/4?COLORS.turquoise:COLORS.red}`,color:progress>=(index+1)/4?COLORS.cream:"#5d6669"}}>{String(index+1).padStart(2,"0")} · {label}</div>)}</CropSafeColumn><SignalPulse compact /></PrimitiveFrame>;
};

const PullbackTimeline: React.FC<{absoluteFrame:number}> = ({absoluteFrame}) => {
  const pull=clamp((absoluteFrame-6624)/(6839-6624));
  return <PrimitiveFrame kicker="The camera keeps pulling backward" title="The film reveals its own construction"><div style={{position:"absolute",left:260,right:260,top:300,bottom:270,transform:`scale(${1-.24*pull})`,border:"2px solid #284149",padding:30,boxSizing:"border-box"}}>{[0,1,2,3].map((track)=><div key={track} style={{height:62,marginBottom:20,background:"#102329",borderLeft:`5px solid ${track===2?COLORS.amber:COLORS.turquoise}`,width:`${70+track*7}%`}} />)}<div style={{position:"absolute",left:`${pull*88}%`,top:0,bottom:0,width:3,background:COLORS.turquoise}} /></div><SignalPulse compact /></PrimitiveFrame>;
};

const FinalReveal: React.FC<{absoluteFrame:number}> = ({absoluteFrame}) => {
  const showTracks=absoluteFrame>=6840&&absoluteFrame<=6899;
  const showLanes=absoluteFrame>=6900;
  const showCenteredLanes=absoluteFrame>=6900&&absoluteFrame<=6959;
  const lock=clamp((absoluteFrame-6900)/59);
  const showChat=absoluteFrame>=6960;
  const showPlan=absoluteFrame>=7020;
  const converge=clamp((absoluteFrame-7080)/59);
  const promise=absoluteFrame>=7140;
  const end=absoluteFrame>=7176;
  if(end) return <AbsoluteFill style={{background:COLORS.ink,color:COLORS.cream,fontFamily:FONT_FAMILY,display:"grid",placeItems:"center"}}><div style={{width:560,textAlign:"center"}}><div style={{fontSize:62,fontWeight:700,letterSpacing:5}}>STORYENGINE</div><div style={{height:5,background:COLORS.turquoise,margin:"26px 0"}}/><div style={{fontSize:30}}>Tell it what you want to make.</div></div></AbsoluteFill>;
  return <PrimitiveFrame
    kicker="One request · one approved film"
    title="StoryEngine Custom Film"
    titleStyle={{opacity: absoluteFrame >= 7080 ? 0 : 1}}
  >
    {showTracks&&<div style={{position:"absolute",left:720,top:270,width:480,display:"grid",gridTemplateColumns:"1fr 1fr",gap:14}}>{["OPENING","EVIDENCE","WITNESS","EXPLANATION"].map((label,index)=><div key={label} style={{height:82,padding:"0 16px",boxSizing:"border-box",display:"flex",alignItems:"center",background:COLORS.panelSoft,borderLeft:`5px solid ${COLORS.turquoise}`}}>0{index+1} · {label}</div>)}</div>}
    {showCenteredLanes&&<div style={{position:"absolute",left:720,top:245,width:480}}><div style={{fontSize:15,letterSpacing:3,color:COLORS.turquoise,marginBottom:12,textAlign:"center"}}>PRODUCTION LANES LOCKED</div><div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>{["MAP","EVIDENCE","CAPTIONS","AUDIO","MOTION"].map((label,index)=><div key={label} style={{height:62,gridColumn:index===4?"1 / span 2":undefined,padding:"0 16px",display:"flex",alignItems:"center",justifyContent:"center",boxSizing:"border-box",background:"#0d2026",border:`1px solid ${COLORS.turquoise}`,transform:`scale(${.9+lock*.1})`}}>{label}</div>)}</div></div>}
    {showLanes&&!showCenteredLanes&&<>{["MAP","EVIDENCE","CAPTIONS","AUDIO","MOTION"].map((label,index)=>{const left=index<3?220:1450;const top=index<3?280+index*105:280+(index-3)*105;return <div key={label} style={{position:"absolute",left,top,width:250,height:62,padding:"0 16px",boxSizing:"border-box",display:"flex",alignItems:"center",background:"#0d2026",border:`1px solid ${COLORS.turquoise}`}}>{label}</div>})}</>}
    <CropSafeColumn top={170} bottom={170}>
      {showChat&&<div style={{padding:20,background:"#122329",border:"1px solid #315059",fontSize:17,lineHeight:1.42}}><b style={{display:"block",color:COLORS.turquoise,marginBottom:8}}>CUSTOM FILM REQUEST</b>{SHOWCASE_REQUEST}</div>}
      {showPlan&&<div style={{marginTop:14}}><div style={{fontSize:14,letterSpacing:2,color:COLORS.turquoise}}>APPROVED FOUR-SECTION PLAN</div><div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:7,marginTop:9}}>{["Opening · 45s","Evidence · 105s","Witness · 90s","Reveal · 60s"].map((line,index)=><div key={line} style={{padding:9,background:"#0d2026",borderLeft:`3px solid ${COLORS.turquoise}`,fontSize:14}}>0{index+1} {line}</div>)}</div><div style={{marginTop:10,padding:10,border:`1px solid ${COLORS.amber}`,color:COLORS.amber,textAlign:"center"}}>EXACT ESTIMATE $5.57 · HARD CAP $15.00 · APPROVAL REQUIRED</div></div>}
      <div style={{position:"absolute",left:0,right:0,top:610,textAlign:"center",opacity:promise?1:converge}}><div style={{fontSize:16,letterSpacing:3,color:COLORS.turquoise}}>STORYENGINE</div><div style={{height:5,width:`${converge*100}%`,background:COLORS.turquoise,margin:"14px auto",boxShadow:`0 0 ${converge*26}px ${COLORS.turquoise}`}}/><div style={{fontSize:promise?25:18,fontWeight:700}}>{promise?"One idea. The best production method for every part. One coherent film.":"ONE VERIFIED MASTER"}</div></div>
    </CropSafeColumn>
    {showLanes&&!showCenteredLanes&&<svg style={{position:"absolute",inset:0}} width="1920" height="1080">{[[470,311],[470,416],[470,521],[1450,311],[1450,416]].map(([x,y],index)=><path key={index} d={`M ${x} ${y} C ${x<960?720:1200} ${y}, ${x<960?800:1120} 760, 960 800`} fill="none" stroke={COLORS.turquoise} strokeWidth="3" pathLength="1" strokeDasharray="1" strokeDashoffset={1-converge}/>)}</svg>}
    <SignalPulse compact />
  </PrimitiveFrame>;
};

const GenericLayeredBeat: React.FC<{
  cue: LayeredSceneRecipe;
  absoluteFrame: number;
}> = ({cue, absoluteFrame}) => {
  const progress = clamp(
    (absoluteFrame - cue.from) / Math.max(1, cue.durationInFrames - 1),
  );
  const kicker = cue.signals.intents.join(" · ");
  const title = cue.narrativeFunction
    ? cue.narrativeFunction
    : cue.signals.dialogue
      ? "A human voice changes the picture"
      : cue.presentation === "StoryEngineReveal"
      ? "Every production lane becomes one film"
      : cue.presentation === "NetworkExplainer"
        ? "The system reveals its order"
        : "The evidence moves the story forward";
  let visual: React.ReactNode;
  if (cue.presentation === "OutageMap") {
    visual = <svg style={{position:"absolute",left:300,top:230}} width="1320" height="520" viewBox="0 0 1320 520"><rect width="1320" height="520" rx="24" fill="rgba(3,15,19,.58)" stroke="#315059"/><path d="M120 350 C320 90 520 410 700 180 S980 390 1190 210" fill="none" stroke={COLORS.turquoise} strokeWidth="7" pathLength="1" strokeDasharray="1" strokeDashoffset={1-progress}/>{[[120,350],[410,250],[700,180],[980,310],[1190,210]].map(([x,y],index)=><circle key={index} cx={x} cy={y} r="10" fill={progress>=index/5?COLORS.amber:"#274047"}/>)}</svg>;
  } else if (cue.presentation === "EvidenceBoard") {
    visual = <div style={{position:"absolute",left:350,right:350,top:235,height:500}}>{[0,1,2].map(index=><div key={index} style={{position:"absolute",left:80+index*300,top:40+(index%2)*100,width:250,height:320,transform:`rotate(${index*4-4}deg) scale(${.92+progress*.08})`,background:"rgba(226,216,190,.82)",border:"8px solid rgba(245,237,215,.72)",boxShadow:"0 20px 50px rgba(0,0,0,.35)"}}><div style={{height:110,margin:18,background:"#26383c"}}/><div style={{height:7,margin:18,background:COLORS.amber}}/><div style={{height:5,margin:18,background:"#556669"}}/></div>)}</div>;
  } else if (cue.presentation === "IncidentTimeline") {
    visual = <svg style={{position:"absolute",left:300,top:300}} width="1320" height="400" viewBox="0 0 1320 400"><path d="M80 200 H1240" stroke="#29454b" strokeWidth="5"/><path d="M80 200 H1240" stroke={COLORS.turquoise} strokeWidth="5" pathLength="1" strokeDasharray="1" strokeDashoffset={1-progress}/>{[180,650,1140].map((x,index)=><g key={x} opacity={progress>=index/3?1:.18}><circle cx={x} cy="200" r="16" fill={COLORS.amber}/><path d={`M${x} 170 V90`} stroke={COLORS.amber} strokeWidth="3"/></g>)}</svg>;
  } else if (cue.presentation === "RadioWaveform" || cue.presentation === "BilingualCaptions") {
    visual = <CropSafeColumn top={300} bottom={330} style={{background:"rgba(3,15,19,.58)",borderLeft:`5px solid ${COLORS.amber}`,display:"grid",placeItems:"center"}}><svg width="520" height="150" viewBox="0 0 520 150"><path d="M0 75 H80 L110 20 145 132 185 42 225 100 260 75 H520" fill="none" stroke={COLORS.turquoise} strokeWidth="6" pathLength="1" strokeDasharray="1" strokeDashoffset={1-progress}/></svg>{cue.signals.captions&&<div style={{fontSize:24,color:COLORS.cream,textAlign:"center"}}>VOICE / VOZ · {Math.round(progress*100)}%</div>}</CropSafeColumn>;
  } else if (cue.presentation === "NetworkExplainer") {
    visual = <svg style={{position:"absolute",left:620,top:230}} width="680" height="520" viewBox="0 0 680 520"><path d="M100 150 L340 70 580 150 340 430 Z" fill="none" stroke={COLORS.turquoise} strokeWidth="5"/>{[[100,150],[340,70],[580,150],[340,430]].map(([x,y],index)=><circle key={index} cx={x} cy={y} r="38" fill={progress>=(index+1)/4?COLORS.turquoise:COLORS.red}/>)}</svg>;
  } else if (cue.presentation === "StoryEngineReveal") {
    visual = <CropSafeColumn top={250} bottom={300}>{[0,1,2,3].map(index=><div key={index} style={{height:62,marginBottom:18,width:`${76+index*7}%`,background:"rgba(10,38,44,.78)",borderLeft:`5px solid ${index===2?COLORS.amber:COLORS.turquoise}`}}/>)}<div style={{height:6,width:`${progress*100}%`,background:COLORS.turquoise,boxShadow:`0 0 ${progress*32}px ${COLORS.turquoise}`}}/></CropSafeColumn>;
  } else {
    visual = <CropSafeColumn top={235} bottom={285} style={{background:"radial-gradient(circle at 50% 48%,rgba(45,226,208,.24),rgba(3,10,13,.48) 55%)",border:"1px solid #315059",transform:`scale(${1+progress*.035})`}}><div/></CropSafeColumn>;
  }
  return <PrimitiveFrame kicker={kicker} title={title} mediaAware>{visual}</PrimitiveFrame>;
};

const ShowcaseRecipePresentation: React.FC<{
  cue: LayeredSceneRecipe;
  absoluteFrame: number;
}> = ({cue, absoluteFrame}) => {
  if (cue.id.includes(":beat:")) {
    return <GenericLayeredBeat cue={cue} absoluteFrame={absoluteFrame}/>;
  }
  switch (cue.presentation) {
    case "Boundary":
      return <BoundaryView cue={cue}/>;
    case "CinematicOpening":
      return <OpeningView cue={cue} absoluteFrame={absoluteFrame}/>;
    case "OutageMap":
      return <ShowcaseMap absoluteFrame={absoluteFrame}/>;
    case "EvidenceBoard":
      if (cue.id === "evidence-voice-packet") return <VoicePacket/>;
      return <EvidenceBoard timelineOffsetFrames={24}/>;
    case "IncidentTimeline":
      return <ShowcaseTimeline absoluteFrame={absoluteFrame}/>;
    case "BilingualCaptions":
      if (cue.id === "witness-measured-line") return <MeasuredCaption absoluteFrame={absoluteFrame}/>;
      if (cue.id === "witness-objection-response") return <MeasuredCaption absoluteFrame={absoluteFrame} response/>;
      if (cue.id === "witness-reaction") return <MaraPortrait label="“That’s my brother.”" sub="The room insists the voice must be synthetic."/>;
      return <MaraPortrait label="Mara hears a familiar voice" sub="Emergency operator · bilingual witness"/>;
    case "RadioWaveform":
      return cue.id === "witness-recovery-key" ? <RecoveryKey/> : <RadioWaveform/>;
    case "NetworkExplainer":
      if (cue.id === "reveal-node-collapse") return <NetworkState absoluteFrame={absoluteFrame} reconnect={false}/>;
      if (cue.id === "reveal-ordered-reconnect") return <NetworkState absoluteFrame={absoluteFrame} reconnect/>;
      return <CityReturn absoluteFrame={absoluteFrame}/>;
    case "StoryEngineReveal":
      return cue.id === "reveal-pullback-timeline"
        ? <PullbackTimeline absoluteFrame={absoluteFrame}/>
        : <FinalReveal absoluteFrame={absoluteFrame}/>;
    case "SignalPulse":
      return <OpeningView cue={cue} absoluteFrame={absoluteFrame}/>;
    default:
      throw new Error(`Unsupported layered presentation: ${cue.presentation}/${cue.id}`);
  }
};

export const ShowcaseCueScene: React.FC<{cue: LayeredSceneRecipe}> = ({cue}) => {
  const localFrame=useCurrentFrame();
  const absoluteFrame=cue.from+localFrame;
  return (
    <AbsoluteFill
      data-recipe-id={cue.id}
      data-recipe-primitives={cue.motionLayers.map(({primitive}) => primitive).join(",")}
      style={{zIndex: 30}}
    >
      <ShowcaseRecipePresentation cue={cue} absoluteFrame={absoluteFrame}/>
      <TransformationThread recipe={cue} absoluteFrame={absoluteFrame}/>
    </AbsoluteFill>
  );
};
