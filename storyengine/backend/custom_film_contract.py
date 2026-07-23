"""Validated, deterministic Custom Film contracts and persistence helpers.

This module is deliberately planner- and runtime-agnostic.  It accepts only
values already present in the four public production profiles, derives an
explicit compatibility matrix from those snapshots, and persists immutable
plan revisions.  Free-form planner prose never becomes a reusable recipe.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Mapping
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import execute, fetch_all, fetch_one, get_pool
from production_styles import (
    PUBLIC_PRODUCTION_STYLE_IDS,
    REQUIRED_KNOB_KEYS,
    list_public_profiles,
    normalize_profile_row,
)


CONTRACT_SCHEMA_VERSION = 1
COMPATIBILITY_RULESET = "public-profile-semantic-v1"
WEIGHT_UNITS = 1_000_000
RECIPE_ROLES = frozenset(
    {
        "full_film",
        "opening",
        "context",
        "explanation",
        "evidence",
        "contrast",
        "case_study",
        "resolution",
        "closing",
    }
)


class CustomFilmContractError(ValueError):
    """Base fail-closed contract error."""


class DuplicateRecipeError(CustomFilmContractError):
    """Raised when a recipe copies a public or active tenant recipe."""

    def __init__(self, duplicate_kind: str, duplicate_id: str):
        super().__init__(f"Recipe duplicates {duplicate_kind} {duplicate_id}")
        self.duplicate_kind = duplicate_kind
        self.duplicate_id = duplicate_id


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return the one canonical JSON encoding used by all Custom Film hashes."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=_json_default,
        )
    except (TypeError, ValueError) as exc:
        raise CustomFilmContractError(f"Contract is not canonical JSON: {exc}") from exc


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _json_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CustomFilmContractError(f"{field_name} must be a JSON object")
    canonical_json(value)
    return copy.deepcopy(value)


@dataclass(frozen=True)
class CapabilityManifest:
    """Allowlist and compatibility matrix derived from the public snapshots."""

    version: str
    profiles: Mapping[str, Mapping[str, Any]]
    allowed_values: Mapping[str, Mapping[str, tuple[str, ...]]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ruleset": COMPATIBILITY_RULESET,
            "version": self.version,
            "public_profile_ids": sorted(self.profiles),
            "dimensions": {
                key: [
                    {
                        "value": json.loads(encoded),
                        "profile_ids": list(profile_ids),
                    }
                    for encoded, profile_ids in sorted(values.items())
                ]
                for key, values in sorted(self.allowed_values.items())
            },
            "compatibility_domains": {
                "static_docu": (
                    "ken_burns + per_item + item + narrator + no dubbing + "
                    "three_complementary_views"
                ),
                "coverage_dialogue": (
                    "grok_native + dialogue_shape + speaker_turn + "
                    "dialogue_coverage + matched language/dubbing"
                ),
                "coverage_visual_cue": (
                    "grok_native + visual_cue + investigative_coverage + "
                    "narrator or simple_single_language + no dubbing"
                ),
                "independent_dimensions": ["script_profile", "visual_profile"],
            },
        }


def build_capability_manifest(profiles: list[dict[str, Any]]) -> CapabilityManifest:
    """Build an explicit allowlist/matrix from exactly the four public rows."""
    normalized: dict[str, dict[str, Any]] = {}
    for raw in profiles:
        profile = normalize_profile_row(raw)
        if profile is None:
            raise CustomFilmContractError("Malformed public production profile")
        style_id = profile["id"]
        if style_id in normalized:
            raise CustomFilmContractError(f"Duplicate public profile: {style_id}")
        if not profile["requires_byok"]:
            raise CustomFilmContractError(
                f"Custom Film profile {style_id} must require BYOK"
            )
        knob_keys = set(profile["knobs"])
        if knob_keys != set(REQUIRED_KNOB_KEYS):
            unknown = sorted(knob_keys - set(REQUIRED_KNOB_KEYS))
            missing = sorted(set(REQUIRED_KNOB_KEYS) - knob_keys)
            raise CustomFilmContractError(
                f"Profile {style_id} knob keys mismatch; unknown={unknown}, missing={missing}"
            )
        canonical_json(profile["knobs"])
        normalized[style_id] = profile

    if set(normalized) != set(PUBLIC_PRODUCTION_STYLE_IDS):
        raise CustomFilmContractError(
            "Capability manifest requires exactly the four public production profiles"
        )

    dimensions = sorted(REQUIRED_KNOB_KEYS)
    allowed: dict[str, dict[str, tuple[str, ...]]] = {}
    for dimension in dimensions:
        provenance: dict[str, list[str]] = {}
        for style_id, profile in normalized.items():
            encoded = canonical_json(profile["knobs"][dimension])
            provenance.setdefault(encoded, []).append(style_id)
        allowed[dimension] = {
            encoded: tuple(sorted(style_ids))
            for encoded, style_ids in provenance.items()
        }

    manifest_source = {
        "ruleset": COMPATIBILITY_RULESET,
        "profiles": {
            style_id: {
                "version": profile["version"],
                "knobs": profile["knobs"],
            }
            for style_id, profile in sorted(normalized.items())
        },
    }
    version = f"{COMPATIBILITY_RULESET}:{canonical_hash(manifest_source)[:16]}"
    return CapabilityManifest(
        version=version,
        profiles=copy.deepcopy(normalized),
        allowed_values=allowed,
    )


async def load_capability_manifest() -> CapabilityManifest:
    return build_capability_manifest(await list_public_profiles())


def normalize_section_knobs(
    raw_knobs: Any,
    manifest: CapabilityManifest,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Validate one section and derive per-dimension public provenance."""
    knobs = _json_object(raw_knobs, "knobs")
    keys = set(knobs)
    required = set(REQUIRED_KNOB_KEYS)
    if keys != required:
        raise CustomFilmContractError(
            f"Section knob keys mismatch; unknown={sorted(keys - required)}, "
            f"missing={sorted(required - keys)}"
        )

    encoded: dict[str, str] = {}
    provenance: dict[str, list[str]] = {}
    for dimension in sorted(required):
        encoded[dimension] = canonical_json(knobs[dimension])
        profile_ids = manifest.allowed_values[dimension].get(encoded[dimension])
        if profile_ids is None:
            raise CustomFilmContractError(
                f"Unsupported {dimension} value: {knobs[dimension]!r}"
            )
        provenance[dimension] = list(profile_ids)

    _validate_semantic_compatibility(knobs, manifest)
    return knobs, provenance


