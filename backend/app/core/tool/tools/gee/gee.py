from langchain.tools import tool, ToolRuntime

from pydantic import BaseModel
from typing import Optional, Literal, Any

import ee
import json
import requests
import os
from google.oauth2.service_account import Credentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tool.tools.gee.authz import get_tool_runtime_bundle, RuntimeContext
SCOPES = [
    "https://www.googleapis.com/auth/earthengine",
    "https://www.googleapis.com/auth/cloud-platform",
]

from sqlmodel import select
from app.models.tool import Tool

IMAGE_PATH = "images"
DEM_PATH = "dems"
CLIMATE_PATH = "climate"

class GEEAuthParams(BaseModel):
    method: Literal["service_account", "default"] = "service_account"
    service_account_email: Optional[str] = None
    service_account_key_json: Optional[str] = None
    project_id: Optional[str] = None


async def _fetch_gee_auth_from_tool_runtime_params(
    db: AsyncSession,
    user_id: str,
    tool_name: str,
) -> GEEAuthParams:
    bundle = await get_tool_runtime_bundle(db, user_id, tool_name=tool_name)
    values: dict[str, Any] = bundle.get("values", {})
    return GEEAuthParams(**values)


async def gee_initialized(runtime: ToolRuntime[RuntimeContext], tool_name: str | None = None) -> Optional[dict]:
    ctx = runtime.context
    db: AsyncSession = ctx.db
    user_id: str = ctx.user_id
    tool_name = tool_name or getattr(runtime, "tool_name", None)
    try:
        cred = await _fetch_gee_auth_from_tool_runtime_params(db, user_id, tool_name)
        sa_json = cred.service_account_key_json
        if sa_json:
            info = json.loads(sa_json)
            creds = Credentials.from_service_account_info(
                info,
                scopes=SCOPES,
            )
            ee.Initialize(credentials=creds, project=info["project_id"])
        else:
            # 使用本机默认凭证（~/.config/earthengine/credentials），或无凭证情况下尝试匿名
            if cred.project_id:
                ee.Initialize(project=cred.project_id)
            else:
                ee.Initialize()
        return None
    except Exception as e:
        return {"error": f"GEE 初始化失败: {e}"}


class BaseParams(BaseModel):
    location_label: str
    polygon: Optional[list]
    scale: int = 30

class SatelliteImageryParams(BaseParams):
    product: str
    cloud_pct: int = 20
    start_date: str
    end_date: str
    max_images: int = 5  # 避免大规模下载


class DEMParams(BaseParams):
    product: str

class ClimateParams(BaseParams):
    lon: Optional[float]
    lat: Optional[float]
    product: str
    variable: str
    output_format: Literal["csv", "tiff"] = "tiff"
    start_date: str
    end_date: str
    time_scale: Literal["DAILY", "MONTHLY", "YEARLY"] = "MONTHLY"


def _normalize_polygon(poly: list) -> list:
    """如果传入的是单个 ring（[[lng,lat], ...]），包裹成 [ring]。"""
    if not poly:
        return poly
    if poly and isinstance(poly[0], list) and poly and isinstance(poly[0][0], (int, float)):
        # 形如 [[lng,lat], ...]
        return [poly]
    return poly


