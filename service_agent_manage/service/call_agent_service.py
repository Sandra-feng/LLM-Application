#!/usr/bin/env python
"""
优化后的 call_agent_withtag 函数
重构目标：
1. 消除重复代码
2. 提高可读性
3. 改善性能
4. 增强错误处理
"""

import json
import time
import traceback
from types import SimpleNamespace
from typing import Optional

# logger = loguru logger (auto-migrated)
from bson import ObjectId
from fastapi import Request
from loguru import logger
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.mysql_util import query2dict_status
from base_utils.redis_util import RedisUtil
from base_utils.rerank_util import RerankUtil
from base_utils.ret_util import RetUtil
from service_agent_manage.entity.agent_entity import TestAgentInfo_v1
from service_agent_manage.service.agent_service import AgentService
from service_knowledge_manage.api.routes.knowledge_hub_route import knwolege_retrieval
from service_knowledge_manage.entity.knowledge_hub_entity import (
    KnowledgeRetrivalInfo,
)
from service_model_manage.entity.chat_completion_entity import ChatCompletionRequestParams_v1
from service_model_manage.service.chat_completion_service import OpenAILLMService
from service_model_manage.service.chat_db_service import ChatConversationService
from service_model_manage.service.KnowledgeTrace import KnowledgeTrace
from service_model_manage.service.QAKnowledgeRetrieval import KnowledgeRetrievalLLMQA
from service_permission_manage.service.config_service import ConfigService
from service_prompt_manage.model.prompt_info_model import Prompt_Model


# 添加优化后的辅助类和函数
class ThinkTagProcessor:
    """处理 <think> 标签的专用类"""

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
        self.stream_count = 0

    def process_token(self, token: str, is_think: bool) -> tuple[str, str, bool]:
        """
        处理单个token
        返回: (处理后的token, content_type, 是否应该跳过)
        """
        # if token !="" and token !=None:
        if not is_think:
            self.content += token
            return token, "text", False

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
            self.stream_count += 1

        return token, self.content_type, should_skip


class PromptBuilder:
    """构建提示词的专用类"""

    @staticmethod
    def build_tool_prompt(prompt: str, tool_result: str, system_prompts: str, history_system_prompts: str) -> str:
        """构建工具调用的提示词"""
        if system_prompts:
            return f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息:{tool_result}{system_prompts}回答用户的问题。
            注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}以及{system_prompts}就是事实。
            """
        elif history_system_prompts:
            return f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息:{tool_result}{history_system_prompts}回答用户的问题。
            注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}以及{history_system_prompts}就是事实。
            """
        else:
            return f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息{tool_result}回答用户的问题。
            注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}就是事实。
            """

    @staticmethod
    def build_knowledge_prompt(prompt: str, docs: str, system_prompts: str, history_system_prompts: str) -> str:
        """构建知识库检索的提示词"""
        if system_prompts:
            return f"""
            【系统提示词】
            {prompt}
            
            【知识库检索结果】
            {docs}
            
            【用户上传的个人知识】
            {system_prompts}
            
            【用户问题】
            请根据上述内容和你自身掌握的通用知识，整合信息，准确、有帮助地回答用户的问题。如信息不足，请直接说明。

            """
        elif history_system_prompts:
            return f"""
            【系统提示词】
            {prompt}
            
            【知识库检索结果】
            {docs}
            
            【用户上传的个人知识】
            {history_system_prompts}
            
            【用户问题】
            请根据上述内容和你自身掌握的通用知识，整合信息，准确、有帮助地回答用户的问题。如信息不足，请直接说明。

            """
        else:
            return f"""
            【系统提示词】
            {prompt}
            
            【知识库检索结果】
            {docs}

            【用户问题】
            请根据上述内容和你自身掌握的通用知识，整合信息，准确、有帮助地回答用户的问题。如信息不足，请直接说明。

            """

    @staticmethod
    def build_knowledgeTrace_prompt(prompt: str, docs: str, system_prompts: str, history_system_prompts: str) -> str:
        """构建知识库检索的提示词"""
        if system_prompts:
            return f"""
            【系统提示词】
            {prompt}
            
            【知识库检索结果】
            {docs}
            
            【用户上传的个人知识】
            {system_prompts}
            
            【用户问题】
            基于知识库内容来回答用户的问题，确保答案简洁、权威且可溯源，并注释知识库的引用编号index。
⚠️ 注意事项：  
1. **引用标注**：每一句包含知识来源的陈述都必须标注引用，引用严格按照标注格式，格式为[citation:1]（例如：太阳系有8颗行星 [citation:1]）。
2. **必须回答问题**：不输出任何思考、推理、分析或无关内容。思考阶段不输出任何"citation"文字，只在最终回答中根据知识库内容添加正确的标注格式。
3. **合并引用标注**：如果知识库中有多个片段支持同一句话的回答点，应合并标注（例如：月球轨道为椭圆[citation:1,2,3]）。  
4.**引用编号必须是知识库片段的引用编号**,不得凭空引用或捏造引用编号，只要统一标注引用编号，无需拆分知识库内容为多个子编号，不要引用知识库内容中的编号。
5. 若问题超出知识库范围，请根据自己的知识做补充。   

            """
        elif history_system_prompts:
            return f"""
            【系统提示词】
            {prompt}
            
            【知识库检索结果】
            {docs}
            
            【用户上传的个人知识】
            {history_system_prompts}
            
            【用户问题】
            基于知识库内容来回答用户的问题，确保答案简洁、权威且可溯源，并注释知识库的引用编号index。
