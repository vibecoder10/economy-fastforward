"""Functional tests for the dialogue-line alignment chain (2026-07-02 fix).

The live failure: every spoken line landed ~2 shots early because (a) the
turn splitter merged same-speaker lines across narration, and (b) the line
reconcile ignored the planner's LINE markers and stamped turns positionally.
These tests pin the fixed behavior at every layer: turn splitting, the shot
budget, planner-respecting reconcile, and assigned_dialogue line matching.

No network, no DB: heavy imports are stubbed (module-stub pattern).
Run: python3 tests/functional/test_dialogue_alignment.py  (from backend dir)
"""

import os
import sys
import types

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BACKEND)

# ── Stub coverage_to_app's runtime deps BEFORE importing it ──
def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod

async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")

_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import (  # noqa: E402
    _coverage_shape,
    _dialogue_turns,
    _reconcile_moment_dialogue,
    _match_scene_env,
    _norm_env_text,
)
from clip_dialogue import match_assigned  # noqa: E402

# The Marco scene's dialogue skeleton (narration abbreviated).
MARCO_SCENE = """
**Marco:** ¡Espera! ¡Espera!
Marco's running to school. Again. His backpack bouncing, breath short, shoes slapping the pavement. No one's waiting.
**Marco:** Lo siento. Llegué tarde otra vez.
Lo siento means I'm sorry. Marco always says this. Every single morning his friends don't even look up anymore.
Lunchtime. Marco sits by himself. He pulls out his sandwich.
**Sofia:** ¿Por qué siempre llegas tarde, Marco?
Sofia's asking him why do you always arrive late. Por qué means why and siempre means always in Spanish.
**Marco:** No sé. Corro rápido, pero...
I don't know. I run fast but. Corro means I run. But it's never fast enough for him to arrive.
Then one morning, something changes. Marco sprints to school, same as always, but everyone else is running too.
**Marco:** ¿Qué pasa? ¿Por qué corren?
What's happening, why are you all running he asks them all in the street.
**Sofia:** ¡Llegamos tarde! ¡El reloj de la escuela estaba roto!
We're late, the school clock was broken. Marco stops and looks at Sofia and laughs for the first time in weeks.
"""


def _moment(summary, shot="MS", speaker=None, line=None):
    return {"summary": summary, "master": {"shot_type": shot, "description": summary},
            "angles": [], "speaker": speaker, "line": line}


def test_turns_split_across_narration():
    turns = _dialogue_turns(MARCO_SCENE)
    assert [(s, t[:12]) for s, t in turns] == [
        ("Marco", "¡Espera! ¡Es"),
        ("Marco", "Lo siento. L"),
        ("Sofia", "¿Por qué sie"),
        ("Marco", "No sé. Corro"),
        ("Marco", "¿Qué pasa? ¿"),
        ("Sofia", "¡Llegamos ta"),
    ], turns


def test_turns_adjacent_same_speaker_still_merge():
    text = "**Tom:** Hello there.\n**Tom:** It is me.\nNarration between.\n**Tom:** New turn."
    turns = _dialogue_turns(text)
    assert turns == [("Tom", "Hello there. It is me."), ("Tom", "New turn.")], turns


def test_reconcile_respects_planner_markers():
    """The live bug scenario: silent moments first, speaking moments marked."""
    moments = [
        _moment("Silent establishing — Marco sprints down the street", "WS"),
        _moment("Marco calls out racing toward the gate", speaker="Marco",
                line="Espera, espera! (planner paraphrase)"),
        _moment("Silent — Marco slides into his seat", "WS"),
        _moment("Sofia questions Marco at the cafeteria", speaker="Sofia",
                line="Por que siempre llegas tarde"),
        _moment("Marco answers Sofia", speaker="Marco", line="No se, corro rapido"),
        _moment("Sofia reveals the clock was broken", speaker="Sofia",
                line="Llegamos tarde"),
    ]
    turns = [("Marco", '¡Espera! ¡Espera!'), ("Sofia", '¿Por qué siempre llegas tarde, Marco?'),
             ("Marco", 'No sé. Corro rápido, pero...'), ("Sofia", '¡Llegamos tarde!')]
    text = "\n".join(f"{s}: {t}" if i % 2 == 0 else f"narration here\n{s}: {t}"
                     for i, (s, t) in enumerate(turns))
    out = _reconcile_moment_dialogue(moments, text)
    # Silent moments stay silent
    assert out[0]["line"] is None and out[2]["line"] is None
    # Marked moments carry VERBATIM script words, in order
    assert out[1]["line"] == '¡Espera! ¡Espera!' and out[1]["speaker"] == "Marco"
    assert out[3]["line"] == '¿Por qué siempre llegas tarde, Marco?'
    assert out[4]["line"] == 'No sé. Corro rápido, pero...'
    assert out[5]["line"] == '¡Llegamos tarde!'