def _profile_value(
    manifest: CapabilityManifest,
    style_id: str,
    dimension: str,
) -> Any:
    return manifest.profiles[style_id]["knobs"][dimension]


def _matches(value: Any, expected: Any) -> bool:
    return canonical_json(value) == canonical_json(expected)


def _validate_semantic_compatibility(
    knobs: Mapping[str, Any],
    manifest: CapabilityManifest,
) -> None:
    """Apply the explicit safe domains over the public allowlisted values.

    Script and visual profiles are intentionally independent because the
    existing runtime already resolves those seams separately. Structural,
    performance, and static-documentary dimensions remain cohesive.
    """
    render_mode = knobs["render_mode"]
    density = knobs["image_density"]
    animation = knobs["animation"]
    language = knobs["language"]
    dubbing = knobs["dubbing"]
    segmentation = knobs["segmentation"]
    camera = knobs["camera"]
    quality_laws = knobs["quality_laws"]

    photo = manifest.profiles["photo_documentary"]["knobs"]
    bilingual = manifest.profiles["bilingual_character_animation"]["knobs"]
    simple = manifest.profiles["simple_language_animation"]["knobs"]
    investigative = manifest.profiles["animated_investigative_documentary"]["knobs"]

    if _matches(render_mode, photo["render_mode"]):
        required = {
            "image_density": photo["image_density"],
            "animation": photo["animation"],
            "language": photo["language"],
            "dubbing": photo["dubbing"],
            "segmentation": photo["segmentation"],
            "camera": photo["camera"],
            "quality_laws": photo["quality_laws"],
        }
        if any(not _matches(knobs[key], value) for key, value in required.items()):
            raise CustomFilmContractError(
                "Incompatible static_docu section; static documentary structure "
                "must retain its still-image, item, narrator, camera, and quality laws"
            )
        return

    if not _matches(render_mode, investigative["render_mode"]):
        raise CustomFilmContractError("Incompatible production render mode")
    if not _matches(animation, investigative["animation"]):
        raise CustomFilmContractError(
            "Incompatible coverage section; coverage requires supported animation"
        )

    if _matches(density, bilingual["image_density"]):
        if not (
            _matches(segmentation, bilingual["segmentation"])
            and _matches(camera, bilingual["camera"])
        ):
            raise CustomFilmContractError(
                "Incompatible dialogue coverage structure"
            )
        if _matches(language, bilingual["language"]):
            expected_dubbing = bilingual["dubbing"]
            expected_quality = bilingual["quality_laws"]
        elif _matches(language, simple["language"]):
            expected_dubbing = simple["dubbing"]
            expected_quality = simple["quality_laws"]
        else:
            raise CustomFilmContractError(
                "Incompatible dialogue coverage language"
            )
        if not (
            _matches(dubbing, expected_dubbing)
            and _matches(quality_laws, expected_quality)
        ):
            raise CustomFilmContractError(
                "Incompatible dialogue performance, dubbing, or quality laws"
            )
        return

    if _matches(density, investigative["image_density"]):
        if not (
            _matches(segmentation, investigative["segmentation"])
            and _matches(camera, investigative["camera"])
            and _matches(dubbing, investigative["dubbing"])
            and _matches(quality_laws, investigative["quality_laws"])
            and (
                _matches(language, investigative["language"])
                or _matches(language, simple["language"])
            )
        ):
            raise CustomFilmContractError(
                "Incompatible visual-cue coverage structure or performance"
            )
        return

    raise CustomFilmContractError("Incompatible coverage image density")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProposedSection(_StrictModel):
    section_id: UUID
    role: str
    purpose: str = Field(min_length=1, max_length=500)
    duration_weight: Decimal = Field(gt=0)
    knobs: dict[str, Any]
    estimated_media: "EstimatedMedia" = Field(default_factory=lambda: EstimatedMedia())

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in RECIPE_ROLES:
            raise ValueError(f"Unknown section role: {value}")
        return value



