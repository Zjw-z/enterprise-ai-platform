# Enterprise AI Platform 环境版本说明

本文档记录项目的实际验证环境、项目声明的版本范围，以及团队推荐的统一
开发环境。更新时间：2026-07-26。

## 1. 推荐统一环境

| 组件 | 推荐版本 | 说明 |
|---|---:|---|
| 操作系统 | Windows 11 / Linux | 当前开发机为 Windows 10.0.26300 |
| Python | 3.12.x | 与 `pyproject.toml`、Ruff `py312` 目标一致 |
| Conda 环境 | `enterprise-ai` | 建议所有后端开发和测试统一使用 |
| Node.js | 24.x LTS | 前端最低要求为 `>=22.13.0` |
| npm | 11.x | 与当前 Node.js 环境配套 |
| Git | 2.45+ | 用于源码管理 |
| SQLite | 3.x | 本地开发、测试和单机运行 |
| PostgreSQL | 16+ | 推荐生产数据库 |

推荐的后端解释器路径：

```text
D:\Tool\miniconda3\envs\enterprise-ai\python.exe
```

推荐的前端运行时路径：

```text
D:\Java\nodejs\node.exe
```

## 2. 本次实际验证环境

| 组件 | 实际版本 |
|---|---:|
| Python | 3.13.11 |
| pip | 25.3 |
| Node.js | 24.12.0 |
| npm | 11.6.2 |
| Git | 2.45.1.windows.1 |
| WSL | 2.6.3.0 |
| pytest | 9.1.1 |
| coverage | 7.15.2 |
| Ruff | 0.16.0 |

本次后端测试实际使用：

```text
D:\Tool\miniconda3\python.exe
```

本次验证结果：

- 后端测试：137 项通过；
- 后端覆盖率：78%；
- Ruff：通过；
- Python 编译：通过；
- 前端 ESLint：通过；
- 前端测试：2 项通过；
- 前端生产构建：通过。

## 3. Python 核心依赖

项目要求以 `pyproject.toml` 为准：

| 依赖 | 项目要求 | 实际测试环境 |
|---|---:|---:|
| Python | `>=3.12` | 3.13.11 |
| FastAPI | `>=0.118,<1` | 0.110.0 |
| Pydantic | `>=2.11,<3` | 2.12.4 |
| SQLAlchemy | `>=2.0,<3` | 2.0.49 |
| Alembic | `>=1.14,<2` | 1.18.5 |
| aiosqlite | `>=0.20,<1` | 0.22.1 |
| OpenAI SDK | `>=1.99,<2` | 2.37.0 |
| Uvicorn | `>=0.37,<1` | 0.28.0 |
| PyYAML | `>=6,<7` | 6.0.3 |
| httpx（开发） | `>=0.27` | 0.28.1 |
| pytest（开发） | `>=8.3` | 9.1.1 |
| coverage（开发） | `>=7.6` | 7.15.2 |
| Ruff（开发） | `>=0.12` | 0.16.0 |

注意：实际测试环境中的 FastAPI、OpenAI SDK 和 Uvicorn 与项目声明范围
不一致。虽然当前测试通过，但不能把它作为可重复部署环境。后续应在
`enterprise-ai` 环境中重新安装项目声明依赖并再次执行全量测试。

## 4. 前端核心依赖

前端精确版本由 `web/package-lock.json` 锁定。

| 依赖 | 版本 |
|---|---:|
| React | 19.2.6 |
| React DOM | 19.2.6 |
| Next.js | 16.2.6 |
| TypeScript | 5.9.3 |
| vinext | 0.0.50 |
| Vite | 8.0.13 |
| ESLint | 9.39.4 |

## 5. 创建统一后端环境

```powershell
conda create -n enterprise-ai python=3.12 -y
conda activate enterprise-ai
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

如果只做本地 SQLite 开发：

```powershell
python -m pip install -e ".[dev]"
```

验证依赖一致性：

```powershell
python -m pip check
python -m pytest
python -m coverage run -m pytest
python -m coverage report
python -m ruff check .
```

## 6. 安装和验证前端

```powershell
cd web
npm ci
npm run lint
npm test
```

`npm ci` 会严格按照 `package-lock.json` 安装，不应使用全局安装的前端
依赖替代项目依赖。

## 7. 运行环境配置

环境版本和业务配置是两件事：

- `ENVIRONMENT.md`：记录运行时和依赖版本；
- `config.yaml`：只选择 `test` 或 `production`；
- `config.test.yaml`：本地测试配置，不提交 Git；
- `config.production.yaml`：生产配置模板；
- 环境变量：保存生产密钥、数据库凭据和模型 API Key。

常用密钥环境变量：

```text
DASHSCOPE_API_KEY
EAP_SYSTEM_JWT_SECRET
EAP_SYSTEM_ADMIN_PASSWORD
EAP_JWT_SECRET
EAP_ADMIN_API_KEY
```

任何真实密钥都不应写入本文件、`pyproject.toml`、前端源码或
`web/package.json`。
