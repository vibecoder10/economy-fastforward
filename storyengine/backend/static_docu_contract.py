"""Shared constants for the static-documentary multi-view format.

Kept dependency-free so generation, cost quoting, and tests all use the same
numbers without importing the large pipeline modules into one another.
"""

STATIC_VIEWS_TARGET = 3
STATIC_VIEWS_MINIMUM = 2

STATIC_VIEW_PLANS = (
    {
        "role": "three_quarter",
        "label": "Three-quarter identification",
        "shot_type": "wide",
        "composition": "wide",
        "direction": (
            "Show the complete machine in a front three-quarter view at a natural "
            "eye-level camera height. The nose/front and one full side must both be "
            "visible so the audience can read its overall shape. Never use a pure "
            "side-on profile."
        ),
    },
    {
        "role": "top_oblique",
        "label": "Elevated top-oblique",
        "shot_type": "overhead",
        "composition": "overhead",
        "direction": (
            "Show the complete machine from an elevated three-quarter top-oblique "
            "view, revealing its planform and upper surfaces. Use the opposite visual "
            "bias from the identification view. Never use a pure side-on profile."
        ),
    },
    {
        "role": "engineering_detail",
        "label": "Engineering detail",
        "shot_type": "closeup",
        "composition": "medium",
        "direction": (
            "Use a closer three-quarter engineering-detail view of the verified "
            "feature named below. Keep enough of the machine visible for immediate "
            "identification and do not invent, redesign, or exaggerate the feature."
        ),
    },
)
