#!/usr/bin/env python
"""
LangChain 工具模块

基于 LangChain 1.0 的 @tool 装饰器模式
支持函数式工具、MCP 集成和工具注册机制
"""

# 函数式工具创建函数（推荐使用）
# 向后兼容的类接口
from service_agent_manage.langchain_core.tools.http_tool import (
    HttpToolConfig,
    HttpToolWrapper,
    create_http_tool,
    create_http_tool_with_context,
)
from service_agent_manage.langchain_core.tools.knowledge_tool import (
    KnowledgeBaseConfig,
    KnowledgeRetrieverConfig,
    KnowledgeRetrieverTool,
    create_knowledge_tool,
)

# 工具中间件
from service_agent_manage.langchain_core.tools.middleware import (
    DEFAULT_TOOL_MIDDLEWARE,
    combine_error_handling_and_logging,
)

# 工具工厂和注册表
from service_agent_manage.langchain_core.tools.tool_factory import (
    ToolFactory,
    ToolRegistry,
)

__all__ = [
    # 函数式工具（推荐）
    "create_http_tool",
    "create_http_tool_with_context",
    "create_knowledge_tool",
    # 配置类
    "HttpToolConfig",
    "KnowledgeBaseConfig",
    "KnowledgeRetrieverConfig",
    # 工具工厂
    "ToolFactory",
    "ToolRegistry",
    # 中间件
    "DEFAULT_TOOL_MIDDLEWARE",
    "combine_error_handling_and_logging",
    "handle_tool_errors",
    "log_tool_execution",
    # 向后兼容
    "HttpToolWrapper",
    "KnowledgeRetrieverTool",
]
