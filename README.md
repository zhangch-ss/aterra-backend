# ATERRA: Autonomous Task Exploration, Reasoning and Response Agents for Geospatial Intelligence

ATERRA 面向地理空间智能（Geospatial Intelligence, GI）的智能体运行时：以“智能体”为核心，将模型、工具与知识作为可组合能力，支持地理数据的自动探索、推理与响应（Exploration → Reasoning → Response）。

当前项目仍处于早期阶段（Alpha），地理相关能力尚不完善；我们将持续迭代完善工具集成、智能体范式与基础设施，欢迎反馈与共建。

ATERRA 以“智能体（Agent）”为中心，提供面向生产的智能体运行时：
- 多类型 Agent（deepagent/Plan-Act 等）统一编排与事件流（SSE）
- 工具（Tools）自动扫描、注册、热更新，按需动态加载
- 知识增强（RAG）：文档入库、切分、向量化、Milvus 检索
- 用户级模型凭据与多云厂商适配（OpenAI / Azure OpenAI 等）
- 标准化 API（REST + SSE），可直接对接前端/工作流平台

核心目标：以“智能体”为中心组织应用，把模型、工具与知识作为能力插件进行组合与治理。

提示：体系结构的 Mermaid 图已收录至 docs/，见 docs/architecture.md。

## 地理智能体（Geospatial Intelligence Agents）

将地理数据处理（影像下载、地形分析、气候统计等）封装为可编排的“工具”，由智能体在规划-执行-反思的范式下按需调用，并与 RAG 结合以形成“数据→洞察”的端到端流程。

当前能力（Alpha，示例工具见 app/core/tool/tools/gee/gee.py）：
- GEE 集成与凭据管理：支持服务账号 JSON 或本机默认凭据
  - 卫星影像下载：gee_get_satellite_imagery（Sentinel‑2/Landsat‑8，按时间/区域/云量过滤，按波段导出 GeoTIFF 到 images/）
  - DEM 下载：gee_get_dem（SRTM/NASADEM，导出 GeoTIFF 到 dems/）
  - 气候数据提取：gee_get_climate（ERA5‑Land，变量映射，GeoTIFF 或 CSV 输出到 climate/）
- 工具治理与可观测性：标准化错误码/超时、调用日志与简单指标

路线图（精简版，2026‑03 → 2026‑07）：
- 2026‑03：
  - 工具集成基础：HTTP/REST Tool 适配层（鉴权/重试/限流/入参校验），工具 Schema 统一；
  - MCP 基础：MCP 客户端管道（注册/发现/调用/超时/错误码）及示例接入；
  - GEE 工具加固：超时/错误码标准化，结果可选上传 MinIO（统一前缀）。
- 2026‑04：
  - 地理工具扩展（优先 API，后续 MCP）：STAC/EO 数据发现、地理编码、栅格裁剪/拼接/重投影、Zonal Statistics；
  - Skills 能力（v0）：可复用的工具+提示词+权限组合，Agent 可绑定多个 Skill；
  - Planner‑Executor‑Reflect（PER）范式增强，TaskGraph/DAG 编排雏形。
- 2026‑05：
  - 智能体范式深化：Multi‑Agent（Supervisor/Worker）、RetrieverAgent（地理 RAG 专用）；
  - Skills 市场化形态与评测：版本、启停、基准输入/输出与质量指标；
  - 基础设施：Milvus/pgvector 基线与可观测性（OTel/Prom/Grafana）、权限与配额细化。
- 2026‑06 ~ 07：
  - 数据服务化：COG/STAC 元数据生产与托管，瓦片服务（如 TiTiler）集成；
  - 异步任务/队列与长任务状态机；压测与容量规划；v0.1 发布。

## 快速开始（Docker Compose）

```bash
# 1) 在仓库根创建 .env
cp backend/.env.example backend/.env

# 2) 构建基础镜像
docker build -f backend/docker/Dockerfile.base -t project-base:latest .

# 3) 构建应用镜像
docker build -f backend/docker/Dockerfile.runtime -t project-app:latest .

# 4) 启动依赖与后端（Postgres/Redis/MinIO/Caddy/Backend）
docker compose -f infra/docker-compose.yml up -d

# 5) 如需向量库 Milvus（可选）
docker compose -f infra/milvus/docker-compose.yml up -d
```

环境变量要点：
- 根 .env 提供 DATABASE_*/REDIS_*/MINIO_*/BACKEND_CORS_ORIGINS/SECRET_KEY/ENCRYPT_KEY 等
- BACKEND_CORS_ORIGINS 需为 JSON 列表字符串，例如：
  `BACKEND_CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000"]`

## 核心概念

