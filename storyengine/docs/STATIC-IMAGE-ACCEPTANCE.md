# Static documentary image acceptance

Ryan approved this rule on 2026-09-14 after reviewing the Barling image generated directly in chat.

Accept slight camera-angle deviations when the image clearly serves its intended documentary view. Do not reject or regenerate an otherwise usable image solely because the camera is not an exact engineering projection.

- Side view: full length and side silhouette readable; slight three-quarter perspective, visible nose/engine fronts, and some upper surfaces are acceptable.
- Three-quarter identification: an end and substantial side visible, overall shape readable; modest elevation/rotation differences are acceptable.
- Overhead: upper surfaces and planform dominate; a slightly oblique overhead angle is acceptable.

Reject a materially wrong view that obscures what the role needs to show. Aircraft identity, major structural accuracy, and genuinely complementary coverage remain separate requirements. This rule does not approve missing wings, invented components, or duplicate crops as distinct views.

Approved visual example for camera tolerance: [Barling chat sample](../tasks/dvsu-simple-aircraft-review/ryan-approved-camera-example.png). Ryan accepted its slight angle and studio presentation; this is not evidence of a complete historical audit or permission to replace a saved production asset.

Implementation: `backend/static_docu.py` `_ROLE_GEOMETRY_REQUIREMENTS` and `_view_role_confirms`. Keep generation prompts short; desired angles are targets, and acceptance uses the tolerance above. Existing saved approvals remain valid. Previously rejected images are not automatically promoted.

## Automatic structural review

Judge recognizable identity and clearly visible major structures. Different angles hide or overlap wings, far-side engines, propellers and tail surfaces. Not visible is not evidence of missing. An exhaustive component count or small-detail certainty is not required for a usable documentary depiction. Reject only a clear visible identity or major structural contradiction that perspective/occlusion cannot explain, or blank output. Both the primary reviewer and independent arbiter use this rule. Do not send otherwise usable images for human approval merely because the reviewer cannot verify every component.