class EstimatedMedia(_StrictModel):
    """No-cost structural counts only; provider pricing belongs to M2-3."""

    still_images: int = Field(default=0, ge=0, le=100_000)
    animation_clips: int = Field(default=0, ge=0, le=100_000)
    voice_tracks: int = Field(default=0, ge=0, le=100_000)
    duration_seconds: Decimal = Field(default=Decimal(0), ge=0)


class ProposedPlan(_StrictModel):
    compatibility_version: str
    sections: list[ProposedSection] = Field(min_length=1, max_length=100)


class RecipeSectionDraft(_StrictModel):
    role: str
    duration_weight: Decimal = Field(gt=0)
    knobs: dict[str, Any]

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in RECIPE_ROLES:
            raise ValueError(f"Unknown recipe role: {value}")
        return value


class RecipeDraft(_StrictModel):
    compatibility_version: str
    sections: list[RecipeSectionDraft] = Field(min_length=1, max_length=100)


def _normalized_weight_units(weights: list[Decimal]) -> list[int]:
    total = sum(weights, Decimal(0))
    if total <= 0:
        raise CustomFilmContractError("Section weights must total more than zero")
    if len(weights) > WEIGHT_UNITS:
        raise CustomFilmContractError("Too many sections to allocate positive duration")
    exact = [(weight / total) * WEIGHT_UNITS for weight in weights]
    units = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
    remainder = WEIGHT_UNITS - sum(units)
    ranked = sorted(
        range(len(exact)),
        key=lambda index: (-(exact[index] - units[index]), index),
    )
    for index in ranked[:remainder]:
        units[index] += 1
    # Positive Decimals can underflow the million-unit representation. Move
    # one unit from the largest section to each underflowed section so the
    # normalized result remains valid for the DB's duration_units > 0 law.
    for zero_index in (index for index, value in enumerate(units) if value == 0):
        donor = min(
            (index for index, value in enumerate(units) if value > 1),
            key=lambda index: (-units[index], index),
        )
        units[zero_index] = 1
        units[donor] -= 1
    return units


def normalize_plan(raw: Any, manifest: CapabilityManifest) -> dict[str, Any]:
    try:
        draft = ProposedPlan.model_validate(raw)
    except Exception as exc:
        raise CustomFilmContractError(f"Invalid Custom Film plan: {exc}") from exc
    if draft.compatibility_version != manifest.version:
        raise CustomFilmContractError("Plan compatibility manifest is stale")
    section_ids = [str(section.section_id) for section in draft.sections]
    if len(section_ids) != len(set(section_ids)):
        raise CustomFilmContractError("Section IDs must be unique")
    units = _normalized_weight_units(
        [section.duration_weight for section in draft.sections]
    )
    sections = []
    for order_index, (section, duration_units) in enumerate(zip(draft.sections, units)):
        knobs, provenance = normalize_section_knobs(section.knobs, manifest)
        sections.append(
            {
                "section_id": str(section.section_id),
                "order_index": order_index,
                "role": section.role,
                "purpose": section.purpose,
                "duration_units": duration_units,
                "knobs": knobs,
                "provenance": provenance,
                "estimated_media": section.estimated_media.model_dump(mode="json"),
            }
        )
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "compatibility_version": manifest.version,
        "sections": sections,
    }