def test_reconcile_folds_missing_moment_onto_same_speaker():
    """Planner made ONE Marco moment but the script has two Marco turns."""
    moments = [
        _moment("Silent wide", "WS"),
        _moment("Marco speaks", speaker="Marco", line="something"),
        _moment("Sofia replies", speaker="Sofia", line="reply"),
    ]
    text = "Marco: First line here.\nnarration\nMarco: Second line too.\nnarration\nSofia: Reply words."
    out = _reconcile_moment_dialogue(moments, text)
    assert out[0]["line"] is None
    assert out[1]["line"] == "First line here. Second line too."  # folded, no loss
    assert out[2]["line"] == "Reply words."


def test_reconcile_kills_hallucinated_line():
    """A planner LINE for a speaker who never talks in the script goes silent."""
    moments = [
        _moment("Marco speaks", speaker="Marco", line="real"),
        _moment("Ghost speaks", speaker="Narrator", line="I do not exist in the script"),
    ]
    out = _reconcile_moment_dialogue(moments, "Marco: Hola amigo.")
    assert out[0]["line"] == "Hola amigo."
    assert out[1]["line"] is None and out[1]["speaker"] is None


def test_reconcile_legacy_fallback_skips_silent_summaries():
    """No LINE rows at all → positional stamp, but never onto 'Silent —' moments."""
    moments = [
        _moment("Silent establishing — street"),
        _moment("Marco shouts at the gate"),
        _moment("Sofia answers him"),
    ]
    out = _reconcile_moment_dialogue(
        moments, "Marco: Hola.\nnarration\nSofia: Adiós.")
    assert out[0]["line"] is None
    assert out[1]["line"] == "Hola." and out[1]["speaker"] == "Marco"
    assert out[2]["line"] == "Adiós."


def test_reconcile_replays_the_real_marco_plan():
    """The EXACT plan the planner produced live (cached coverage.json,
    2026-07-02) — made under the old 4-turn merged checklist — replayed with
    the new 6-turn splitter. Text-cover matching must land every line on the
    moment the planner built for it: merged-turn masters share, silents stay
    silent, nothing drifts."""
    moments = [
        _moment("Silent establishing — Marco sprints down the school street", "WS"),
        _moment("Marco calls out as he races toward the school gate",
                speaker="Marco", line="¡Espera! ¡Espera! Lo siento. Llegué tarde otra vez."),
        _moment("Silent — Marco slides into his seat alone; the Teacher nods", "WS"),
        _moment("Sofia questions Marco at the cafeteria lunch table",
                speaker="Sofia", line="¿Por qué siempre llegas tarde, Marco?"),
        _moment("Marco answers Sofia, then reacts to everyone running in",
                speaker="Marco", line="No sé. Corro rápido, pero... ¿Qué pasa? ¿Por qué corren?"),
        _moment("Sofia reveals the clock was broken — Marco laughs",
                speaker="Sofia", line="¡Llegamos tarde! ¡El reloj de la escuela estaba roto!"),
    ]
    out = _reconcile_moment_dialogue(moments, MARCO_SCENE)
    assert out[0]["line"] is None and out[2]["line"] is None       # silents stay silent
    assert out[1]["line"] == "¡Espera! ¡Espera! Lo siento. Llegué tarde otra vez."
    assert out[3]["line"] == "¿Por qué siempre llegas tarde, Marco?"
    assert out[4]["line"] == "No sé. Corro rápido, pero... ¿Qué pasa? ¿Por qué corren?"
    assert out[5]["line"] == "¡Llegamos tarde! ¡El reloj de la escuela estaba roto!"
    assert out[1]["speaker"] == "Marco" and out[3]["speaker"] == "Sofia"


def test_shape_echo_paces_to_runtime():
    """voice_over echo channels: one moment per ~8s of speech, angles 0-2 and
    EARNED, total frames capped at 2× the paced count (≤40). Ryan's rule."""
    mm, amin, amax, mframes = _coverage_shape(MARCO_SCENE, "voice_over")
    assert (amin, amax) == (0, 2)
    est_seconds = len(MARCO_SCENE.split()) / 2.5
    expected = max(6 + 2, round(est_seconds / 8))
    assert mm == expected, (mm, expected)
    assert mframes == min(2 * expected, 40), mframes
    # A long scene rides the 40-frame ceiling, never beyond
    heavy = MARCO_SCENE + ("\nThe narrator keeps teaching lots of extra words. " * 60)
    assert _coverage_shape(heavy, "voice_over")[3] == 40
    # Tiny pure-dialogue scene → masters-only branch (turns + establishing)
    assert _coverage_shape("Tom: Hi.\nLisa: Hey.", "voice_over")[0] == 3


