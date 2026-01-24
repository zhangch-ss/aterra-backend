# 安全策略（Security Policy）

## 漏洞报告

如你发现本项目存在安全问题，请不要在公开 Issue 中披露。请通过以下方式私下报告：

- 发送邮件至：security@example.com（请替换为维护者实际邮箱）
- 标题包含：`[SECURITY]` 关键词
- 描述问题影响范围、复现方式、PoC（如有）

我们会尽快确认并跟进修复。感谢你的负责任披露！

## 支持版本

我们通常仅对默认分支（main）进行安全修复。如你使用的是旧版本，请考虑升级。

## 最佳实践

- 不要把任何密钥/密码/令牌提交至仓库
- 使用 .env 或秘密管理服务（如 GitHub Secrets、Vault）
- 生产环境务必替换 SECRET_KEY/ENCRYPT_KEY 等默认示例值
- 定期运行 `pip-audit` / `bandit` 进行安全检查
