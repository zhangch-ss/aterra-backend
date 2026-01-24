from app.crud.lake_crud import crud_lake
from app.models.lake_model import LakeAreaTimeSeries, LakeLevelTimeSeries, LakeVolumeTimeSeries, LakeVolumeChangeTimeSeries

from fastapi import APIRouter, Query, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from app.api.deps import get_db
from typing import Optional, List, Any
from sqlmodel import SQLModel
from geoalchemy2.shape import to_shape
from pydantic import field_serializer
from shapely.geometry import Point
from sqlmodel import select

router = APIRouter()

class LakeRead(SQLModel):
    lake_id: int
    lake_name: str
    location: Optional[Any] = None      # 用序列化器把 WKBElement → GeoJSON 风格 dict
    lake_type: Optional[str] = None
    country: Optional[str] = None

    @field_serializer("location")
    def _serialize_location(self, v):
        if v is None:
            return None
        # 如果已经是 [lon, lat]，直接返回
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return list(v)
        try:
            geom = to_shape(v)
            if isinstance(geom, Point):
                return [geom.x, geom.y]  # [lon, lat]
            # 其他类型可按需处理
            return geom.__geo_interface__
        except Exception:
            return str(v)
        
@router.get("/by-bounds", response_model=List[LakeRead])
async def get_lakes_by_bounds(
    min_lat: float = Query(..., description="最小纬度"),
    max_lat: float = Query(..., description="最大纬度"),
    min_lon: float = Query(..., description="最小经度"),
    max_lon: float = Query(..., description="最大经度"),
    db: AsyncSession = Depends(get_db)
):
    lakes = await crud_lake.get_by_bounds(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        db_session=db
    )
    return lakes

# 新增：根据 lake_id 查询时间序列数据
from typing import Dict

@router.get("/lake-timeseries/{lake_id}", response_model=Dict[str, list])
async def get_lake_timeseries(
    lake_id: int,
    db: AsyncSession = Depends(get_db)
):
    area_q = select(LakeAreaTimeSeries).where(LakeAreaTimeSeries.lake_id == lake_id)
    level_q = select(LakeLevelTimeSeries).where(LakeLevelTimeSeries.lake_id == lake_id)
    volume_q = select(LakeVolumeTimeSeries).where(LakeVolumeTimeSeries.lake_id == lake_id)
    change_q = select(LakeVolumeChangeTimeSeries).where(LakeVolumeChangeTimeSeries.lake_id == lake_id)

    area_res = await db.exec(area_q)
    level_res = await db.exec(level_q)
    volume_res = await db.exec(volume_q)
    change_res = await db.exec(change_q)

    return {
        "area_timeseries": area_res.all(),
        "level_timeseries": level_res.all(),
        "volume_timeseries": volume_res.all(),
        "volume_change_timeseries": change_res.all()
    }

