#!/usr/bin/env python
"""
配置模型
统一管理智能体运行时的所有配置
"""

from dataclasses import dataclass, field

from langchain_core.tools import BaseTool


@dataclass
class AgentRuntimeConfig:
    """
    智能体运行时配置

    统一管理所有配置，避免配置分散在多个类中
    """

    # === 基础信息 ===
    agent_id: str
    conversation_id: str
    account_id: str
    team_code: str

    # === 智能体配置 ===
    agent_config: dict
    model_params: dict
    prompt: str

    # === 运行时选项 ===
    enable_think: bool = False
    enable_citation: bool = False
    enable_tool :bool = False
    history_count: int = 0

    # === 工具配置 ===
    tools: list[BaseTool] = field(default_factory=list)
    kb_sources: list = field(default_factory=list)

    # === Agent 配置 ===
    recursion_limit: int = 15
    timeout: int = 300

    def get_agent_config(self, talk_id: str) -> dict:
        """
        获取 Agent 执行配置

        Args:
            talk_id: 对话 ID

        Returns:
            配置字典
        """
        return {
            "configurable": {"thread_id": talk_id},
            "recursion_limit": self.recursion_limit,
        }
