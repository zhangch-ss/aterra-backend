# 贡献指南

感谢你对本项目的兴趣！我们欢迎任何形式的贡献：Issue、PR、文档、测试、示例等。

## 开发环境

1. 安装依赖
   - Poetry：`poetry install`
   - 或使用 pip：`poetry export -f requirements.txt --output requirements.txt --without-hashes && pip install -r requirements.txt`
2. 复制环境变量：`cp backend/.env.example .env`（Docker Compose 使用根级 .env；后端本地开发使用 backend/.env）
3. 数据库迁移：`alembic upgrade head`
4. 运行：`uvicorn app.main:app --reload`

## 代码规范

- Lint：`ruff check .`
- Format：`black .`
- Type check：`mypy app tests`
- Test：`pytest -q`

建议安装预提交钩子：

```bash
pre-commit install
pre-commit run -a
```

## 提交规范

- 提交信息建议遵循 Conventional Commits（如 feat/fix/docs/test/chore/refactor 等）。
- PR 请描述：动机/变更点/兼容性/是否需要文档更新。
- 如涉及接口/数据库变更，请补充迁移与文档说明。

## 分支策略

- main：稳定分支
- feature/*：功能分支
- fix/*：缺陷修复

## 安全

请不要在 PR/Issue 中曝光密钥或敏感数据。如发现漏洞，参见 SECURITY.md 进行私下披露。
