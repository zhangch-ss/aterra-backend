# earth_agent_structured.py
from typing import List
from pydantic import BaseModel, Field
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from geopy.geocoders import Nominatim
import geopandas as gpd
from shapely.geometry import Point

from langchain.tools import tool
from langchain.agents import create_agent

EARTH_AGENT_PROMPT = """
You are **Earth-Agent**, an intelligent geospatial analysis assistant capable of reasoning about the Earth’s surface, geographic data, and environmental information.

You have access to three main tools — **Google Search**, **google_earth**, and **utils** — and you must use them strategically to fulfill the user’s request.

---

### 🧭 Available Tools and Usage Rules

#### 1. Google Search
**Purpose:** Retrieve general, non-spatial information from the internet.
**Function:** `search(queries: list[str])` — searches online sources and returns concise text summaries.

**When to use:**
- The query asks about historical, scientific, or factual information unrelated to geometry or map data.
- Example: “What is the history of Mount Fuji?” → Use Google Search.

---

#### 2. google_earth
Your primary tool for geospatial tasks and spatial data operations.

| Function | Description | Example Workflow |
|-----------|--------------|------------------|
| `resolve_to_geometry(locations: list[str])` | Convert place names into geographic geometries (points or polygons). | “Show the location of Rome.” |
| `search_data_spec(data_type: str)` | Search for available geospatial datasets (e.g., airports, rivers, vegetation). | “Find available airport data.” |
| `get_data_in_locations(dataset, geometry)` | Extract data entries within a specified geographic area. | Combine dataset and region to get all airports in Canada. |
| `save(sgt, name)` | Save or display geographic features as a named layer on the map. | After fetching data, save as “Airports in Canada.” |
| `load_context()` | Retrieve the user’s current map extent or selected area. | “Find all parks near me.” |

**Typical Workflow:**
1. Use `resolve_to_geometry` to locate the region.
2. Use `search_data_spec` to confirm dataset availability.
3. Use `get_data_in_locations` to extract features.
4. Use `save` to visualize or store results.

---

#### 3. utils
A supporting spatial analysis toolkit for geometric and tabular operations.

| Function | Description | Example |
|-----------|-------------|----------|
| `add_buffer(sgt, distance_meters)` | Expand a point or polygon by a specified distance (in meters) for “nearby” or “within distance” queries. | “Restaurants within 1 km of my hotel.” |
| `add_area(sgt)` | Calculate the area of a polygon in square meters or square kilometers. | “How large is this lake?” |
| `deserialize_to_geodataframe(...)` / `serialize_from_geodataframe(...)` | Convert between spatial data and tabular GeoDataFrame formats for filtering, ranking, or analysis. | “Show the five largest parks in New York City.” |

---

### 🧩 Reasoning Strategy
1. Identify whether the user’s query is informational (→ Google Search) or spatial (→ google_earth / utils).
2. Decompose complex tasks into sequential tool calls when necessary.
3. Combine multiple tools logically (e.g., create buffer → query within buffer → calculate area).
4. Provide concise, factual summaries of the results — not raw data unless requested.
5. When visual outputs are involved, mention the layer name clearly.
6. Prefer factual reasoning and correct tool use over free-form guessing.

---

### 🧠 Example Interactions

**User:** “Map all airports in Canada.”  
**You:**  
1. `resolve_to_geometry(["Canada"])`  
2. `search_data_spec("airports")`  
3. `get_data_in_locations("airports", Canada_geometry)`  
4. `save(result, "Airports in Canada")`  
→ “Mapped all airports in Canada and added them as a new layer.”

**User:** “How big is Qinghai Lake?”  
→ `resolve_to_geometry(["Qinghai Lake"])` → `add_area(lake_polygon)`  
→ “Qinghai Lake covers approximately 4,400 km².”

**User:** “What is the history of Mount Fuji?”  
→ Use `Google Search` and summarize findings in 2–3 sentences.

---

You are a professional Earth observation and geospatial intelligence expert.  
Always reason through each step and select the correct tools to produce reliable, concise, and factually grounded results.
"""

# ========== 1️⃣ Google Search ==========

class GoogleSearchInput(BaseModel):
    """Search the internet for general, non-geospatial information."""
    queries: List[str] = Field(description="List of search queries to look up online")

@tool(args_schema=GoogleSearchInput)
def google_search(queries: List[str]) -> str:
    """Perform a web search and return summarized results."""
    return f"Search results for {queries}: Relevant information retrieved from online sources."


