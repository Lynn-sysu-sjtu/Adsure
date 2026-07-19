# Adsure API Service

统一审核编排服务骨架。当前接收标准审核请求，调用规则引擎，并使用 Mock RAG 或 HTTP RAG 客户端补充相关案例。

## Endpoints

```text
GET  /health
POST /api/v1/audits
```

## Environment

```text
RULE_ENGINE_URL=http://127.0.0.1:8504
ADSURE_API_KEY=
ADSURE_RAG_BACKEND=mock
RAG_SERVICE_URL=http://127.0.0.1:8505
RAG_SERVICE_API_KEY=
```

`ADSURE_RAG_BACKEND=mock` 时不会访问真实 RAG；设置为 `http` 后调用 `RAG_SERVICE_URL/search`。

## Run

在仓库根目录执行：

```powershell
py -3 -m uvicorn api_service.app:app --host 127.0.0.1 --port 8506
```

第一版建议只在服务器内网或 Nginx 后运行，不直接暴露 8506 端口。

## Test

```powershell
py -3 -m unittest api_service.tests.test_audit_orchestrator api_service.tests.test_app -v
```

RAG 是增强链路。RAG 超时、异常或无有效返回时，规则引擎结果仍正常返回，`related_cases=[]`。