⚠️ 注意事项：  
1. **引用标注**：每一句包含知识来源的陈述都必须标注引用，引用严格按照标注格式，格式为[citation:1]（例如：太阳系有8颗行星 [citation:1]）。
2. **必须回答问题**：不输出任何思考、推理、分析或无关内容。思考阶段不输出任何"citation"文字，只在最终回答中根据知识库内容添加正确的标注格式。
3. **合并引用标注**：如果知识库中有多个片段支持同一句话的回答点，应合并标注（例如：月球轨道为椭圆[citation:1,2,3]）。  
4.**引用编号必须是知识库片段的引用编号**,不得凭空引用或捏造引用编号，只要统一标注引用编号，无需拆分知识库内容为多个子编号，不要引用知识库内容中的编号。
5. 若问题超出知识库范围，请根据自己的知识做补充。   

            """
        else:
            return f"""
            【系统提示词】
            {prompt}
            
            【知识库检索结果】
            {docs}

            【用户问题】
            基于知识库内容来回答用户的问题，确保答案简洁、权威且可溯源，并注释知识库的引用编号index。
⚠️ 注意事项：  
1. **引用标注**：每一句包含知识来源的陈述都必须标注引用，引用严格按照标注格式，格式为[citation:1]（例如：太阳系有8颗行星 [citation:1]）。
2. **必须回答问题**：不输出任何思考、推理、分析或无关内容。思考阶段不输出任何"citation"文字，只在最终回答中根据知识库内容添加正确的标注格式。
3. **合并引用标注**：如果知识库中有多个片段支持同一句话的回答点，应合并标注（例如：月球轨道为椭圆[citation:1,2,3]）。  
4.**引用编号必须是知识库片段的引用编号**,不得凭空引用或捏造引用编号，只要统一标注引用编号，无需拆分知识库内容为多个子编号，不要引用知识库内容中的编号。
5. 若问题超出知识库范围，请根据自己的知识做补充。   

            """

    @staticmethod
    def build_simple_prompt(prompt: str, system_prompts: str, history_system_prompts: str) -> str:
        """构建简单的提示词"""
        if system_prompts:
            return f"""
            {prompt}
            尽可能以有用且准确的方式回复人类。
            个人知识：{system_prompts}
            根据用户输入和个人知识和你自己的知识进行知识整合，对用户问题进行回答。
            """
        elif history_system_prompts:
            return f"""
            {prompt}
            尽可能以有用且准确的方式回复人类。
            个人知识：{history_system_prompts}
            根据用户输入和个人知识和你自己的知识进行知识整合，对用户问题进行回答。
            """
        else:
            return prompt


class AgentDataProcessor:
    """智能体数据处理类"""

    @staticmethod
    def get_prompt_from_db(db: Session, prompt_id: str) -> str:
        """从数据库获取提示词"""
        if not prompt_id:
            return ""

        prompt_info = query2dict_status(
            db.query(Prompt_Model).filter(Prompt_Model.prompt_id == prompt_id, Prompt_Model.status != 0).first(),
            Prompt_Model,
        )
        return prompt_info["prompt_content"] if prompt_info else ""

    @staticmethod
    def setup_model_params(model_params: dict) -> dict:
        """设置模型参数默认值"""
        if model_params.get("presence_penalty") is None:
            model_params["presence_penalty"] = 0
        if model_params.get("frequency_penalty") is None:
            model_params["frequency_penalty"] = 0
        return model_params

    @staticmethod
    def get_history_system_prompts(chatbot: list, system_prompts: str) -> str:
        """获取历史系统提示词"""
        if system_prompts:
            return ""

        for conversation in chatbot:
            if conversation.get("prompt", None):
                return conversation["prompt"]
        return ""

    @staticmethod
    def build_kb_list(kb_ids: list) -> list:
        """构建知识库列表"""
        kb_list = []
        for kb_id in kb_ids:
            kb_result = MongodbUtil.query_doc_by_id(CollectionConfig.KB_COLLECTION, doc_id=ObjectId(kb_id))
            kb_list.append(
                {
                    "id": kb_id,
                    "kb_name": kb_result["kb_name"],
                    "rerank_model": kb_result.get("rerank_model", ""),
                    "rerank_id": kb_result.get("rerank_id", ""),
                    "recall_num": kb_result.get("retrieval_count", 10),
                    "rerank_num": kb_result.get("rerank_num", 3),
                    "score": kb_result.get("score", 0.1),
                    "enhance_rounds": kb_result.get("enhance_rounds", 0),
                    "search_type": kb_result.get("search_type", "semantic"),
                    "fusion_weights": kb_result.get("fusion_weights", []),
                }
            )
        return kb_list


import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class DatabaseWriteQueue:
    """数据库写入队列 - 全局单例，管理所有数据库写入操作"""

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.write_queue = asyncio.Queue(maxsize=1000)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="db_writer")
        self.worker_task = None
        self._initialized = True
        self._start_worker()

    def _start_worker(self):
        """启动后台写入工作者"""
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._write_worker())

    async def _write_worker(self):
        """后台写入工作者"""
        while True:
            try:
                # 批量获取写入任务
                write_tasks = []
                try:
                    # 获取第一个任务（阻塞等待）
                    first_task = await self.write_queue.get()
                    write_tasks.append(first_task)

                    # 尝试获取更多任务（非阻塞）
                    while len(write_tasks) < 10:  # 最多批量处理10个
                        try:
                            task = self.write_queue.get_nowait()
                            write_tasks.append(task)
                        except asyncio.QueueEmpty:
                            break

                except asyncio.CancelledError:
                    break

                # 批量执行写入
                await self._batch_execute_writes(write_tasks)

            except Exception as e:
                logger.exception(f"数据库写入工作者异常: {str(e)}")
                await asyncio.sleep(0.1)  # 短暂休息后继续

    async def _batch_execute_writes(self, write_tasks: list):
        """批量执行写入任务"""
        for task_data in write_tasks:
            try:
                db, talk_id, token_data = task_data
                await ChatConversationService.update_talk_data_agent(db=db, talk_id=talk_id, token_data=token_data)
            except Exception as e:
                logger.exception(f"批量写入任务失败: {str(e)}")

    async def enqueue_write(self, db: Session, talk_id: str, token_data: str):
        """将写入任务加入队列"""
        try:
            await self.write_queue.put((db, talk_id, token_data))
        except asyncio.QueueFull:
            logger.warning("数据库写入队列已满，丢弃写入任务")

    async def shutdown(self):
        """关闭队列"""
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        self.executor.shutdown(wait=True)


class OptimizedStreamResponseHandler:
    """优化的流式响应处理类 - 支持异步写入"""

    def __init__(
        self,
        db: Session,
        talk_id: str,
        start_time: float,
        chat_request: Request,
    ):
        self.db = db
        self.talk_id = talk_id
        self.start_time = start_time
        self.chat_request = chat_request
        self.first_output = True
        self.think_processor = ThinkTagProcessor()
        self.citation_processor = KnowledgeTrace()
        self.real_think = 0
        # 累积本次对话的完整回答（基于流式token）
        self.full_answer = ""

    async def handle_chunk(
        self,
        chunk,
        params,
        conversation_type: int,
        new_source: list,
        is_think: bool,
        model_list: list,
        citation_open: int,
    ):
        """处理单个chunk - 优化版本"""
        if chunk.choices[0].delta.content == "" or chunk.choices[0].delta.content is None:
            return None

        token = chunk.choices[0].delta.content
        self.full_answer += token
        results = []

        # 处理think标签
        processed_token, content_type, should_skip = self.think_processor.process_token(token, is_think)

        if should_skip:
            return None

        # 处理citation标签（仅处理非思考内容）
        if content_type != "thinking" and self.model_params["model_uid"] in model_list and citation_open == 1:
            skip_token, token, results = self.citation_processor.process_token_citation(
                token=processed_token, content_type=content_type, think_time=0
            )
            if skip_token:
                return None

        # 检查停止状态
        redis = self.chat_request.app.state.redis_pool
        status = await RedisUtil.get_cached_data(key=f"{self.talk_id}", redis=redis)
        if status:
            status = int(status.get("value"))

        if status == 3:  # 中断
            logger.info(f"对话被中断 | talk_id={self.talk_id}")
            # 保存当前数据
            data = self._build_update_data(params, conversation_type, new_source, self.real_think)
            await self._async_db_update(data)
            return "STOP"

        # 计算思考时间
        think_time = 0

        if self.think_processor.stream_count == 1:
            think_time = round(time.time() - self.start_time, 1)
        if think_time != 0:
            self.real_think = think_time

        # 构建响应数据
        result_list = []

        if results:
            for result_text in results:
                result_data = {
                    "token": result_text["token"],
                    "talk_id": self.talk_id,
                    "type": result_text["type"],
                    "think_time": think_time,
                }

                if self.first_output:
                    result_data["new_source"] = new_source
                    self.first_output = False

                result_list.append(result_data)
        else:  # 不溯源的普通token
            result_data = {
                "token": processed_token,
                "talk_id": self.talk_id,
                "type": content_type,
                "think_time": think_time,
            }
            if self.first_output:
                result_data["new_source"] = new_source
                self.first_output = False
            result_list.append(result_data)

        return result_list

    def _build_update_data(self, params, conversation_type: int, new_source: list, think_time: float) -> dict[str, Any]:
        """构建更新数据"""
        cleaned_content, citation_numbers = KnowledgeTrace.process_content(self.think_processor.content)
        return {
            "prompt": params.system_prompts,
            "user": params.input,
            "assistant": {
                "content": cleaned_content,
                "think": self.think_processor.think,
                "think_time": think_time if think_time != 0 else 0,
                "chunk_citation": citation_numbers,
            },
            "type": conversation_type,
            "new_source": new_source,
        }

    async def _async_db_update(self, data: dict[str, Any]):
        """异步数据库更新 - 使用队列优化"""
        try:
            # 使用全局写入队列
            db_queue = DatabaseWriteQueue()
            await db_queue.enqueue_write(self.db, self.talk_id, json.dumps(data))
        except Exception as e:
            logger.exception(f"异步数据库更新失败: {str(e)}")
            # 降级到直接写入
            try:
                await ChatConversationService.update_talk_data_agent(
                    db=self.db, talk_id=self.talk_id, token_data=json.dumps(data)
                )
            except Exception as fallback_e:
                logger.exception(f"降级数据库写入也失败: {str(fallback_e)}")

    async def finalize(self, params, conversation_type: int, new_source: list):
        """完成处理 - 确保所有数据都已保存"""
        # 构建更新数据
        data = self._build_update_data(params, conversation_type, new_source, self.real_think)
        # 异步执行数据库更新
        await self._async_db_update(data)
        # 记录完整回答，便于查看
        # try:
        #     logger.info(f"完整回答(累计token) | talk_id={self.talk_id} | 长度={len(self.full_answer)}")
        #     logger.info(self.full_answer)
        # except Exception:
        #     pass


# 保持原有的简单版本作为备选
class StreamResponseHandler:
    """原始流式响应处理类 - 保持向后兼容"""

    def __init__(self, db: Session, talk_id: str, start_time: float):
        self.db = db
        self.talk_id = talk_id
        self.start_time = start_time
        self.first_output = True
        self.think_processor = ThinkTagProcessor()

    async def handle_chunk(self, chunk, params, conversation_type: int, new_source: list, is_think: bool):
        """处理单个chunk"""
        if chunk.choices[0].delta.content == "" or chunk.choices[0].delta.content is None:
            return None

        token = chunk.choices[0].delta.content

        # 处理think标签
        processed_token, content_type, should_skip = self.think_processor.process_token(token, is_think)

        if should_skip:
            return None

        # 检查停止状态
        status = ChatConversationService.check_talk_stop_status(db=self.db, talk_id=self.talk_id, talk_num=0)
        if status == 3:  # 中断
            return "STOP"

        # 计算思考时间
        think_time = 0
        if self.think_processor.stream_count == 1:
            think_time = round(time.time() - self.start_time, 1)

        # 构建响应数据
        result_data = {
            "token": processed_token,
            "talk_id": self.talk_id,
            "type": content_type,
            "think_time": think_time,
        }

        if self.first_output:
            result_data["new_source"] = new_source
            self.first_output = False

        # 更新数据库
        await self._update_talk_data(params, conversation_type, new_source, think_time)

        return result_data

    async def _update_talk_data(self, params, conversation_type: int, new_source: list, think_time: float):
        """更新对话数据"""
        data = {
            "prompt": params.system_prompts,
            "user": params.input,
            "assistant": {
                "content": self.think_processor.content,
                "think": self.think_processor.think,
                "think_time": think_time if think_time != 0 else 0,
            },
            "type": conversation_type,
            "new_source": new_source,
        }
        await ChatConversationService.update_talk_data_agent(
            db=self.db, talk_id=self.talk_id, token_data=json.dumps(data)
        )


class AgentCallOptimizer:
    """智能体调用优化器 - 主要业务逻辑类"""

    def __init__(
        self,
        db: Session,
        params: TestAgentInfo_v1,
        account_id: str,
        conversation_type: int = 2,
        chat_request: Request = None,
        is_workflow: bool = False,
    ):
        self.db = db
        self.params = params
        self.need_new_source = params.need_new_source
        self.account_id = account_id
        self.conversation_type = conversation_type
        self.start_time = time.time()
        self.chat_request = chat_request
        self.is_workflow = is_workflow

        # 初始化数据
        self.agent_config = None
        self.model_params = None
        self.prompt = ""
        self.kb_list = []
        self.tool_list = []
        self.history_system_prompts = ""
        self.talk_id = ""
        self.new_source = []
        self.real_think = 0
        self.team_code = ""
        self.rewrite_query = ""
        self.retrieval_query = ""
        self.synonym_list = []
        self.is_question_rewriting = False
        self.docs = ""

    async def initialize_agent_data(self) -> bool:
        """初始化智能体数据"""
        try:
            synonym_list = []
            result = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(self.params.agent_id)
            )
            synonym_binding_info = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.SYNONYM_BINDING,
                search_condition={"id": self.params.agent_id, "type": 0},
            )
            for item in synonym_binding_info:
                synonym_list = item["synonym_id_list"]
            self.synonym_list = synonym_list
            self.is_question_rewriting = result.get("is_question_rewriting", False)
            # 获取智能体配置
            self.agent_config = MongodbUtil.query_doc_by_id(
                CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(self.params.agent_id)
            )
            self.team_code = MongodbUtil.query_doc_by_id(
                CollectionConfig.AGENT_COLLECTION, doc_id=ObjectId(self.params.agent_id)
            ).get("team_code", "")
            # 处理参数
            params_dic = self.params.agent_params
            params_dic_id = ChatConversationService.task_query_id(params_dic, self.account_id)
            self.agent_config.update(params_dic_id)

            if self.agent_config["model_params"]["id"]:
                model_data = MongodbUtil.query_doc_by_id(
                collection_name = CollectionConfig.MODEL_RUN_COLLECTION,
                doc_id = ObjectId(self.agent_config["model_params"]["id"]),
            )
                self.agent_config["model_params"]["model_uid"] = model_data.get("model_uid", "")

            if self.agent_config["recall_setting"].get("rerank_id","")!="" and self.agent_config["recall_setting"]["rerank_id"]:
                model_data2 = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    doc_id=ObjectId(self.agent_config["recall_setting"]["rerank_id"]),
                )
                if model_data2:
                    self.agent_config["recall_setting"]["rerank_model"] = model_data2.get("model_uid", "")


            # 设置模型参数
            self.model_params = AgentDataProcessor.setup_model_params(self.agent_config["model_params"])

            # 获取提示词
            self.prompt = await self._get_prompt()

            # 获取历史对话
            await self._setup_history()

            # 验证配置
            if not self._validate_config():
                return False

            # 构建知识库和工具列表
            await self._setup_kb_and_tools()

            return True

        except Exception as e:
            logger.exception(f"初始化智能体数据失败: {e}")
            return False

    async def _get_prompt(self) -> str:
        """获取提示词"""
        if self.params.prompt_id:
            prompt = AgentDataProcessor.get_prompt_from_db(self.db, self.params.prompt_id)
        else:
            prompt_id = self.agent_config.get("prompt_id", "")
            if prompt_id:
                prompt = AgentDataProcessor.get_prompt_from_db(self.db, prompt_id)
            else:
                prompt = self.agent_config["prompt"]

        return ChatConversationService.prompt_params(self.params.agent_params, prompt)

    async def _setup_history(self):
        """设置历史对话"""
        talk_info = ChatConversationService.check_talk_info_history(
            db=self.db, conversation_id=self.params.conversation_id
        )

        if len(talk_info) > self.model_params["history"]:
            if self.model_params["history"] == 0:
                chatbot = []
            else:
                chatbot = talk_info[-self.model_params["history"] :]
        else:
            chatbot = talk_info

        self.history_system_prompts = AgentDataProcessor.get_history_system_prompts(chatbot, self.params.system_prompts)

    def _validate_config(self) -> bool:
        """验证配置"""
        if "知识库ID不存在，请给出正确的知识库ID" in self.agent_config["kb_list"]:
            return False
        if "工具ID不存在，请给出正确的工具ID" in self.agent_config["tool_list"]:
            return False
        return True

    async def _setup_kb_and_tools(self):
        """设置知识库和工具"""
        # 构建知识库列表
        self.kb_list = AgentDataProcessor.build_kb_list(self.agent_config["kb_list"])

        # 构建工具列表
        self.tool_list = await AgentService.tool_list(self.agent_config)

    async def execute_agent_call(self) -> EventSourceResponse:
        """执行智能体调用"""
        try:
            # 检查是否使用工具
            tools = self._prepare_tools()
            tool_result, tool_use = await self._check_tool_usage(tools)

            if tool_use:
                return await self._handle_tool_response(tool_result)
            elif self.kb_list:
                return await self._handle_knowledge_response()
            else:
                return await self._handle_simple_response()

        except Exception as e:
            logger.exception(f"执行智能体调用失败: {e}")
            raise

    async def execute_agent_workflow(self) -> EventSourceResponse:
        """执行智能体调用"""
        try:
            # 检查是否使用工具
            tools = self._prepare_tools()
            tool_result, tool_use = await self._check_tool_usage(tools)

            if tool_use:
                return await self._handle_tool_response(tool_result)
            elif self.kb_list:
                return await self._workflow_knowledge_response()
            else:
                return await self._handle_simple_response()

        except Exception as e:
            logger.exception(f"执行智能体调用失败: {e}")
            raise

    def _prepare_tools(self) -> list:
        """准备工具列表"""
        tools = []
        for tool_info in self.tool_list:
            tool_parm = tool_info["tool_parm"]
            tool_function = tool_parm["function"]
            tool_function["parameters"] = tool_parm["function"].get("parameters", {})
            tools.append({"type": "function", "function": tool_function})
        return tools

    async def _check_tool_usage(self, tools: list) -> tuple[str, bool]:
        """检查工具使用情况"""
        if not tools:
            return "", False

        return await AgentService.tool_agent(self.chat_request, self.params, self.model_params, tools, self.tool_list)

    async def _handle_tool_response(self, tool_result: str) -> EventSourceResponse:
        """处理工具响应"""
        self._save_talk_data()
        final_prompt = PromptBuilder.build_tool_prompt(
            self.prompt, tool_result, self.params.system_prompts, self.history_system_prompts
        )
        return await self._create_stream_response(final_prompt, history=0)

    # 之前的逻辑
    # async def _handle_knowledge_response(self) -> EventSourceResponse:
    #     """处理知识库响应"""
    #     docs, self.new_source = await knowledge_retrieval(
    #         self.params, self.agent_config["recall_setting"], self.kb_list
    #     )
    #
    #     self._save_talk_data()
    #     prompt_answer = PromptBuilder.build_knowledge_prompt(
    #         self.prompt, docs, self.params.system_prompts, self.history_system_prompts
    #     )
    #     return await self._create_stream_response(prompt_answer)
    async def _handle_knowledge_response(self) -> EventSourceResponse:
        """处理知识库响应"""
        if self.is_question_rewriting:  # 为true,问题改写
            # 同义词扩展
            logger.info("同义词扩展")
            synonym = SimpleNamespace(synonym=self.synonym_list)
            KnowledgeRetrieval1 = KnowledgeRetrievalLLMQA(synonym, {})
            self.rewrite_query, self.retrieval_query = await KnowledgeRetrieval1.synonym_rewrite(
                self.db,
                self.params.input,
                self.account_id,
                self.team_code,
            )
            logger.info("同义词扩展后用户问题：{}", self.retrieval_query)
        docs, self.new_source, docs_notrace = await self._unified_knowledge_retrieval()
        self.docs = docs
        self._save_talk_data()
        # 获取知识溯源配置
        configs = ConfigService.query_config_by_name(db=self.db, config_name="citation")
        # 当无配置或取值异常时，使用默认值
        model_config = {}
        if isinstance(configs, list) and len(configs) > 0 and hasattr(configs[0], "config_description"):
            model_config = configs[0].config_description or {}
        model_list = model_config.get("model_uid", [])
        citation_open = model_config.get("open", 0)
        # 类型保护，确保默认值生效
        if not isinstance(model_list, list):
            model_list = []
        try:
            citation_open = int(citation_open)
        except Exception:
            citation_open = 0
        logger.info("知识溯源配置：{}", model_config)
        if (
            self.model_params["model_uid"] in model_list and citation_open == 1
        ):  # 如果当前模型支持知识溯源，则构建知识溯源prompt
            prompt_answer = PromptBuilder.build_knowledgeTrace_prompt(
                self.prompt, docs, self.params.system_prompts, self.history_system_prompts
            )
        else:
            prompt_answer = PromptBuilder.build_knowledge_prompt(
                self.prompt, docs_notrace, self.params.system_prompts, self.history_system_prompts
            )
        return await self._create_stream_response(prompt_answer)

    async def _workflow_knowledge_response(self) -> EventSourceResponse:
        """处理知识库响应,工作流智能体不溯源"""
        if self.is_question_rewriting:  # 为true,问题改写
            # 同义词扩展
            logger.info("同义词扩展")
            synonym = SimpleNamespace(synonym=self.synonym_list)
            KnowledgeRetrieval1 = KnowledgeRetrievalLLMQA(synonym, {})
            self.rewrite_query, self.retrieval_query = await KnowledgeRetrieval1.synonym_rewrite(
                self.db,
                self.params.input,
                self.account_id,
                self.team_code,
            )
            logger.info("同义词扩展后用户问题：{}", self.rewrite_query)
        docs, self.new_source, docs_notrace = await self._unified_knowledge_retrieval()
        self.docs = docs
        self._save_talk_data()
        prompt_answer = PromptBuilder.build_knowledge_prompt(
            self.prompt, docs_notrace, self.params.system_prompts, self.history_system_prompts
        )
        return await self._create_stream_response(prompt_answer)

    async def _unified_knowledge_retrieval(self):
        """统一使用 knwolege_retrieval 方法进行知识库检索"""
        try:
            all_docs = []
            results=[]
            all_sources = []
            # 初始化 docs，避免在无检索结果时出现未赋值错误
            docs = ""
            docs_notrace = ""

            # 读取agent配置的召回数量、是否重排等参数
            if self.agent_config:
                recall_num = self.agent_config["recall_setting"].get("recall_num", None)
                if self.agent_config["recall_setting"]["is_rerank"]:
                    rerank_model = self.agent_config["recall_setting"]["rerank_model"]
                    rerank_id = self.agent_config["recall_setting"]["rerank_id"]
                    top_k = self.agent_config["recall_setting"]["top_k"]
                else:
                    rerank_model = ""
                    rerank_id = ""

            # 遍历所有知识库，逐个调用 knwolege_retrieval
            for kb in self.kb_list:
                # 构建检索参数

                retrieval_params = KnowledgeRetrivalInfo(
                    id=kb["id"],
                    kb_name=kb["kb_name"],
                    user_query=self.retrieval_query if self.retrieval_query else self.params.input,
                    rerank_model=kb.get("rerank_model", ""),
                    rerank_id=kb.get("rerank_id", ""),
                    recall_num=kb.get("recall_num", 10),
                    rerank_num=kb.get("rerank_num", 3),
                    score=kb.get("score", 0.1),
                    enhance_rounds=kb.get("enhance_rounds", 0),
                    search_type=kb.get("search_type", "semantic"),
                    fusion_weights=kb.get("fusion_weights", None),
                )

                # 调用统一的检索方法
                response = await knwolege_retrieval(retrieval_params)

                # 解析响应
                if response.body.decode() and "code" in response.body.decode():
                    import json

                    response_data = json.loads(response.body.decode())
                    if response_data.get("code") == 200:
                        results = response_data.get("data", {}).get("results", [])

                        # 处理检索结果
                        for result in results:
                            # all_docs.append(result["chunk_content"])
                            docs_index = []
                            for sub_retrival_info in result["child_docs"]:
                                sub_retrival_info = sub_retrival_info["entity"]
                                docs_index.append(int(sub_retrival_info.get("number")))
                            result["child_docs"] = docs_index

                            # 构建统一的 source 数据结构
                            source_item = {
                                "chunk_content": result["chunk_content"],
                                "recall_score": result["recall_score"]
                                if result["recall_score"] > 0
                                else result["recall_score"],
                                "reference_file": result["file_name"],
                                "reference_node": result["reference_node"],  # 可以从 reference_node 中提取
                                "file_urls": result["file_urls"],
                                "reference_chunk_id": result["number"],
                                "page": result["page"],
                                "row": result["row"],
                                # "location": [],  # 可以从 reference_node 中提取
                                # "abandon_area": {},  # 可以从 reference_node 中提取
                                "recall_index": result["recall_index"],
                                "child_docs": result["child_docs"],
                                "reference_kb_id": kb["id"],
                                "reference_kb_name": kb["kb_name"],
                                "convert_path": result.get("convert_path", ""),
                                "remove_image_path": result.get("remove_image_path", ""),
                                "file_id": result.get("file_id", ""),
                                "chunk_id": result.get("chunk_id", ""),
                            }
                            all_sources.append(source_item)

                        # if len(results) > 0:

            # 后处理知识检索结果(召回数量、是否重排)
            if self.agent_config["recall_setting"]["is_rerank"] and len(results)!=0:
                content = [item["chunk_content"] for item in all_sources]
                rerank_id = self.agent_config["recall_setting"]["rerank_id"]
                rerank_results = RerankUtil(rerank_id=rerank_id).socre_rerank(
                    model_uid=rerank_model,
                    documents=content,
                    query=self.params.input,
                    top_n=top_k,
                    return_documents=True,
                    threshold=self.agent_config["recall_setting"]["score"],
                )
                sorted_results = sorted(rerank_results, key=lambda x: x["relevance_score"], reverse=True)
                final_sources = []
                for result in sorted_results:
                    source_item = all_sources[result["index"]]
                    source_item["rerank_score"] = result["relevance_score"]
                    source_item["rerank_index"] = result["index"]
                    final_sources.append(source_item)

            else:
                sorted_sources = sorted(all_sources, key=lambda x: x["recall_score"], reverse=True)
                if recall_num is not None:
                    final_sources = sorted_sources[:recall_num]
                else:
                    final_sources = sorted_sources
            if final_sources:
                all_docs = KnowledgeRetrievalLLMQA._build_chunk_content_with_images(final_sources)
                new_list = [item["chunk_content"] for item in all_docs if "chunk_content" in item]
                docs_notrace = new_list
                docs = KnowledgeRetrievalLLMQA._build_chunk_content(all_docs)

            return docs, final_sources, docs_notrace

        except Exception as e:
            logger.exception(f"智能体调用知识库检索失败: {e}")
            raise

    async def _handle_simple_response(self) -> EventSourceResponse:
        """处理简单响应"""
        self._save_talk_data()
        prompt_answer = PromptBuilder.build_simple_prompt(
            self.prompt, self.params.system_prompts, self.history_system_prompts
        )
        return await self._create_stream_response(prompt_answer)

    def _save_talk_data(self):
        """保存对话数据"""
        self.talk_id = ChatConversationService.save_talk_data_agent(
            db=self.db,
            conversation_id=self.params.conversation_id,
            account_id=self.account_id,
            token="",
            question=self.params.input,
            kb_id="",
            model_id="",
            ag_id=self.params.agent_id,
            type=self.conversation_type,
            system_prompt=self.params.system_prompts,
        )

        ChatConversationService.save_talk_data_file_stop(
            db=self.db,
            conversation_id=self.params.conversation_id,
            account_id=self.account_id,
            type=self.conversation_type,
            talk_id=self.talk_id,
            talk_num=0,
        )

    async def _create_stream_response(self, prompt: str, history: Optional[int] = None) -> EventSourceResponse:
        """创建流式响应"""

        async def stream_generator():
            try:
                final_result = ""
                # 获取模型思考能力配置
                model_config = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(self.model_params["id"])
                )
                is_think = model_config.get("is_think", False)

                # 创建流处理器
                handler = OptimizedStreamResponseHandler(self.db, self.talk_id, self.start_time, self.chat_request)
                # 注入模型参数，避免 handler 访问未定义属性
                handler.model_params = self.model_params
                # 创建LLM服务
                llm_service = OpenAILLMService(id=self.model_params["id"])

                # 构建请求参数
                request_params = ChatCompletionRequestParams_v1(
                    model_uid=self.model_params["model_uid"],
                    temperature=self.model_params["temperature"],
                    history=history if history is not None else self.model_params["history"],
                    max_token_length=self.model_params["max_token_length"],
                    system_prompts=prompt,
                    conversation_id=self.params.conversation_id,
                    retrival_params={
                        "kb_name": "",
                        "user_query": self.retrieval_query
                        if self.retrieval_query
                        else self.params.input,  # 知识库检索的query
                        "rerank_model": "",
                        "recall_num": 0,
                        "rerank_num": 0,
                    },
                    presence_penalty=self.model_params["presence_penalty"],
                    frequency_penalty=self.model_params["frequency_penalty"],
                )
                # 获取知识溯源配置
                configs = ConfigService.query_config_by_name(db=self.db, config_name="citation")
                # 当无配置或取值异常时，使用默认值
                model_config = {}
                if isinstance(configs, list) and len(configs) > 0 and hasattr(configs[0], "config_description"):
                    model_config = configs[0].config_description or {}
                model_list = model_config.get("model_uid", [])
                citation_open = model_config.get("open", 0)
                # 类型保护，确保默认值生效
                if not isinstance(model_list, list):
                    model_list = []
                try:
                    citation_open = int(citation_open)
                except Exception:
                    citation_open = 0
                logger.info("知识检索+模型配置花费的时间{}", time.time() - self.start_time)
                # 处理流式响应
                start_time = time.time()
                if self.rewrite_query:
                    async for chunk in await llm_service.stream_chat_v1_with_Synonyms(
                        db=self.db,
                        request=request_params,
                        chunk_content="",
                        type=self.conversation_type,
                        model_list=model_list,
                        rewrite_query=self.rewrite_query,
                    ):
                        results = await handler.handle_chunk(
                            chunk,
                            self.params,
                            self.conversation_type,
                            self.new_source if self.need_new_source else [],
                            is_think,
                            model_list=model_list,
                            citation_open=citation_open,
                        )
                        if results == "STOP":
                            break
                        elif results:
                            for result in results:
                                # final_result += result.get("token")
                                yield f"{json.dumps(RetUtil.response_stream(data=result), ensure_ascii=False)}"
                else:
                    async for chunk in await llm_service.stream_chat_v1_with_Synonyms(
                        db=self.db,
                        request=request_params,
                        chunk_content="",
                        type=self.conversation_type,
                        model_list=model_list,
                        rewrite_query="",
                    ):
                        results = await handler.handle_chunk(
                            chunk,
                            self.params,
                            self.conversation_type,
                            self.new_source if self.need_new_source else [],
                            is_think,
                            model_list=model_list,
                            citation_open=citation_open,
                        )

                        if results == "STOP":
                            break
                        elif results:
                            for result in results:
                                # final_result += result.get("token")
                                yield f"{json.dumps(RetUtil.response_stream(data=result), ensure_ascii=False)}"

                # 确保所有数据都已保存
                # 流式输出正常完成日志
                logger.info(
                    "流式输出完成 | 总耗时={:.3f}s | conversation_id={}",
                    time.time() - start_time,
                    self.params.conversation_id,
                )
                await handler.finalize(self.params, self.conversation_type, self.new_source)

            except Exception as e:
                logger.exception(f"流式响应处理异常: {e}")
                # 流式输出异常耗时日志
                logger.exception(
                    "流式输出异常 | 总耗时={:.3f}s | conversation_id={} | 错误={}",
                    time.time() - self.start_time,
                    self.params.conversation_id,
                    str(e),
                )
                if self.talk_id:
                    ChatConversationService.delete_talk(db=self.db, talk_id=self.talk_id)
                error_result = {"token": "系统繁忙,请稍后再试", "talk_id": self.talk_id, "new_source": self.new_source if self.need_new_source else []}
                yield f"{json.dumps(RetUtil.response_stream(data=error_result), ensure_ascii=False)}"
                raise

        if self.is_workflow:
            return stream_generator()
        else:
            return EventSourceResponse(stream_generator())
