#!/usr/bin/env python
"""
Think 标签中间件
处理模型思考过程的 <think> 标签
"""

from langchain_core.callbacks import AsyncCallbackHandler
from loguru import logger


class ThinkTagProcessor:
    """
    Think 标签处理器

    复用现有的 ThinkTagProcessor 逻辑，用于解析 <think> 标签
    """

    def __init__(self):
        self.start_tag = "<think>"
        self.end_tag = "</think>"
        self.reset()

    def reset(self):
        """重置处理状态"""
        self.in_thinking = 0
        self.tag_buf = ""
        self.content_type = "text"
        self.content = ""
        self.think = ""
        self.think_count = 0

    def process_token(self, token: str) -> tuple[str, str, bool]:
        """
        处理单个 token

        Args:
            token: 输入 token

        Returns:
            (处理后的token, content_type, 是否应该跳过)
        """
        self.tag_buf += token
        should_skip = False

        # 检测思考开始
        if self.in_thinking == 0 and "<" in token:
            self.in_thinking = 1
        elif self.in_thinking != 4:
            self.in_thinking = 2
            self.content_type = "thinking"

        # 处理开始标签
        if self.start_tag in self.tag_buf:
            self.in_thinking = 2
            self.content_type = "thinking"
            if len(self.tag_buf.split(self.start_tag)) > 1:
                token = self.tag_buf.split(self.start_tag)[-1]
                self.tag_buf = self.tag_buf.replace(self.start_tag, "")
            else:
                self.tag_buf = self.tag_buf.replace(self.start_tag, "")
                should_skip = True

        # 检测思考中的标签
        if self.in_thinking == 2 and "<" in self.tag_buf:
            self.in_thinking = 3

        # 处理结束标签
        if self.end_tag in self.tag_buf:
            self.in_thinking = 4
            self.content_type = "text"
            if len(self.tag_buf.split(self.end_tag)) > 1:
                token = self.tag_buf.split(self.end_tag)[-1]
                self.tag_buf = self.tag_buf.replace(self.end_tag, "")
            else:
                self.tag_buf = self.tag_buf.replace(self.end_tag, "")
                should_skip = True

        # 跳过中间状态
        if self.in_thinking in [1, 3]:
            should_skip = True

        if should_skip:
            return "", self.content_type, should_skip

        # 累积内容
        if self.content_type == "thinking":
            self.think += token
        elif self.content_type == "text" and token is not None:
            self.content += token

        # 记录思考完成时间点
        if self.in_thinking == 4:
            self.think_count += 1

        return token, self.content_type, should_skip


class ThinkTagCallbackHandler(AsyncCallbackHandler):
    """
    Think 标签回调处理器

    作为 LangChain AsyncCallbackHandler 实现，
    在流式输出时拦截和处理 Think 标签
    """

    def __init__(self, enable_think: bool = True):
        """
        初始化回调处理器

        Args:
            enable_think: 是否启用 Think 标签处理
        """
        super().__init__()
        self.enable_think = enable_think
        self.processor = ThinkTagProcessor()
        logger.info(f"ThinkTag 回调处理器初始化 | enable={enable_think}")

    async def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs):
        """LLM 开始时重置状态"""
        self.processor.reset()
        logger.debug("ThinkTag 处理器状态已重置")

    async def on_llm_new_token(self, token: str, **kwargs):
        """
        处理新 token

        Args:
            token: 新生成的 token
            **kwargs: 其他参数
        """
        if not self.enable_think:
            return

        # 处理 token
        processed_token, content_type, should_skip = self.processor.process_token(token)

        # 可以在这里记录日志或执行其他操作
        if content_type == "thinking":
            logger.debug(f"思考内容: {processed_token}")

    async def on_llm_end(self, response, **kwargs):
        """LLM 结束时记录统计信息"""
        logger.debug(
            f"ThinkTag 处理完成 | 思考内容长度: {len(self.processor.think)} | "
            f"输出内容长度: {len(self.processor.content)}"
        )

    def get_think_content(self) -> str:
        """获取思考内容"""
        return self.processor.think

    def get_output_content(self) -> str:
        """获取输出内容"""
        return self.processor.content

    def get_think_time(self) -> int:
        """获取思考次数"""
        return self.processor.think_count
