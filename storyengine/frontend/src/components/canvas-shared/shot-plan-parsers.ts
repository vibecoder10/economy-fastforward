/**
 * Pure parsers for the saved coverage directive / storyboard prompt text.
 * Harvested out of ScenesWorkspaceTab.tsx (DIRECTOR-CHAT-PLAN.md Task 0.2)
 * so the canvas (Board/Shot altitudes) can read the same shot-plan shape
 * without importing the whole Scenes tab. No React, no side effects.
 */

export function parseStoryboardPromptBlocks(promptText: string | null | undefined) {
  const prompt = (promptText || "").trim();
  if (!prompt) return [];
  const beatRegex = /--- BEAT (\d+) ---\s*\n([\s\S]*?)(?=\n--- BEAT \d+ ---|$)/g;
  const beats = Array.from(prompt.matchAll(beatRegex)).map((match) => ({
    beatNumber: Number(match[1]),
    prompt: match[2].trim(),
  }));
  if (beats.length > 0) return beats;
  return [{ beatNumber: 1, prompt }];
}

/** Parse the saved coverage directive (the shot plan) into a clean structure:
 * the [SET | ...] geography/props line plus one row per SHOT with its global
 * panel number (masters then angles, in order — the SAME numbering the board
 * sheets use, so row 13 here IS panel 13 on the boards). */
export function parseShotPlan(directive: string | null | undefined) {
  const text = (directive || "").trim();
  if (!text) return null;
  const setMatch = text.match(/\[SET\s*\|\s*([^\]]+)\]/i);
  const momentRe = /\[MOMENT\s+(\d+)\s*\|\s*([^\]]*)\]/gi;
  const heads = Array.from(text.matchAll(momentRe));
  let panel = 0;
  const shots: Array<{ panel: number; moment: number; summary: string; role: string;
    shotType: string; speaker: string | null; line: string | null; desc: string }> = [];
  heads.forEach((h, i) => {
    const block = text.slice((h.index || 0) + h[0].length,
      i + 1 < heads.length ? heads[i + 1].index : text.length);
    const lineMatch = block.match(/^\s*\*{0,2}\s*LINE\s*:\s*([^|"\n]+?)\s*\|\s*"([^"]+)"/im);
    const shotRe = /-\s*\*{0,2}\s*(MASTER|ANGLE)\s*\[?\s*([A-Za-z][\w /-]*?)\s*\]?\s*\*{0,2}\s*:\s*([\s\S]*?)(?=\n\s*-\s*\*{0,2}\s*(?:MASTER|ANGLE)\b|$)/gi;
    let first = true;
    for (const m of Array.from(block.matchAll(shotRe))) {
      panel += 1;
      shots.push({
        panel,
        moment: Number(h[1]),
        summary: h[2].trim(),
        role: m[1].toUpperCase(),
        shotType: m[2].trim().toUpperCase(),
        speaker: first && lineMatch ? lineMatch[1].trim() : null,
        line: first && lineMatch ? lineMatch[2].trim() : null,
        desc: m[3].trim().replace(/\s+/g, " "),
      });
      first = false;
    }
  });
  if (!shots.length) return null;
  return { set: setMatch ? setMatch[1].trim() : null, shots };
}

/** Parse the ENFORCED plan out of the persisted BEAT blocks — the exact
 * numbered panel briefs the board sheets draw ([13] M13 MS — desc SPEAKING …),
 * grouped per board. The raw directive can contain MORE shots than the budget
 * allows (planner overshoot), so parsing it showed "40 shots" while the boards
 * draw 27 — the BEAT blocks are post-budget and match the boards 1:1. */
export function parseEnforcedPlan(promptText: string | null | undefined) {
  const beats = parseStoryboardPromptBlocks(promptText);
  if (!beats.length || !beats[0].prompt.includes("[1]")) return null;
  const shots: Array<{ panel: number; moment: number; board: number; role: string;
    shotType: string; speaker: string | null; line: string | null; desc: string }> = [];
  const lineRe = /\[(\d+)\]\s+M(\d+)\s+(ANGLE\s+)?([A-Za-z][\w /-]*?)\s+—\s+([^\n]*)/g;
  for (const b of beats) {
    for (const m of Array.from(b.prompt.matchAll(lineRe))) {
      let desc = m[5].trim();
      let speaker: string | null = null, line: string | null = null;
      const sp = desc.match(/\sSPEAKING\s+([^:]+):\s*"([^"]*)"?\s*$/);
      if (sp) { speaker = sp[1].trim(); line = sp[2].trim(); desc = desc.slice(0, sp.index).trim(); }
      shots.push({ panel: Number(m[1]), moment: Number(m[2]), board: b.beatNumber,
        role: m[3] ? "ANGLE" : "MASTER", shotType: m[4].trim().toUpperCase(), speaker, line, desc });
    }
  }
  return shots.length ? shots : null;
}
