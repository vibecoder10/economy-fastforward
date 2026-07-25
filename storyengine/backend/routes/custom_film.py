"""GET /api/custom-film/recipes — strictly read-only list of a tenant's
active saved Custom Film recipes.

Why this exists: `custom_film_recipes` has zero rows in production today
because the only way to save one is a magic chat phrase, and the only
existing *reader*, `custom_film_contract.list_active_recipes_for_chat`, is
not a safe read path — it opens a transaction, takes an advisory xact lock,
and appends two `chat_conversations` turns as a side effect. This route
instead calls `custom_film_contract.list_active_recipes(tenant_id)`, which
already exists, already has the correct tenant-scoped query, and has never
had a production caller: one plain `SELECT ... WHERE tenant_id = $1 AND
archived_at IS NULL`, no transaction, no lock, no writes.

`custom_film_recipes` has no `last_used_at` column and `videos` has no
`recipe_id` column (no video->recipe link exists), so neither is exposed
here — see schema.sql's `custom_film_recipes` table (migration
122_custom_film_contract.sql, altered by 128_custom_film_recipe_lifecycle.sql,
neither touches those columns).
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_tenant_id
from custom_film_contract import list_active_recipes

router = APIRouter(prefix="/api/custom-film", tags=["custom-film"])


class RecipeSectionMix(BaseModel):
    role: str
    duration_units: int
    share: float  # 0..1 fraction of this recipe's total duration_units


class CustomFilmRecipeResponse(BaseModel):
    id: str
    name: str
    recipe_family_id: str
    version: int
    compatibility_version: str
    section_mix: list[RecipeSectionMix]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CustomFilmRecipesResponse(BaseModel):
    recipes: list[CustomFilmRecipeResponse]


def _section_mix(recipe: dict[str, Any]) -> list[RecipeSectionMix]:
    """Parse the recipe JSONB's `sections` list (each with a `role` and
    `duration_units`, per custom_film_contract.normalize_recipe) into a
    display-ready mix with each section's share of the recipe's total
    duration units."""
    sections = recipe.get("sections") or []
    total = sum(int(section.get("duration_units") or 0) for section in sections)
    return [
        RecipeSectionMix(
            role=str(section.get("role")),
            duration_units=int(section.get("duration_units") or 0),
            share=(
                round(int(section.get("duration_units") or 0) / total, 4)
                if total > 0
                else 0.0
            ),
        )
        for section in sections
    ]


@router.get("/recipes", response_model=CustomFilmRecipesResponse)
async def list_custom_film_recipes(tenant_id: str = Depends(get_tenant_id)):
    """Active saved Custom Film recipes for this tenant (newest version per
    recipe family). Strictly read-only — see module docstring. Returns an
    empty list, not a 404, when the tenant has no saved recipes."""
    rows = await list_active_recipes(tenant_id)
    recipes = [
        CustomFilmRecipeResponse(
            id=row["id"],
            name=row["name"],
            recipe_family_id=row["recipe_family_id"],
            version=row["version"],
            compatibility_version=row["compatibility_version"],
            section_mix=_section_mix(row.get("recipe") or {}),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
        for row in rows
    ]
    return CustomFilmRecipesResponse(recipes=recipes)