def normalize_recipe(raw: Any, manifest: CapabilityManifest) -> dict[str, Any]:
    """Return a topic-free recipe; unexpected prose/content fields fail closed."""
    try:
        draft = RecipeDraft.model_validate(raw)
    except Exception as exc:
        raise CustomFilmContractError(f"Invalid reusable recipe: {exc}") from exc
    if draft.compatibility_version != manifest.version:
        raise CustomFilmContractError("Recipe compatibility manifest is stale")
    units = _normalized_weight_units(
        [section.duration_weight for section in draft.sections]
    )
    sections = []
    for order_index, (section, duration_units) in enumerate(zip(draft.sections, units)):
        knobs, provenance = normalize_section_knobs(section.knobs, manifest)
        sections.append(
            {
                "order_index": order_index,
                "role": section.role,
                "duration_units": duration_units,
                "knobs": knobs,
                "provenance": provenance,
            }
        )
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "compatibility_version": manifest.version,
        "sections": sections,
    }


def plan_hash(normalized_plan: Mapping[str, Any]) -> str:
    return canonical_hash(normalized_plan)


def revision_input_from_normalized_plan(
    normalized_plan: Mapping[str, Any],
    manifest: CapabilityManifest,
) -> dict[str, Any]:
    """Convert a compiler-normalized plan to revision input without hash drift."""
    raw = {
        "compatibility_version": normalized_plan["compatibility_version"],
        "sections": [
            {
                "section_id": section["section_id"],
                "role": section["role"],
                "purpose": section["purpose"],
                "duration_weight": section["duration_units"],
                "knobs": section["knobs"],
                "estimated_media": section["estimated_media"],
            }
            for section in normalized_plan["sections"]
        ],
    }
    round_tripped = normalize_plan(raw, manifest)
    if canonical_json(round_tripped) != canonical_json(dict(normalized_plan)):
        raise CustomFilmContractError(
            "Compiled Custom Film plan changed while preparing persistence"
        )
    return raw


def recipe_signature(normalized_recipe: Mapping[str, Any]) -> str:
    """Hash only role, proportions, knobs, and compatibility version."""
    return canonical_hash(
        {
            "compatibility_version": normalized_recipe["compatibility_version"],
            "sections": [
                {
                    "role": section["role"],
                    "duration_units": section["duration_units"],
                    "knobs": section["knobs"],
                }
                for section in normalized_recipe["sections"]
            ],
        }
    )


def approval_binding_hash(plan_digest: str, quote_inputs: Mapping[str, Any]) -> str:
    return canonical_hash(
        {
            "plan_hash": plan_digest,
            "quote_inputs": _json_object(dict(quote_inputs), "quote_inputs"),
        }
    )


def public_recipe_signatures(
    manifest: CapabilityManifest,
) -> dict[str, str]:
    signatures: dict[str, str] = {}
    for style_id, profile in manifest.profiles.items():
        recipe = normalize_recipe(
            {
                "compatibility_version": manifest.version,
                "sections": [
                    {
                        "role": "full_film",
                        "duration_weight": 1,
                        "knobs": profile["knobs"],
                    }
                ],
            },
            manifest,
        )
        signatures[recipe_signature(recipe)] = style_id
    return signatures


async def find_recipe_duplicate(
    tenant_id: str,
    normalized_recipe: Mapping[str, Any],
    manifest: CapabilityManifest,
) -> tuple[str, str] | None:
    signature = recipe_signature(normalized_recipe)
    # Any recipe whose every section is 100% the same public profile is a public
    # clone, even when planner prose splits it into cosmetic opening/context/
    # closing sections. Section labels and counts cannot manufacture novelty.
    sections = normalized_recipe["sections"]
    for style_id, profile in manifest.profiles.items():
        profile_knobs = canonical_json(profile["knobs"])
        if sections and all(
            canonical_json(section["knobs"]) == profile_knobs
            for section in sections
        ):
            return ("public_profile", style_id)
    public_match = public_recipe_signatures(manifest).get(signature)
    if public_match:
        return ("public_profile", public_match)
    row = await fetch_one(
        """SELECT id
           FROM custom_film_recipes
           WHERE tenant_id = $1 AND signature = $2 AND archived_at IS NULL
           ORDER BY created_at DESC
           LIMIT 1""",
        tenant_id,
        signature,
    )
    return ("saved_recipe", str(row["id"])) if row else None


