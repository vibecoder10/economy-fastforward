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
#
# three_quarter geometry relaxed for large vehicles (2026-08-03, same-day
# follow-up): live output on HMS Argus (video d2e37cd6, scene 1) showed
# side_profile and top_planform pass role-conformance QA on the first try,
# but three_quarter was generated twice and REJECTED twice ($0.10 burned,
# parked qa_rejected) — a 170m warship shot "at natural eye-level height"
# while also showing both the bow/front AND a full side is near-geometrically
# contradictory (eye-level foreshortens everything for a subject that long),
# and the model — anchored to a side-on reference photo — kept splitting the
# difference between the two demands instead of committing to either. Fixed
# direction asks for the classic bow-quarter press/aerial photo instead: a
# SLIGHTLY elevated vantage (not eye-level, not steep), which is exactly how
# real-world three-quarter identification shots of large aircraft, ships, and
# vehicles are actually taken. Bow/front and one side both stay clearly
# visible and overall shape/length must read cleanly — identity accuracy is
# untouched, only the eye-level constraint is dropped.
#
# bow-vs-stern made non-decisive (2026-08-03, second same-day follow-up):
# with the elevation fix above in place, three_quarter started generating
# clean, correctly-elevated quarter views via anchor chaining — but the
# role judge kept rejecting them anyway over WHICH END faces the camera.
# Video d2e37cd6 scene 1 was rejected twice more with the judge reason
# "stern-quarter, not bow-quarter" while the preserved rejected frame
# itself was a textbook identification quarter view: one end + one full
# side, slightly elevated, shape and length both readable. The actual
# requirement was never bow-specific — a stern-quarter shot satisfies the
# same identification purpose as a bow-quarter shot. Fixed direction keeps
# bow-quarter as the PREFERRED framing (still named first, still steering
# the model toward it) but stops treating bow-vs-stern as decisive: either
# end of the machine, paired with one full side, at a slightly elevated
# vantage, satisfies the role.
STATIC_VIEW_PLANS = (
    {
        "role": "three_quarter",
        "label": "Three-quarter identification",
        "shot_type": "wide",
        "composition": "wide",
        "direction": (
            "CAMERA: a front three-quarter view from a slightly elevated "
            "vantage point — ideally the classic bow-quarter press or "
            "aerial identification photo, though a stern-quarter angle "
            "from the same elevation is equally acceptable — not "
            "eye-level and not a steep overhead angle. Positioned so BOTH "
            "one end of the machine (bow or stern) and one full side are "
            "visible together in the same frame, with the overall shape "
            "and length clearly readable. This is the standard "
            "identification angle — not a flat side-on profile and not a "
            "top-down angle."
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

# Never-built machines use the same three-angle documentary contract as
# built machines. Their first generation is grounded in a verified design
# drawing and later views chain from the first approved reconstruction.
NEVER_BUILT_VIEW_ROLES = ("three_quarter", "side_profile", "top_planform")
NEVER_BUILT_VIEW_PLANS = tuple(
    plan for plan in STATIC_VIEW_PLANS if plan["role"] in NEVER_BUILT_VIEW_ROLES
)
