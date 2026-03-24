from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.models import User, RhinoList, RhinoIdentity
from app.auth import get_current_user

router = APIRouter(prefix="/lists", tags=["lists"])


class ListCreate(BaseModel):
    name: str
    list_type: str  # "high_quality" | "images"


class ListResponse(BaseModel):
    id: int
    name: str
    list_type: str
    source_path: str | None

    class Config:
        from_attributes = True


class IdentityResponse(BaseModel):
    id: int
    name: str
    pid: int | None

    class Config:
        from_attributes = True


@router.get("", response_model=list[ListResponse])
async def list_lists(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(RhinoList).order_by(RhinoList.id))
    return list(result.scalars().all())


@router.post("", response_model=ListResponse)
async def create_list(
    data: ListCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.list_type not in ("high_quality", "images"):
        raise HTTPException(status_code=400, detail="list_type must be high_quality or images")
    rl = RhinoList(name=data.name, list_type=data.list_type)
    db.add(rl)
    await db.flush()
    return rl


@router.get("/{list_id}", response_model=ListResponse)
async def get_list(
    list_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(RhinoList).where(RhinoList.id == list_id))
    rl = result.scalar_one_or_none()
    if not rl:
        raise HTTPException(status_code=404, detail="List not found")
    return rl


@router.get("/{list_id}/identities", response_model=list[IdentityResponse])
async def list_identities(
    list_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(RhinoIdentity).where(RhinoIdentity.list_id == list_id).order_by(RhinoIdentity.id)
    )
    return list(result.scalars().all())


@router.post("/{list_id}/identities")
async def create_identity(
    list_id: int,
    name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(RhinoList).where(RhinoList.id == list_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="List not found")
    ident = RhinoIdentity(list_id=list_id, name=name)
    db.add(ident)
    await db.flush()
    return {"id": ident.id, "name": ident.name}


class MigrateRequest(BaseModel):
    source_list_id: int
    target_list_id: int
    identity_ids: list[int] | None = None  # None = migrate all


@router.post("/migrate")
async def migrate_list(
    data: MigrateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    src = await db.get(RhinoList, data.source_list_id)
    tgt = await db.get(RhinoList, data.target_list_id)
    if not src or not tgt:
        raise HTTPException(status_code=404, detail="List not found")
    result = await db.execute(
        select(RhinoIdentity).where(RhinoIdentity.list_id == data.source_list_id)
    )
    identities = list(result.scalars().all())
    if data.identity_ids:
        identities = [i for i in identities if i.id in data.identity_ids]
    for ident in identities:
        ident.list_id = data.target_list_id
    return {"migrated": len(identities)}
