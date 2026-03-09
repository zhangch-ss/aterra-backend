from fastapi import HTTPException
from typing import Any, Generic, TypeVar
from uuid import UUID
from app.schemas.common import IOrderEnum
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination import Params, Page
from pydantic import BaseModel
from sqlmodel import SQLModel, select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import Select
from sqlalchemy import exc
from sqlalchemy.orm import selectinload
from app.utils.logger import setup_logger



ModelType = TypeVar("ModelType", bound=SQLModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)
SchemaType = TypeVar("SchemaType", bound=BaseModel)
T = TypeVar("T", bound=SQLModel)


logger = setup_logger("CRUDBase")


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: type[ModelType]):
        """
        CRUD object with default methods to Create, Read, Update, Delete (CRUD).
        **Parameters**
        * `model`: A SQLModel model class
        * `schema`: A Pydantic model (schema) class
        """
        self.model = model

    @staticmethod
    def _ensure_session(db_session: AsyncSession | None) -> AsyncSession:
        if db_session is None:
            raise RuntimeError(
                "AsyncSession is required. Ensure you inject it via Depends(get_db) and pass db_session explicitly."
            )
        return db_session

    async def get(
        self, *, id: UUID | str, db_session: AsyncSession | None = None
    ) -> ModelType | None:
        db_session = self._ensure_session(db_session)
        query = select(self.model).where(self.model.id == id)
        response = await db_session.execute(query)
        return response.scalar_one_or_none()

    async def get_by_ids(
        self,
        *,
        list_ids: list[UUID | str],
        db_session: AsyncSession | None = None,
    ) -> list[ModelType]:
        db_session = self._ensure_session(db_session)
        response = await db_session.execute(
            select(self.model).where(self.model.id.in_(list_ids))
        )
        return response.scalars().all()

    async def get_count(
        self, db_session: AsyncSession | None = None
    ) -> int:
        db_session = self._ensure_session(db_session)
        response = await db_session.execute(
            select(func.count()).select_from(select(self.model).subquery())
        )
        return response.scalar_one()

    async def get_multi(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        query: T | Select[T] | None = None,
        db_session: AsyncSession | None = None,
    ) -> list[ModelType]:
        db_session = self._ensure_session(db_session)
        if query is None:
            query = select(self.model).offset(skip).limit(limit).order_by(self.model.id)
        response = await db_session.execute(query)
        return response.scalars().all()

    async def get_multi_paginated(
        self,
        *,
        params: Params | None = Params(),
        query: T | Select[T] | None = None,
        db_session: AsyncSession | None = None,
    ) -> Page[ModelType]:
        db_session = self._ensure_session(db_session)
        if query is None:
            query = select(self.model)

        output = await paginate(db_session, query, params)
        return output

    async def get_multi_paginated_ordered(
        self,
        *,
        params: Params | None = Params(),
        order_by: str | None = None,
        order: IOrderEnum | None = IOrderEnum.ascendent,
        query: T | Select[T] | None = None,
        db_session: AsyncSession | None = None,
    ) -> Page[ModelType]:
        db_session = self._ensure_session(db_session)

        columns = self.model.__table__.columns

        if order_by is None or order_by not in columns:
            order_by = "id"

        if query is None:
            if order == IOrderEnum.ascendent:
                query = select(self.model).order_by(columns[order_by].asc())
            else:
                query = select(self.model).order_by(columns[order_by].desc())

        return await paginate(db_session, query, params)

    async def get_multi_ordered(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        order_by: str | None = None,
        order: IOrderEnum | None = IOrderEnum.ascendent,
        db_session: AsyncSession | None = None,
    ) -> list[ModelType]:
        db_session = self._ensure_session(db_session)

        columns = self.model.__table__.columns

        if order_by is None or order_by not in columns:
            order_by = "id"

        if order == IOrderEnum.ascendent:
            query = (
                select(self.model)
                .offset(skip)
                .limit(limit)
                .order_by(columns[order_by].asc())
            )
        else:
            query = (
                select(self.model)
                .offset(skip)
                .limit(limit)
                .order_by(columns[order_by].desc())
            )

        response = await db_session.execute(query)
        return response.scalars().all()

    async def create(
        self,
        *,
        obj_in: CreateSchemaType | ModelType,
        created_by_id: UUID | str | None = None,
        db_session: AsyncSession | None = None,
    ) -> ModelType:
        db_session = self._ensure_session(db_session)
        db_obj = self.model.model_validate(obj_in)  # type: ignore

        if created_by_id:
            db_obj.created_by_id = created_by_id

        try:
            db_session.add(db_obj)
            await db_session.commit()
            await db_session.refresh(db_obj)
            return db_obj

        except exc.IntegrityError as e:
            logger.warning("IntegrityError on create: %r", e)
            await db_session.rollback()
            raise HTTPException(status_code=409, detail="Resource already exists")

        except Exception as e:
            # 必须 rollback
            await db_session.rollback()
            logger.exception("CREATE ERROR: %r", e)
            raise HTTPException(status_code=500, detail=f"Database error: {repr(e)}")


    async def update(
        self,
        *,
        obj_current: ModelType,
        obj_new: UpdateSchemaType | dict[str, Any] | ModelType,
        db_session: AsyncSession | None = None,
    ) -> ModelType:
        db_session = self._ensure_session(db_session)

        if isinstance(obj_new, dict):
            update_data = obj_new
        else:
            update_data = obj_new.dict(
                exclude_unset=True
            )  # This tells Pydantic to not include the values that were not sent

        # 仅更新模型真实列，忽略不可写/不存在的字段（如关系 ids 等）
        try:
            allowed_columns = set(self.model.__table__.columns.keys())
        except Exception:
            allowed_columns = set()

        for field, value in update_data.items():
            if field not in allowed_columns:
                # 安静跳过未知字段，避免 ValueError: no field "..."
                continue
            setattr(obj_current, field, value)

        db_session.add(obj_current)
        await db_session.commit()
        await db_session.refresh(obj_current)
        return obj_current

    async def remove(
        self, *, id: UUID | str, db_session: AsyncSession | None = None
    ) -> ModelType:
        db_session = self._ensure_session(db_session)
        response = await db_session.execute(
            select(self.model).where(self.model.id == id)
        )
        obj = response.scalar_one()
        await db_session.delete(obj)
        await db_session.commit()
        return obj


    async def get_with_relations(
        self,
        *,
        id: UUID | str,
        relations: list[str] | None = None,
        db_session: AsyncSession | None = None,
    ) -> ModelType | None:
        """
        根据主键获取对象并可选预加载关联关系（selectinload）
        例如: await crud_agent.get_with_relations(id=agent_id, relations=["tools", "subagents"])
        """
        db_session = self._ensure_session(db_session)

        query = select(self.model)
        if relations:
            for rel in relations:
                try:
                    query = query.options(selectinload(getattr(self.model, rel)))
                except AttributeError:
                    continue
        query = query.where(self.model.id == id)

        result = await db_session.execute(query)
        return result.scalar_one_or_none()