- Agent（智能体）
  - 可执行实体，绑定“模型 + 工具 + 知识 + 子智能体”等能力
  - 内置类型：
    - deep_agent：偏链式/总结/对话等通用任务
    - plan_act：具备“规划-执行-反思”的工具调用能力
  - 运行时由 AgentOrchestrator 统一消费事件并输出 SSE

- Tool（工具）
  - 基于 LangChain BaseTool/StructuredTool 的可执行能力
  - 从 app/core/tool/tools/* 自动扫描；支持热更新（TOOL_WATCHER_ENABLE）
  - 工具元数据与运行参数落库；敏感字段支持遮罩与凭据专库

- Knowledge（知识/RAG）
  - 文档对象存储（MinIO）+ 切分（text_splitter）+ 嵌入（OpenAI/Azure）+ 检索（Milvus）
  - 在 Agent 中作为“检索器”参与答案生成

- Model（模型）
  - 支持用户级 Provider 凭据与全局回退；通过 llm_factory 动态构造 SDK 客户端
  - Embeddings 工厂按用户/提供商创建向量模型

## 典型流程

1) 创建一个 Agent（绑定模型、工具、知识）
2) 创建会话（Chat Session）
3) 发送消息，通过 SSE 获取 token/工具调用/最终结果

## API 快速示例

- 获取访问令牌（OAuth2 密码，简化示例）：
  POST /api/v1/auth/login/access-token

- 列出我的智能体
```bash
curl -H "Authorization: Bearer <ACCESS_TOKEN>" \
  http://localhost:8000/api/v1/agents
```

- 创建智能体（简化示例）
```bash
curl -X POST -H "Authorization: Bearer <ACCESS_TOKEN>" -H "Content-Type: application/json" \
  -d '{
        "name": "My Planner",
        "desc": "会规划与执行的助手",
        "type": "plan_act",
        "scene": "general",
        "model_id": "<model-id>",
        "tool_ids": ["<tool-id-1>", "<tool-id-2>"]
      }' \
  http://localhost:8000/api/v1/agents
```

- 创建会话
```bash
curl -X POST -H "Authorization: Bearer <ACCESS_TOKEN>" \
  http://localhost:8000/api/v1/chat/sessions
```

- 智能体对话（SSE 流式）
```bash
curl -N -X POST -H "Authorization: Bearer <ACCESS_TOKEN>" -H "Content-Type: application/json" \
  -d '{
        "query": "帮我规划一次周末徒步，并估算时间",
        "agent_id": "<agent-id>",
        "session_id": "<session-id>",
        "config": {
          "mode": "plan_act",            
          "persist_history": true,        
          "ephemeral": false              
        }
      }' \
  http://localhost:8000/api/v1/chat/completions/stream
```
返回的 SSE 事件包含：
- token：模型增量文本
- tool：工具执行起止状态
- tool_msg：工具返回内容（含结构化 JSON 时会透传）
- 最后一帧 final=true 提供耗时与模型信息

- 工具系统运维
```bash
# 查看已加载工具名
curl http://localhost:8000/api/v1/tools/loaded

# 查看扫描错误
curl http://localhost:8000/api/v1/tools/errors

# 同步扫描到的工具到数据库（基于 module+function 唯一）
curl -X POST http://localhost:8000/api/v1/tools/sync

# 查看指定工具的入参 Schema（含 secure 元数据）
curl http://localhost:8000/api/v1/tools/schema/name/<tool-name>
```

## 文档站（MkDocs）与架构图

项目提供 MkDocs 文档。Mermaid 架构图见：docs/architecture.md。

本地预览文档：

```bash
pip install mkdocs mkdocs-material
mkdocs serve
# 打开 http://127.0.0.1:8000 预览
```

## 本地开发（Poetry 推荐）

```bash
cd backend
poetry install
cp .env.example .env

# 数据库迁移与初始化
poetry run alembic upgrade head

# 启动服务
poetry run uvicorn app.main:app --reload --port 8000

# 运行测试
poetry run pytest -q --maxfail=1 --disable-warnings
```

## 安全与生产最佳实践

- 请不要将任何密钥/密码/令牌提交至仓库；使用环境变量或秘密管理服务
- 生产环境务必替换 `SECRET_KEY` / `ENCRYPT_KEY` 等默认示例值
- 访问令牌校验 + Redis 黑名单撤销；Provider 凭据加密存储
- 如发现安全问题，请参见 `SECURITY.md` 进行私下披露

## 贡献与许可

- 欢迎 Issue/PR！请先阅读 CONTRIBUTING.md 与 CODE_OF_CONDUCT.md
- 变更记录：CHANGELOG.md
- 许可证：MIT（见 LICENSE）
