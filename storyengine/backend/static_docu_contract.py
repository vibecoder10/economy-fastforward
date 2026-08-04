"""Shared constants for the static-documentary multi-view format.

Kept dependency-free so generation, cost quoting, and tests all use the same
numbers without importing the large pipeline modules into one another.
"""

STATIC_VIEWS_TARGET = 3
STATIC_VIEWS_MINIMUM = 2

# Ryan's fix (2026-08-03): live output on HMS Argus (video d2e37cd6) showed
# THREE near-identical left-side three-quarter compositions at slightly
# different heights instead of genuinely rotated views. Root cause: every
# `direction` below asked for a three-quarter view (two of them explicitly
# forbade a side-on profile), and `static_docu.py`'s `_studio_prompt` led
# with "THE EXACT SAME machine as in the verified reference photo" —
# viewpoint fidelity, not just identity fidelity — so the single reference
# photo's own angle dominated weak view language. Fixed contract: three
# genuinely different camera geometries ("qtr angle, side view, top view"),
# each written as an explicit imperative camera instruction strong enough to
# override the reference photo's own angle (see `_studio_prompt` in
# static_docu.py, which now leads with this `direction` text and phrases
# reference fidelity as identity-only). Role-conformance vision QA
# (`_view_role_confirms` in static_docu.py) then checks the GENERATED image
# actually delivers each role's geometry, not just the right machine.
#
# The old `engineering_detail` role (a closer three-quarter feature shot) is
# DROPPED for now — three roles, three real angles. `detail_focus` keeps
# flowing from subject planning (`_scene_subjects`) unused by the current
# plans; a future 4th view could reintroduce a detail/close-up role and pick
# it back up.
STATIC_VIEW_PLANS = (
    {
        "role": "three_quarter",
        "label": "Three-quarter identification",
        "shot_type": "wide",
        "composition": "wide",
        "direction": (
            "CAMERA: a front three-quarter angle at natural eye-level height, "
            "positioned so BOTH the nose/front and one full side of the "
            "machine are visible together in the same frame. This is the "
            "standard identification angle — not a flat side-on profile and "
            "not a top-down angle."
        ),
    },
    {
        "role": "side_profile",
        "label": "Full side profile",
        "shot_type": "wide",
        "composition": "wide",
        "direction": (
            "CAMERA: a TRUE side-on profile shot — positioned directly to "
            "the side of the machine, at a 90-degree angle from its "
            "longitudinal axis, at the machine's own mid-height. The "
            "complete silhouette must read as a flat side elevation, like a "
            "museum recognition-chart profile rendered as a photograph: "
            "almost no front-on or top-down surface visible, the full "
            "length framed edge to edge with museum-catalogue accuracy. "
            "This view IS meant to be a pure side-on profile."
        ),
    },
    {
        "role": "top_planform",
        "label": "High top-down planform",
        "shot_type": "overhead",
        "composition": "overhead",
        "direction": (
            "CAMERA: positioned high above the machine, looking steeply "
            "down at roughly 70-85 degrees from horizontal (near-vertical, "
            "bird's-eye), so the upper surfaces dominate the frame — "
            "wings/rotor disc and fuselage outline for an aircraft, the "
            "deck and hull outline for a ship, the top deck and turret for "
            "a vehicle. Sides and undercarriage should barely register. "
            "This is a genuine HIGH top-down planform view, not a modestly "
            "elevated three-quarter angle."
        ),
    },
)
