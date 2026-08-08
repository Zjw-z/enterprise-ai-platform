# 推理服务与异步 Worker 部署指南

## 目标部署形态

生产环境建议拆为六个独立进程：

1. 主 API：运行 Runtime、Agent、系统管理和业务 API；
2. 推理服务：独立加载 BGE-M3 与 bge-reranker-large；
3. Vector Worker：消费 PostgreSQL Outbox 并写入 Milvus。
4. Workflow Worker：领取并执行持久化工作流任务。
5. Knowledge Worker：消费文档解析租约，执行MinerU、质量检测和切块。
6. Maintenance Worker：按保留策略清理终态运行数据。

这样可以让 GPU 推理、HTTP 流量、异步索引和长工作流分别扩缩容。当前单体模式仍然保留，
测试环境无需拆分。

## 启动

```powershell
docker build -f Dockerfile -t eap-api .
docker build -f Dockerfile.inference -t eap-inference .
docker build -f Dockerfile.worker -t eap-vector-worker .
docker build -f Dockerfile.workflow-worker -t eap-workflow-worker .
docker build -f Dockerfile.knowledge-worker -t eap-knowledge-worker .
docker build -f Dockerfile.maintenance-worker -t eap-maintenance-worker .
```

推理服务默认监听 `8100`。设置 `EAP_INFERENCE_API_KEY` 后，请求必须携带
`Authorization: Bearer <key>`。

生产主 API 配置远程模型：

```yaml
embedding_models:
  bge-m3:
    provider: platform_http
    model: bge-m3
    endpoint: http://eap-inference:8100
    api_key_env: EAP_INFERENCE_API_KEY
    dimensions: 1024
    timeout_seconds: 60

rerank_models:
  bge-reranker-large:
    provider: platform_http
    model: bge-reranker-large
    endpoint: http://eap-inference:8100
    api_key_env: EAP_INFERENCE_API_KEY
    timeout_seconds: 60
```

推理容器自身使用本地 `sentence_transformers` 和 `cross_encoder` Profile。
不要让推理服务也配置为 `platform_http`，否则会形成递归调用。

主 API 的 `vector_outbox_worker_enabled` 在生产模板中为 `false`；
独立 Worker 入口会显式启用它。多个 Worker 可利用数据库领取机制并行消费。

## Workflow Worker

API 进程保持：

```yaml
workflow_worker_enabled: false
```

独立镜像入口为 `workflow_worker.py`，它会启用 Workflow Worker，并复用与 API 相同的
PostgreSQL、Agent 包和 Workflow 包配置。部署前必须执行：

```powershell
python -m alembic upgrade head
```

可以水平扩展多个 Workflow Worker。数据库租约、心跳和 fencing token 会协调任务归属；
不要为不同 Worker 配置不同的 PostgreSQL 或不同版本的 Agent/Workflow 包。滚动发布时，
先部署数据库迁移，再部署 Worker，最后部署 API。

## Knowledge 与 Maintenance Worker

生产 API 保持：

```yaml
knowledge_ingestion_worker_enabled: false
retention_worker_enabled: false
```

`knowledge_worker.py` 使用PostgreSQL租约处理文档，宕机后任务可被其他实例恢复；
`maintenance_worker.py` 分批清理过期Task、Trace、Audit、LLM Usage与完成Outbox。
两者都可独立扩缩容，但Maintenance通常只部署一个副本。
