from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class LakeBase(BaseModel):
    user_id: int
    organization_id: Optional[int] = None
    last_modified_by: Optional[int] = None
    
    lake_name: str
    location: Optional[str] = None
    lake_type: Optional[str] = None
    country: Optional[str] = None


class LakeCreate(LakeBase):
    lake_id: Optional[int] = None  # 对于从外部数据源导入时，可能需要指定lake_id


class LakeUpdate(LakeBase):
    lake_name: Optional[str] = None  # 更新时字段可选


# -------------------------------
# 时序数据基类
# -------------------------------
class TimeSeriesBase(BaseModel):
    user_id: int
    organization_id: Optional[int] = None
    last_modified_by: Optional[int] = None
    
    lake_id: int
    timestamp: datetime
    source: Optional[str] = None


# -------------------------------
# 面积时序数据
# -------------------------------
class LakeAreaTimeSeriesBase(TimeSeriesBase):
    area: float


class LakeAreaTimeSeriesCreate(LakeAreaTimeSeriesBase):
    pass


class LakeAreaTimeSeriesUpdate(BaseModel):
    area: Optional[float] = None
    source: Optional[str] = None


# -------------------------------
# 水位时序数据
# -------------------------------
class LakeLevelTimeSeriesBase(TimeSeriesBase):
    water_level: float


class LakeLevelTimeSeriesCreate(LakeLevelTimeSeriesBase):
    pass


class LakeLevelTimeSeriesUpdate(BaseModel):
    water_level: Optional[float] = None
    source: Optional[str] = None


# -------------------------------
# 水量时序数据
# -------------------------------
class LakeVolumeTimeSeriesBase(TimeSeriesBase):
    water_volume: float


class LakeVolumeTimeSeriesCreate(LakeVolumeTimeSeriesBase):
    pass


class LakeVolumeTimeSeriesUpdate(BaseModel):
    water_volume: Optional[float] = None
    source: Optional[str] = None
