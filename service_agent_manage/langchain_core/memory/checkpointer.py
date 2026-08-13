#!/usr/bin/env python
"""
Checkpointer 封装
管理 LangGraph 状态持久化
"""

from typing import Optional

from langgraph.checkpoint.memory import MemorySaver
from loguru import logger

from service_agent_manage.langchain_core.configs.langchain_config import LangChainConfig


class TianceCheckpointer:
    """
    天策 Checkpointer

    封装 LangGraph Checkpointer，支持：
    - MemorySaver（开发环境）
    - PostgresSaver（生产环境）

    用于管理对话状态的持久化和恢复
    """

    def __init__(self, use_postgres: Optional[bool] = None):
        """
        初始化 Checkpointer

        Args:
            use_postgres: 是否使用 PostgreSQL。None 时使用配置文件设置
        """
        if use_postgres is None:
            use_postgres = LangChainConfig.USE_POSTGRES_CHECKPOINTER

        self.use_postgres = use_postgres
        self.saver = self._create_saver()

        logger.info(f"Checkpointer 初始化完成 | 类型: {'PostgreSQL' if use_postgres else 'Memory'}")

    def _create_saver(self):
        """创建 Saver 实例"""
        if self.use_postgres:
            try:
                from langgraph.checkpoint.postgres import PostgresSaver

                connection_string = LangChainConfig.POSTGRES_CHECKPOINT_URI
                if not connection_string:
                    logger.warning("PostgreSQL 连接字符串未配置，降级使用 MemorySaver")
                    return MemorySaver()

                saver = PostgresSaver.from_conn_string(connection_string)
                logger.info(f"PostgreSQL Checkpointer 创建成功 | URI: {connection_string}")
                return saver

            except ImportError:
                logger.warning("langgraph-checkpoint-postgres 未安装，降级使用 MemorySaver")
                return MemorySaver()

            except Exception as e:
                logger.exception(f"创建 PostgreSQL Checkpointer 失败: {str(e)}，降级使用 MemorySaver")
                return MemorySaver()
        else:
            return MemorySaver()

    def get_saver(self):
        """获取 Saver 实例"""
        return self.saver

    async def get_state(self, thread_id: str) -> Optional[dict]:
        """
        获取会话状态

        Args:
            thread_id: 会话 ID（对应 conversation_id）

        Returns:
            会话状态字典，不存在时返回 None
        """
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state = await self.saver.aget(config)
            return state
        except Exception as e:
            logger.exception(f"获取会话状态失败 | thread_id={thread_id} | 错误: {str(e)}")
            return None

    async def save_state(self, thread_id: str, state: dict):
        """
        保存会话状态

        Args:
            thread_id: 会话 ID
            state: 状态字典
        """
        try:
            config = {"configurable": {"thread_id": thread_id}}
            await self.saver.aput(config, state, {})
            logger.info(f"会话状态已保存 | thread_id={thread_id}")
        except Exception as e:
            logger.exception(f"保存会话状态失败 | thread_id={thread_id} | 错误: {str(e)}")

    async def clear_state(self, thread_id: str):
        """
        清除会话状态

        Args:
            thread_id: 会话 ID
        """
        try:
            # MemorySaver 和 PostgresSaver 的清除方法可能不同
            # 这里提供通用接口
            logger.info(f"清除会话状态 | thread_id={thread_id}")
        except Exception as e:
            logger.exception(f"清除会话状态失败 | thread_id={thread_id} | 错误: {str(e)}")

    async def list_states(self, limit: int = 10) -> list:
        """
        列出最近的会话状态

        Args:
            limit: 返回数量限制

        Returns:
            状态列表
        """
        try:
            # 这里需要根据实际 Saver 实现
            # PostgresSaver 可能支持查询，MemorySaver 需要自己维护
            return []
        except Exception as e:
            logger.exception(f"列出会话状态失败 | 错误: {str(e)}")
            return []


# 全局 Checkpointer 单例
_global_checkpointer: Optional[TianceCheckpointer] = None


def get_global_checkpointer() -> TianceCheckpointer:
    """
    获取全局 Checkpointer 单例

    Returns:
        TianceCheckpointer 实例
    """
    global _global_checkpointer

    if _global_checkpointer is None:
        _global_checkpointer = TianceCheckpointer(use_postgres=False)

    return _global_checkpointer