# ========== 2️⃣ google_earth 工具组 ==========
class ResolveToGeometryInput(BaseModel):
    locations: List[str] = Field(description="List of place names to convert to coordinates or polygons")

@tool(args_schema=ResolveToGeometryInput)
def resolve_to_geometry(locations: List[str]) -> str:
    """Convert place names into geographic geometries."""
    geolocator = Nominatim(user_agent="earth_agent")
    records = []

    for loc in locations:
        result = geolocator.geocode(loc, exactly_one=True, addressdetails=True)
        if result:
            records.append({
                "name": loc,
                "latitude": result.latitude,
                "longitude": result.longitude,
                "geometry": Point(result.longitude, result.latitude),
            })
        else:
            records.append({"name": loc, "geometry": None})

    gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
    # 可返回 JSON 结果供下游工具使用
    return gdf.to_json()

class SearchDataSpecInput(BaseModel):
    data_type: str = Field(description="Dataset type to search, e.g., airports, rivers, cities")

@tool(args_schema=SearchDataSpecInput)
def search_data_spec(data_type: str) -> str:
    """Search for available dataset specifications within Google Earth."""
    return f"Dataset '{data_type}' is available in catalog."


class GetDataInLocationsInput(BaseModel):
    dataset: str = Field(description="Dataset name to extract data from")
    region: str = Field(description="Region or country name defining spatial boundary")

@tool(args_schema=GetDataInLocationsInput)
def get_data_in_locations(dataset: str, region: str) -> str:
    """Extract data entries within a given region."""
    return f"Extracted {dataset} data entries within {region}."


class SaveLayerInput(BaseModel):
    name: str = Field(description="Layer name to save or display")
    count: int = Field(default=0, description="Number of features in the layer")

@tool(args_schema=SaveLayerInput)
def save(name: str, count: int = 0) -> str:
    """Save geographic features as a named layer on the map."""
    return f"Layer '{name}' saved successfully with {count} features."


class LoadContextInput(BaseModel):
    """No parameters needed to load context."""
    pass

@tool(args_schema=LoadContextInput)
def load_context() -> str:
    """Retrieve the current visible map extent or selected area."""
    return "Loaded current map context."


# ========== 3️⃣ utils 工具组 ==========

class AddBufferInput(BaseModel):
    location: str = Field(description="Place or feature name to create a buffer around")
    distance_m: float = Field(description="Buffer radius in meters")

@tool(args_schema=AddBufferInput)
def add_buffer(location: str, distance_m: float) -> str:
    """Create a circular buffer around a point or polygon."""
    return f"Created a buffer of {distance_m} meters around {location}."


class AddAreaInput(BaseModel):
    shape_name: str = Field(description="Name of the polygon or feature to measure")

@tool(args_schema=AddAreaInput)
def add_area(shape_name: str) -> str:
    """Calculate the area of a polygon or region."""
    return f"The area of {shape_name} has been calculated."


class DeserializeInput(BaseModel):
    """Deserialize spatial data into tabular format."""
    data: str = Field(description="Serialized geographic data string")

@tool(args_schema=DeserializeInput)
def deserialize_to_geodataframe(data: str) -> str:
    """Convert map data into a GeoDataFrame for analysis."""
    return f"Deserialized map data into a GeoDataFrame."


class SerializeInput(BaseModel):
    """Serialize table data back into geographic format."""
    table: str = Field(description="Tabular GeoDataFrame string")

@tool(args_schema=SerializeInput)
def serialize_from_geodataframe(table: str) -> str:
    """Convert analytical results back into geographic features."""
    return f"Serialized GeoDataFrame into geographic features."


# ============================================================
# 🤖 二、创建智能体 (Agent)
# ============================================================

tools = [
    # google_search,
    resolve_to_geometry,
    search_data_spec,
    get_data_in_locations,
    add_buffer,
    add_area,
]

earth_agent = create_deep_agent(
    model="azure_openai:gpt-4o",
    tools=tools,
    system_prompt=EARTH_AGENT_PROMPT,
    backend=FilesystemBackend(
        root_dir=r"E:/open_source/fastapi-alembic-sqlmodel-async/backend/app/work",
        virtual_mode=True
        )
)

# ============================================================
# 🚀 三、使用示例
# ============================================================

if __name__ == "__main__":
    queries = [
        "列出当前目录的文件"
    ]

    for q in queries:
        print(f"\n🧭 User: {q}")
        result = earth_agent.invoke(
            {"messages": [{"role": "user", "content": f"{q}"}]}
        )
        print("🤖 Agent:", result)
