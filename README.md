# Aterra Agents — 可插拔智能体后端

Aterra Agents 以“智能体（Agent）”为中心，提供面向生产的智能体运行时：
- 多类型 Agent（深度链式/Plan-Act 等）统一编排与事件流（SSE）
- 工具（Tools）自动扫描、注册、热更新，按需动态加载
- 知识增强（RAG）：文档入库、切分、向量化、Milvus 检索
- 用户级模型凭据与多云厂商适配（OpenAI / Azure OpenAI 等）
- 标准化 API（REST + SSE），可直接对接前端/工作流平台

核心目标：以“智能体”为中心组织应用，把模型、工具与知识作为能力插件进行组合与治理。

提示：体系结构的 Mermaid 图已收录至 docs/，见 docs/architecture.md。

## 快速开始（Docker Compose）

```bash
# 1) 在仓库根创建 .env
cp .env.example .env

# 2) 构建应用镜像（生产近似运行环境）
docker build -f backend/docker/Dockerfile.runtime -t project-app:latest .

# 3) 启动依赖与后端（Postgres/Redis/MinIO/Caddy/Backend）
docker compose -f infra/docker-compose.yml up -d

# 4) 如需向量库 Milvus（可选）
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

## Agent 字段说明

基于 app/schemas/agent.py，常用入参/出参字段如下（节选）：

AgentCreate（创建）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| name | str | 是 | 智能体名称 |
| desc | str | 否 | 描述 |
| type | str | 是 | 智能体类型，例如 `plan_act` 或 `deep_agent` |
| scene | str | 是 | 使用场景标签，例如 `general`、`analysis` |
| model_id | str | 否 | 绑定的模型 ID（从 /api/v1/models 获取） |
| invoke_config | InvokeConfig | 否 | 运行时调用配置（名称/描述/参数） |
| parent_agent_id | str | 否 | 父智能体 ID（用于子智能体编排） |
| tool_ids | list[str] | 否 | 绑定工具 ID 列表 |
| knowledge_ids | list[str] | 否 | 绑定知识库 ID 列表 |
| system_prompt | str | 否 | 系统提示词（覆盖/补充系统默认） |

InvokeConfig：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| name | str | 是 | 调用名（用于内部标识/链路跟踪） |
| description | str | 否 | 调用描述 |
| parameters | dict | 否 | 透传给具体实现的配置参数 |

AgentUpdate（更新）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| name | str | 否 | 名称 |
| desc | str | 否 | 描述 |
| invoke_config | InvokeConfig | 否 | 调用配置 |
| model_id | str | 否 | 模型 ID |
| parent_agent_id | str | 否 | 父智能体 |
| tool_ids | list[str] | 否 | 工具列表（覆盖式更新） |
| knowledge_ids | list[str] | 否 | 知识库列表（覆盖式更新） |

AgentRead/AgentOut（查询返回，节选）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 智能体唯一标识 |
| user_id | str | 所属用户 |
| created_at/updated_at | datetime | 创建/更新时间 |
| model_id | str | 绑定模型 ID |
| tools/knowledges | list | 绑定的工具/知识卡片 |
| subagents/parent_agent | list/dict | 子智能体/父智能体 |
| model | ModelBase | 绑定的模型信息（简） |

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

提示：`tests/agent/test_plan_act_agent.py` 默认使用 stub；若需真实调用 Azure OpenAI，请设置 USE_OPENAI/OPENAI_API_KEY/AZURE_OPENAI_ENDPOINT。

## 安全与生产最佳实践

- 请不要将任何密钥/密码/令牌提交至仓库；使用环境变量或秘密管理服务
- 生产环境务必替换 `SECRET_KEY` / `ENCRYPT_KEY` 等默认示例值
- 访问令牌校验 + Redis 黑名单撤销；Provider 凭据加密存储
- 如发现安全问题，请参见 `SECURITY.md` 进行私下披露

## 贡献与许可

- 欢迎 Issue/PR！请先阅读 CONTRIBUTING.md 与 CODE_OF_CONDUCT.md
- 变更记录：CHANGELOG.md
- 许可证：MIT（见 LICENSE）
