#!/usr/bin/env python
"""
LangChain 核心模块
用于基于 LangChain 1.0 的智能体系统

优化后架构：
- AgentExecutor: 统一的智能体执行器
- StreamProcessor: 统一的流处理器
- AgentRuntimeConfig: 配置模型
"""

from service_agent_manage.langchain_core.agent_executor import AgentExecutor
from service_agent_manage.langchain_core.config_models import AgentRuntimeConfig
from service_agent_manage.langchain_core.stream_processor import StreamProcessor

__version__ = "2.0.0"

__all__ = [
    "AgentExecutor",
    "StreamProcessor",
    "AgentRuntimeConfig",
]

