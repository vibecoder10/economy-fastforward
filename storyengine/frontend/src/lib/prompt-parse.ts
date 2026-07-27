/**
 * Deterministic (non-LLM, non-classifier) parsers for DirectorHome's
 * single-prompt entry box.
 *
 * Two things typed IN the sentence need to land at CREATION time, before the
 * seeded message ever reaches the chat copilot's classifier — the
 * classifier only ever extracts ONE verb per turn (see routes/chat.py's
 * COPILOT_ACTIONS / `verb` field), so a sentence that reads mainly as "make
 * a video about X" naturally classifies as `build` and never even looks at
 * a co-occurring "cap the spend at $1" — that phrase would otherwise be
 * silently dropped (found live 2026-07-27, same shape as the length bug
 * fixed in 84f18d55):
 *   - a spoken length ("a five minute video") — parseLengthMinutes.
 *   - a spend cap ("cap the spend at $1") — parseSpendCapDollars.
 *
 * Both live in this one shared file (not duplicated in DirectorHome.tsx and
 * ChatCore.tsx) because ChatCore needs the EXACT SAME parse result to
 * disclose what it found (or explicitly didn't find) in the opening chat
 * turn — see ChatCore's `initialMessage` mount effect. A regex + a plain
 * word->number lookup, not a classifier — good enough for the realistic
 * phrasing, not a general NLP amount parser.
 */

const ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
const TEENS = [
  "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
  "sixteen", "seventeen", "eighteen", "nineteen",
];
const NUMBER_WORDS: Record<string, number> = {};
ONES.forEach((w, i) => (NUMBER_WORDS[w] = i + 1));
TEENS.forEach((w, i) => (NUMBER_WORDS[w] = i + 10));
NUMBER_WORDS.twenty = 20;
NUMBER_WORDS.thirty = 30;
ONES.forEach((w, i) => {
  NUMBER_WORDS[`twenty-${w}`] = 20 + i + 1;
  NUMBER_WORDS[`twenty ${w}`] = 20 + i + 1;
});

const NUMBER_WORD_ALTERNATION = Object.keys(NUMBER_WORDS)
  .sort((a, b) => b.length - a.length) // "twenty-five" before "five"
  .map((w) => w.replace(/[- ]/g, "[- ]"))
  .join("|");

// --- length ("a five minute video" / "10 min") ------------------------------

export const LENGTH_FLOOR_MINUTES = 1;
export const LENGTH_CEILING_MINUTES = 30;

const DIGIT_LENGTH_RE = /\b(\d{1,2})\s*[- ]?\s*(minutes?|mins?)\b/i;
const WORD_LENGTH_RE = new RegExp(
  `\\b(${NUMBER_WORD_ALTERNATION})\\s*[- ]?\\s*(minutes?|mins?)\\b`,
  "i"
);

function clampLength(n: number): number {
  return Math.max(LENGTH_FLOOR_MINUTES, Math.min(LENGTH_CEILING_MINUTES, Math.round(n)));
}

export function parseLengthMinutes(text: string): number | null {
  const digit = text.match(DIGIT_LENGTH_RE);
  if (digit) {
    const n = parseInt(digit[1], 10);
    if (!Number.isNaN(n)) return clampLength(n);
  }
  const word = text.match(WORD_LENGTH_RE);
  if (word) {
    const key = word[1].toLowerCase().replace(/\s+/g, " ").trim();
    const val = NUMBER_WORDS[key] ?? NUMBER_WORDS[key.replace(/ /g, "-")];
    if (val != null) return clampLength(val);
  }
  return null;
}

// --- spend cap ("cap the spend at $1" / "budget of $5" / "$3 cap") ---------
//
// Keyword-anchored, NOT "grab the first number in the sentence" — a naive
// first-dollar-amount parser would misfire on a story that happens to
// mention a number ("a boy with 5 dragons... cap it at $2" must read $2,
// not 5). Requires a cap/budget/limit keyword within a short distance of
// the dollar amount, in either order. Deliberately narrower than
// actions.py's `_resolve_budget_cap_text` (which grabs the first dollar-ish
// number in the WHOLE message) — that function only ever runs on a
// follow-up turn where the classifier already decided the entire message
// IS about the budget; this one runs on a mixed free-text sentence where
// most of it is about something else entirely.
const SPEND_KEYWORD = "(?:cap(?:ped|ping)?|budget(?:ed)?|limit(?:ed)?)";
const DOLLAR_NUM = "\\$?\\s*(\\d+(?:\\.\\d{1,2})?)\\s*(?:dollars?|usd|\\$)?";
const SPEND_CAP_FORWARD_RE = new RegExp(`\\b${SPEND_KEYWORD}\\b[^.$\\d]{0,25}${DOLLAR_NUM}`, "i");
const SPEND_CAP_REVERSE_RE = new RegExp(`${DOLLAR_NUM}[^.]{0,15}\\b${SPEND_KEYWORD}\\b`, "i");
// Spelled-out amount ("cap it at five dollars") — reuses the same
// number-word table parseLengthMinutes uses above.
const SPEND_CAP_WORD_RE = new RegExp(
  `\\b${SPEND_KEYWORD}\\b[^.\\d]{0,25}\\b(${NUMBER_WORD_ALTERNATION})\\b\\s*(?:dollars?|usd)?`,
  "i"
);
const SPEND_MENTION_RE = new RegExp(`\\b${SPEND_KEYWORD}\\b`, "i");

/** Parsed dollar amount (2dp), or null if no cap/budget/limit language with
 * a readable amount was found. */
export function parseSpendCapDollars(text: string): number | null {
  const t = text || "";
  const fwd = t.match(SPEND_CAP_FORWARD_RE);
  if (fwd) {
    const n = parseFloat(fwd[1]);
    if (Number.isFinite(n) && n > 0) return Math.round(n * 100) / 100;
  }
  const rev = t.match(SPEND_CAP_REVERSE_RE);
  if (rev) {
    const n = parseFloat(rev[1]);
    if (Number.isFinite(n) && n > 0) return Math.round(n * 100) / 100;
  }
  const word = t.match(SPEND_CAP_WORD_RE);
  if (word) {
    const key = word[1].toLowerCase().replace(/\s+/g, " ").trim();
    const val = NUMBER_WORDS[key] ?? NUMBER_WORDS[key.replace(/ /g, "-")];
    if (val != null) return val;
  }
  return null;
}

/** True when the sentence uses cap/budget/limit language but
 * parseSpendCapDollars couldn't resolve an amount from it — the "typed a
 * cap but it didn't land" case that must be disclosed, never silently
 * dropped (money-safety: a creator who believes they capped spend when
 * they didn't is the failure mode this whole fix exists to prevent). */
export function mentionsSpendCapWithoutAmount(text: string): boolean {
  return SPEND_MENTION_RE.test(text || "") && parseSpendCapDollars(text) == null;
}

// The exact prefix DirectorHome's confirmModel() seeds as the opening chat
// turn for a modeled (YouTube-reference) video. ChatCore uses this to skip
// the channel-identity disclosure on that path — modeling still fully
// inherits the tenant's locked channel identity (unchanged); only the
// plain-description box opts out (see routes/videos.py
// CreateVideoRequest.apply_channel_identity).
export const MODEL_VIDEO_MESSAGE_PREFIX = "Model this video:";