async def create_recipe_version(
    tenant_id: str,
    name: str,
    raw_recipe: Any,
    manifest: CapabilityManifest,
    *,
    recipe_family_id: str | None = None,
) -> dict[str, Any]:
    """Persist one immutable tenant recipe version after duplicate checks."""
    normalized = normalize_recipe(raw_recipe, manifest)
    signature = recipe_signature(normalized)
    duplicate = await find_recipe_duplicate(tenant_id, normalized, manifest)
    if duplicate:
        raise DuplicateRecipeError(*duplicate)
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 120:
        raise CustomFilmContractError("Recipe name must be 1-120 characters")
    family_id = recipe_family_id or str(uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Serialize version allocation per tenant/family without requiring
            # a mutable counter row. The unique constraint remains the backstop.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"custom-film-recipe:{tenant_id}:{family_id}",
            )
            row = await conn.fetchrow(
                """INSERT INTO custom_film_recipes
                     (tenant_id, recipe_family_id, version, name,
                      compatibility_version, recipe, signature)
                   SELECT $1, $2::uuid,
                          COALESCE(MAX(version), 0) + 1,
                          $3, $4, $5::jsonb, $6
                   FROM custom_film_recipes
                   WHERE tenant_id = $1 AND recipe_family_id = $2::uuid
                   RETURNING id, tenant_id, recipe_family_id, version, name,
                             compatibility_version, recipe, signature,
                             archived_at::text, created_at::text, updated_at::text""",
                tenant_id,
                family_id,
                normalized_name,
                manifest.version,
                canonical_json(normalized),
                signature,
            )
    if not row:
        raise RuntimeError("Recipe insert returned no row")
    return _serialize_recipe_row(row)


