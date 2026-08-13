#!/usr/bin/env python
"""
工具工厂 - 动态创建和管理 LangChain 工具
支持函数式工具、MCP 工具和工具注册机制
"""

from collections.abc import Callable
from typing import Any, Optional, Union

from bson import ObjectId
from fastapi import Request
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from loguru import logger
from sqlalchemy.orm import Session

from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.redis_util import RedisUtil
from service_agent_manage.langchain_core.tools.http_tool import (
    HttpToolConfig,
    HttpToolWrapper,
    create_http_tool,
)
from service_agent_manage.langchain_core.tools.knowledge_tool import (
    KnowledgeBaseConfig,
    KnowledgeRetrieverConfig,
    KnowledgeRetrieverTool,
    create_knowledge_tool,
)


class ToolRegistry:
    """
    工具注册表

    支持工具的动态注册和查找，便于扩展自定义工具
    """

    _registry: dict[str, Callable] = {}

    @classmethod
    def register(cls, tool_type: str, factory: Callable):
        """
        注册工具工厂函数

        Args:
            tool_type: 工具类型（如 "http", "knowledge", "mcp"）
            factory: 工具工厂函数
        """
        cls._registry[tool_type] = factory
        logger.info(f"注册工具类型: {tool_type}")

    @classmethod
    def create(cls, tool_type: str, **kwargs) -> Any:
        """
        创建工具实例

        Args:
            tool_type: 工具类型
            **kwargs: 工具配置参数

        Returns:
            工具实例

        Raises:
            ValueError: 工具类型未注册
        """
        factory = cls._registry.get(tool_type)
        if not factory:
            raise ValueError(f"未注册的工具类型: {tool_type}")

        return factory(**kwargs)

    @classmethod
    def list_types(cls) -> list[str]:
        """列出所有已注册的工具类型"""
        return list(cls._registry.keys())