def test_shape_pure_dialogue_plans_masters_only():
    """Couple format: no narrator → no clock for silent angles. One
    establishing + one master per line for the PLANNER (max_moments/angles
    unchanged), but max_frames now carries headroom (C8 fix (a)) above the
    master count so enforce_reaction_insert_floors can ADD its reaction/
    insert/re-establish shots instead of being forced into a conversion that
    can never succeed with zero angle-role shots on the board (angles_max=0
    here). Headroom = the SAME ratios the floor validator itself uses:
    max(1, turns // 4) reactions + masters // 7 inserts + masters // 10
    re-establishes. 24 turns → 25 masters, headroom = max(1,6) + 3 + 2 = 11."""
    turns = 24
    text = "\n".join(f"{'Ryan' if i % 2 else 'Vanessa'}: line {i} palabra." for i in range(turns))
    mm, amin, amax, mf = _coverage_shape(text, "voice_over")
    masters = turns + 1
    expected_headroom = max(1, turns // 4) + masters // 7 + masters // 10
    assert (mm, amin, amax) == (masters, 0, 0), (mm, amin, amax)
    assert mf == masters + expected_headroom == 36, (mf, expected_headroom)


def test_shape_pure_dialogue_headroom_matches_real_scene2_dry_run():
    """Pins the exact live dry-run scene (Spanish Class scene 2, video
    cd5d2883): 35 speaking turns, no narrator. Before C8 fix (a), max_frames
    equalled the 36 masters exactly (zero headroom) and the floor validator
    could place 0 of 8 wanted reactions. This is the number that, fed
    through the real deterministic pipeline on the scene's saved planner
    directive, actually funds all 8 reactions (see shot-list-scene2-v2.md)."""
    turns = 35
    text = "\n".join(f"{'Ryan' if i % 2 else 'Vanessa'}: turn {i}." for i in range(turns))
    mm, amin, amax, mf = _coverage_shape(text, "voice_over")
    assert (mm, amin, amax, mf) == (36, 0, 0, 52), (mm, amin, amax, mf)


def test_shape_pure_dialogue_headroom_capped_for_a_pathological_scene():
    """A scene with hundreds of turns must not let the floor validator ADD an
    unbounded number of shots — COVERAGE_FLOOR_HEADROOM_CAP (default 20)
    bounds the EXTRA headroom (never the master count itself, which is the
    one-shot-per-line law and always survives uncapped)."""
    turns = 300
    text = "\n".join(f"{'Ryan' if i % 2 else 'Vanessa'}: t{i}." for i in range(turns))
    mm, amin, amax, mf = _coverage_shape(text, "voice_over")
    masters = turns + 1
    assert (mm, amin, amax) == (masters, 0, 0)
    assert mf == masters + 20, (mf, masters)  # headroom capped, masters uncapped


def test_shape_pure_dialogue_headroom_cap_is_env_tunable():
    turns = 300
    text = "\n".join(f"{'Ryan' if i % 2 else 'Vanessa'}: t{i}." for i in range(turns))
    os.environ["COVERAGE_FLOOR_HEADROOM_CAP"] = "5"
    try:
        mm, amin, amax, mf = _coverage_shape(text, "voice_over")
    finally:
        os.environ.pop("COVERAGE_FLOOR_HEADROOM_CAP", None)
    assert mf == (turns + 1) + 5, mf


def test_shape_grok_native_keeps_cinematic_coverage():
    mm, amin, amax, mframes = _coverage_shape(MARCO_SCENE, "grok_native")
    assert (amin, amax) == (1, 2)  # the Pixar-grade multi-angle path
    assert mframes is None
    assert mm >= 10, mm
    # Pure narration keeps classic coverage in both modes
    assert _coverage_shape("Just narration, no speakers at all.") == (3, 2, 3, None)


# ── C8 fix (b): _match_scene_env real-data fixtures ──
# Verbatim (read-only, `se db`) scene 1 and scene 2 text and the two approved
# environments for video cd5d2883 (Spanish Class) — the exact live dry-run
# proof case. video_environments real ORDER BY sort, created_at: Home
# kitchen at sort=0, Community kitchen at sort=1.
_SPANISH_SCENE_1_TEXT = (
    "**Ryan:** I have one hour to learn enough Spanish to survive a cooking "
    "class in front of strangers. Vanessa enrolled us three weeks ago. She "
    "told me one hour ago.\n\n**Vanessa:** Sorpresa.\n\n**Ryan:** Sorpresa. "
    "Surprise. Yeah. I'm surprised. I'm very surprised. Why didn't you tell "
    "me three weeks ago?\n\n**Vanessa:** Because you would have said no.\n\n"
    "**Ryan:** Yes. I would have said no. Because I don't speak Spanish.\n\n"
    "**Vanessa:** Poco a poco, mi amor. Little by little. We have one hour. "
    "I'll teach you everything you need.\n\n**Ryan:** Everything. In one "
    "hour. For a cooking class. In Spanish.\n\n**Vanessa:** Sí. The class is "
    "tortilla española. Spanish omelet. Very simple.\n\n**Ryan:** Simple. "
    "Great. What's a tortilla española?\n\n**Vanessa:** Eggs, potatoes, "
    "onions. That's it. Three ingredients."
)
_SPANISH_SCENE_2_TEXT = (
    "**Vanessa:** Now the actions. You need to know how to peel.\n\n"
    "**Ryan:** Peel. What's peel?\n\n**Vanessa:** Pelar. Pelar las patatas. "
    "Peel the potatoes.\n\n**Ryan:** Pelar. Peel. Pelar las patatas. I peel "
    "the potatoes with the… wait, what's knife again?\n\n**Vanessa:** "
    "Cuchillo.\n\n**Ryan:** Cuchillo. Right. I peel the potatoes with the "
    "cuchillo. Wait, no. Do I peel with a knife? Don't I need a peeler?\n\n"
    "**Vanessa:** In the class, you use a knife. Pelar con el cuchillo.\n\n"
    "**Ryan:** Pelar con el cuchillo. This sounds dangerous. What's cut?"
)
_SPANISH_ENVS = [
    {"name": "Home kitchen — cram session",
     "description": "A sunlit Mediterranean-style kitchen with sage green "
                     "cabinetry, warm terracotta tile flooring."},
    {"name": "Community cooking class kitchen",
     "description": "Professional culinary kitchen with multiple wooden "
                     "islands featuring stainless steel countertops."},
]


def test_match_scene_env_scene1_is_genuinely_the_class_kitchen():
    """Scene 1's own name-phrase doesn't appear verbatim, but "cooking" and
    "class" both hit distinctly (>=2 distinct words) — strong enough
    evidence to win outright, same as before this fix (C8 fix (b) only
    raises the bar for a SINGLE stray word, not for real multi-word
    overlap)."""
    env = _match_scene_env(_SPANISH_SCENE_1_TEXT, _SPANISH_ENVS)
    assert env["name"] == "Community cooking class kitchen", env


def test_match_scene_env_scene2_is_genuinely_the_home_kitchen():
    """The live bug: scene 2 never names either environment, and the ONLY
    word-level signal is "class" appearing ONCE ("In the class, you use a
    knife") — before this fix that single stray word handed the whole
    home cram-session scene to the wrong (community) kitchen. Now a lone
    word with no distinct partner and no margin isn't enough, so the match
    falls through to the first approved environment — which, on cd5d2883's
    real video_environments row order, IS the home kitchen."""
    env = _match_scene_env(_SPANISH_SCENE_2_TEXT, _SPANISH_ENVS)
    assert env["name"] == "Home kitchen — cram session", env


def test_match_scene_env_no_evidence_falls_back_to_first_approved():
    """A scene whose text names neither environment at all, word or phrase,
    still needs SOME anchor rather than crashing the draw with no location
    lock — falls back to envs[0] (the creator's own first-added/approved
    environment, `_approved_envs`'s own sort order)."""
    envs = [{"name": "Rooftop bar", "description": "d"},
            {"name": "Downtown loft", "description": "d"}]
    env = _match_scene_env("Two friends argue about nothing in particular.", envs)
    assert env["name"] == "Rooftop bar", env


def test_match_scene_env_single_stray_word_never_wins_alone():
    """Direct regression pin for the exact failure mode: a SINGLE word hit,
    for only ONE environment, with the other environment at zero — must NOT
    win by itself anymore (score=1, distinct=1, runner=0 fails every strong-
    evidence branch)."""
    envs = [{"name": "Home kitchen — cram session", "description": "d"},
            {"name": "Community cooking class kitchen", "description": "d"}]
    text = "The only thing on the mind of every student in class is dinner."
    env = _match_scene_env(text, envs)
    # "class" hits once for Community, nothing for Home — old code returned
    # Community; new code falls back to envs[0] (Home, listed first).
    assert env["name"] == "Home kitchen — cram session", env


def test_match_scene_env_two_distinct_words_still_win_over_the_fallback():
    """Two distinct word hits (not the same word repeated) DO clear the new
    bar — the fallback only kicks in when evidence is genuinely thin."""
    envs = [{"name": "Home kitchen — cram session", "description": "d"},
            {"name": "Community cooking class kitchen", "description": "d"}]
    text = "The community show runs a cooking segment before class starts."
    env = _match_scene_env(text, envs)
    assert env["name"] == "Community cooking class kitchen", env


# ── locked-location mismatch, video 686b4651 scene 2 (verbatim, `se db`) ──
# Real environments (video_environments, ORDER BY sort) and the real scene 2
# coverage_directive (its [SET | ...] header, trimmed to the parts that
# matter — the full body is ~1500 more chars of shot setups irrelevant to
# the match). Live failure: scene 2's own SET header correctly names "Elite
# Viewing Hall", but that same header ALSO mentions, in passing, that its
# screen "displays a live feed of the underground bubble-pod warren" (what's
# ON the screen — a real, different environment — not the scene's own
# location). A hyphen inside "bubble-pod" was mis-split as a title/subtitle
# separator (the same code path meant for "Home kitchen — cram session"),
# manufacturing a nonsense "Underground bubble" head-fragment that phrase-
# matched the passing mention and tied "Underground bubble-pod warren"'s
# score with the scene's genuine "Elite viewing hall" match — the tie
# silently resolved to whichever environment iterates first (sort=0,
# Underground). Storyboard generation then locked the LOCKED LOCATION
# reference block (scripts/coverage_to_app.py, `env['name']` in the sheet
# prompt) to the WRONG location, contradicting the prompt's own scene
# description — and got rejected by the image provider's content filter for
# naming two different, contradictory locations in one prompt. This test
# fails on the pre-fix code (asserts "Elite viewing hall", pre-fix code
# returns "Underground bubble-pod warren") and passes after.
_VIDEO_686B4651_ENVS = [
    {"name": "Underground bubble-pod warren", "description": "d"},
    {"name": "Nyla's glass bubble-pod interior", "description": "d"},
    {"name": "Elite viewing hall", "description": "d"},
]
_VIDEO_686B4651_SCENE_2_DIRECTIVE = (
    "[SET | Elite Viewing Hall: black ornamental walls with gold accents, "
    "arched alcoves with sconces, decorative urns in alcoves, ceiling "
    "chandelier/medallion lit overhead, leather armchairs in curved rows "
    "with brass candleholders and gold side tables between them, "
    "railing/barrier panel at the base of the massive curved screen — "
    "screen currently displaying a live feed of the underground bubble-pod "
    "warren. No characters from the underground appear in this scene. "
    "Three Elites seated in the front curved row, spread across the width "
    "of the hall, all facing the screen.]"
)
_VIDEO_686B4651_SCENE_2_TEXT = (
    "Far above, the elites gather each night around a screen the size of a "
    "building. They watch the bubbles below like weather, like pets. It is "
    "their favorite show, and no one below knows they are the cast."
)


def test_match_scene_env_set_header_wins_over_a_passing_mention_of_another_location():
    env = _match_scene_env(
        _VIDEO_686B4651_SCENE_2_DIRECTIVE + " " + _VIDEO_686B4651_SCENE_2_TEXT,
        _VIDEO_686B4651_ENVS,
    )
    assert env["name"] == "Elite viewing hall", env


# ── D6-6b: nested-frame mention outscores the scene's own declared set ──
# Video 8d90df90-be0f-4328-b9d3-20f6bb5b71a6 scene 4 (the elites scene),
# verbatim: environments from `se db` (video_environments ORDER BY sort:
# Pod=1, Corridor=2, Elite Viewing Hall=3), scene_text from the scripts row,
# and the [SET|] header + the one nested-frame INSERT shot from the exact
# coverage_directive the D6-6a dry run planned (both trimmed to the parts
# that decide the match — the full directive is ~6.8kB of setups).
#
# The third instance of the "a scene legitimately names ANOTHER location"
# bug class, and the first that neither prior fix covers. Scene 4's own
# header declares The Elite Viewing Hall, and its INSERT shot correctly
# describes what is ON the hall's giant screen — Nyla's pod (a BOARD-LAWS
# L11 nested frame: normal, expected, correct content). Phrase counting sees
# only totals: "pod" twice (2*3=6) beats "elite viewing hall" once (1*3=3),
# so the scene matched the POD and the pod's material_map got stamped into
# the emitted board prompt on a scene set in a solid-walled hall.
#
# Note what does NOT save it here. No score was inflated (both prior
# regressions above turn on inflation), so the hyphen fix is irrelevant —
# the counts are honest and the wrong one is genuinely higher. And
# _SET_HEADER_ENV_RE never fires: this header is "Name, prose…" with no
# name/description colon, its first colon ~800 chars in ("a permanent
# feature of this set:"), far past that pattern's 80-char reach.
_VIDEO_8D90DF90_ENVS = [
    {"name": "Pod", "description": "d"},
    {"name": "Corridor", "description": "d"},
    {"name": "Elite Viewing Hall", "description": "d"},
]
_VIDEO_8D90DF90_SCENE_4_DIRECTIVE = (
    "[SET | The Elite Viewing Hall, a private theatre high above the warren. "
    "Black ornamental walls with gold accents, arched alcoves holding lit "
    "sconces and decorative urns, a chandelier medallion glowing overhead, "
    "deep leather armchairs in a single curved front row with gold side "
    "tables and brass candleholders between them, a low brass railing at the "
    "base of the screen. The screen is a permanent feature of this set: a "
    "single curved screen the size of a building filling frame-CENTRE, always "
    "on, always showing a live feed of the underground warren below. No "
    "character from the underground is ever physically present in this hall; "
    "they appear only as picture on the screen.]\n"
    "[MOMENT 2 | Gold Woman points her glass at Nyla on the screen]\n"
    "[INSERT]: (SETUP D) the feed fills the whole panel: the grid of stacked "
    "bubble-pods, and picked out nearer the centre one lit pod holding Nyla "
    "standing with one palm raised flat against the curve of her pod, tiny in "
    "the vast grid; no hall furniture and no elites in frame."
)
_VIDEO_8D90DF90_SCENE_4_TEXT = (
    "Far above, the elites gather each night around a screen the size of a "
    "building. They watch the bubbles below like weather, like pets. \"Look at "
    "this one,\" a woman in gold says, pointing her glass at Nyla. \"She talks "
    "to the ceiling. How sweet.\" The room laughs softly. \"They never look "
    "up,\" an old man smiles. \"That is what makes it fun.\" It is their "
    "favorite show, and no one below knows they are the cast."
)


def test_match_scene_env_nested_frame_mention_never_beats_the_declared_set():
    """The live D6-6a repro. Pre-fix this returns Pod (score 6 vs the hall's
    3); post-fix the header's own declaration settles it before phrase
    scoring ever runs."""
    env = _match_scene_env(
        _VIDEO_8D90DF90_SCENE_4_DIRECTIVE + " " + _VIDEO_8D90DF90_SCENE_4_TEXT,
        _VIDEO_8D90DF90_ENVS,
    )
    assert env["name"] == "Elite Viewing Hall", env


def test_match_scene_env_declared_set_wins_even_when_phrase_count_disagrees():
    """Pins the PRECEDENCE, not just the outcome: the losing environment must
    genuinely out-count the winner on the phrase score, otherwise this test
    would still pass with the header check deleted. Asserts the scoring the
    header now overrides is really stacked the wrong way."""
    text = _VIDEO_8D90DF90_SCENE_4_DIRECTIVE + " " + _VIDEO_8D90DF90_SCENE_4_TEXT
    low = f" {_norm_env_text(text)} "

    def _score(name):
        return low.count(f" {_norm_env_text(name)} ") * 3

    assert _score("Pod") > _score("Elite Viewing Hall"), (
        _score("Pod"), _score("Elite Viewing Hall"))
    assert _match_scene_env(text, _VIDEO_8D90DF90_ENVS)["name"] == "Elite Viewing Hall"


def test_match_scene_env_header_declaration_beats_a_later_mention_in_that_same_header():
    """The header pass reads only the OPENING of a header body, so a passing
    mention of another location INSIDE the set description can't hijack it
    either — 686b4651 scene 2's shape ("…screen currently displaying a live
    feed of the underground bubble-pod warren", hundreds of chars into the
    scene's own header). Here the exact-colon check is deliberately defeated
    (leading "The", so it can't settle this) to force the new pass to be the
    one deciding."""
    envs = [
        {"name": "Underground bubble-pod warren", "description": "d"},
        {"name": "Elite viewing hall", "description": "d"},
    ]
    text = (
        "[SET | The Elite viewing hall, a private theatre. Black ornamental "
        "walls with gold accents, arched alcoves with sconces, leather "
        "armchairs in curved rows with brass candleholders and gold side "
        "tables between them, a railing at the base of the massive curved "
        "screen -- screen currently displaying a live feed of the underground "
        "bubble-pod warren.]"
    )
    env = _match_scene_env(text, envs)
    assert env["name"] == "Elite viewing hall", env


def test_match_scene_env_locset_key_declares_the_location_too():
    """L3 multi-location plans declare each location as a [LOCSET | <name> |
    <text>] key rather than a single [SET|] line. Those keys are the same
    kind of structural declaration, so they must outrank phrase counting the
    same way — here "Pod" is mentioned twice as nested-screen content and
    would otherwise win outright."""
    envs = [{"name": "Pod", "description": "d"},
            {"name": "Elite Viewing Hall", "description": "d"}]
    text = (
        "[LOCSET | Elite Viewing Hall | black ornamental walls, a curved "
        "screen the size of a building.]\n"
        "[INSERT]: the feed shows one lit pod holding Nyla, her palm flat "
        "against the curve of her pod."
    )
    env = _match_scene_env(text, envs)
    assert env["name"] == "Elite Viewing Hall", env


def test_match_scene_env_hyphen_inside_a_compound_word_is_not_a_title_separator():
    """Narrower regression pin, isolating just the head-splitting mechanism
    (no [SET | ...] header involved, and no full-name or multi-word overlap
    that the word-fallback's own >=2-distinct-word bar would independently
    catch). "Basement-level arcade"'s glued hyphen (no surrounding spaces —
    unlike "Home kitchen — cram session"'s em-dash, or a genuine "Title -
    Subtitle") is not a title/subtitle separator. Before the fix it was
    mis-split into head "Basement" (>=8 chars, clears the bonus floor),
    which phrase-matches the single stray word "basement" in this text and
    wins OUTRIGHT in the primary scoring loop — bypassing the fallback's
    deliberately stricter "single stray word never wins alone" bar entirely
    (see test_match_scene_env_single_stray_word_never_wins_alone above; that
    guard only runs when the primary loop finds nothing). After the fix, the
    un-split full name doesn't appear as a phrase, the primary loop finds
    nothing, and the fallback's own stray-word bar correctly rejects the
    lone "basement" hit and defaults to envs[0]."""
    envs = [
        {"name": "Rooftop garden", "description": "d"},
        {"name": "Basement-level arcade", "description": "d"},
    ]
    text = "It was cold outside. He went down to the basement to grab his coat, then left for the party."
    env = _match_scene_env(text, envs)
    assert env["name"] == "Rooftop garden", env


def test_enforce_budget_frame_ceiling_strips_angles_first():
    from storyboard.coverage import enforce_shot_budget
    moments = [{"moment_number": i + 1, "summary": f"m{i+1}",
                "master": {"shot_type": "MS", "description": "d"},
                "angles": [{"shot_type": "CU", "description": "a1"},
                           {"shot_type": "OTS", "description": "a2"}]}
               for i in range(10)]  # 30 frames planned
    out = enforce_shot_budget(moments, 10, 2, max_frames=18)
    frames = sum(1 + len(m["angles"]) for m in out)
    assert frames == 18, frames
    assert len(out) == 10  # every master survives — angles paid the bill
    # stripping starts at the tail: the earliest moments keep their angles
    assert all(len(m["angles"]) == 2 for m in out[:4])
    assert all(len(m["angles"]) == 0 for m in out[5:])
    # Masters alone above the ceiling → tail moments drop, never crash
    out2 = enforce_shot_budget([dict(m, angles=[]) for m in moments], 10, 2, max_frames=4)
    assert len(out2) == 4


def _coverage_directive(n_moments: int, angles_per_moment: int, axis: bool = True) -> str:
    """A synthetic coverage plan with a KNOWN shot count:
    n_moments * (1 master + angles_per_moment angles). AXIS-format (drives
    panels_per_sheet_for's hard-6 branch) when axis=True; no [AXIS|...] line
    (legacy plan, always caps at 12) when axis=False."""
    lines = []
    if axis:
        lines += ["[AXIS | Left frame-left, Right frame-right.]", ""]
    for i in range(1, n_moments + 1):
        lines.append(f"[MOMENT {i} | moment {i} happens]")
        lines.append(f"- MASTER [WS]: master shot for moment {i}.")
        for a in range(angles_per_moment):
            lines.append(f"- ANGLE [CU]: angle {a + 1} for moment {i}.")
        lines.append("")
    return "\n".join(lines)


def test_panels_per_sheet_for_is_a_hard_six_for_axis_plans_any_size():
    """Pins the design fixed 2026-07-21: panels_per_sheet_for used to scale
    the cap up to ceil(shots/5) (floored at 6) for scenes too big to fit 5
    boards at 6 — but that let the cap climb back to 9 on big scenes (proven
    live on the Spanish Class video: prompts said "a grid of 9 panels"
    despite the 6-target fix) and even 7-8 still flirts with the same content
    filter. The fix drops the adaptive math entirely: an AXIS plan is ALWAYS
    6, no matter how big the raw plan is (proven here with a 45-shot
    directive) — a scene that big simply previews only its first 30 panels,
    which generate_storyboard_sheet_for_scene's prompts[:5] slice and the
    board-anchor block's `si < len(board_urls)` guard already handle without
    crashing or losing any shot from the actual pictures step."""
    from storyboard.coverage import panels_per_sheet_for, parse_coverage

    fat_directive = _coverage_directive(15, 2)  # 15 * (1 + 2) = 45 shots
    raw_shots = sum(1 + len(m.get("angles") or []) for m in parse_coverage(fat_directive))
    assert raw_shots == 45, raw_shots
    assert panels_per_sheet_for(fat_directive) == 6

    # A small AXIS scene is the same hard 6 — no scaling either direction.
    small_directive = _coverage_directive(3, 2)  # 3 * 3 = 9 shots
    assert panels_per_sheet_for(small_directive) == 6

    # Legacy (non-AXIS) plans always keep 12, regardless of size.
    legacy_directive = _coverage_directive(15, 2, axis=False)
    assert panels_per_sheet_for(legacy_directive) == 12


def test_sheet_chunk_sizes_balances_boards():
    """Balanced chunking (Ryan, 2026-07-21): fixed-stride chunking left the
    last board a runt (15 shots drew 6+6+3, 20 drew 6+6+6+2). Board count is
    unchanged (ceil(total/cap)); the panels are spread evenly instead."""
    from storyboard.coverage import sheet_chunk_sizes

    assert sheet_chunk_sizes(15, 6) == [5, 5, 5]
    assert sheet_chunk_sizes(16, 6) == [6, 5, 5]
    assert sheet_chunk_sizes(20, 6) == [5, 5, 5, 5]
    assert sheet_chunk_sizes(33, 6) == [6, 6, 6, 5, 5, 5]
    assert sheet_chunk_sizes(6, 6) == [6]
    assert sheet_chunk_sizes(3, 6) == [3]
    # Legacy cap goes through the same function.
    assert sheet_chunk_sizes(16, 12) == [8, 8]
    assert sheet_chunk_sizes(0, 6) == []
    # Invariants, swept: no chunk over cap, everything accounted for, board
    # count identical to fixed-stride, sizes within 1 of each other.
    for cap in (6, 12):
        for total in range(1, 61):
            sizes = sheet_chunk_sizes(total, cap)
            assert sum(sizes) == total, (total, cap, sizes)
            assert len(sizes) == -(-total // cap), (total, cap, sizes)  # ceil
            assert all(s <= cap for s in sizes), (total, cap, sizes)
            assert max(sizes) - min(sizes) <= 1, (total, cap, sizes)


def test_sheet_chunking_and_anchor_math_share_one_source_of_truth():
    """The whole point of sheet_chunk_sizes: sheet CHUNKING (which panels
    _plan_sheet_prompts puts on which board) and picture ANCHORING (which
    board_url a shot pins to in storyboard.coverage's board-anchor block)
    must agree on the boundaries, or pictures anchor to a panel on the wrong
    sheet. Both now derive from sheet_chunk_sizes — this proves the actual
    _plan_sheet_prompts output lands every panel on the board the anchor
    math (cumulative sheet_chunk_sizes boundaries, exactly as coverage.py
    computes them) assigns it, and that each prompt header's declared panel
    count is the same sizes entry end to end."""
    import re
    from scripts.coverage_to_app import _plan_sheet_prompts
    from storyboard.coverage import sheet_chunk_sizes

    cap = 6
    for total in (9, 15, 16, 20, 33):
        moments = []
        for i in range(total):  # masters-only: total moments == total panels
            m = _moment(f"beat {i + 1} action")
            m["moment_number"] = i + 1
            moments.append(m)
        sizes = sheet_chunk_sizes(total, cap)
        prompts = _plan_sheet_prompts(moments, "Pixar 3D", panels_per_sheet=cap)
        assert len(prompts) == len(sizes), (total, len(prompts), sizes)

        # The board each panel ACTUALLY landed on, parsed from the prompts.
        actual_board = {}
        for bi, prompt in enumerate(prompts):
            for match in re.finditer(r"^\[(\d+)\]", prompt, re.MULTILINE):
                actual_board[int(match.group(1))] = bi
        assert sorted(actual_board) == list(range(1, total + 1)), total

        # The board the anchor math assigns — the cumulative-boundary lookup
        # exactly as storyboard.coverage's board-anchor block computes it.
        bounds, run = [], 0
        for size in sizes:
            run += size
            bounds.append(run)
        for k in range(1, total + 1):
            si = next(i for i, b in enumerate(bounds) if k <= b)
            assert actual_board[k] == si, (total, k, actual_board[k], si)

        # End to end: each header's declared panel count is the sizes entry.
        for bi, prompt in enumerate(prompts):
            m = re.search(r"grid of (\d+) panels", prompt)
            assert m and int(m.group(1)) == sizes[bi], (total, bi, sizes)


def test_match_assigned():
    lines = [
        {"speaker": "Marco", "text": "¡Espera! ¡Espera!", "audio_url": "u1"},
        {"speaker": "Marco", "text": "Lo siento. Llegué tarde otra vez.", "audio_url": "u2"},
        {"speaker": "Sofia", "text": "¿Por qué siempre llegas tarde, Marco?", "audio_url": "u3"},
    ]
    # exact single turn
    got = match_assigned('Marco: "¡Espera! ¡Espera!"', lines)
    assert [l["audio_url"] for l in got] == ["u1"], got
    # folded master carrying two Marco turns → both, in order
    got = match_assigned('Marco: "¡Espera! ¡Espera! Lo siento. Llegué tarde otra vez."', lines)
    assert [l["audio_url"] for l in got] == ["u1", "u2"], got
    # speaker must match — Sofia's words on a Marco label match nothing
    assert match_assigned('Marco: "¿Por qué siempre llegas tarde, Marco?"', lines[:2]) == []
    # no assigned / junk assigned
    assert match_assigned(None, lines) == []
    assert match_assigned("not a line", lines) == []


def test_sheet_prompts_preview_the_whole_plan():
    from scripts.coverage_to_app import _plan_sheet_prompts, _scene_text_hash
    moments = []
    for i in range(9):  # 9 moments, every 3rd speaks, every 2nd has an angle
        m = _moment(f"moment {i+1} action", speaker="Marco" if i % 3 == 0 else None,
                    line=f"linea {i+1}" if i % 3 == 0 else None)
        m["moment_number"] = i + 1
        if i % 2 == 0:
            m["angles"] = [{"shot_type": "CU", "description": f"angle of {i+1}"}]
        moments.append(m)
    prompts = _plan_sheet_prompts(moments, "Pixar 3D", panels_per_sheet=12)
    total_panels = 9 + 5  # masters + angles
    assert len(prompts) == 2, len(prompts)  # balanced 7 + 7 (was fixed-stride 12 + 2)
    joined = "\n".join(prompts)
    for k in range(1, total_panels + 1):
        assert f"[{k}]" in joined, f"panel {k} missing"
    # C25a-fix14 (Ryan, 2026-07-20): spoken lines are NO LONGER baked into the
    # sheet image (they were the surviving content-filter trigger; the sheet is
    # a preview and the lines live in the saved plan). The sheet previews every
    # PANEL, but carries no dialogue text.
    assert "CAPTION" not in "".join(prompts)
    assert "linea 1" not in "".join(prompts)
    assert "Pixar 3D" in prompts[0] and "Pixar 3D" in prompts[1]
    assert "sheet 1 of 2" in prompts[0] and "sheet 2 of 2" in prompts[1]
    # hash pins the plan to the text, whitespace-insensitively
    assert _scene_text_hash("a  b\nc") == _scene_text_hash("a b c")
    assert _scene_text_hash("a b c") != _scene_text_hash("a b d")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} dialogue-alignment tests passed")
