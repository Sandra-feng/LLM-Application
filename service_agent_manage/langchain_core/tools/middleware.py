#!/usr/bin/env python
"""
工具中间件 - 工具错误处理和日志记录
基于 LangChain 1.0 的 @wrap_tool_call 中间件模式
"""

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage
from loguru import logger


@wrap_tool_call
async def combine_error_handling_and_logging(request, handler):
    """
    组合中间件：错误处理 + 日志记录（异步版本）

    Args:
        request: 工具调用请求
        handler: 工具执行处理器

    Returns:
        工具执行结果或错误消息
    """
    tool_name = request.tool_call.get("name", "unknown")
    tool_args = request.tool_call.get("args", {})

    logger.info(f"[工具调用] {tool_name} | 参数: {tool_args}")

    try:
        result = await handler(request)
        logger.debug(f"[工具执行结果] {result}")
        return result

    except Exception as e:
        logger.exception(f"[工具异常] {tool_name} | {str(e)}")

        return ToolMessage(
            content=f"工具调用失败，请重试或使用其他方法。错误: {str(e)}",
            tool_call_id=request.tool_call["id"],
        )


# ==================== 导出默认中间件 ====================

DEFAULT_TOOL_MIDDLEWARE = [
    combine_error_handling_and_logging,
]
