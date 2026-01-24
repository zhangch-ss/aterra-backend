该目录包含 Milvus 本地开发/测试的独立编排（docker-compose.yml）。

重要：不要将实际运行产生的持久化数据提交到仓库！
- volumes/* 路径已在仓库根 .gitignore 中忽略（infra/milvus/volumes/）。
- 如需清理本地数据，请手动删除该目录或使用 `docker-compose down -v`。

使用方法：
```bash
# 启动或更新 Milvus 独立栈（etcd/minio/milvus）
docker-compose -f infra/milvus/docker-compose.yml up -d

# 健康检查
curl -f http://localhost:9091/healthz
```
