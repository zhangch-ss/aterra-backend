# FastAPI + SQLModel + Alembic (Async) Backend

提示：项目总体介绍与快速开始请参阅仓库根级的 README.md。本文件专注于后端模块的开发与运行细节。

一个基于 FastAPI、SQLModel、Alembic 与异步栈的后端框架，集成了 RAG/Agent 能力、工具扫描注册、对象存储（MinIO）、向量库（Milvus）等常用组件。适合作为生产可用的起点工程。

- Python 3.11
- FastAPI + SQLModel（SQLAlchemy 2.x）
- Alembic 迁移
- Redis、MinIO、Milvus（可选）
- 健康检查 /healthz, /readyz
- CI：ruff/black/mypy/test/安全扫描
- Docker 多阶段构建

## 快速开始

### 1) 克隆与依赖安装

- 使用 Poetry（推荐）

```bash
poetry install
cp .env.example .env
```

- 使用 pip（CI 同款方式）

```bash
poetry export -f requirements.txt --output requirements.txt --without-hashes
pip install -r requirements.txt
```

### 2) 配置环境变量

复制 .env.example 到 .env，并按需修改。关键项：
- 数据库：DATABASE_*（Postgres）
- Redis：REDIS_*
- MinIO：MINIO_*
- CORS：BACKEND_CORS_ORIGINS（开发环境可设置为 http://localhost:3000）
- 生产环境务必显式设置 SECRET_KEY、ENCRYPT_KEY

### 3) 数据库迁移与初始化

```bash
alembic upgrade head
# 可选：初始化数据
python -m app.initial_data
```

### 4) 启动服务

```bash
uvicorn app.main:app --reload --port 8000
```

- OpenAPI 文档：/docs 或 /redoc
- OpenAPI schema：/api/v1/openapi.json
- 健康检查：/healthz, /readyz

## 使用 Docker

项目已提供统一的多阶段构建文件：backend/docker/Dockerfile（以及 runtime/base 变体）。

```bash
# 构建（可在中国大陆使用镜像：--build-arg USE_CN_MIRROR=true）
docker build -f backend/docker/Dockerfile -t fastapi-backend:dev .

# 运行（纯镜像方式，不包含依赖服务）
docker run --rm -it -p 8000:8000 --env-file .env fastapi-backend:dev
```

推荐使用统一编排：infra/docker-compose.yml

```bash
# 1) 在仓库根创建 .env（参考 backend/.env.example）
cp backend/.env.example .env

# 2) 构建应用镜像
docker build -f backend/docker/Dockerfile.runtime -t project-app:latest .

# 3) 启动依赖与后端（Postgres/Redis/MinIO/Caddy/Backend）
docker-compose -f infra/docker-compose.yml up -d

# 4) 如需启动/更新 Milvus（单独栈）
docker-compose -f infra/milvus/docker-compose.yml up -d
```

## 代码质量与提交规范

- Lint：ruff
- Format：black
- Type：mypy
- Test：pytest（已集成覆盖率）
- 预提交钩子：

```bash
pre-commit install
pre-commit run -a
```

## 运行测试

```bash
pytest -q --maxfail=1 --disable-warnings
```

注意：tests/agent/test_plan_act_agent.py 默认使用 stub，若需真实调用 Azure OpenAI，请设置：
- USE_OPENAI=true
- OPENAI_API_KEY=...
- AZURE_OPENAI_ENDPOINT=...

## 安全

- 请不要将实际密钥写入仓库。使用环境变量或秘密管理服务。
- 如发现安全问题，请参考 SECURITY.md 进行私下披露。

## 目录结构（摘录）

- app/main.py：应用入口，集成中间件与路由
- app/core/config.py：配置管理（Pydantic Settings）
- app/api/v1：API 路由与端点
- app/models / app/schemas：数据模型定义
- app/services：业务服务
- app/core/tool：Agent 工具框架
- alembic：数据库迁移
- tests：测试用例
- scripts/：运维/初始化脚本（例如 create-dbs.sql）
- static/：供 Caddy 直接服务的静态资源（已在 infra/docker-compose.yml 中挂载到 /code/static）
- infra/：基础设施与编排
  - docker-compose.yml：后端/依赖统一编排
  - caddy/Caddyfile：反向代理与静态服务配置
  - milvus/docker-compose.yml：Milvus 独立编排
  - scripts/restart.sh：一键重启脚本

说明：
- 旧版根目录的 docker-compose.yml / caddy/Caddyfile / restart.sh 已迁移至 infra/ 下；
- 根目录 static/ 已废弃，请使用 backend/static/；
- Milvus 的 volumes（二进制数据）不应提交到仓库，已在 .gitignore 中忽略。

## 许可协议

本项目使用 MIT 许可证，详见 LICENSE。

## 贡献

欢迎 Issue/PR！请先阅读 CONTRIBUTING.md 与 CODE_OF_CONDUCT.md。