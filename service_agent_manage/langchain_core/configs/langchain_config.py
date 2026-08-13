#!/usr/bin/env python
"""
LangChain 配置文件
管理 LangChain 相关的全局配置
"""

import os
from typing import Optional


class LangChainConfig:
    """LangChain 配置类"""

    # LangSmith 追踪配置（可选）
    LANGSMITH_TRACING_ENABLED: bool = os.getenv("LANGSMITH_TRACING_ENABLED", "false").lower() == "true"
    LANGSMITH_API_KEY: Optional[str] = os.getenv("LANGSMITH_API_KEY")
    LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", "tiance-agent")
    LANGSMITH_ENDPOINT: str = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

    # Checkpointer 配置
    USE_POSTGRES_CHECKPOINTER: bool = os.getenv("USE_POSTGRES_CHECKPOINTER", "false").lower() == "true"
    POSTGRES_CHECKPOINT_URI: Optional[str] = os.getenv(
        "POSTGRES_CHECKPOINT_URI", "postgresql://user:password@localhost:5432/tiance_checkpoints"
    )

    # Memory 配置
    MAX_HISTORY_MESSAGES: int = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))
    USE_CONVERSATION_SUMMARY: bool = os.getenv("USE_CONVERSATION_SUMMARY", "false").lower() == "true"
    SUMMARY_TRIGGER_ROUNDS: int = int(os.getenv("SUMMARY_TRIGGER_ROUNDS", "5"))

    # Agent 配置
    MAX_ITERATIONS: int = int(os.getenv("AGENT_MAX_ITERATIONS", "15"))
    AGENT_TIMEOUT: int = int(os.getenv("AGENT_TIMEOUT", "300"))  # 秒

    # 流式输出配置
    STREAM_CHUNK_SIZE: int = int(os.getenv("STREAM_CHUNK_SIZE", "1024"))
    ENABLE_THINK_TAG: bool = os.getenv("ENABLE_THINK_TAG", "true").lower() == "true"
    ENABLE_CITATION: bool = os.getenv("ENABLE_CITATION", "true").lower() == "true"

    @classmethod
    def setup_langsmith(cls):
        """设置 LangSmith 追踪"""
        if cls.LANGSMITH_TRACING_ENABLED and cls.LANGSMITH_API_KEY:
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = cls.LANGSMITH_API_KEY
            os.environ["LANGCHAIN_PROJECT"] = cls.LANGSMITH_PROJECT
            os.environ["LANGCHAIN_ENDPOINT"] = cls.LANGSMITH_ENDPOINT

    @classmethod
    def get_checkpointer_config(cls) -> dict:
        """获取 Checkpointer 配置"""
        return {
            "use_postgres": cls.USE_POSTGRES_CHECKPOINTER,
            "connection_string": cls.POSTGRES_CHECKPOINT_URI,
        }

    @classmethod
    def get_memory_config(cls) -> dict:
        """获取 Memory 配置"""
        return {
            "max_history": cls.MAX_HISTORY_MESSAGES,
            "use_summary": cls.USE_CONVERSATION_SUMMARY,
            "summary_trigger_rounds": cls.SUMMARY_TRIGGER_ROUNDS,
        }