class ToolFactory:
    """
    工具工厂类

    负责从配置动态创建各类工具：
    - HTTP 工具
    - 知识库检索工具
    - MCP 工具
    - 自定义工具
    """

    @staticmethod
    async def create_http_tool(
        tool_config: dict, token: Optional[str] = None, use_new_api: bool = True
    ) -> Union[BaseTool, HttpToolWrapper]:
        """
        从配置创建 HTTP 工具

        Args:
            tool_config: 工具配置字典
            token: 认证 Token
            use_new_api: 是否使用新的函数式 API（默认 True）

        Returns:
            LangChain Tool 实例或 HttpToolWrapper（向后兼容）
        """
        args_info = tool_config.get("properties_list", [])
        args_schema = {}
        for arg in args_info:
            args_schema[arg["name"]] = {
                "type": arg["type"],
                "required": arg["required"],
                "description": arg["description"],
                "example": arg["example"],
            }

        config = HttpToolConfig(
            tool_name=tool_config["tool_name"],
            description=tool_config.get("description", "HTTP 工具"),
            tool_url=tool_config["url"],
            tool_method=tool_config.get("method", "POST"),
            token=token,
            parameters_schema=args_schema,
        )

        if use_new_api:
            tool = create_http_tool(config)
            logger.info(f"创建 HTTP 工具 (新API): {config.tool_name}")
        else:
            # 向后兼容模式
            tool = HttpToolWrapper(
                name=config.tool_name,
                description=config.description,
                tool_url=config.tool_url,
                tool_method=config.tool_method,
                token=config.token,
                parameters_schema=config.parameters_schema,
            )
            logger.info(f"创建 HTTP 工具 (兼容模式): {config.tool_name}")

        return tool

    @staticmethod
    def create_knowledge_tool(
        kb_configs: list,
        recall_setting: dict,
        enable_synonym: bool = False,
        synonym_list: Optional[list] = None,
        db: Session = None,
        account_id: str = "",
        team_code: str = "",
        use_new_api: bool = True,
    ) -> Union[BaseTool, KnowledgeRetrieverTool]:
        """
        创建知识库检索工具

        Args:
            kb_configs: 知识库配置列表
            recall_setting: 召回设置
            enable_synonym: 是否启用同义词扩展
            synonym_list: 同义词列表
            db: 数据库会话
            account_id: 账户 ID
            team_code: 团队代码
            use_new_api: 是否使用新的函数式 API（默认 True）

        Returns:
            LangChain Tool 实例或 KnowledgeRetrieverTool（向后兼容）
        """
        if use_new_api:
            # 转换为 Pydantic 模型
            kb_configs_typed = [KnowledgeBaseConfig(**kb) for kb in kb_configs]

            config = KnowledgeRetrieverConfig(
                kb_configs=kb_configs_typed,
                recall_setting=recall_setting,
                enable_synonym=enable_synonym,
                synonym_list=synonym_list or [],
                db=db,
                account_id=account_id,
                team_code=team_code,
            )

            tool = create_knowledge_tool(config)
            logger.info(f"创建知识库工具 (新API) | 知识库数量: {len(kb_configs)}")
        else:
            # 向后兼容模式
            tool = KnowledgeRetrieverTool(
                kb_configs=kb_configs,
                recall_setting=recall_setting,
                enable_synonym=enable_synonym,
                synonym_list=synonym_list or [],
                db=db,
                account_id=account_id,
                team_code=team_code,
            )
            logger.info(f"创建知识库工具 (兼容模式) | 知识库数量: {len(kb_configs)}")

        return tool

    @staticmethod
    async def create_mcp_tool(mcp_tools_config: dict) -> list[BaseTool]:
        """
        创建 MCP 工具，支持多服务器连接

        Args:
            mcp_tools_config: MCP 工具配置字典
                {
                    "server_id1": ["tool_name1", "tool_name2"],  # 指定工具列表
                    "server_id2": [],  # 空列表表示加载所有工具
                    ...
                }

        Returns:
            LangChain Tool 实例列表

        Note:
            充分利用 MultiServerMCPClient 的多服务器连接能力，
            一次连接所有服务器，而不是分别为每个服务器创建连接
        """
        try:
            # 构建多服务器配置
            servers = {}
            requested_tools = set()

            for server_id, tool_names in mcp_tools_config.items():
                # 从 MongoDB 获取 MCP 服务器配置
                mcp_config = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.OUTSIDE_MCP_CONFIG, doc_id=server_id
                )

                if not mcp_config:
                    logger.error(f"MCP 服务器配置不存在: {server_id}")
                    continue

                # 处理headers格式转换
                headers = {}
                raw_headers = mcp_config.get("headers", [])
                if isinstance(raw_headers, list):
                    # 将 [{"name": "header-name", "value": "header-value"}] 转换为 {"header-name": "header-value"}
                    for header_item in raw_headers:
                        if isinstance(header_item, dict) and "name" in header_item and "value" in header_item:
                            headers[header_item["name"]] = header_item["value"]
                        else:
                            logger.warning(f"跳过无效的header配置: {header_item}")
                    logger.info(f"Headers转换完成: {headers}")
                elif isinstance(raw_headers, dict):
                    # 如果已经是字典格式，直接使用
                    headers = raw_headers
                else:
                    logger.warning(f"未知的headers格式类型: {type(raw_headers)}")

                servers[mcp_config["name"]] = {
                    "transport": "streamable_http",
                    "url": mcp_config["url"],
                    "headers": headers,
                }

                # 收集请求的工具名称
                requested_tools.update(tool_names)

            if not servers:
                logger.warning("没有可用的 MCP 服务器配置")
                return []

            # 创建单一的多服务器客户端
            client = MultiServerMCPClient(servers)
            all_tools = await client.get_tools()

            logger.info(f"MCP 多服务器连接成功 | 服务器数量: {len(servers)} | 总工具数: {len(all_tools)}")

            # 如果没有指定工具名称，返回所有工具
            if not requested_tools:
                tools = all_tools
                logger.info(f"加载所有 MCP 工具 | 数量: {len(tools)}")
            else:
                # 筛选指定的工具
                tools = [tool for tool in all_tools if tool.name in requested_tools]
                logger.info(
                    f"MCP 工具筛选 | 总数: {len(all_tools)} | 筛选后: {len(tools)} | 请求工具: {list(requested_tools)}"
                )

            for tool in tools:
                logger.info(f"MCP 工具: {tool.name}")

            return tools

        except Exception as e:
            logger.exception(f"创建 MCP 工具失败 | 错误: {str(e)}")
            return []

    @staticmethod
    async def load_agent_tools(
        agent_config: dict,
        request: Request,
        db: Session,
        account_id: str,
        team_code: str,
        use_new_api: bool = True,
    ) -> tuple[list[BaseTool], list]:
        """
        从智能体配置加载所有工具

        Args:
            agent_config: 智能体配置
            request: FastAPI 请求对象
            db: 数据库会话
            account_id: 账户 ID
            team_code: 团队代码
            use_new_api: 是否使用新的函数式 API（默认 True）

        Returns:
            (tools, kb_sources): 工具列表和知识库来源列表
        """
        tools: list[BaseTool] = []
        kb_sources = []

        # 1. 获取 Token
        token = request.headers.get("token")
        if not token:
            redis = request.app.state.redis_pool
            token_info = await RedisUtil.get_cached_data(key=account_id, redis=redis)
            if token_info:
                token = token_info.get("value")

        # 2. 加载 HTTP 工具
        tool_list = agent_config.get("tool_list", [])
        if tool_list:
            logger.info(f"加载 HTTP 工具 | 工具数量: {len(tool_list)}")
            for tool_id in tool_list:
                try:
                    # 从 MongoDB 获取工具配置
                    tool_doc = MongodbUtil.query_doc_by_id(
                        collection_name=CollectionConfig.TOOL_INFO_COLLECTION, doc_id=tool_id
                    )

                    if tool_doc:
                        http_tool = await ToolFactory.create_http_tool(
                            tool_config=tool_doc, token=token, use_new_api=use_new_api
                        )
                        tools.append(http_tool)
                    else:
                        logger.warning(f"工具配置不存在: {tool_id}")

                except Exception as e:
                    logger.exception(f"加载工具失败: {tool_id} | 错误: {str(e)}")

        # 3. 加载知识库工具
        kb_list = agent_config.get("kb_list", [])
        if kb_list:
            logger.info(f"加载知识库工具 | 知识库数量: {len(kb_list)}")

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

            if kb_configs:
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

                # 创建知识库工具
                kb_tool = ToolFactory.create_knowledge_tool(
                    kb_configs=kb_configs,
                    recall_setting=agent_config.get("recall_setting", {}),
                    enable_synonym=enable_synonym,
                    synonym_list=synonym_list,
                    db=db,
                    account_id=account_id,
                    team_code=team_code,
                    use_new_api=use_new_api,
                )
                tools.append(kb_tool)

        # 4. 加载 MCP 工具（未来支持）
        mcp_tools = agent_config.get("mcp_tools", [])
        if mcp_tools:
            logger.info(f"检测到 MCP 工具配置 | 数量: {len(mcp_tools)}")
            # for mcp_config in mcp_tools:
            #     try:
            #         mcp_tool = await ToolFactory.create_mcp_tool(mcp_config)
            #         tools.append(mcp_tool)
            #     except Exception as e:
            #         logger.exception(f"加载 MCP 工具失败: {str(e)}")

        logger.info(f"工具加载完成 | 总工具数: {len(tools)}")
        return tools, kb_sources


# ==================== 注册内置工具类型 ====================

# ToolRegistry.register("http", create_http_tool)
# ToolRegistry.register("knowledge", create_knowledge_tool)
# ToolRegistry.register("mcp", create_mcp_tool)  # 未来支持
