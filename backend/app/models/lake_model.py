from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field, UniqueConstraint
from sqlalchemy import Column, Index, BigInteger, SmallInteger, Integer, DateTime, Float, String, Boolean
from sqlalchemy.dialects.postgresql import TIMESTAMP, NUMERIC
from geoalchemy2 import Geography
# -------------------------------
# 基本字段
# -------------------------------
class BaseLakeModel(SQLModel):
    user_id: int = Field(index=True, description="数据归属用户ID")
    organization_id: Optional[int] = Field(default=None, index=True, description="所属组织ID")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
    last_modified_by: Optional[int] = Field(default=None, description="最后修改该数据的用户ID")

    is_active: bool = Field(default=True, description="是否为有效数据（支持软删除）")
    is_public: bool = Field(default=False, description="是否公开共享")
    visibility: Optional[str] = Field(default="private", description="可见性（如 private/org/public）")
# -------------------------------
# 湖泊基本信息表
# -------------------------------
class Lake(BaseLakeModel, table=True):
    __tablename__ = "lakes"
    __table_args__ = (
        Index("idx_lakes_location", "location", postgresql_using="gist"),
    )

    lake_id: Optional[int] = Field(default=None, primary_key=True)
    lake_name: str = Field(index=True, nullable=False, description="湖泊名称")
    location: Optional[str] = Field(
        sa_column=Column(Geography(geometry_type='POINT', srid=4326)),
        description="湖泊经纬度位置（Point 类型，WGS84）"
    )
    lake_type: Optional[str] = Field(default=None, description="湖泊类型")
    country: Optional[str] = Field(default=None, description="所在国家")

# -------------------------------
# 面积时序表
# -------------------------------
class LakeAreaTimeSeries(BaseLakeModel, table=True):
    __tablename__ = "lake_area_time_series"
    __table_args__ = (UniqueConstraint("lake_id", "timestamp"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    lake_id: int = Field(foreign_key="lakes.lake_id", index=True)
    timestamp: datetime = Field(index=True, description="观测时间")
    area: float = Field(description="水域面积，单位 m²")
    source: Optional[str] = Field(default=None, description="数据来源")

    class Config:
        json_schema_extra = {
            "example": {
                "lake_id": 1,
                "timestamp": "2023-01-01T00:00:00",
                "area": 125000.0,
                "source": "遥感"
            }
        }

# -------------------------------
# 水位时序表
# -------------------------------
class LakeLevelTimeSeries(BaseLakeModel, table=True):
    __tablename__ = "lake_level_time_series"
    __table_args__ = (UniqueConstraint("lake_id", "timestamp"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    lake_id: int = Field(foreign_key="lakes.lake_id", index=True)
    timestamp: datetime = Field(index=True, description="观测时间")
    water_level: float = Field(description="水位，单位 m")
    source: Optional[str] = Field(default=None, description="数据来源")

# -------------------------------
# 水量时序表
# -------------------------------
class LakeVolumeTimeSeries(BaseLakeModel, table=True):
    __tablename__ = "lake_volume_time_series"
    __table_args__ = (UniqueConstraint("lake_id", "timestamp"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    lake_id: int = Field(foreign_key="lakes.lake_id", index=True)
    timestamp: datetime = Field(index=True, description="观测时间")
    water_volume: float = Field(description="水量，单位 m³")
    source: Optional[str] = Field(default=None, description="数据来源")

# -------------------------------
# 水量变化时序表
# -------------------------------
class LakeVolumeChangeTimeSeries(BaseLakeModel, table=True):
    __tablename__ = "lake_volume_change_time_series"
    __table_args__ = (UniqueConstraint("lake_id", "timestamp"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    lake_id: int = Field(foreign_key="lakes.lake_id", index=True)
    timestamp: datetime = Field(index=True, description="观测时间")
    water_volume: float = Field(description="水量，单位 m³")
    source: Optional[str] = Field(default=None, description="数据来源")



__all__ = [
    # 原始模型
    "BaseLakeModel",
    "Lake", 
    "LakeAreaTimeSeries",
    "LakeLevelTimeSeries", 
    "LakeVolumeTimeSeries",
    "LakeVolumeChangeTimeSeries"
]