def _serialize_recipe_row(row: Mapping[str, Any]) -> dict[str, Any]:
    recipe = row.get("recipe")
    if isinstance(recipe, str):
        recipe = json.loads(recipe)
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "recipe_family_id": str(row["recipe_family_id"]),
        "version": int(row["version"]),
        "name": str(row["name"]),
        "compatibility_version": str(row["compatibility_version"]),
        "recipe": copy.deepcopy(recipe),
        "signature": str(row["signature"]),
        "archived_at": row.get("archived_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


async def list_recipe_versions(
    tenant_id: str,
    recipe_family_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        """SELECT id, tenant_id, recipe_family_id, version, name,
                  compatibility_version, recipe, signature,
                  archived_at::text, created_at::text, updated_at::text
           FROM custom_film_recipes
           WHERE tenant_id = $1
             AND ($2::uuid IS NULL OR recipe_family_id = $2::uuid)
           ORDER BY recipe_family_id, version DESC""",
        tenant_id,
        recipe_family_id,
    )
    return [_serialize_recipe_row(row) for row in rows]


async def create_plan_revision(
    tenant_id: str,
    video_id: str,
    raw_plan: Any,
    manifest: CapabilityManifest,
    *,
    quote_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically persist an immutable plan revision and its section rows."""
    normalized = normalize_plan(raw_plan, manifest)
    digest = plan_hash(normalized)
    quote = _json_object(dict(quote_inputs or {}), "quote_inputs")
    quote_digest = canonical_hash(quote)
    plan_id = str(uuid4())

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            video = await conn.fetchrow(
                """SELECT id FROM videos
                   WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
                   FOR UPDATE""",
                tenant_id,
                video_id,
            )
            if not video:
                raise CustomFilmContractError("Video not found for tenant")
            revision = await conn.fetchval(
                """SELECT COALESCE(MAX(revision), 0) + 1
                   FROM custom_film_plans
                   WHERE tenant_id = $1 AND video_id = $2""",
                tenant_id,
                video_id,
            )
            await conn.execute(
                """INSERT INTO custom_film_plans
                     (id, tenant_id, video_id, revision, compatibility_version,
                      plan, plan_hash, quote_inputs, quote_inputs_hash)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8::jsonb, $9)""",
                plan_id,
                tenant_id,
                video_id,
                revision,
                manifest.version,
                canonical_json(normalized),
                digest,
                canonical_json(quote),
                quote_digest,
            )
            for section in normalized["sections"]:
                await conn.execute(
                    """INSERT INTO custom_film_sections
                         (tenant_id, plan_id, video_id, section_id, order_index, role,
                          purpose, duration_units, knobs, provenance, estimated_media)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                               $9::jsonb, $10::jsonb, $11::jsonb)""",
                    tenant_id,
                    plan_id,
                    video_id,
                    section["section_id"],
                    section["order_index"],
                    section["role"],
                    section["purpose"],
                    section["duration_units"],
                    canonical_json(section["knobs"]),
                    canonical_json(section["provenance"]),
                    canonical_json(section["estimated_media"]),
                )
            await conn.execute(
                """UPDATE videos
                   SET custom_film_plan_id = $3,
                       custom_film_plan_revision = $4,
                       custom_film_plan_hash = $5,
                       custom_film_quote_inputs_hash = $6,
                       custom_film_approval_hash = NULL,
                       custom_film_approved_at = NULL,
                       updated_at = now()
                   WHERE tenant_id = $1 AND id = $2""",
                tenant_id,
                video_id,
                plan_id,
                revision,
                digest,
                quote_digest,
            )
    return await load_current_plan(tenant_id, video_id)  # type: ignore[return-value]


async def approve_current_plan(
    tenant_id: str,
    video_id: str,
    expected_approval_hash: str,
) -> dict[str, Any]:
    """Bind one explicit approval to the exact locked plan and quote inputs.

    The video and plan rows are locked together.  Replays, stale quotes, and
    already-approved revisions fail closed without changing either pointer.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """SELECT v.custom_film_plan_id, v.custom_film_plan_hash,
                          v.custom_film_quote_inputs_hash,
                          v.custom_film_approval_hash,
                          p.plan_hash, p.quote_inputs, p.quote_inputs_hash,
                          p.approval_hash
                   FROM videos v
                   JOIN custom_film_plans p
                     ON p.id = v.custom_film_plan_id
                    AND p.tenant_id = v.tenant_id
                    AND p.video_id = v.id
                   WHERE v.tenant_id = $1 AND v.id = $2
                     AND v.deleted_at IS NULL
                   FOR UPDATE OF v, p""",
                tenant_id,
                video_id,
            )
            if not row:
                raise CustomFilmContractError("Current Custom Film plan not found")
            quote_inputs = _parse_json(row["quote_inputs"])
            current = approval_binding_hash(str(row["plan_hash"]), quote_inputs)
            pointers_match = (
                str(row["custom_film_plan_hash"]) == str(row["plan_hash"])
                and str(row["custom_film_quote_inputs_hash"])
                == str(row["quote_inputs_hash"])
            )
            if not pointers_match or current != str(expected_approval_hash):
                raise CustomFilmContractError(
                    "This Custom Film estimate changed. Review the current plan and approve again."
                )
            if row.get("approval_hash") or row.get("custom_film_approval_hash"):
                raise CustomFilmContractError(
                    "This Custom Film approval was already used or recorded."
                )
            await conn.execute(
                """UPDATE custom_film_plans
                   SET approval_hash = $3, approved_at = now()
                   WHERE tenant_id = $1 AND id = $2""",
                tenant_id,
                str(row["custom_film_plan_id"]),
                current,
            )
            await conn.execute(
                """UPDATE videos
                   SET custom_film_approval_hash = $3,
                       custom_film_approved_at = now(),
                       updated_at = now()
                   WHERE tenant_id = $1 AND id = $2""",
                tenant_id,
                video_id,
                current,
            )
    return await load_current_plan(tenant_id, video_id)  # type: ignore[return-value]


async def consume_current_plan_approval(
    tenant_id: str,
    video_id: str,
    expected_approval_hash: str,
) -> bool:
    """Atomically consume approval immediately before exactly-once scheduling."""
    result = await execute(
        """UPDATE videos
           SET custom_film_approval_hash = NULL,
               custom_film_approved_at = NULL,
               updated_at = now()
           WHERE tenant_id = $1 AND id = $2
             AND custom_film_approval_hash = $3
             AND custom_film_plan_id IS NOT NULL""",
        tenant_id,
        video_id,
        expected_approval_hash,
    )
    # asyncpg returns e.g. "UPDATE 1"; fakes commonly return bool/int.
    if isinstance(result, str):
        return result.rsplit(" ", 1)[-1] == "1"
    return bool(result)