@tool
async def gee_get_satellite_imagery(
    location_label: str,
    product: str,
    polygon: Optional[list],
    start_date: str,
    end_date: str,
    scale: int,
    cloud_pct: int,
    max_images: int,
    runtime: ToolRuntime[RuntimeContext],
) -> dict:
    """
    Download satellite imagery from Google Earth Engine for a given region and time range.

    Supports optical products such as Sentinel-2 and Landsat-8. Images are filtered by
    date, region, and cloud coverage, and exported as GeoTIFF files by band.

    Args:
        location_label (str): Location name used in output filenames.
        product (str): Satellite product ("Sentinel-2", "Landsat-8").
        polygon (list): Area of interest polygon (WGS84 coordinates).
        start_date (str): Start date (YYYY-MM-DD).
        end_date (str): End date (YYYY-MM-DD).
        scale (int): Spatial resolution in meters.
        cloud_pct (int): Maximum cloud percentage.
        max_images (int): Maximum number of images to download.

    Returns:
        dict: Download results or {"error": str} if failed.
    """

    init_err = await gee_initialized(runtime, tool_name="gee_get_satellite_imagery")
    if init_err:
        return init_err

    tool_name = getattr(runtime, "tool_name", "gee_get_satellite_imagery")

    if not polygon:
        return {"error": "polygon is required"}

    pt = ee.Geometry.Polygon(_normalize_polygon(polygon))

    # 影像集合
    if product == "Sentinel-2":
        col = (
            ee.ImageCollection("COPERNICUS/S2_HARMONIZED")
            .filterBounds(pt)
            .filterDate(start_date, end_date)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
        )
    elif product == "Landsat-8":
        col = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterBounds(pt).filterDate(start_date, end_date)
    else:
        return {"error": f"Unsupported product {product}"}

    count = int(col.size().getInfo() or 0)
    if count == 0:
        return {"error": "No images found"}

    # 限制下载数量
    dl_count = min(count, max(1, int(max_images)))

    output_dir = os.path.join(IMAGE_PATH, product)
    os.makedirs(output_dir, exist_ok=True)

    images = col.toList(dl_count)
    results = []

    for i in range(dl_count):
        try:
            img = ee.Image(images.get(i))
            info = img.getInfo()
            img_id = (info.get("id") or f"{product}_{i}").replace("/", "_")

            band_dir = os.path.join(output_dir, img_id)
            os.makedirs(band_dir, exist_ok=True)

            for band in img.bandNames().getInfo():
                try:
                    band_img = img.select([band])
                    filename = f"{location_label}_{img_id}_{band}.tif"
                    local_path = os.path.join(band_dir, filename)

                    url = band_img.getDownloadURL({
                        "scale": scale,
                        "region": pt,
                        "format": "GEO_TIFF"
                    })

                    resp = requests.get(url, timeout=120)
                    if resp.status_code != 200:
                        results.append({"band": band, "error": f"HTTP {resp.status_code}", "url": url})
                        continue
                    with open(local_path, "wb") as f:
                        f.write(resp.content)

                    results.append({
                        "band": band,
                        "saved_to": local_path
                    })
                except Exception as be:
                    results.append({"band": band, "error": str(be)})
        except Exception as e:
            results.append({"error": f"image {i} failed: {e}"})

    return {
        "tool": tool_name,
        "product": product,
        "total_images": count,
        "downloaded": dl_count,
        "output_dir": output_dir,
        "downloads": results
    }


@tool
async def gee_get_dem(
    location_label: str,
    product: str,
    polygon: Optional[list],
    scale: int,
    runtime: ToolRuntime[RuntimeContext],
) -> dict:
    """
    Download a Digital Elevation Model (DEM) from Google Earth Engine.

    Supports common global DEM products and exports elevation data as a GeoTIFF.

    Args:
        location_label (str): Location name used in output filename.
        product (str): DEM product ("SRTM", "NASADEM").
        polygon (list): Area of interest polygon (WGS84 coordinates).
        scale (int): Spatial resolution in meters.

    Returns:
        dict: DEM file path or {"error": str} if failed.
    """

    init_err = await gee_initialized(runtime, tool_name="gee_get_dem")
    if init_err:
        return init_err

    if not polygon:
        return {"error": "polygon required"}

    pt = ee.Geometry.Polygon(_normalize_polygon(polygon))

    dem_map = {
        "SRTM": ("USGS/SRTMGL1_003", "elevation"),
        "NASADEM": ("NASA/NASADEM_HGT/001", "elevation"),
    }

    if product not in dem_map:
        return {"error": f"Unsupported DEM {product}"}

    img_id, band = dem_map[product]
    dem = ee.Image(img_id).select([band])

    try:
        url = dem.getDownloadURL({
            "scale": scale,
            "region": pt,
            "format": "GEO_TIFF"
        })
    except Exception as e:
        return {"error": f"构建下载链接失败: {e}"}

    os.makedirs(DEM_PATH, exist_ok=True)
    local_path = os.path.join(DEM_PATH, f"{location_label}_{product}.tif")

    try:
        resp = requests.get(url, timeout=120)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "url": url}
        with open(local_path, "wb") as f:
            f.write(resp.content)
    except Exception as e:
        return {"error": f"下载失败: {e}"}

    return {
        "product": product,
        "saved_to": local_path
    }


