from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from pydantic import BaseModel
from app.api.deps import get_db, get_current_user
from app.schemas.model import ModelCreateInput, ModelUpdate, ModelRead, InvokeConfig
from app.services.model_service import (
    model_service,
    ProviderCredentialsInput,
    ModelVerifyInput,
)

router = APIRouter()



@router.get("", response_model=list[ModelRead])
async def list_models(
    provider: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    items = await model_service.list_models(
        user_id=current_user.id,
        db_session=db,
        provider=provider,
        keyword=keyword,
    )
    return [ModelRead.model_validate(m, from_attributes=True) for m in items]


@router.get("/{model_id}", response_model=ModelRead)
async def get_model(model_id: str, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    model = await model_service.get_owned_model(model_id=model_id, user_id=current_user.id, db_session=db)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return ModelRead.model_validate(model, from_attributes=True)


@router.post("", response_model=ModelRead)
async def create_model(payload: ModelCreateInput, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    created = await model_service.create_model(payload=payload, user_id=current_user.id, db_session=db)
    return ModelRead.model_validate(created, from_attributes=True)


@router.put("/{model_id}", response_model=ModelRead)
async def update_model(model_id: str, payload: ModelUpdate, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    updated = await model_service.update_model(model_id=model_id, payload=payload, user_id=current_user.id, db_session=db)
    if not updated:
        raise HTTPException(status_code=404, detail="Model not found")
    return ModelRead.model_validate(updated, from_attributes=True)


@router.delete("/{model_id}", response_model=dict)
async def delete_model(model_id: str, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    ok = await model_service.delete_model(model_id=model_id, user_id=current_user.id, db_session=db)
    if not ok:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"ok": True}





@router.post("/verify", response_model=dict)
async def verify_model(
    payload: ModelVerifyInput,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    result = await model_service.verify_model(
        user_id=current_user.id,
        db_session=db,
        model_id=payload.model_id,
        provider=payload.provider,
        invoke_config=payload.invoke_config,
    )
    if not result.get("ok") and result.get("error") == "Unsupported provider: None":
        raise HTTPException(status_code=400, detail="Missing provider")
    return result


# ===== Provider credentials management (stored in PostgreSQL, optionally encrypted at rest) =====
@router.post("/credentials/{provider}", response_model=dict)
async def set_provider_credentials(
    provider: str,
    payload: ProviderCredentialsInput,
    current_user = Depends(get_current_user),
):
    await model_service.set_provider_credentials(user_id=current_user.id, provider=provider, payload=payload)
    return {"ok": True}


@router.get("/credentials/{provider}", response_model=dict)
async def get_provider_credentials_route(
    provider: str,
    reveal: bool | None = False,
    current_user = Depends(get_current_user),
):
    creds = await model_service.get_provider_credentials(user_id=current_user.id, provider=provider, reveal_secret=bool(reveal))
    return creds


@router.delete("/credentials/{provider}", response_model=dict)
async def delete_provider_credentials_route(provider: str, current_user = Depends(get_current_user)):
    await model_service.delete_provider_credentials(user_id=current_user.id, provider=provider)
    return {"ok": True}
