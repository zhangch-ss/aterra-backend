from langchain.tools import tool

# 预存一些省份的 bbox（示例）
PROVINCE_BBOX = {
    "山东省": (114.80, 34.38, 122.70, 38.45),
    "北京市": (115.42, 39.43, 117.51, 41.06),
    "江苏省": (116.30, 30.75, 121.90, 35.09)
}

@tool
def locate_region(name: str) -> dict:
    """定位到某个地区的位置，返回四角坐标"""
    if name not in PROVINCE_BBOX:
        return {"error": f"未找到该省份: {name}"}
    bbox = PROVINCE_BBOX[name]
    return {"bbox": bbox}