@tool
async def gee_get_climate(
    location_label: str,
    product: str,
    variable: str,
    lon: Optional[float],
    lat: Optional[float],
    polygon: Optional[list],
    start_date: str,
    end_date: str,
    scale: int,
    output_format: str,
    time_scale: str,
    runtime: ToolRuntime[RuntimeContext],
) -> dict:
    """
    Extract climate variables from Google Earth Engine for a point or region.

    Retrieves climate data (e.g. temperature, precipitation), aggregates it over time,
    and exports results as GeoTIFF or CSV.

    Args:
        location_label (str): Location name used in output filenames.
        product (str): Climate dataset (e.g. "ERA5", "ERA5_LAND").
        variable (str): Climate variable name.
        lon (float, optional): Longitude for point extraction.
        lat (float, optional): Latitude for point extraction.
        polygon (list, optional): Area of interest polygon.
        start_date (str): Start date (YYYY-MM-DD).
        end_date (str): End date (YYYY-MM-DD).
        scale (int): Spatial resolution in meters.
        output_format (str): "tiff" or "csv".
        time_scale (str): Temporal aggregation scale.

    Returns:
        dict: Export result or {"error": str} if failed.
    """

    init_err = await gee_initialized(runtime, tool_name="gee_get_climate")
    if init_err:
        return init_err

    # region
    if lon is not None and lat is not None:
        region = ee.Geometry.Point([lon, lat])
    elif polygon:
        region = ee.Geometry.Polygon(_normalize_polygon(polygon))
    else:
        return {"error": "location required"}

    # 数据集与变量映射
    product_key = (product or "").upper()
    dataset = "ECMWF/ERA5_LAND/HOURLY" if product_key in ("ERA5_LAND", "ERA5") else "ECMWF/ERA5_LAND/HOURLY"

    var_map = {
        "temperature": "temperature_2m",
        "temp": "temperature_2m",
        "t2m": "temperature_2m",
        "precipitation": "total_precipitation",
        "prcp": "total_precipitation",
        "u_wind": "u_component_of_wind_10m",
        "v_wind": "v_component_of_wind_10m",
    }
    var_key = variable.lower()
    var_band = var_map.get(var_key, variable)

    try:
        col = ee.ImageCollection(dataset).filterBounds(region).filterDate(start_date, end_date).select(var_band)
    except Exception as e:
        return {"error": f"构建集合失败: {e}"}

    # 聚合到时间平均影像
    try:
        img = col.mean()
    except Exception as e:
        return {"error": f"聚合失败: {e}"}

    os.makedirs(CLIMATE_PATH, exist_ok=True)
    base_name = f"{location_label}_{product}_{var_band}"

    if output_format.lower() == "tiff":
        try:
            url = img.getDownloadURL({
                "scale": scale,
                "region": region,
                "format": "GEO_TIFF"
            })
        except Exception as e:
            return {"error": f"构建下载链接失败: {e}"}

        local_path = os.path.join(CLIMATE_PATH, base_name + ".tif")
        try:
            resp = requests.get(url, timeout=120)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "url": url}
            with open(local_path, "wb") as f:
                f.write(resp.content)
        except Exception as e:
            return {"error": f"下载失败: {e}"}

        return {
            "product": product,
            "variable": var_band,
            "saved_to": local_path
        }

    # CSV 输出：对区域/点进行 reduceRegion(mean)，写入简易 CSV
    try:
        stat = img.reduceRegion(reducer=ee.Reducer.mean(), geometry=region, scale=scale, maxPixels=1e13)
        # 获取数值；band 名即 var_band
        value = stat.get(var_band).getInfo()
    except Exception as e:
        return {"error": f"统计失败: {e}"}

    local_path = os.path.join(CLIMATE_PATH, base_name + ".csv")
    try:
        # 简易 CSV：header,value
        with open(local_path, "w", encoding="utf-8") as f:
            f.write("variable,value\n")
            f.write(f"{var_band},{value}\n")
    except Exception as e:
        return {"error": f"写入 CSV 失败: {e}"}

    return {
        "product": product,
        "variable": var_band,
        "saved_to": local_path,
        "aggregation": "mean"
    }
