import json
from app.core.tool.tools.gee import (
    gee_get_satellite_imagery,
    gee_get_dem,
    gee_get_climate,
    GEEAuthParams,
)


def test_satellite_imagery_stub():
    auth = GEEAuthParams(method="default", service_account_email=None, service_account_key_json=None)
    resp = gee_get_satellite_imagery.invoke({
        "polygon": [[100.0, 34.0], [100.05, 34.0], [100.05, 34.05], [100.0, 34.05]],
        "location_label": "aa",
        "product": "Sentinel-2",
        "start_date": "2023-01-01",
        "end_date": "2023-01-15",
        "cloud_pct": 10,
        "auth": auth,
        "scale": 10,
    })
    assert resp is not None


def test_dem_stub():
    auth = GEEAuthParams(method="default", service_account_email=None, service_account_key_json=None)
    resp = gee_get_dem.invoke({
        "location_label": "aa",
        "product": "SRTM",
        "polygon": [[100.0, 34.0], [101.0, 34.0], [101.0, 35.0], [100.0, 35.0]],
        "auth": auth,
    })
    assert resp is not None


def test_climate_stub():
    auth = GEEAuthParams(method="default", service_account_email=None, service_account_key_json=None)
    resp = gee_get_climate.invoke({
        "location_label": "aa",
        "product": "ERA5",
        "variable": "temperature",
        "lon": 100.0,
        "lat": 34.0,
        "start_date": "2023-06-01",
        "end_date": "2023-06-30",
        "output_format": "csv",
        "auth": auth,
    })
    assert resp is not None
