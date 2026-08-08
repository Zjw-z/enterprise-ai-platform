# 企业级 AI 平台管理端

本目录是平台统一管理端和业务模块入口，采用 React、TypeScript 和 vinext。

已实现：

- 用户登录、访问令牌和动态菜单；
- 工作台、用户、角色、菜单与操作日志；
- Agent、模型、Prompt、Tool、Workflow 资产视图；
- Runtime 任务列表、事件和 Trace 详情；
- Tool / Workflow 审批中心；
- 单 Agent 天气助手业务页面。

## 本地运行

先在项目根目录启动后端：

```powershell
python run.py
```

再启动前端：

```powershell
cd web
npm install
npm run dev
```

默认 API 地址为 `http://127.0.0.1:8000`。如需修改：

```powershell
$env:NEXT_PUBLIC_API_BASE_URL="https://api.example.com"
npm run dev
```

部署时可通过 `NEXT_PUBLIC_SITE_URL` 设置管理端的公开地址，用于生成分享
链接元数据。前端不再依赖 Sites、Cloudflare Worker、D1 或 Wrangler。

生产构建：

```powershell
npm run build
```

生产环境还需同步修改 `config.production.yaml` 中的
`system_frontend_origins`，后端权限校验始终独立于前端菜单显示。
