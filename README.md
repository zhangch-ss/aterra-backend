# FastAPI + SQLModel + Alembic (Async)

一个生产可用的后端起点工程，基于 FastAPI、SQLModel（SQLAlchemy 2.x）、Alembic 与异步栈，集成 RAG/Agent 能力、工具扫描注册、对象存储（MinIO）、向量库（Milvus）等常用组件。适合作为开源模板与二次开发基础。

特性概览：
- Python 3.11、FastAPI、SQLModel/SQLAlchemy 2.x、Alembic 迁移
- 可选组件：Redis、MinIO、Milvus
- 健康检查：`/healthz`, `/readyz`
- 代码质量：ruff、black、mypy、pytest（覆盖率）
- 安全扫描：bandit、pip-audit
- Docker 多阶段构建；infra/docker-compose 统一编排

## 快速开始（Docker Compose）

仓库已提供统一编排在 `infra/docker-compose.yml`。

```bash
# 1) 在仓库根创建 .env
cp .env.example .env

# 2) 构建应用镜像（runtime 变体，更接近生产运行环境）
docker build -f backend/docker/Dockerfile.runtime -t project-app:latest .

# 3) 启动依赖与后端（Postgres/Redis/MinIO/Caddy/Backend）
docker-compose -f infra/docker-compose.yml up -d

# 4) 如需启动/更新 Milvus（独立栈，可选）
docker-compose -f infra/milvus/docker-compose.yml up -d
```

### 环境变量与 Compose 说明

本项目使用两个层面的环境配置：

- 根目录 .env（运行时环境）
  - 通过 `env_file: "../.env"` 注入到容器内部，供 FastAPI、Postgres、Redis、MinIO、Milvus 等服务在运行时读取。
  - 例如：`DATABASE_*`、`REDIS_*`、`OPENAI_*`、`MINIO_*`、`SECRET_KEY` 等。
  - 注意：`BACKEND_CORS_ORIGINS` 需为 JSON 列表字符串，例如：
    
    ```
    BACKEND_CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000"]
    ```
    
    否则 Pydantic 会报错（期望 list 类型）。

- infra/.env（Compose 变量插值）
  - 用于替换 `infra/docker-compose.yml` 中的占位符 `${VAR}`（例如 Caddy 的 `EXT_ENDPOINT1`、`LOCAL_1`、`LOCAL_2`）。
  - 这是编排层面的变量，不会作为容器内部环境变量自动注入（除非显式使用 `env_file`）。
  - 这些值应为“裸主机名”，不要包含 `http://` 或端口。例如：
    
    ```
    EXT_ENDPOINT1=stash.localhost
    LOCAL_1=api.localhost
    LOCAL_2=static.localhost
    ```
    
    若写成 URL（如 `http://stash.localhost:8080`），Caddy 配置会不生效或报错。

#### 推荐运行方式

```bash
# 1) 在仓库根创建 .env 并填写运行时变量
cp .env.example .env
# 建议将 BACKEND_CORS_ORIGINS 设置为 JSON 列表字符串

# 2) 构建应用镜像（生产近似环境）
docker build -f backend/docker/Dockerfile.runtime -t project-app:latest .

# 3) 准备 infra/.env（仅用于 Compose 插值，专注于 Caddy 等编排层变量）
# 示例：EXT_ENDPOINT1/LOCAL_1/LOCAL_2 使用裸主机名

# 4) 启动编排
# 方式 A：将 infra/.env 与 compose 同目录放置（Compose 会自动读取）
docker compose -f infra/docker-compose.yml up -d

# 方式 B：显式指定 env-file（等价）
docker compose --env-file infra/.env -f infra/docker-compose.yml up -d

# 5) 如需单文件管理
# 也可以把占位变量放回根 .env，并用 --env-file ../.env 执行 Compose，但要确保值为主机名而非 URL。
```

#### 常见问题

- 数据库容器 unhealthy：通常是根 `.env` 未设置 `DATABASE_USER/DATABASE_PASSWORD/DATABASE_NAME`，或健康检查使用的用户为空。补齐后重新 `docker compose up -d`。
- 后端启动报 `BACKEND_CORS_ORIGINS` 格式错误：请使用 JSON 列表字符串形式，如示例所示。
- Caddy 启动但反代不生效：检查 `infra/.env` 的 `EXT_ENDPOINT1/LOCAL_1/LOCAL_2` 是否为裸主机名，且与 `infra/caddy/Caddyfile` 中的 `domain` 一致。

## 本地开发（Poetry 推荐）

```bash
cd backend
poetry install
cp .env.example .env

# 数据库迁移与初始化
poetry run alembic upgrade head
poetry run python -m app.initial_data  # 可选

# 启动服务
poetry run uvicorn app.main:app --reload --port 8000

# 运行测试
poetry run pytest -q --maxfail=1 --disable-warnings
```

提示：`tests/agent/test_plan_act_agent.py` 默认使用 stub；若需真实调用 Azure OpenAI，请设置：
- `USE_OPENAI=true`
- `OPENAI_API_KEY=...`
- `AZURE_OPENAI_ENDPOINT=...`

## 目录结构（摘录）

```
.
├─ README.md                 # 项目总览（你正在看的）
├─ backend/                  # 后端应用代码与模块级文档
│  ├─ app/                   # 应用入口、路由、核心模块、CRUD、模型/Schema、服务等
│  ├─ alembic/               # 数据库迁移
│  ├─ docker/                # Dockerfile（多阶段）
│  ├─ tests/                 # 测试用例
│  └─ README.md              # 模块级使用说明（开发细节）
├─ infra/                    # 基础设施与编排
│  ├─ docker-compose.yml     # 后端与依赖服务统一编排
│  ├─ caddy/Caddyfile        # 反向代理与静态服务（唯一来源）
│  └─ milvus/docker-compose.yml
├─ docs/                     # 文档站（MkDocs）
├─ .github/                  # CI 工作流与 Issue/PR 模板、Dependabot 等
└─ LICENSE / CONTRIBUTING.md / CODE_OF_CONDUCT.md / SECURITY.md / CHANGELOG.md
```

说明：
- 根目录下历史遗留的 `caddy/` 与 `static/` 已清理；请以 `infra/caddy` 与 `backend/static` 为准。
- Milvus 的二进制数据目录已通过 `.gitignore` 忽略，不应提交至仓库。

## 文档站（MkDocs）

本仓库包含基础 MkDocs 配置（Material 主题）。本地预览：


```bash
pip install mkdocs mkdocs-material
mkdocs serve
# 打开 http://127.0.0.1:8000 预览文档
```

## 安全与生产最佳实践

- 请不要将任何密钥/密码/令牌提交至仓库；使用环境变量或秘密管理服务
- 生产环境务必替换 `SECRET_KEY` / `ENCRYPT_KEY` 等默认示例值
- 定期运行 `pip-audit` / `bandit` 进行安全检查
- 如发现安全问题，请参见 `SECURITY.md` 进行私下披露

## 贡献与行为准则

欢迎 Issue/PR！请先阅读：
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [SECURITY.md](SECURITY.md)

变更记录请查阅：
- [CHANGELOG.md](CHANGELOG.md)

## 许可协议

本项目使用 MIT 许可证，详见 [LICENSE](LICENSE)。
