"""Camera Movement Catalog — the durable vocabulary of camera moves.

Seeded by aicameramovements.com's 46-move grid (7 categories), pruned and
tuned to what the wired animators (grok-imagine, seedance, veo, kling)
actually execute cleanly.

The key idea: a camera move is a CONTRACT between two prompts.
- ``motion_prompt`` is the phrase fed to the animator.
- ``image_setup`` is the composition the STILL IMAGE must have for the
  move to land (a dolly-in needs depth layers; an orbit needs a hero
  subject with space around it; a pass-through needs a foreground portal).

The selector (camera_selector.py) picks a move BEFORE image generation so
``image_setup`` can be injected into the image prompt — the image is
composed for the move, not animated blind.

Compatibility: every move carries a ``legacy_key`` mapping onto the 8-key
``CAMERA_MOVEMENTS`` dict in prompt_builder.py, and every motion_prompt
contains a keyword that ``detect_camera_movement()`` recognizes, so the
existing rotation-history and validation machinery keeps working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Camera purposes — mirror animation_prompt_engine constants (string-typed
# here to avoid an import cycle; values must match).
PURPOSE_REVEAL = "REVEAL"
PURPOSE_SCALE = "SCALE"
PURPOSE_ISOLATION = "ISOLATION"
# Extended earned purposes (selector-only; classify_camera_purpose never
# returns these — they come from shot position, see camera_selector.py):
PURPOSE_ESTABLISH = "ESTABLISH"   # scene-opening wide that sets the space
PURPOSE_PAYOFF = "PAYOFF"         # scene-final shot that lands the beat

# Subject kinds
SUBJECT_CHARACTER = "character"       # a person/creature is the hero
SUBJECT_TWO_SUBJECTS = "two_subjects" # two focal elements at different depths
SUBJECT_ENVIRONMENT = "environment"   # place/landscape is the hero
SUBJECT_DATA = "data"                 # chart/map/display is the hero
SUBJECT_OBJECT = "object"             # single prop/product is the hero

# All wired animators (channel_profile.MODEL_REGISTRY keys)
_ALL_MODELS = ("grok-imagine", "seedance-2-fast", "veo-3.1-fast",
               "veo-3.1-quality", "kling-3.0-pro", "runway-gen4-turbo",
               "hailuo-2.3-standard")
# Specials that only the stronger motion models execute reliably
_STRONG_MODELS = ("seedance-2-fast", "veo-3.1-quality", "kling-3.0-pro")


@dataclass(frozen=True)
class CameraMove:
    """One camera move: what the animator does + what the image needs."""

    id: str
    name: str
    category: str            # dolly_track | zoom_lens | drone_crane | pan_tilt | physical | human_camera | specials
    motion_prompt: str       # phrase for the animation prompt (contains a legacy-detectable keyword)
    image_setup: str         # composition the still image MUST have
    best_for: tuple          # purposes this move serves (PURPOSE_* values)
    subject_fit: tuple       # SUBJECT_* kinds this move works on
    pace: str                # slow | medium | fast
    intensity: int           # 1 (calm) .. 5 (aggressive)
    legacy_key: str          # maps onto prompt_builder.CAMERA_MOVEMENTS keys
    model_support: tuple = _ALL_MODELS
    avoid_when: str = ""     # plain-English condition that breaks this move


CAMERA_MOVES: dict[str, CameraMove] = {m.id: m for m in [

    # ------------------------------------------------------------------
    # DOLLY / TRACK
    # ------------------------------------------------------------------
    CameraMove(
        id="dolly_in", name="Dolly In", category="dolly_track",
        motion_prompt="Camera slowly dollies in, pushing in toward the subject in a straight line",
        image_setup="compose with clear depth layers — distinct foreground elements framing the edges, subject in midground, visible background behind",
        best_for=(PURPOSE_ISOLATION, PURPOSE_PAYOFF),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_OBJECT, SUBJECT_DATA),
        pace="slow", intensity=2, legacy_key="push-in",
        avoid_when="the frame is flat with no depth layers — reads as a cheap zoom",
    ),
    CameraMove(
        id="dolly_out", name="Dolly Out", category="dolly_track",
        motion_prompt="Camera slowly dollies out, pulling back in a straight line to widen the view",
        image_setup="compose tight on the subject with hints of a larger surrounding space at the frame edges that a pull-back can reveal",
        best_for=(PURPOSE_SCALE, PURPOSE_REVEAL),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_ENVIRONMENT, SUBJECT_DATA, SUBJECT_OBJECT),
        pace="slow", intensity=2, legacy_key="pull-back",
        avoid_when="there is nothing beyond the subject worth revealing",
    ),
    CameraMove(
        id="truck_left", name="Truck Left", category="dolly_track",
        motion_prompt="Camera trucks left on a straight horizontal track, pan across the scene while facing forward",
        image_setup="compose with lateral breadth — content extending past the left frame edge and layered foreground/background for parallax",
        best_for=(PURPOSE_REVEAL, PURPOSE_ESTABLISH),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER, SUBJECT_DATA),
        pace="medium", intensity=2, legacy_key="lateral-pan",
        avoid_when="the scene has no lateral content or foreground layers for parallax",
    ),
    CameraMove(
        id="truck_right", name="Truck Right", category="dolly_track",
        motion_prompt="Camera trucks right on a straight horizontal track, pan across the scene while facing forward",
        image_setup="compose with lateral breadth — content extending past the right frame edge and layered foreground/background for parallax",
        best_for=(PURPOSE_REVEAL, PURPOSE_ESTABLISH),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER, SUBJECT_DATA),
        pace="medium", intensity=2, legacy_key="lateral-pan",
        avoid_when="the scene has no lateral content or foreground layers for parallax",
    ),
    CameraMove(
        id="tracking_follow", name="Tracking Follow", category="dolly_track",
        motion_prompt="Camera moves in a tracking shot, following the subject and keeping them centered as they move",
        image_setup="compose the subject mid-motion with clear travel direction and open space ahead of them in the frame",
        best_for=(PURPOSE_REVEAL,),
        subject_fit=(SUBJECT_CHARACTER,),
        pace="medium", intensity=3, legacy_key="lateral-pan",
        avoid_when="the subject is stationary — nothing to follow",
    ),
    CameraMove(
        id="pedestal_up", name="Pedestal Up", category="dolly_track",
        motion_prompt="Camera rises vertically in a smooth crane up, keeping the framing level",
        image_setup="compose with vertical layering — meaningful content stacked from bottom to top of frame so rising reveals more",
        best_for=(PURPOSE_REVEAL, PURPOSE_SCALE),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER, SUBJECT_DATA),
        pace="slow", intensity=2, legacy_key="tilt-up",
        avoid_when="content is a single horizontal band with empty space above",
    ),
    CameraMove(
        id="pedestal_down", name="Pedestal Down", category="dolly_track",
        motion_prompt="Camera descends vertically in a smooth crane down, keeping the framing level",
        image_setup="compose with vertical layering — meaningful content continuing below the subject so descending reveals more",
        best_for=(PURPOSE_REVEAL, PURPOSE_ISOLATION),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER, SUBJECT_DATA),
        pace="slow", intensity=2, legacy_key="tilt-down",
        avoid_when="the lower frame is empty ground with nothing to reveal",
    ),
    CameraMove(
        id="dolly_in_low", name="Low-Angle Dolly In", category="dolly_track",
        motion_prompt="Camera dollies in from a low angle, pushing in upward toward the subject so it towers in frame",
        image_setup="compose from a low angle looking up at the subject, subject dominant against sky or ceiling, foreground ground plane visible",
        best_for=(PURPOSE_SCALE, PURPOSE_PAYOFF),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_OBJECT, SUBJECT_ENVIRONMENT),
        pace="slow", intensity=3, legacy_key="push-in",
        avoid_when="the shot is intimate or vulnerable — low-angle reads as power",
    ),
    CameraMove(
        id="dolly_zoom", name="Dolly Zoom (Vertigo)", category="dolly_track",
        motion_prompt="Dolly zoom effect: camera pushing in while the lens pulls wider, background warping away while the subject stays the same size",
        image_setup="compose subject fixed center-frame with a deep, receding background full of parallel lines or repeating depth cues",
        best_for=(PURPOSE_ISOLATION, PURPOSE_PAYOFF),
        subject_fit=(SUBJECT_CHARACTER,),
        pace="medium", intensity=5, legacy_key="push-in",
        model_support=_STRONG_MODELS,
        avoid_when="background lacks depth cues, or the beat isn't a dread/realization moment",
    ),

    # ------------------------------------------------------------------
    # ZOOM / LENS
    # ------------------------------------------------------------------
    CameraMove(
        id="slow_zoom_in", name="Slow Zoom In", category="zoom_lens",
        motion_prompt="Slow steady zoom pushing in, the frame gradually tightening on the subject",
        image_setup="compose with the subject clearly centered and enough margin around it that a tightening frame stays clean",
        best_for=(PURPOSE_ISOLATION,),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_OBJECT, SUBJECT_DATA),
        pace="slow", intensity=1, legacy_key="push-in",
        avoid_when="the subject is at a frame edge — the zoom will crop it out",
    ),
    CameraMove(
        id="slow_zoom_out", name="Slow Zoom Out", category="zoom_lens",
        motion_prompt="Slow steady zoom out, the frame gradually widening to show more of the scene",
        image_setup="compose the frame edge-to-edge with meaningful content — a widening frame must find more scene, not empty margins",
        best_for=(PURPOSE_SCALE, PURPOSE_REVEAL),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_DATA, SUBJECT_CHARACTER),
        pace="slow", intensity=1, legacy_key="pull-back",
        avoid_when="the composition is already a wide with dead space at the edges",
    ),
    CameraMove(
        id="crash_zoom_in", name="Crash Zoom In", category="zoom_lens",
        motion_prompt="Crash zoom: the lens snaps rapidly in toward the main target with sudden aggressive speed",
        image_setup="compose with one unmistakable focal target — high contrast against its surroundings, dead center or on a strong third",
        best_for=(PURPOSE_ISOLATION, PURPOSE_PAYOFF),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_OBJECT, SUBJECT_DATA),
        pace="fast", intensity=5, legacy_key="snap-zoom",
        avoid_when="the beat is calm or emotional — crash zoom is a punchline/shock tool",
    ),
    CameraMove(
        id="fast_zoom_in", name="Fast Zoom In", category="zoom_lens",
        motion_prompt="Fast push toward the main visual target, quick zoom tightening the frame with urgency",
        image_setup="compose with a single dominant focal target centered, secondary elements kept to the margins",
        best_for=(PURPOSE_ISOLATION,),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_OBJECT, SUBJECT_DATA),
        pace="fast", intensity=4, legacy_key="snap-zoom",
        avoid_when="multiple competing focal points would make the target ambiguous",
    ),
    CameraMove(
        id="rack_focus", name="Rack Focus", category="zoom_lens",
        motion_prompt="Static shot with a rack focus: focus pulls from the foreground element to the background subject",
        image_setup="compose two subjects at clearly different depths — a sharp foreground element and a distinct background subject, both readable",
        best_for=(PURPOSE_REVEAL, PURPOSE_ISOLATION),
        subject_fit=(SUBJECT_TWO_SUBJECTS,),
        pace="slow", intensity=2, legacy_key="static",
        model_support=_STRONG_MODELS,
        avoid_when="only one subject exists, or both sit at the same depth",
    ),

    # ------------------------------------------------------------------
    # DRONE / CRANE
    # ------------------------------------------------------------------
    CameraMove(
        id="crane_up_reveal", name="Crane Up Reveal", category="drone_crane",
        motion_prompt="Camera cranes up and tilts down slightly, rising shot revealing the scale of the scene below",
        image_setup="compose from an elevated angle with the wider world extending beyond and behind the subject — the space above and beyond must contain real content",
        best_for=(PURPOSE_SCALE, PURPOSE_REVEAL, PURPOSE_PAYOFF),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER),
        pace="slow", intensity=3, legacy_key="tilt-up",
        avoid_when="the scene is an interior with a ceiling or the wider world isn't visible",
    ),
    CameraMove(
        id="crane_down_arrive", name="Crane Down Arrival", category="drone_crane",
        motion_prompt="Camera cranes down from high, descending shot settling toward the subject as the scene comes to eye level",
        image_setup="compose from a high vantage looking down with the subject small but distinct below, clear ground detail around it",
        best_for=(PURPOSE_ESTABLISH, PURPOSE_ISOLATION),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER),
        pace="slow", intensity=3, legacy_key="tilt-down",
        avoid_when="the shot is a closeup — nowhere to descend from",
    ),
    CameraMove(
        id="drone_flyover", name="Drone Flyover", category="drone_crane",
        motion_prompt="Aerial drone tracking shot flying forward over the landscape, terrain passing beneath the camera",
        image_setup="compose as a high aerial view with terrain stretching to a deep horizon, landmarks distributed from near to far",
        best_for=(PURPOSE_SCALE, PURPOSE_ESTABLISH),
        subject_fit=(SUBJECT_ENVIRONMENT,),
        pace="medium", intensity=3, legacy_key="lateral-pan",
        model_support=_STRONG_MODELS,
        avoid_when="the scene is an interior or a closeup — flyover needs open terrain",
    ),
    CameraMove(
        id="drone_orbit", name="Drone Orbit", category="drone_crane",
        motion_prompt="Aerial camera orbits around the subject in a wide circle, orbiting while keeping it centered",
        image_setup="compose the hero subject isolated with generous space on all sides, background varied enough that rotation shows new angles",
        best_for=(PURPOSE_SCALE, PURPOSE_ESTABLISH),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_OBJECT),
        pace="medium", intensity=3, legacy_key="orbital",
        model_support=_STRONG_MODELS,
        avoid_when="the subject sits against a wall or frame edge — nothing to orbit through",
    ),
    CameraMove(
        id="fpv_dive", name="FPV Dive", category="drone_crane",
        motion_prompt="FPV drone dive: camera plunges steeply downward toward the target, fast push with accelerating speed",
        image_setup="compose a high aerial view directly above a clear target below, strong vertical depth cues between camera and target",
        best_for=(PURPOSE_ISOLATION, PURPOSE_PAYOFF),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_OBJECT),
        pace="fast", intensity=5, legacy_key="snap-zoom",
        model_support=_STRONG_MODELS,
        avoid_when="the beat is calm — a dive is pure adrenaline",
    ),

    # ------------------------------------------------------------------
    # PAN / TILT
    # ------------------------------------------------------------------
    CameraMove(
        id="pan_left", name="Pan Left", category="pan_tilt",
        motion_prompt="Camera pans left from a fixed position, pan across the scene rotating horizontally",
        image_setup="compose with the reveal target placed left-of-center and secondary content on the right for the pan to leave behind",
        best_for=(PURPOSE_REVEAL,),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER, SUBJECT_DATA, SUBJECT_OBJECT, SUBJECT_TWO_SUBJECTS),
        pace="slow", intensity=1, legacy_key="lateral-pan",
        avoid_when="there is nothing new to find on the left side of the scene",
    ),
    CameraMove(
        id="pan_right", name="Pan Right", category="pan_tilt",
        motion_prompt="Camera pans right from a fixed position, pan across the scene rotating horizontally",
        image_setup="compose with the reveal target placed right-of-center and secondary content on the left for the pan to leave behind",
        best_for=(PURPOSE_REVEAL,),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER, SUBJECT_DATA, SUBJECT_OBJECT, SUBJECT_TWO_SUBJECTS),
        pace="slow", intensity=1, legacy_key="lateral-pan",
        avoid_when="there is nothing new to find on the right side of the scene",
    ),
    CameraMove(
        id="tilt_up_reveal", name="Tilt Up Reveal", category="pan_tilt",
        motion_prompt="Camera tilts up from a fixed position, tilting up to reveal what rises above",
        image_setup="compose with a strong vertical subject — its base in frame and its full height extending toward or past the top edge",
        best_for=(PURPOSE_SCALE, PURPOSE_REVEAL),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER, SUBJECT_OBJECT),
        pace="slow", intensity=2, legacy_key="tilt-up",
        avoid_when="nothing meaningful exists above the current framing",
    ),
    CameraMove(
        id="tilt_down_reveal", name="Tilt Down Reveal", category="pan_tilt",
        motion_prompt="Camera tilts down from a fixed position, tilting down to reveal what lies below",
        image_setup="compose with meaningful content at the bottom of frame and below — the ground level must carry the payoff detail",
        best_for=(PURPOSE_REVEAL, PURPOSE_ISOLATION),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_CHARACTER, SUBJECT_OBJECT),
        pace="slow", intensity=2, legacy_key="tilt-down",
        avoid_when="the lower frame holds no story information",
    ),
    CameraMove(
        id="whip_pan", name="Whip Pan", category="pan_tilt",
        motion_prompt="Whip pan: camera snaps rapidly sideways in a fast blurred pan across to the new subject",
        image_setup="compose two distinct focal subjects far apart horizontally with clean space between them for the blur to cross",
        best_for=(PURPOSE_REVEAL, PURPOSE_PAYOFF),
        subject_fit=(SUBJECT_TWO_SUBJECTS,),
        pace="fast", intensity=5, legacy_key="lateral-pan",
        model_support=_STRONG_MODELS,
        avoid_when="only one subject exists, or the tone is slow and contemplative",
    ),

    # ------------------------------------------------------------------
    # PHYSICAL MOVES
    # ------------------------------------------------------------------
    CameraMove(
        id="orbit_left", name="Orbit Left", category="physical",
        motion_prompt="Camera orbits left around the subject in a smooth arc, orbiting while keeping the subject centered",
        image_setup="compose the hero subject with clear separation from the background and open space around it on all sides",
        best_for=(PURPOSE_ISOLATION, PURPOSE_PAYOFF),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_OBJECT),
        pace="medium", intensity=3, legacy_key="orbital",
        avoid_when="the subject is flat against a wall — rotation exposes nothing new",
    ),
    CameraMove(
        id="orbit_right", name="Orbit Right", category="physical",
        motion_prompt="Camera orbits right around the subject in a smooth arc, orbiting while keeping the subject centered",
        image_setup="compose the hero subject with clear separation from the background and open space around it on all sides",
        best_for=(PURPOSE_ISOLATION, PURPOSE_PAYOFF),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_OBJECT),
        pace="medium", intensity=3, legacy_key="orbital",
        avoid_when="the subject is flat against a wall — rotation exposes nothing new",
    ),
    CameraMove(
        id="arc_in", name="Arc In", category="physical",
        motion_prompt="Camera arcs around the subject in a quarter circle while slowly moving closer, arc around combining orbit and approach",
        image_setup="compose the subject three-quarters turned with depth behind it, space open on the arcing side",
        best_for=(PURPOSE_ISOLATION, PURPOSE_REVEAL),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_OBJECT),
        pace="medium", intensity=3, legacy_key="orbital",
        model_support=_STRONG_MODELS,
        avoid_when="the frame is too tight for the camera to travel an arc",
    ),
    CameraMove(
        id="rise_up", name="Rise Up", category="physical",
        motion_prompt="Camera rises straight up from low, rising shot lifting past the subject as the view expands",
        image_setup="compose starting low with the ground plane in view and the subject rising above the lens height, world extending above",
        best_for=(PURPOSE_SCALE, PURPOSE_REVEAL),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_ENVIRONMENT),
        pace="medium", intensity=3, legacy_key="tilt-up",
        avoid_when="the scene has a low ceiling or empty upper frame",
    ),
    CameraMove(
        id="descend", name="Descend", category="physical",
        motion_prompt="Camera descends smoothly from above, descending shot lowering toward the subject's level",
        image_setup="compose from above eye level with the subject below and ground-level detail worth arriving at",
        best_for=(PURPOSE_ISOLATION, PURPOSE_ESTABLISH),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_ENVIRONMENT, SUBJECT_OBJECT),
        pace="medium", intensity=2, legacy_key="tilt-down",
        avoid_when="the shot is already at eye level",
    ),
    CameraMove(
        id="over_shoulder_push", name="Over-Shoulder Push", category="physical",
        motion_prompt="Camera pushes in past the foreground figure's shoulder, dolly in settling on what they are looking at",
        image_setup="compose over one character's shoulder — their head and shoulder soft in the near foreground, the point of interest sharp beyond",
        best_for=(PURPOSE_REVEAL, PURPOSE_ISOLATION),
        subject_fit=(SUBJECT_TWO_SUBJECTS, SUBJECT_CHARACTER),
        pace="slow", intensity=2, legacy_key="push-in",
        avoid_when="no foreground figure exists to shoot past",
    ),
    CameraMove(
        id="overhead_topdown", name="Overhead Top-Down Drift", category="physical",
        motion_prompt="Directly overhead top-down camera drifts slowly forward, pan across the layout below",
        image_setup="compose as a flat top-down bird's-eye view — the layout below arranged like a map with graphic clarity",
        best_for=(PURPOSE_SCALE, PURPOSE_ESTABLISH),
        subject_fit=(SUBJECT_ENVIRONMENT, SUBJECT_DATA, SUBJECT_OBJECT),
        pace="slow", intensity=2, legacy_key="lateral-pan",
        avoid_when="the scene's meaning depends on faces or horizon lines",
    ),

    # ------------------------------------------------------------------
    # HUMAN CAMERA
    # ------------------------------------------------------------------
    CameraMove(
        id="handheld_follow", name="Handheld Follow", category="human_camera",
        motion_prompt="Handheld camera follows the subject in a tracking shot with natural organic shake and breathing movement",
        image_setup="compose at human eye height close behind or beside the subject, slight imperfect framing, motion-ready stance",
        best_for=(PURPOSE_REVEAL,),
        subject_fit=(SUBJECT_CHARACTER,),
        pace="medium", intensity=4, legacy_key="lateral-pan",
        model_support=_STRONG_MODELS,
        avoid_when="the tone is composed and formal — handheld reads as urgency/danger",
    ),
    CameraMove(
        id="pov_walk", name="POV Walk", category="human_camera",
        motion_prompt="First-person POV camera walks forward, dolly in with a subtle natural sway as if through the character's eyes",
        image_setup="compose as a first-person view — no visible protagonist, path ahead open, environment wrapping the frame edges",
        best_for=(PURPOSE_REVEAL,),
        subject_fit=(SUBJECT_ENVIRONMENT,),
        pace="medium", intensity=3, legacy_key="push-in",
        model_support=_STRONG_MODELS,
        avoid_when="the hero character must stay visible in frame",
    ),

    # ------------------------------------------------------------------
    # SPECIALS
    # ------------------------------------------------------------------
    CameraMove(
        id="pass_through", name="Pass-Through", category="specials",
        motion_prompt="Camera moves forward, pushing in toward the foreground opening and passing through it into the space beyond",
        image_setup="compose with a clear foreground portal — a doorway, window, gap, or frame — with the destination space visible through it",
        best_for=(PURPOSE_REVEAL, PURPOSE_ESTABLISH),
        subject_fit=(SUBJECT_ENVIRONMENT,),
        pace="medium", intensity=4, legacy_key="push-in",
        model_support=_STRONG_MODELS,
        avoid_when="no natural portal exists in the scene",
    ),
    CameraMove(
        id="bullet_time", name="Bullet Time", category="specials",
        motion_prompt="Bullet time: action freezes mid-motion while the camera circles, orbiting around the frozen moment",
        image_setup="compose the subject mid-action at the peak instant — airborne, mid-swing, mid-impact — with 360-degree clearance around them",
        best_for=(PURPOSE_PAYOFF,),
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_OBJECT),
        pace="fast", intensity=5, legacy_key="orbital",
        model_support=_STRONG_MODELS,
        avoid_when="no peak action instant exists to freeze",
    ),
    CameraMove(
        id="hyperlapse", name="Hyperlapse", category="specials",
        motion_prompt="Hyperlapse: camera moves forward through the scene in accelerated time, dolly in as time streaks past",
        image_setup="compose a deep repeating path — a street, corridor, or route — with strong leading lines converging toward a destination",
        best_for=(PURPOSE_SCALE, PURPOSE_ESTABLISH),
        subject_fit=(SUBJECT_ENVIRONMENT,),
        pace="fast", intensity=4, legacy_key="push-in",
        model_support=_STRONG_MODELS,
        avoid_when="the moment is a single continuous beat where time-compression breaks continuity",
    ),
    CameraMove(
        id="static_locked", name="Static Locked-Off", category="specials",
        motion_prompt="Static shot, locked-off camera, no camera movement",
        image_setup="",  # a static frame imposes no special composition contract
        best_for=(),     # never scored; the selector returns None for static instead
        subject_fit=(SUBJECT_CHARACTER, SUBJECT_ENVIRONMENT, SUBJECT_DATA, SUBJECT_OBJECT, SUBJECT_TWO_SUBJECTS),
        pace="slow", intensity=1, legacy_key="static",
    ),
]}


# Purposes the base classifier can return, plus the two positional purposes
ALL_PURPOSES = (PURPOSE_REVEAL, PURPOSE_SCALE, PURPOSE_ISOLATION,
                PURPOSE_ESTABLISH, PURPOSE_PAYOFF)


def get_move(move_id: str) -> CameraMove | None:
    """Look up a catalog move by id. Returns None for unknown/blank ids."""
    if not move_id:
        return None
    return CAMERA_MOVES.get(move_id.strip())


def moves_for_purpose(purpose: str) -> list[CameraMove]:
    """All non-static moves that serve the given purpose."""
    return [m for m in CAMERA_MOVES.values() if purpose in m.best_for]


def moves_supported_by(model: str) -> list[CameraMove]:
    """All moves the given animation model executes reliably."""
    return [m for m in CAMERA_MOVES.values() if model in m.model_support]
