# app/crud/crud_lake.py

from typing import List, Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, cast
from sqlalchemy import exc
from fastapi import HTTPException
from geoalchemy2 import shape
from shapely.geometry import Polygon
from sqlalchemy import func
from app.crud.base_crud import CRUDBase
from app.models.lake_model import Lake, LakeAreaTimeSeries, LakeLevelTimeSeries, LakeVolumeTimeSeries, LakeVolumeChangeTimeSeries
from app.schemas.lake_schema import LakeCreate, LakeUpdate
from geoalchemy2 import Geography
import json


class CRUDFLake(CRUDBase[Lake, LakeCreate, LakeUpdate]):
    def __init__(self):
        super().__init__(Lake)

    async def get_by_bounds(
        self,
        *,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        db_session: Optional[AsyncSession] = None
    ) -> List[Lake]:
        db_session = db_session or self.db.session
        envelope_geog = cast(
            func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326),
            Geography
        )
        stmt = (
            select(Lake)
            .where(
                func.ST_Covers(envelope_geog, Lake.location)  # geography 支持 ST_Covers
            ).limit(100)
        )
        res = await db_session.exec(stmt)
        return res.all()

    async def bulk_create_lakes(
        self,
        *,
        lakes_data: List[LakeCreate],
        db_session: AsyncSession | None = None,
    ) -> List[Lake]:
        """批量创建湖泊记录"""
        db_session = db_session or self.db.session
        db_objs = []
        for lake_data in lakes_data:
            db_obj = Lake.model_validate(lake_data)
            db_objs.append(db_obj)
        
        try:
            db_session.add_all(db_objs)
            await db_session.commit()
            
            # 刷新所有对象以获取生成的ID
            for db_obj in db_objs:
                await db_session.refresh(db_obj)
                
        except exc.IntegrityError as e:
            await db_session.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Bulk insert failed: {str(e)}",
            )
        return db_objs

    async def bulk_create_area_timeseries(
        self,
        *,
        timeseries_data: List[dict],
        db_session: AsyncSession | None = None,
    ) -> List[LakeAreaTimeSeries]:
        """批量创建面积时序数据"""
        db_session = db_session or self.db.session
        
        db_objs = []
        for data in timeseries_data:
            db_obj = LakeAreaTimeSeries(**data)
            db_objs.append(db_obj)
        
        try:
            db_session.add_all(db_objs)
            await db_session.commit()
            
            for db_obj in db_objs:
                await db_session.refresh(db_obj)
                
        except exc.IntegrityError as e:
            await db_session.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Bulk insert area timeseries failed: {str(e)}",
            )
        
        return db_objs

    async def bulk_create_level_timeseries(
        self,
        *,
        timeseries_data: List[dict],
        db_session: AsyncSession | None = None,
    ) -> List[LakeLevelTimeSeries]:
        """批量创建水位时序数据"""
        db_session = db_session or self.db.session
        
        db_objs = []
        for data in timeseries_data:
            db_obj = LakeLevelTimeSeries(**data)
            db_objs.append(db_obj)
        
        try:
            db_session.add_all(db_objs)
            await db_session.commit()
            
            for db_obj in db_objs:
                await db_session.refresh(db_obj)
                
        except exc.IntegrityError as e:
            await db_session.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Bulk insert level timeseries failed: {str(e)}",
            )
        
        return db_objs

    async def bulk_create_volume_timeseries(
        self,
        *,
        timeseries_data: List[dict],
        db_session: AsyncSession | None = None,
    ) -> List[LakeVolumeTimeSeries]:
        """批量创建水量时序数据"""
        db_session = db_session or self.db.session
        
        db_objs = []
        for data in timeseries_data:
            db_obj = LakeVolumeTimeSeries(**data)
            db_objs.append(db_obj)
        
        try:
            db_session.add_all(db_objs)
            await db_session.commit()
            
            for db_obj in db_objs:
                await db_session.refresh(db_obj)
                
        except exc.IntegrityError as e:
            await db_session.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Bulk insert volume timeseries failed: {str(e)}",
            )
        
        return db_objs


crud_lake = CRUDFLake()
