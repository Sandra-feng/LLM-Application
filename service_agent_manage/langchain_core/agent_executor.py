#!/usr/bin/env python
"""
统一的智能体执行器
合并 BaseAgentExecutor 和 TianceReActAgent 的功能
"""

from collections.abc import AsyncGenerator
from typing import Optional

from bson import ObjectId
from fastapi import Request
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from sqlalchemy.orm import Session

from base_configs.model_config import ModelConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.mysql_util import query2dict_status
from base_utils.redis_util import RedisUtil
from service_agent_manage.entity.agent import CallAgentParams
from service_agent_manage.langchain_core.config_models import AgentRuntimeConfig
from service_agent_manage.langchain_core.tools import DEFAULT_TOOL_MIDDLEWARE, ToolFactory
from service_model_manage.service.chat_db_service import ChatConversationService
from service_permission_manage.entity.config_entity import ConfigQueryEntity
from service_permission_manage.service.config_service import ConfigService
from service_prompt_manage.model.prompt_info_model import Prompt_Model


class AgentExecutor:
    """
    统一的智能体执行器

    职责：
    1. 加载和管理智能体配置
    2. 初始化 LLM 和工具
    3. 构建 Agent 和消息历史
    4. 执行流式输出
    """

    def __init__(self):
        """初始化执行器"""
        self.config: Optional[AgentRuntimeConfig] = None
        self.agent = None
        self.messages = []
        self.talk_id: Optional[str] = None
        self.db: Optional[Session] = None
        self.request: Optional[Request] = None
        self.conversation_type: int = 2
        self.kb_config: Optional[dict] = None  # 知识库配置（用于预检索）

    async def initialize(
        self,
        params: CallAgentParams,
        request: Request,
        db: Session,
        conversation_type: int = 2,
    ) -> bool:
        """
        初始化执行器

        Args:
            params: 智能体调用参数
            request: FastAPI 请求对象
            db: 数据库会话
            conversation_type: 对话类型

        Returns:
            是否初始化成功
        """
        try:
            self.db = db
            self.request = request
            self.conversation_type = conversation_type

            logger.info(f"开始初始化 Agent | agent_id={params.agent_id}")

            # 1. 加载智能体配置
            agent_config = await self._load_agent_config(params.agent_id)
            if not agent_config:
                return False

            # 2. 加载运行时选项（需要先获取以便配置 prompt）
            enable_think, enable_citation ,enable_tool= self._load_runtime_options(agent_config.get("model_params", {}), db)

            # 3. 加载提示词（根据 enable_citation 决定是否添加引用规则）
            prompt = await self._load_prompt(agent_config, enable_citation, agent_params=params.agent_params)
            if prompt is None:
                return False

            # 4. 加载工具和知识库配置
            tools, kb_config = await self._load_tools(agent_config, request, db, request.state.account_id)
            if tools is None:
                return False

            # 保存知识库配置用于后续预检索
            self.kb_config = kb_config

            # 5. 构建运行时配置（kb_sources 初始为空，预检索后更新）
            self.config = AgentRuntimeConfig(
                agent_id=params.agent_id,
                conversation_id=params.conversation_id,
                account_id=request.state.account_id,
                team_code=agent_config.get("team_code", ""),
                agent_config=agent_config,
                model_params=agent_config.get("model_params", {}),
                prompt=prompt,
                enable_think=enable_think,
                enable_citation=enable_citation,
                enable_tool=enable_tool,
                history_count=agent_config.get("model_params", {}).get("history", 0),
                tools=tools,
                kb_sources=[],  # 初始为空，预检索后更新
            )

            # 6. 初始化 LLM
            llm = self._init_llm()
            if not llm:
                return False

            # 7. 创建 Agent
            # checkpointer = get_global_checkpointer().get_saver()
            if enable_tool:
                self.agent = create_agent(
                    model=llm,
                    tools=tools,
                    system_prompt=prompt,
                    checkpointer=None,
                    middleware=DEFAULT_TOOL_MIDDLEWARE,
                )
            else:
                self.agent = create_agent(
                    model=llm,
                    system_prompt=prompt,
                    checkpointer=None,
                    middleware=DEFAULT_TOOL_MIDDLEWARE,
                )


            # 8. 构建消息历史
            self.messages = await self._build_messages(params, db)

            # 9. 创建对话记录
            self.talk_id = ChatConversationService.save_talk_data_agent(
                db=db,
                conversation_id=params.conversation_id,
                account_id=request.state.account_id,
                token="",
                question=params.input,
                kb_id="",
                model_id="",
                ag_id=params.agent_id,
                type=conversation_type,
                system_prompt=prompt,
            )

            logger.info(f"Agent 初始化成功 | talk_id={self.talk_id}")
            return True

        except Exception as e:
            logger.exception(f"初始化 Agent 失败: {str(e)}")
            return False

    async def execute_stream(self) -> AsyncGenerator:
        """
        执行流式输出

        Yields:
            Agent 流式事件
        """
        if not self.config or not self.agent or not self.talk_id:
            raise RuntimeError("Agent 未初始化")

        try:
            logger.info(f"Agent 开始执行 | talk_id={self.talk_id}")

            # 构建配置
            config = self.config.get_agent_config(talk_id=self.talk_id)

            # 流式执行
            async for event in self.agent.astream(
                {"messages": self.messages},
                config=config,
                stream_mode="messages",
            ):
                yield event

        except Exception as e:
            logger.exception(f"Agent 执行异常: {str(e)}")
            raise

    async def execute(self) -> dict:
        """
        执行非流式输出，等待完整结果

        Returns:
            包含完整响应的字典，格式：
            {
                "messages": [...],  # 完整的消息列表
                "content": "...",   # 最终的文本内容
            }
        """
        if not self.config or not self.agent or not self.talk_id:
            raise RuntimeError("Agent 未初始化")

        try:
            logger.info(f"Agent 开始执行（非流式） | talk_id={self.talk_id}")

            # 构建配置
            config = self.config.get_agent_config(talk_id=self.talk_id)

            # 使用 ainvoke 获取完整结果
            result = await self.agent.ainvoke(
                {"messages": self.messages},
                config=config,
            )

            # 提取最终的文本内容
            final_content = ""
            if result and "messages" in result:
                # 获取最后一条消息的内容
                last_message = result["messages"][-1] if result["messages"] else None
                if last_message and hasattr(last_message, "content"):
                    final_content = last_message.content

            logger.info(f"Agent 执行完成（非流式） | talk_id={self.talk_id} | 内容长度: {len(final_content)}")

            return {
                "messages": result.get("messages", []),
                "content": final_content,
            }

        except Exception as e:
            logger.exception(f"Agent 执行异常（非流式）: {str(e)}")
            raise

    async def _load_agent_config(self, agent_id: str) -> Optional[dict]:
        """加载智能体配置"""
        try:
            agent_config = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION,
                doc_id=ObjectId(agent_id),
            )

            if not agent_config:
                logger.error(f"智能体配置不存在: {agent_id}")
                return None

            # 设置模型参数默认值
            model_params = agent_config.get("model_params", {})
            if model_params.get("presence_penalty") is None:
                model_params["presence_penalty"] = 0
            if model_params.get("frequency_penalty") is None:
                model_params["frequency_penalty"] = 0

            # 验证配置
            if "知识库ID不存在" in str(agent_config.get("kb_list", [])):
                logger.error("知识库ID不存在")
                return None
            if "工具ID不存在" in str(agent_config.get("tool_list", [])):
                logger.error("工具ID不存在")
                return None

            # 加载团队代码
            agent_info = MongodbUtil.query_doc_by_id(CollectionConfig.AGENT_COLLECTION, doc_id=ObjectId(agent_id))
            agent_config["team_code"] = agent_info.get("team_code", "") if agent_info else ""

            return agent_config

        except Exception as e:
            logger.exception(f"加载智能体配置失败: {str(e)}")
            return None

    async def _load_prompt(
        self, agent_config: dict, enable_citation: bool = False, agent_params: Optional[dict] = None
    ) -> Optional[str]:
        """
        加载提示词

        Args:
            agent_config: Agent 配置
            enable_citation: 是否启用 citation（如果启用，在 prompt 中添加引用规则）
        """
        try:
            prompt_id = agent_config.get("prompt_id", "")

            if prompt_id:
                prompt_info = query2dict_status(
                    self.db.query(Prompt_Model)
                    .filter(Prompt_Model.prompt_id == prompt_id, Prompt_Model.status != 0)
                    .first(),
                    Prompt_Model,
                )
                base_prompt = prompt_info.get("prompt_content", "") if prompt_info else ""
                if base_prompt == "":
                    base_prompt = "你是一个有帮助的助手。"
            else:
                base_prompt = agent_config.get("prompt", "你是一个有帮助的助手。")
                if base_prompt == "":
                    base_prompt = "你是一个有帮助的助手。"

            # 如果启用 citation，在 prompt 中添加引用规则
            if enable_citation:
                prompt = f"""{base_prompt}

⚠️ 重要：知识引用规范
严格注意：你需要判断用户的提问是否涉及知识库内容，如果涉及，则必须遵循以下引用规范，如果知识库的内容与用户问题无关，以解决用户问题为准，不要引用知识库内容。

当回答涉及知识库内容时，必须遵循以下引用规范：
1. **引用格式**：使用 [citation:数字] 格式标注引用，例如：太阳系有8颗行星 [citation:1]
2. **引用位置**：在使用知识库内容的句子后立即标注
3. **合并引用**：多个来源支持同一句话时合并标注，例如：[citation:1,2,3]
4. **编号对应**：引用编号必须对应知识库检索结果中的"引用编号"
5. **严禁杜撰**：不得编造不存在的引用编号

回答规则：

- 如果用户问题与知识库信息相关，优先结合并整合知识库内容回答。

- 如果知识库信息无关或缺失，也要独立回答，不能拒答。

- 能用工具解决的问题，应主动判断并正确调用工具。
"""
            else:
                prompt = base_prompt

            # 进行参数替换
            if agent_params and agent_params.get("prompt_params"):
                prompt = ChatConversationService.prompt_params(agent_params, prompt)

            logger.info(f"提示词加载完成 | 长度: {len(prompt)} | citation增强: {enable_citation}")
            return prompt

        except Exception as e:
            logger.exception(f"加载提示词失败: {str(e)}")
            return None

    async def _load_tools(
        self, agent_config: dict, request: Request, db: Session, account_id: str
    ) -> tuple[Optional[list], Optional[dict]]:
        """
        加载工具

        Returns:
            (tools, kb_config): 工具列表和知识库配置字典
        """
        try:
            # 只加载 HTTP 工具
            tools = await self._load_agent_tools(agent_config, request)

            # 收集知识库配置（不创建工具）
            kb_config = await self._load_kb_config(agent_config, db, account_id)

            logger.info(f"工具加载完成 | HTTP工具数: {len(tools)} | 知识库配置: {kb_config is not None}")
            return tools, kb_config

        except Exception as e:
            logger.exception(f"加载工具失败: {str(e)}")
            return None, None

    async def _load_agent_tools(self, agent_config: dict, request: Request) -> list:
        """加载 Agent 工具"""
        tools = []
        tool_list = agent_config.get("tool_list", [])

        if not tool_list:
            return tools

        # 获取 Token
        token = request.headers.get("token")
        if not token:
            redis = request.app.state.redis_pool
            token_info = await RedisUtil.get_cached_data(key=self.request.state.account_id, redis=redis)
            if token_info:
                token = token_info.get("value")

        # 处理新的二维数组格式
        system_tools_count = 0
        mcp_tools_count = 0

        # 用于分组 MCP 工具的字典，key: server_id, value: list[tool_name]
        mcp_tools_map = {}

        for tool_item in tool_list:
            try:
                if not isinstance(tool_item, list) or len(tool_item) != 3:
                    logger.warning(f"工具配置格式错误: {tool_item}")
                    continue

                tool_type = tool_item[0]
                second_param = tool_item[1]
                third_param = tool_item[2]

                if tool_type == "system_tools":
                    # 处理系统工具（内置和自定义）
                    tool_id = third_param
                    logger.info(f"加载系统工具: {tool_id} (类型: {'内置' if second_param == '1' else '自定义'})")

                    # 从 MongoDB 获取工具配置
                    tool_doc = MongodbUtil.query_doc_by_id(
                        collection_name=CollectionConfig.TOOL_INFO_COLLECTION, doc_id=tool_id
                    )

                    if tool_doc:
                        http_tool = await ToolFactory.create_http_tool(
                            tool_config=tool_doc, token=token, use_new_api=True
                        )
                        tools.append(http_tool)
                        system_tools_count += 1
                    else:
                        logger.warning(f"工具配置不存在: {tool_id}")

                elif tool_type == "mcp_tools":
                    # 分组 MCP 工具
                    server_id = second_param
                    tool_name = third_param

                    if server_id not in mcp_tools_map:
                        mcp_tools_map[server_id] = []
                    mcp_tools_map[server_id].append(tool_name)

                else:
                    logger.warning(f"未知的工具类型: {tool_type}")

            except Exception as e:
                logger.exception(f"加载工具失败: {tool_item} | 错误: {str(e)}")

        # 批量处理 MCP 工具 - 一次性连接所有服务器
        if mcp_tools_map:
            try:
                logger.info(f"加载 MCP 工具 | 服务器数量: {len(mcp_tools_map)} | 工具配置: {mcp_tools_map}")

                # 一次性连接所有 MCP 服务器
                mcp_tools = await ToolFactory.create_mcp_tool(mcp_tools_config=mcp_tools_map)
                tools.extend(mcp_tools)
                mcp_tools_count += len(mcp_tools)

            except Exception as e:
                logger.exception(f"加载 MCP 工具失败 | 错误: {str(e)}")

        logger.info(f"工具加载完成 | 系统工具: {system_tools_count} | MCP工具: {mcp_tools_count} | 总计: {len(tools)}")
        return tools

    async def _load_kb_config(self, agent_config: dict, db: Session, account_id: str) -> Optional[dict]:
        """
        加载知识库配置（用于预检索）

        Returns:
            知识库配置字典，包含：
            - kb_configs: 知识库配置列表
            - recall_setting: 召回设置
            - enable_synonym: 是否启用同义词
            - synonym_list: 同义词列表
        """
        kb_list = agent_config.get("kb_list", [])
        if not kb_list:
            return None

        logger.info(f"加载知识库配置 | 知识库数量: {len(kb_list)}")

        # 构建知识库配置
        kb_configs = []
        for kb_id in kb_list:
            try:
                kb_result = MongodbUtil.query_doc_by_id(CollectionConfig.KB_COLLECTION, doc_id=ObjectId(kb_id))

                if kb_result:
                    kb_configs.append(
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
            except Exception as e:
                logger.exception(f"加载知识库配置失败: {kb_id} | 错误: {str(e)}")

        if not kb_configs:
            return None

        # 获取同义词配置
        synonym_list = []
        enable_synonym = agent_config.get("is_question_rewriting", False)

        if enable_synonym:
            synonym_binding_info = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.SYNONYM_BINDING,
                search_condition={"id": agent_config.get("_id", ""), "type": 0},
            )
            for item in synonym_binding_info:
                synonym_list = item.get("synonym_id_list", [])
                break

        return {
            "kb_configs": kb_configs,
            "recall_setting": agent_config.get("recall_setting", {}),
            "enable_synonym": enable_synonym,
            "synonym_list": synonym_list,
            "db": db,
            "account_id": account_id,
            "team_code": agent_config.get("team_code", ""),
        }

    async def _pre_retrieve_knowledge(self, query: str) -> dict:
        """
        执行知识库预检索

        Args:
            query: 用户查询

        Returns:
            检索结果字典，包含：
            - docs: 格式化的文档内容
            - sources: 知识库来源列表（用于溯源）
            - docs_notrace: 不带溯源标记的文档内容
            - retrieval_query: 实际检索查询（可能经过同义词扩展）
        """
        # 如果没有知识库配置，返回空结果
        if not self.kb_config:
            logger.info("未配置知识库，跳过预检索")
            return {"docs": "", "sources": [], "docs_notrace": [], "retrieval_query": query}

        try:
            import time

            start_time = time.time()

            logger.info(f"开始知识库预检索 | 查询: {query[:100]}")

            # 复用现有的知识库检索逻辑
            from service_agent_manage.langchain_core.tools.knowledge_tool import (
                KnowledgeBaseConfig,
                KnowledgeRetrieverConfig,
                _retrieve_knowledge,
            )

            # 转换为 Pydantic 模型
            kb_configs_typed = [KnowledgeBaseConfig(**kb) for kb in self.kb_config["kb_configs"]]

            config = KnowledgeRetrieverConfig(
                kb_configs=kb_configs_typed,
                recall_setting=self.kb_config["recall_setting"],
                enable_synonym=self.kb_config["enable_synonym"],
                synonym_list=self.kb_config["synonym_list"],
                db=self.kb_config["db"],
                account_id=self.kb_config["account_id"],
                team_code=self.kb_config["team_code"],
            )

            # 执行检索
            result = await _retrieve_knowledge(query, config)

            elapsed = round(time.time() - start_time, 2)
            sources_count = len(result.get("sources", []))
            docs_length = len(result.get("docs", ""))

            logger.info(f"知识库预检索完成 | 耗时: {elapsed}s | 检索结果数: {sources_count} | 内容长度: {docs_length}")

            return result

        except Exception as e:
            logger.exception(f"知识库预检索失败: {str(e)}")
            # 降级：返回空结果，不影响主流程
            return {"docs": "", "sources": [], "docs_notrace": [], "retrieval_query": query}

    def _load_runtime_options(self, model_params: dict, db: Session) -> tuple[bool, bool,bool]:
        """加载运行时选项"""
        enable_think = False
        enable_citation = False
        enable_tool=False

        # 加载 Think 配置
        model_id = model_params.get("id")
        model_uid = model_params.get("model_uid")
        if model_id:
            try:
                model_config = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    doc_id=ObjectId(model_id),
                )
                enable_think = model_config.get("is_think", False) if model_config else False
            except Exception as err:
                logger.warning(f"读取模型配置失败 | model_id={model_id} | err={err}")

        # 加载 Citation 配置
        try:
            # 获取知识溯源配置
            citation_open = 0
            model_list = []
            ci_rows = ConfigService.query_config_by_key(db=db, config_key="citation")
            citation_raw = ci_rows[0].config_value if ci_rows else "0"
            citation_open = int(citation_raw)
            model_rows = ConfigService.query_config_by_key(db=db, config_key="citation_model")
            model_raw = model_rows[0].config_value if model_rows else ""
            model_list = [m.strip() for m in model_raw.split(",") if m.strip()] if model_raw else []
            enable_citation = model_params.get("model_uid") in model_list and citation_open == 1
        except Exception as err:
            logger.warning(f"读取知识溯源配置失败 | err={err}")
        try:
            rows = ConfigService.query_config_by_key(db=db, config_key="tools_support_model")
            raw = rows[0].config_value if rows else ""
            models = [m.strip() for m in raw.split(",") if m.strip()] if raw else []
            if model_uid in models:
                enable_tool = True
        except Exception as err:
            logger.warning(f"读取工具溯源配置失败 | err={err}")


        return enable_think, enable_citation,enable_tool

    def _init_llm(self) -> Optional[BaseChatModel]:
        """初始化 LLM"""
        try:
            model_params = self.config.model_params
            model_id = model_params.get("id")

            if not model_id:
                logger.error("未找到模型 ID")
                return None

            # 从 MongoDB 获取模型配置
            model_config = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                doc_id=ObjectId(model_id),
            )

            if not model_config:
                logger.error(f"模型配置不存在: {model_id}")
                return None

            # 构建 LLM
            if model_config.get("is_external"):
                api_key = model_config.get("api_key", "not-needed")
                base_url = model_config.get("api_url")
            else:
                api_key = ModelConfig.LLM_API_KEY
                base_url = ModelConfig.LLM_API_BASE

            llm = ChatOpenAI(
                model=model_params.get("model_uid", "not-needed"),
                temperature=model_params.get("temperature", 0.7),
                max_tokens=model_params.get("max_token_length", 2048),
                api_key=api_key,
                base_url=base_url,
                streaming=True,
            )

            logger.info(f"LLM 初始化成功 | 模型: {model_params.get('model_uid')}")
            return llm

        except Exception as e:
            logger.exception(f"初始化 LLM 失败: {str(e)}")
            return None

    async def _build_messages(self, params: CallAgentParams, db: Session) -> list:
        """
        构建消息列表（包含预检索和上下文增强）

        执行流程：
        1. 加载历史消息
        2. 执行知识库预检索
        3. 如果有检索结果，增强用户消息
        4. 更新 kb_sources 用于溯源
        """
        messages = []

        try:
            # 1. 加载历史消息
            history_count = self.config.history_count

            if history_count > 0:
                talk_info = ChatConversationService.check_talk_info_history(
                    db=db, conversation_id=params.conversation_id
                )

                if len(talk_info) > history_count:
                    chatbot = talk_info[-history_count:]
                else:
                    chatbot = talk_info

                # 转换为 LangChain 消息格式
                for conversation in chatbot:
                    user_msg = conversation.get("user", "")
                    assistant_msg = conversation.get("assistant", {})

                    if user_msg:
                        messages.append(HumanMessage(content=user_msg))

                    if isinstance(assistant_msg, dict):
                        content = assistant_msg.get("content", "")
                    else:
                        content = assistant_msg

                    if content:
                        messages.append(AIMessage(content=content))

            # 2. 执行知识库预检索
            kb_result = await self._pre_retrieve_knowledge(params.input)

            # 3. 构建用户消息（如果有检索结果则增强）
            user_message_content = self._enhance_user_message(params.input, kb_result)
            messages.append(HumanMessage(content=user_message_content))

            # 4. 更新 kb_sources 用于溯源
            kb_sources = kb_result.get("sources", [])
            if kb_sources:
                self.config.kb_sources = kb_sources

            logger.info(f"消息构建完成 | 消息数: {len(messages)} | 知识库增强: {bool(kb_sources)}")
            return messages

        except Exception as e:
            logger.exception(f"构建消息失败: {str(e)}")
            # 降级：只返回当前输入
            return [HumanMessage(content=params.input)]

    def _enhance_user_message(self, original_query: str, kb_result: dict) -> str:
        """
        增强用户消息（注入知识库检索结果）

        根据是否启用 citation 选择不同格式的知识库内容：
        - 启用 citation: 使用带编号的 docs（包含 [citation:1] 标记）
        - 不启用 citation: 使用不带编号的 docs_notrace

        Args:
            original_query: 原始用户查询
            kb_result: 知识库检索结果

        Returns:
            增强后的用户消息
        """
        # 根据 citation 配置选择正确的文档格式
        if self.config.enable_citation:
            # 启用 citation：使用带编号的 docs
            docs = kb_result.get("docs", "")
        else:
            # 不启用 citation：使用不带编号的 docs_notrace
            docs_notrace_list = kb_result.get("docs_notrace", [])
            if docs_notrace_list:
                docs = "\n\n".join(docs_notrace_list)
            else:
                docs = ""

        # 如果没有检索结果，直接返回原始查询
        if not docs or not docs.strip():
            return original_query

        # 构建增强消息（根据 citation 配置使用不同的提示词格式）
        if self.config.enable_citation:
            # 启用 citation 时的格式（引用规则已在 system_prompt 中说明）
            enhanced_message = f"""【用户问题】
{original_query}

【知识库检索结果】
{docs}

请根据知识库内容回答问题，并按照引用规范标注来源。"""
        else:
            # 不启用 citation 时的格式
            enhanced_message = f"""【用户问题】
{original_query}

【知识库检索结果】
{docs}

请根据上述知识库内容和你自身掌握的通用知识，整合信息，准确、有帮助地回答用户的问题。如信息不足，请直接说明。"""

        return enhanced_message
