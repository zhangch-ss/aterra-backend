# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [0.1.0] - 2026-01-24

### Added
- README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, LICENSE 基础开源文档
- GitHub Actions: CI (ruff/black/mypy/pytest/bandit/pip-audit) 与 Docker 构建 workflow
- Issue/PR 模板（bug_report、feature_request、PULL_REQUEST_TEMPLATE）
- 健康检查端点 /healthz, /readyz
- 统一日志工具并在 app/main.py、ModelService 中接入
- pytest.ini（覆盖率阈值 70%）

### Changed
- Dockerfile 多阶段构建与 .dockerignore 优化镜像上下文
- README 增加快速开始、配置说明、Docker 使用等

### Security
- 引入 bandit 与 pip-audit 静态安全扫描
- 提供 SECURITY.md（需维护者补充安全联络邮箱）
