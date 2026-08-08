"""
Agent注册中心。

负责管理所有业务 Agent 实例的生命周期和访问。它作为 Agent 的“服务注册表”，
提供了注册、查询、替换、删除等核心管理功能，并通过“冻结”机制来保护
运行时的注册表稳定性。

主要功能：
    1. 注册Agent：register()
    2. 获取Agent：get()
    3. 删除Agent：remove()
    4. 获取所有Agent名称：list_agents()
    5. 冻结注册中心：freeze()
    6. 获取所有Agent实例：get_agents()
    7. 动态运行时注册与激活：register_dynamic()、activate_dynamic()
    """

from app.agent.base import BaseAgent
from app.core.exceptions import AgentInitError, AgentNotFoundError


class AgentRegistry:
    """
    Agent注册中心。
    """

    def __init__(self):
        # 用于保存Agent实例的内部字典
        # key: Agent名称（str）
        # value: Agent对象（BaseAgent子类实例）
        self.agents: dict[
            str,
            BaseAgent
        ] = {}
        # 数据库控制面发布的Agent按租户隔离；代码注册Agent仍保留
        # 在全局字典中，作为显式部署的共享基础组件。
        self._tenant_agents: dict[
            tuple[str, str],
            BaseAgent,
        ] = {}
        # 冻结标志，为True时禁止修改注册表
        self._frozen = False


    def register(self, agent: BaseAgent) -> None:
        """
        注册Agent（标准方式）。

        用于在系统启动阶段或初始化流程中注册核心Agent。
        注册前会检查注册表是否已冻结以及是否存在同名Agent。

        Args:
            agent: 要注册的BaseAgent子类实例。

        Raises:
            AgentInitError: 当注册表已被冻结（_frozen=True）或存在同名Agent时抛出。
        """
        # 检查注册表是否已冻结
        if self._frozen:
            raise AgentInitError(
                agent.name,
                "Agent registry is frozen."
            )
        # 检查是否存在同名Agent
        if agent.name in self.agents:
            raise AgentInitError(
                agent.name,
                "Duplicate agent registration."
            )
        # 注册Agent
        self.agents[agent.name] = agent

    def register_dynamic(
        self,
        agent: BaseAgent,
        tenant_id: str | None = None,
    ) -> None:
        """
        动态注册Agent（运行时发现）。

        专用于控制面在运行时动态注册远程发现的Agent，适用于插件或动态扩展场景。
        此方法不检查冻结状态（如果被冻结也无法进行注册），仅检查名称唯一性。

        Args:
            agent: 要注册的BaseAgent子类实例。

        Raises:
            ValueError: 当存在同名Agent时抛出。

        注释:
            与 register() 的区别在于，此方法不受 _frozen 状态影响，
            目的是支持运行时的动态扩展。
        """
        # 检查名称唯一性
        key = (tenant_id, agent.name) if tenant_id else None
        if (
            (key is not None and key in self._tenant_agents)
            or (key is None and agent.name in self.agents)
        ):
            raise ValueError(
                f"Agent already exists: {agent.name}"
            ) # 抛出异常：名称冲突
        # 注册Agent
        if key is not None:
            self._tenant_agents[key] = agent
        else:
            self.agents[agent.name] = agent

    def activate_dynamic(
        self,
        agent: BaseAgent,
        tenant_id: str | None = None,
    ) -> None:
        """
        激活/更新运行时Agent快照。

        由Agent发布服务时调用，用于原子性地新增或替换运行时Agent快照。
        此方法为“无脑覆盖”模式，不检查冻结状态，也不检查名称是否存在。

        Args:
            agent: 要激活或更新的BaseAgent子类实例。

        注释:
            与 register_dynamic() 的区别在于，此方法允许覆盖同名Agent，
            通常用于服务发现场景下的状态刷新。
        """
        if tenant_id:
            self._tenant_agents[(tenant_id, agent.name)] = agent
        else:
            self.agents[agent.name] = agent

    def replace(self, agent: BaseAgent) -> None:
        """
        显式替换已注册Agent。

        用于在系统运行过程中，以新的Agent实例替换已存在的同名Agent。
        替换前会检查注册表是否冻结以及原Agent是否存在。

        Args:
            agent: 用于替换的新BaseAgent子类实例。

        Raises:
            AgentInitError: 当注册表已被冻结（_frozen=True）时抛出。
            AgentNotFoundError: 当不存在同名Agent时抛出，因为替换要求目标必须存在。
        """
        # 检查注册表是否已冻结
        if self._frozen:
            raise AgentInitError(
                agent.name,
                "Agent registry is frozen."
            )

        # 检查原Agent是否存在
        if agent.name not in self.agents:
            raise AgentNotFoundError(agent.name)

        # 替换Agent
        self.agents[agent.name] = agent

    def freeze(self) -> None:
        """
        冻结注册中心。

        将注册表设置为只读模式，防止运行期间被意外修改（如新增、删除、替换）。
        通常在系统启动引导（Bootstrap）阶段完成后调用，以保护核心配置的稳定性。
        """
        self._frozen = True

    @property
    def frozen(self) -> bool:
        """
        获取注册中心是否被冻结。
        """
        return self._frozen


    def get(
        self,
        name: str,
        tenant_id: str | None = None,
    ) -> BaseAgent:
        """
        根据名称获取Agent实例。
        Args:
            name: Agent名称
        Returns:
            BaseAgent: 对应的Agent实例。
        Raises:
            AgentNotFoundError: 当不存在指定名称的Agent时抛出。
        """
        agent = (
            self._tenant_agents.get((tenant_id, name))
            if tenant_id
            else None
        )
        if agent is None:
            agent = self.agents.get(name)

        if agent is None:
            raise AgentNotFoundError(name)

        return agent  # 返回Agent实例

    def exists(
        self,
        name: str,
        tenant_id: str | None = None,
    ) -> bool:
        """
        判断指定名称的Agent是否已注册。

        Args:
            name: Agent的名称。

        Returns:
            bool: 存在返回True，否则返回False。
        """
        return (
            (tenant_id, name) in self._tenant_agents
            if tenant_id
            else name in self.agents
        )


    def remove(
            self,
            name: str
    ) -> None:
        """
        删除指定名称的Agent。

        """
        if self._frozen:
            raise AgentInitError(
                name,
                "Agent registry is frozen."
            )

        if name not in self.agents:
            raise AgentNotFoundError(name)

        del self.agents[name]


    def list_agents(
            self,
            tenant_id: str | None = None,
    ) -> list[str]:
        """
        获取所有Agent名称。
        """
        names = set(self.agents)
        if tenant_id:
            names.update(
                name
                for (tenant, name) in self._tenant_agents
                if tenant == tenant_id
            )
        else:
            names.update(
                name for _, name in self._tenant_agents
            )
        return sorted(names)
