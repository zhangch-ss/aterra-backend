import json
import os
from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain.tools import tool

ARTIFACT_DIR = "/tmp/agent_artifacts"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

# ============================================================
# 1. Load AOI (Vector → file)
# ============================================================

class LoadAOIInput(BaseModel):
    name: str = Field(description="研究区名称，如 北京市")

@tool(
    args_schema=LoadAOIInput,
    description="加载研究区矢量边界，并生成 GeoJSON 文件"
)
def load_aoi(name: str) -> Dict[str, Any]:
    path = os.path.join(ARTIFACT_DIR, f"aoi_{name}.geojson")

    geojson = {
        "type": "FeatureCollection",
        "features": [],
        "properties": {
            "name": name,
            "area_km2": 1250.0
        },
        "crs": "EPSG:4326"
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
    return {
        "path": path,
        "type": "vector",
        "crs": "EPSG:4326"
    }
# ============================================================
# 2. Load Raster Dataset (Raster → file)
# ============================================================

class LoadRasterInput(BaseModel):
    dataset: str = Field(description="栅格数据名称，如 landcover_2020")

@tool(
    args_schema=LoadRasterInput,
    description="加载栅格数据，并生成栅格文件（mock）"
)
def load_raster(dataset: str) -> Dict[str, Any]:
    path = os.path.join(ARTIFACT_DIR, f"{dataset}.tif")

    # mock：仅创建占位文件
    with open(path, "w") as f:
        f.write("MOCK GEOTIFF DATA")

    return {
        "path": path,
        "resolution_m": 30,
        "crs": "EPSG:4326",
        "classes": {
            1: "Grassland",
            2: "Cropland",
            3: "Forest",
            4: "Water"
        }
    }
# ============================================================
# 3. Clip Raster by AOI (file → file)
# ============================================================

class ClipRasterInput(BaseModel):
    raster_path: str = Field(description="输入栅格文件路径")
    aoi_path: str = Field(description="AOI GeoJSON 文件路径")

@tool(
    args_schema=ClipRasterInput,
    description="按研究区裁剪栅格，生成新的栅格文件"
)
def clip_raster(
    raster_path: str,
    aoi_path: str
) -> Dict[str, Any]:
    out_path = os.path.join(ARTIFACT_DIR, "clipped_raster.tif")

    with open(out_path, "w") as f:
        f.write(f"CLIPPED FROM {raster_path} BY {aoi_path}")

    return {
        "path": out_path,
        "resolution_m": 30,
        "pixel_count": 1_388_889
    }
# ============================================================
# 4. Zonal Statistics (file → file)
# ============================================================

class ZonalStatsInput(BaseModel):
    clipped_raster_path: str = Field(description="裁剪后的栅格文件路径")

@tool(
    args_schema=ZonalStatsInput,
    description="统计研究区内各地类面积，并生成统计结果文件"
)
def zonal_stats(clipped_raster_path: str) -> Dict[str, Any]:
    stats = {
        "Grassland": 720.0,
        "Cropland": 310.0,
        "Forest": 180.0,
        "Water": 40.0,
        "unit": "km2"
    }

    out_path = os.path.join(ARTIFACT_DIR, "zonal_stats.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    return {
        "path": out_path,
        "unit": "km2"
    }
# ============================================================
# 5. Interpret Spatial Statistics (file → file)
# ============================================================

class InterpretStatsInput(BaseModel):
    stats_path: str = Field(description="面积统计结果 JSON 文件路径")

@tool(
    args_schema=InterpretStatsInput,
    description="基于面积统计结果生成空间分析结论"
)
def interpret_stats(stats_path: str) -> Dict[str, Any]:
    with open(stats_path, "r", encoding="utf-8") as f:
        stats = json.load(f)

    total = sum(v for k, v in stats.items() if k != "unit")
    dominant_class, dominant_area = max(
        ((k, v) for k, v in stats.items() if k != "unit"),
        key=lambda x: x[1]
    )

    result = {
        "total_area_km2": total,
        "dominant_landcover": dominant_class,
        "dominant_fraction": round(dominant_area / total, 2)
    }

    out_path = os.path.join(ARTIFACT_DIR, "interpretation.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return {
        "path": out_path,
        "summary": result
    }
def get_mock_gis_tools():
    return [
        load_aoi,
        load_raster,
        clip_raster,
        zonal_stats,
        interpret_stats,
    ]
