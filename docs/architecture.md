---
title: 架构概览（Mermaid）
---

# 架构概览

下图展示了 Aterra Agents 的高层组件与数据流：

```mermaid
flowchart LR
  subgraph Client
    FE[Web / Workflow]
  end

  FE -- REST/SSE --> API[FastAPI /api/v1]

  subgraph Application[Application Layer]
    AR[Agent Registry]
    ORC[Agent Orchestrator (SSE)]
    TL[ToolLoader / SchemaExtractor]
    RAG[RAG Pipeline]
  end

  API --> AR
  AR --> ORC
  ORC -->|events: token/tool/tool_msg/final| FE
  AR -. bind .-> TL
  AR -. use .-> RAG

  subgraph Core[Core Services]
    SEC[Auth & Token (Redis Blacklist)]
    LLM[LLM Factory / Embeddings]
  end

  API --> SEC
  ORC --> LLM
  RAG --> LLM

  subgraph Storage[Storages]
    PG[(PostgreSQL)]
    MINIO[(MinIO)]
    MILVUS[(Milvus)]
    REDIS[(Redis)]
  end

  API <--> PG
  ORC <--> PG
  RAG <--> MINIO
  RAG <--> MILVUS
  SEC <--> REDIS

  subgraph Tools[Tools]
    T1[LangChain BaseTool]
    T2[StructuredTool]
  end
  TL --> T1
  TL --> T2
  ORC -->|invoke| Tools
```

要点：
- API 层统一接入（REST + SSE），AgentOrchestrator 负责事件编排与历史持久化
- AgentRegistry 选择具体 Agent 类型（deep_agent / plan_act 等）
- ToolLoader 动态扫描与加载工具；SchemaExtractor 提供入参契约
- RAG 管线管理文档、切分、嵌入与 Milvus 检索
- 核心存储：PostgreSQL（元数据与会话）、Redis（令牌撤销/缓存）、MinIO（对象）、Milvus（向量）
