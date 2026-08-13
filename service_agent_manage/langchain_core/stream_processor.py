#!/usr/bin/env python
"""
统一的流处理器
合并 EventStreamAdapter 和 SSEGenerator 的功能
"""

import json
import time
from collections.abc import AsyncGenerator

from fastapi import Request
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from loguru import logger
from sqlalchemy.orm import Session

from base_utils.redis_util import RedisUtil
from base_utils.ret_util import RetUtil
from service_agent_manage.langchain_core.middleware.think_tag import ThinkTagProcessor
from service_model_manage.service.chat_db_service import ChatConversationService
from service_model_manage.service.KnowledgeTrace import KnowledgeTrace


class StreamProcessor:
    """
    统一的流处理器

    职责：
    1. 事件适配和转换
    2. Think/Citation 处理
    3. SSE 格式化
    4. 中断检查
    5. 数据库保存
    """

    def __init__(
        self,
        db: Session,
        talk_id: str,
        params: dict,
        request: Request,
        kb_sources: list,
        prompt: str,
        enable_think: bool = False,
        enable_citation: bool = False,
        conversation_type: int = 2,
    ):
        """
        初始化流处理器

        Args:
            db: 数据库会话
            talk_id: 对话 ID
            params: 智能体参数
            request: FastAPI 请求对象
            kb_sources: 知识库来源列表
            prompt: 提示词
            enable_think: 是否启用 think 处理
            enable_citation: 是否启用 citation 处理
            conversation_type: 对话类型
        """
        self.db = db
        self.talk_id = talk_id
        self.params = params
        self.prompt = prompt
        self.request = request
        self.kb_sources = kb_sources
        self.conversation_type = conversation_type

        # 中间件
        self.think_processor = ThinkTagProcessor() if enable_think else None
        self.citation_processor = KnowledgeTrace() if enable_citation else None
        self.enable_citation = enable_citation

        # 状态追踪
        self.start_time = time.time()
        self.first_output = True
        self.think_time = 0.0
        self.full_answer = ""
        self.think_content = ""
        self.reasoning_finished = False

        # 工具调用参数累加器
        self.tool_call_accumulators = {}

        logger.info(f"流处理器初始化 | talk_id={talk_id} | think={enable_think} | citation={enable_citation}")

    async def process_stream(self, agent_stream) -> AsyncGenerator[str, None]:
        """
        处理流式输出

        Args:
            agent_stream: Agent 流式输出

        Yields:
            SSE 格式的字符串
        """
        try:
            logger.info(f"开始处理流式输出 | talk_id={self.talk_id}")

            # 处理事件流
            async for event in agent_stream:
                # 检查中断状态
                if await self._check_interrupt():
                    logger.info(f"对话被中断 | talk_id={self.talk_id}")
                    break

                # 提取消息
                message, metadata = self._extract_message(event)
                if message is None:
                    continue

                # 处理消息并生成 SSE
                async for sse_message in self._process_message(message, metadata):
                    yield sse_message

            # 流式输出完成，保存最终数据
            await self._save_final_data()

            logger.info(f"流式输出处理完成 | talk_id={self.talk_id}")

        except Exception as e:
            logger.exception(f"处理流式输出异常: {str(e)}")

            # 发送错误消息
            error_event = {"token": "系统繁忙，请稍后再试", "talk_id": self.talk_id, "error": True}
            yield self._format_sse_message(error_event)

            # 清理数据
            try:
                ChatConversationService.delete_talk(db=self.db, talk_id=self.talk_id)
            except Exception as cleanup_error:
                logger.exception(f"清理失败的对话记录异常: {str(cleanup_error)}")

            raise

    async def _check_interrupt(self) -> bool:
        """检查中断状态"""
        try:
            redis = self.request.app.state.redis_pool
            status = await RedisUtil.get_cached_data(key=f"{self.talk_id}", redis=redis)
            if status:
                status = int(status.get("value"))
                return status == 3  # 中断状态
            return False
        except Exception as e:
            logger.warning(f"检查中断状态失败: {str(e)}")
            return False

    def _extract_message(self, event) -> tuple:
        """从事件中提取消息和元数据"""
        # 格式 1: (namespace, mode, (message, metadata))
        if isinstance(event, tuple) and len(event) == 3 and isinstance(event[1], str):
            inner_event = event[2]
            if isinstance(inner_event, tuple) and len(inner_event) == 2:
                return inner_event

        # 格式 2: (message, metadata)
        if isinstance(event, tuple) and len(event) == 2:
            return event

        return (None, None)

    async def _process_message(self, message, metadata: dict) -> AsyncGenerator[str, None]:
        """处理单个消息"""
        node_name = metadata.get("langgraph_node", "unknown")

        # 只处理特定节点的消息
        if node_name not in ["model", "tools", "__start__", "__end__"]:
            return

        # 处理 AI 消息
        if isinstance(message, (AIMessage, AIMessageChunk)):
            if self._has_content_blocks(message):
                async for sse_msg in self._process_content_blocks(message.content_blocks):
                    yield sse_msg
            # 当接收到空的 content_blocks 时，返回累加的完整参数
            elif (
                hasattr(message, "content_blocks")
                and isinstance(message.content_blocks, list)
                and len(message.content_blocks) == 0
            ):
                if self.tool_call_accumulators:
                    for index, accumulator in self.tool_call_accumulators.items():
                        if accumulator["notified"] and accumulator["args"]:
                            yield self._format_sse_message(
                                {
                                    "type": "tool_call_args",
                                    "tool_name": accumulator["name"],
                                    "talk_id": self.talk_id,
                                    "tool_args": accumulator["args"],
                                    "tool_index": index,
                                }
                            )

        # 处理工具结果
        elif node_name == "tools" and isinstance(message, ToolMessage):
            self.tool_call_accumulators.clear()
            yield self._format_sse_message(
                {
                    "type": "tool_result",
                    "tool_name": message.name,
                    "talk_id": self.talk_id,
                    "tool_result": message.content,
                }
            )

    def _has_content_blocks(self, message: AIMessage) -> bool:
        """检查消息是否有有效的 content_blocks"""
        return (
            hasattr(message, "content_blocks")
            and message.content_blocks
            and isinstance(message.content_blocks, list)
            and len(message.content_blocks) > 0
        )

    async def _process_content_blocks(self, content_blocks: list) -> AsyncGenerator[str, None]:
        """处理 content_blocks"""
        for block in content_blocks:
            block_type = block.get("type")

            # 处理推理/思考块（这里只有是OpenAI或其他 官方 API 才会走到这里，和xinference生成的</think>标签不一致）
            if block_type in ["reasoning", "thinking"]:
                reasoning_text = block.get("reasoning") or block.get("thinking", "")

                if reasoning_text:
                    self.think_content += reasoning_text
                    yield self._format_sse_message(
                        {"token": reasoning_text, "talk_id": self.talk_id, "type": "thinking", "think_time": 0}
                    )

                    if not self.reasoning_finished:
                        self.reasoning_finished = True
                        self.think_time = round(time.time() - self.start_time, 1)

            # 处理文本块
            elif block_type == "text":
                text = block.get("text", "")

                if text:
                    output_type = "text"
                    output_text = text

                    # Think 标签处理
                    if self.think_processor:
                        processed_text, content_type, should_skip = self.think_processor.process_token(text)

                        if should_skip:
                            continue

                        output_type = content_type
                        output_text = processed_text

                        if content_type == "thinking":
                            self.think_content += processed_text

                        if self.think_processor.think_count == 1 and self.think_time == 0:
                            self.think_time = round(time.time() - self.start_time, 1)

                    # Citation 处理（仅处理非思考内容）
                    citation_results = []
                    citation_output_text = output_text  # 保存原始 text，用于输出

                    if self.citation_processor and output_type == "text":
                        try:
                            skip_token, citation_output_text, citation_results = (
                                self.citation_processor.process_token_citation(
                                    token=output_text, content_type=output_type, think_time=self.think_time
                                )
                            )

                            # 确保 [citation:1] 标签的所有部分都被累积
                            if output_type == "text":
                                self.full_answer += output_text

                            if skip_token:
                                continue

                        except Exception as e:
                            logger.exception(f"Citation 处理失败: {str(e)}")
                            # 异常时保持原始值
                            citation_results = []
                            citation_output_text = output_text

                    # 如果有 citation 结果，输出多个事件
                    if citation_results:
                        for result in citation_results:
                            event_data = {
                                "token": result["token"],
                                "talk_id": self.talk_id,
                                "type": result["type"],
                                "think_time": result.get("think_time", self.think_time),
                            }

                            # 首次输出时附加知识库来源（只在循环的第一个 result 中附加，避免重复附加）
                            if self.first_output:
                                if self.kb_sources:
                                    event_data["new_source"] = self.kb_sources
                                self.first_output = False

                            yield self._format_sse_message(event_data)
                    else:
                        # 普通输出（无 citation 结果时使用处理后的 token）
                        event_data = {
                            "token": citation_output_text,  # 使用 citation 处理后的 token
                            "talk_id": self.talk_id,
                            "type": output_type,
                            "think_time": self.think_time,
                        }

                        # 同上
                        if self.first_output:
                            if self.kb_sources:
                                event_data["new_source"] = self.kb_sources
                            self.first_output = False

                        yield self._format_sse_message(event_data)

                    # 更新状态（非 citation 处理的文本累积）
                    if not self.citation_processor and output_type == "text":
                        self.full_answer += output_text

            # 处理工具调用块
            elif block_type == "tool_call_chunk":
                async for sse_msg in self._process_tool_call_chunk(block):
                    yield sse_msg

    async def _process_tool_call_chunk(self, block: dict) -> AsyncGenerator[str, None]:
        """处理工具调用块"""
        index = block.get("index", 0)
        tool_id = block.get("id")
        tool_name = block.get("name")
        args_chunk = block.get("args", "")

        # 初始化累加器
        if index not in self.tool_call_accumulators:
            self.tool_call_accumulators[index] = {
                "id": "",
                "name": "",
                "args": "",
                "notified": False,
            }

        accumulator = self.tool_call_accumulators[index]

        # 更新 ID 和名称
        if tool_id:
            accumulator["id"] = tool_id
        if tool_name:
            accumulator["name"] = tool_name

        # 累加参数
        if args_chunk:
            accumulator["args"] += args_chunk

        # 第一次收到工具调用时立即通知前端
        if not accumulator["notified"] and accumulator["id"] and accumulator["name"]:
            accumulator["notified"] = True
            yield self._format_sse_message(
                {
                    "type": "tool_call_start",
                    "tool_name": accumulator["name"],
                    "talk_id": self.talk_id,
                }
            )

    def _format_sse_message(self, event: dict) -> str:
        """格式化 SSE 消息"""
        response = RetUtil.response_stream(data=event)
        return json.dumps(response, ensure_ascii=False)

    async def _save_final_data(self):
        """保存最终对话数据"""
        try:
            citation_numbers = []
            cleaned_content = self.full_answer

            # 如果启用了 citation 且有内容，则提取 citation 信息并清理标签
            if self.enable_citation and self.full_answer:
                try:
                    cleaned_content, citation_numbers = KnowledgeTrace.process_content(self.full_answer)
                except Exception as e:
                    logger.exception(f"获取 citation 信息失败: {str(e)}")
                    citation_numbers = []
                    cleaned_content = self.full_answer
            else:
                cleaned_content = self.full_answer
                citation_numbers = []

            save_data = {
                "prompt": self.prompt,
                "user": self.params.get("input", ""),
                "assistant": {
                    "content": cleaned_content,  # 清理后的内容（移除了 citation 标签）
                    "think": self.think_content,
                    "think_time": self.think_time if self.think_time != 0 else 0,
                    "chunk_citation": citation_numbers,
                },
                "type": self.conversation_type,
                "new_source": self.kb_sources,
            }

            # 保存到数据库
            await ChatConversationService.update_talk_data_agent(
                db=self.db,
                talk_id=self.talk_id,
                token_data=json.dumps(save_data),
            )

            logger.info(f"对话数据已保存 | talk_id={self.talk_id}")

        except Exception as e:
            logger.exception(f"保存对话数据失败: {str(e)}")
