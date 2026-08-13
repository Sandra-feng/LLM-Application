#!/usr/bin/env python
"""
HTTP 工具 - 基于 @tool 装饰器的函数式设计
将 HTTP 接口封装为 LangChain Tool
"""

import asyncio
from typing import Any, Optional

import aiohttp
from aiohttp import ClientError
from langchain.tools import ToolRuntime, tool
from loguru import logger
from pydantic import BaseModel, Field


class HttpToolConfig(BaseModel):
    """HTTP 工具配置"""

    tool_name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    tool_url: str = Field(..., description="工具 URL")
    tool_method: str = Field(default="POST", description="HTTP 方法")
    token: Optional[str] = Field(default=None, description="认证 Token")
    max_retries: int = Field(default=3, description="最大重试次数")
    retry_delay: float = Field(default=0.3, description="重试延迟（秒）")
    timeout: int = Field(default=3, description="超时时间（秒）")
    parameters_schema: dict = Field(default_factory=dict, description="参数模式")


async def _execute_http_request(
    params: dict[str, Any],
    config: HttpToolConfig,
) -> Any:
    """
    执行 HTTP 请求

    Args:
        params: 请求参数
        config: 工具配置

    Returns:
        请求结果
    """
    headers = {"Content-Type": "application/json"}
    if config.token:
        headers["token"] = config.token

    logger.info(f"调用 HTTP 工具: {config.tool_name} | URL: {config.tool_url}")

    for attempt in range(config.max_retries):
        try:
            logger.info(f"尝试调用: {config.tool_name}, 尝试 {attempt + 1}/{config.max_retries}")

            timeout_config = aiohttp.ClientTimeout(total=config.timeout)
            async with aiohttp.ClientSession(timeout=timeout_config) as session:
                async with session.request(
                    config.tool_method, config.tool_url, headers=headers, json=params
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"{config.tool_name} 返回: {result}")
                        return result
                    else:
                        error_msg = f"HTTP {response.status}"
                        logger.warning(f"工具调用失败: {error_msg}")
                        if attempt == config.max_retries - 1:
                            return {"error": error_msg, "status": response.status}

        except (TimeoutError, ClientError) as e:
            logger.warning(f"网络错误: {str(e)}, 尝试 {attempt + 1}/{config.max_retries}")
            if attempt < config.max_retries - 1:
                await asyncio.sleep(config.retry_delay)
            else:
                return {"error": f"超时: {str(e)}"}

        except Exception as e:
            logger.exception(f"调用异常: {str(e)}, 尝试 {attempt + 1}/{config.max_retries}")
            if attempt < config.max_retries - 1:
                await asyncio.sleep(config.retry_delay)
            else:
                return {"error": f"异常: {str(e)}"}

    return {"error": "达到最大重试次数"}


def create_http_tool(config: HttpToolConfig):
    """
    创建 HTTP 工具

    使用 @tool 装饰器动态创建工具函数

    Args:
        config: HTTP 工具配置

    Returns:
        LangChain Tool 实例

    Example:
        >>> config = HttpToolConfig(
        ...     tool_name="search_user",
        ...     description="搜索用户信息",
        ...     tool_url="https://api.example.com/search",
        ...     parameters_schema={"query": {"type": "string"}}
        ... )
        >>> http_tool = create_http_tool(config)
    """

    @tool(config.tool_name, description=config.description, args_schema=config.parameters_schema)
    async def http_tool(**kwargs: Any) -> Any:
        """
        HTTP 工具执行函数

        Args:
            **kwargs: 工具参数（由 LLM 生成）

        Returns:
            工具执行结果
        """
        return await _execute_http_request(params=kwargs, config=config)

    return http_tool


def create_http_tool_with_context(config: HttpToolConfig):
    """
    创建支持上下文注入的 HTTP 工具

    使用 ToolRuntime 访问运行时状态

    Args:
        config: HTTP 工具配置

    Returns:
        LangChain Tool 实例

    Example:
        >>> config = HttpToolConfig(
        ...     tool_name="create_order",
        ...     description="创建订单",
        ...     tool_url="https://api.example.com/orders"
        ... )
        >>> http_tool = create_http_tool_with_context(config)
    """

    @tool(name=config.tool_name, description=config.description)
    async def http_tool_with_context(runtime: ToolRuntime, **kwargs: Any) -> Any:
        """
        HTTP 工具执行函数（支持上下文注入）

        Args:
            runtime: LangChain ToolRuntime（自动注入，对 LLM 不可见）
            **kwargs: 工具参数（由 LLM 生成）

        Returns:
            工具执行结果
        """
        # 可以从 runtime 访问 state, config, store 等
        # state = runtime.state
        # logger.info(f"当前状态: {state}")

        return await _execute_http_request(params=kwargs, config=config)

    return http_tool_with_context


# ==================== 向后兼容包装器 ====================


class HttpToolWrapper:
    """
    HTTP 工具包装器（向后兼容）

    保留旧的类接口，内部使用新的函数式工具
    """

    def __init__(
        self,
        name: str,
        description: str,
        tool_url: str,
        tool_method: str = "POST",
        token: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 0.3,
        timeout: int = 3,
        parameters_schema: Optional[dict] = None,
    ):
        """初始化 HTTP 工具包装器"""
        self.config = HttpToolConfig(
            tool_name=name,
            description=description,
            tool_url=tool_url,
            tool_method=tool_method,
            token=token,
            max_retries=max_retries,
            retry_delay=retry_delay,
            timeout=timeout,
            parameters_schema=parameters_schema or {},
        )

        # 创建实际工具
        self._tool = create_http_tool(self.config)

    def __call__(self, *args, **kwargs):
        """使包装器可调用"""
        return self._tool(*args, **kwargs)

    @property
    def name(self) -> str:
        """工具名称"""
        return self.config.tool_name

    @property
    def description(self) -> str:
        """工具描述"""
        return self.config.description

    def as_tool(self):
        """返回 LangChain Tool 实例"""
        return self._tool
