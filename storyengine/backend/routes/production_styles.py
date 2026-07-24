"""Authenticated read API for the four public production profiles."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from auth import get_tenant_id
from production_styles import list_public_profiles


router = APIRouter(prefix="/api/production-styles", tags=["production-styles"])


class ProductionStyleResponse(BaseModel):
    id: str
    version: int
    label: str
    description: str
    knobs: dict
    estimate: dict
    requires_byok: bool = True
    sort: int = 0


class ProductionStylesResponse(BaseModel):
    styles: list[ProductionStyleResponse] = Field(default_factory=list)


@router.get("", response_model=ProductionStylesResponse)
async def list_production_styles(
    tenant_id: str = Depends(get_tenant_id),
):
    # tenant_id is deliberately required for auth even though the catalog is
    # global. Never query channel_profiles here: a public style cannot read a
    # different customer's tenant-isolated channel row.
    del tenant_id
    return ProductionStylesResponse(styles=await list_public_profiles())