async def reserve_approved_start_intent(
    tenant_id: str,
    conversation_id: str,
    expected_approval_hash: str,
    manifest: CapabilityManifest,
) -> dict[str, Any]:
    """Atomically reserve one no-provider Custom Film start intention.

    The locked conversation state is authoritative, not the caller's snapshot.
    The transaction creates only a minimal ``custom_film_ready`` video row plus
    its immutable approved contract and CAS-updates the conversation. It does
    not increment usage, create a project, touch Drive, or schedule runtime.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            conversation = await conn.fetchrow(
                """SELECT id, video_id, state
                   FROM chat_conversations
                   WHERE id = $1 AND tenant_id = $2
                   FOR UPDATE""",
                conversation_id,
                tenant_id,
            )
            if not conversation:
                raise CustomFilmContractError("Custom Film conversation not found")
            state = _parse_json(conversation["state"])
            if not isinstance(state, dict):
                raise CustomFilmContractError("Custom Film conversation state is invalid")
            pending = state.get("pending_custom_film_plan")
            if not isinstance(pending, dict):
                raise CustomFilmContractError("Current Custom Film plan not found")

            # Durable replay convergence: a stale caller loaded before the first
            # request committed still returns the one reserved video.
            if (
                pending.get("status") == "start_ready"
                and pending.get("start_intent_hash") == expected_approval_hash
                and pending.get("video_id")
            ):
                return {
                    "video_id": str(pending["video_id"]),
                    "created": False,
                    "approval_hash": expected_approval_hash,
                    "max_spend": float(pending["quote_inputs"]["max_spend"]),
                }
            if conversation.get("video_id"):
                raise CustomFilmContractError(
                    "This conversation is already attached to a different video."
                )

            if pending.get("status") != "awaiting_approval":
                raise CustomFilmContractError(
                    "This Custom Film no longer has a current approval."
                )
            normalized_plan = pending.get("internal_plan")
            quote_inputs = pending.get("quote_inputs")
            if not isinstance(normalized_plan, dict) or not isinstance(
                quote_inputs, dict
            ):
                raise CustomFilmContractError("Custom Film estimate is incomplete")
            current_plan_hash = plan_hash(normalized_plan)
            current_binding = approval_binding_hash(
                current_plan_hash,
                quote_inputs,
            )
            if (
                pending.get("approval_hash") != expected_approval_hash
                or current_binding != expected_approval_hash
            ):
                raise CustomFilmContractError(
                    "This Custom Film estimate changed. Review and approve again."
                )

            duration_seconds = int(quote_inputs.get("requested_duration_seconds") or 0)
            if duration_seconds < 5:
                raise CustomFilmContractError("Custom Film duration is invalid")
            rows = quote_inputs.get("sections")
            if (
                not isinstance(rows, list)
                or sum(int(row.get("duration_seconds") or 0) for row in rows)
                != duration_seconds
            ):
                raise CustomFilmContractError(
                    "Custom Film section durations do not match the approved runtime"
                )
            max_spend = quote_inputs.get("max_spend")
            if max_spend is None:
                raise CustomFilmContractError(
                    "Custom Film needs a durable spending cap before approval"
                )
            from actions import budget_check

            budget_warning = budget_check(
                {"max_spend": float(max_spend), "total_cost": 0},
                float(quote_inputs["totals"]["estimated_cost"]),
            )
            if budget_warning:
                raise CustomFilmContractError(
                    f"{budget_warning['message']} Nothing was reserved."
                )

            raw_plan = revision_input_from_normalized_plan(
                normalized_plan,
                manifest,
            )
            # The round-trip above is the allowlist/compatibility validation;
            # use its canonical normalized result for the immutable rows.
            persisted_plan = normalize_plan(raw_plan, manifest)
            quote_digest = canonical_hash(quote_inputs)
            plan_id = str(uuid4())
            proposal = pending.get("planner_proposal")
            proposal_sections = (
                proposal.get("sections")
                if isinstance(proposal, dict)
                and isinstance(proposal.get("sections"), list)
                else []
            )
            first = proposal_sections[0] if proposal_sections else {}
            title = str(first.get("focus") or "Custom Film").strip()[:200]
            duration_minutes = (
                Decimal(duration_seconds) / Decimal(60)
            ).quantize(Decimal("0.000001"))
            video = await conn.fetchrow(
                """INSERT INTO videos
                     (tenant_id, video_title, status, source,
                      video_length_minutes, max_spend, writer_guidance)
                   VALUES ($1, $2, 'custom_film_ready', 'custom_film',
                           $3, $4, $5)
                   RETURNING id""",
                tenant_id,
                title,
                duration_minutes,
                Decimal(str(max_spend)),
                "Awaiting section-aware runtime execution.",
            )
            video_id = str(video["id"])
            await conn.execute(
                """INSERT INTO custom_film_plans
                     (id, tenant_id, video_id, revision, compatibility_version,
                      plan, plan_hash, quote_inputs, quote_inputs_hash,
                      approval_hash, approved_at)
                   VALUES ($1, $2, $3, 1, $4, $5::jsonb, $6, $7::jsonb,
                           $8, $9, now())""",
                plan_id,
                tenant_id,
                video_id,
                manifest.version,
                canonical_json(persisted_plan),
                current_plan_hash,
                canonical_json(quote_inputs),
                quote_digest,
                expected_approval_hash,
            )
            for section in persisted_plan["sections"]:
                await conn.execute(
                    """INSERT INTO custom_film_sections
                         (tenant_id, plan_id, video_id, section_id, order_index,
                          role, purpose, duration_units, knobs, provenance,
                          estimated_media)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                               $9::jsonb, $10::jsonb, $11::jsonb)""",
                    tenant_id,
                    plan_id,
                    video_id,
                    section["section_id"],
                    section["order_index"],
                    section["role"],
                    section["purpose"],
                    section["duration_units"],
                    canonical_json(section["knobs"]),
                    canonical_json(section["provenance"]),
                    canonical_json(section["estimated_media"]),
                )
            await conn.execute(
                """UPDATE videos
                   SET custom_film_plan_id = $3,
                       custom_film_plan_revision = 1,
                       custom_film_plan_hash = $4,
                       custom_film_quote_inputs_hash = $5,
                       custom_film_approval_hash = $6,
                       custom_film_approved_at = now(),
                       updated_at = now()
                   WHERE tenant_id = $1 AND id = $2""",
                tenant_id,
                video_id,
                plan_id,
                current_plan_hash,
                quote_digest,
                expected_approval_hash,
            )
            pending["status"] = "start_ready"
            pending["start_intent_hash"] = expected_approval_hash
            pending["video_id"] = video_id
            state["pending_custom_film_plan"] = pending
            await conn.execute(
                """UPDATE chat_conversations
                   SET state = $3::jsonb, video_id = $4, phase = 'created',
                       updated_at = now()
                   WHERE id = $1 AND tenant_id = $2""",
                conversation_id,
                tenant_id,
                canonical_json(state),
                video_id,
            )
            return {
                "video_id": video_id,
                "created": True,
                "approval_hash": expected_approval_hash,
                "max_spend": float(max_spend),
                "duration_seconds": duration_seconds,
            }


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return copy.deepcopy(value)


async def load_current_plan(
    tenant_id: str,
    video_id: str,
) -> dict[str, Any] | None:
    row = await fetch_one(
        """SELECT p.id, p.tenant_id, p.video_id, p.revision,
                  p.compatibility_version, p.plan, p.plan_hash,
                  p.quote_inputs, p.quote_inputs_hash,
                  p.approval_hash, p.approved_at::text, p.created_at::text
           FROM videos v
           JOIN custom_film_plans p
             ON p.id = v.custom_film_plan_id
            AND p.tenant_id = v.tenant_id
            AND p.video_id = v.id
           WHERE v.tenant_id = $1 AND v.id = $2 AND v.deleted_at IS NULL""",
        tenant_id,
        video_id,
    )
    if not row:
        return None
    sections = await fetch_all(
        """SELECT section_id, order_index, role, purpose, duration_units,
                  knobs, provenance, estimated_media
           FROM custom_film_sections
           WHERE tenant_id = $1 AND plan_id = $2
           ORDER BY order_index""",
        tenant_id,
        str(row["id"]),
    )
    return {
        "id": str(row["id"]),
        "video_id": str(row["video_id"]),
        "revision": int(row["revision"]),
        "compatibility_version": str(row["compatibility_version"]),
        "plan": _parse_json(row["plan"]),
        "plan_hash": str(row["plan_hash"]),
        "quote_inputs": _parse_json(row["quote_inputs"]),
        "quote_inputs_hash": str(row["quote_inputs_hash"]),
        "approval_hash": row.get("approval_hash"),
        "approved_at": row.get("approved_at"),
        "created_at": row.get("created_at"),
        "sections": [
            {
                "section_id": str(section["section_id"]),
                "order_index": int(section["order_index"]),
                "role": str(section["role"]),
                "purpose": str(section["purpose"]),
                "duration_units": int(section["duration_units"]),
                "knobs": _parse_json(section["knobs"]),
                "provenance": _parse_json(section["provenance"]),
                "estimated_media": _parse_json(section["estimated_media"]),
            }
            for section in sections
        ],
    }
