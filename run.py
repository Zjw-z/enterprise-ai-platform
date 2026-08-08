"""
项目启动入口

整个 AI 平台只有一个启动入口。

职责：

1. 初始化平台
2. 加载配置
3. 初始化日志
4. 初始化容器
5. 初始化 Runtime
6. 创建 FastAPI
7. 启动 Uvicorn

注意：

run.py 不负责业务逻辑。

所有初始化工作均由 Bootstrap 完成。
"""

from app.bootstrap import Bootstrap


def main() -> None:
    """
    平台启动入口
    """
    # Agent、Prompt 与本地 Tool 均由配置和 agents 文件包自动发现。
    # 新增业务资源时不再修改平台启动入口。
    bootstrap = Bootstrap()
    bootstrap.run()


if __name__ == "__main__":
    main()