#!/usr/bin/env python
"""
智能体MCP服务管理
"""

import uuid
from inspect import Parameter, Signature
from typing import Optional

from bson.objectid import ObjectId
from loguru import logger

from base_configs.api_config import ApiConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil


class AgentMCPService:
    """智能体MCP服务管理"""

    @staticmethod
    def update_agent_mcp(
        account_id: str,
        agent_id: str,
        name: str,
        description: str,
        is_mcp_tool: bool,
        properties_list: list,
        server_id: Optional[str] = None,
    ):
        """
        发布或取消发布智能体为MCP服务

        Args:
            account_id: 账户ID
            agent_id: 智能体ID
            name: MCP服务名称
            description: 服务描述
            properties_list: 变量参数列表
            is_mcp_tool: 是否发布为MCP服务
            server_id: 服务器ID（可选）
        """
        try:
            # 1. 检查同名MCP服务（排除当前智能体）
            same_name_configs = list(
                MongodbUtil.query_docs_by_condition(
                    CollectionConfig.INSIDE_MCP_CONFIG,
                    search_condition={"account_id": account_id, "name": name},
                )
            )
            for config in same_name_configs:
                if config["mcp_id"] != agent_id:
                    logger.error(f"存在同名MCP智能体服务: {name}, agent_id: {config['mcp_id']}")
                    raise Exception("存在同名MCP智能体服务，请修改名称")

            # 2. 查询现有MCP配置
            existing_configs = list(
                MongodbUtil.query_docs_by_condition(
                    CollectionConfig.INSIDE_MCP_CONFIG, search_condition={"mcp_id": agent_id}
                )
            )

            existing_config = existing_configs[0] if existing_configs else None
            is_new_config = existing_config is None

            # 3. 处理server_id
            if not server_id:
                if is_new_config:
                    # 新配置生成新的server_id
                    server_id = uuid.uuid4().hex
                    logger.debug(f"生成新的server_id: {server_id}")
                else:
                    # 现有配置使用原有server_id
                    server_id = existing_config.get("server_id", uuid.uuid4().hex)
                    logger.debug(f"使用原有server_id: {server_id}")

            # 4. 准备基础配置数据
            base_config = {
                "mcp_id": agent_id,
                "name": name,
                "description": description,
                "properties_list": properties_list,
                "account_id": account_id,
                "mcp_type": "1",
                "is_mcp_tool": is_mcp_tool,
                "server_id": server_id,
                "mcp_url": f"{ApiConfig.MCP_AGENT_URL}{server_id}/",
            }

            # 5. 根据情况处理配置
            if is_new_config:
                # 新增配置
                logger.info(f"新增MCP配置，agent_id: {agent_id}, is_mcp_tool: {is_mcp_tool}")

                if is_mcp_tool:
                    # 发布MCP服务
                    AgentMCPService._register_mcp_agent(account_id, agent_id, name, description, properties_list)
                    logger.info(f"注册MCP服务成功: {account_id}_{name}")

                MongodbUtil.insert_one(CollectionConfig.INSIDE_MCP_CONFIG, base_config)

            else:
                # 更新现有配置
                logger.info(
                    f"更新MCP配置，agent_id: {agent_id}, 原状态: {existing_config.get('is_mcp_tool')}, 新状态: {is_mcp_tool}"
                )

                old_name = existing_config.get("name", "")
                was_mcp_tool = existing_config.get("is_mcp_tool", False)

                # 处理MCP服务注册状态变更
                if is_mcp_tool and not was_mcp_tool:
                    # 从未发布转为发布
                    AgentMCPService._register_mcp_agent(account_id, agent_id, name, description, properties_list)
                    logger.info("MCP服务状态变更：未发布 -> 已发布")
                elif not is_mcp_tool and was_mcp_tool:
                    # 从发布转为未发布
                    AgentMCPService._unregister_mcp_agent(account_id, old_name)
                    logger.info("MCP服务状态变更：已发布 -> 未发布")
                elif is_mcp_tool and was_mcp_tool and old_name != name:
                    # 已发布但名称变更
                    AgentMCPService._register_mcp_agent(
                        account_id, agent_id, name, description, properties_list, old_name
                    )
                    logger.info(f"MCP服务名称变更：{old_name} -> {name}")

                # 更新数据库配置
                MongodbUtil.update_one(CollectionConfig.INSIDE_MCP_CONFIG, {"mcp_id": agent_id}, {"$set": base_config})

            logger.info(f"智能体MCP配置更新完成，agent_id: {agent_id}, is_mcp_tool: {is_mcp_tool}")

        except Exception as e:
            logger.exception(f"更新智能体MCP配置失败，agent_id: {agent_id}, 错误: {str(e)}")
            raise

    @staticmethod
    def _sync_variable_list_to_properties_list(agent_id: str, existing_config: dict) -> dict:
        """
        同步智能体编排数据中的variable_list到MCP配置的properties_list

        Args:
            agent_id: 智能体ID
            existing_config: 现有的MCP配置

        Returns:
            dict: 更新后的配置
        """
        try:
            # 1. 查询智能体编排数据中的variable_list
            agent_arrange_info = MongodbUtil.query_doc_by_id(
                CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(agent_id)
            )

            if not agent_arrange_info:
                logger.warning(f"未找到智能体编排数据，agent_id: {agent_id}")
                return existing_config

            current_variable_list = agent_arrange_info.get("variable_list", [])
            current_properties_list = existing_config.get("properties_list", [])

            logger.info(f"当前variable_list: {current_variable_list}")
            logger.info(f"当前properties_list: {current_properties_list}")

            # 2. 检查variable_list是否发生变化
            current_variable_names = set(current_variable_list)
            # 从现有properties_list中提取非系统参数名称（排除input和conversation_id）
            current_property_names = {
                prop.get("name")
                for prop in current_properties_list
                if prop.get("name") and prop.get("name") not in ["input", "conversation_id"]
            }

            # 判断是否有变化：新增、删除或变量名不完全匹配
            has_changes = current_variable_names != current_property_names

            if has_changes:
                logger.info("检测到variable_list变化，开始同步更新properties_list")

                # 3. 构造新的properties_list
                new_properties_list = []

                # 首先添加系统固定参数
                for prop in current_properties_list:
                    if prop.get("name") in ["input", "conversation_id"]:
                        new_properties_list.append(prop)

                # 确保基本系统参数存在
                system_params = [
                    {
                        "name": "input",
                        "type": "string",
                        "required": True,
                        "description": "用户输入的问题或指令",
                        "example": "",
                    },
                    {
                        "name": "conversation_id",
                        "type": "string",
                        "required": True,
                        "description": "会话ID，用于管理对话隔离",
                        "example": "",
                    },
                ]

                for sys_param in system_params:
                    if not any(prop.get("name") == sys_param["name"] for prop in new_properties_list):
                        new_properties_list.append(sys_param)

                # 处理variable_list对应的参数
                for variable_name in current_variable_list:
                    # 查找是否已存在同名参数配置
                    existing_prop = None
                    for prop in current_properties_list:
                        if prop.get("name") == variable_name:
                            existing_prop = prop
                            break

                    # 如果存在则保留原有配置，否则创建默认配置
                    if existing_prop:
                        new_properties_list.append(existing_prop)
                    else:
                        new_properties_list.append(
                            {
                                "name": variable_name,
                                "description": f"智能体变量：{variable_name}",
                                "type": "string",
                                "required": True,
                                "example": "",
                            }
                        )

                # 4. 更新数据库中的properties_list
                MongodbUtil.update_one(
                    CollectionConfig.INSIDE_MCP_CONFIG,
                    {"mcp_id": agent_id},
                    {"$set": {"properties_list": new_properties_list}},
                )

                logger.info(f"成功同步更新properties_list，参数数量: {len(new_properties_list)}")

                # 5. 更新返回的配置
                updated_config = existing_config.copy()
                updated_config["properties_list"] = new_properties_list

                return updated_config
            else:
                logger.info("variable_list未发生变化，保持现有properties_list")
                return existing_config

        except Exception as e:
            logger.exception(f"同步variable_list到properties_list失败，agent_id: {agent_id}, 错误: {str(e)}")
            return existing_config

    @staticmethod
    def query_agent_mcp_config(agent_id: str):
        """
        查询智能体MCP配置

        Args:
            agent_id: 智能体ID

        Returns:
            dict: 返回标准化的工具配置结构，包含 tool_id, name, description, properties_list, is_mcp_tool
        """
        try:
            # 1. 先查询数据库是否已有 MCP 配置
            try:
                existing_mcp_configs = MongodbUtil.query_docs_by_condition(
                    CollectionConfig.INSIDE_MCP_CONFIG, search_condition={"mcp_id": agent_id}
                )

                if existing_mcp_configs:
                    # 如果已有配置，先同步variable_list变化，然后返回
                    existing_config = existing_mcp_configs[0]
                    logger.info(f"找到已有MCP配置，agent_id: {agent_id}")

                    # 同步variable_list到properties_list
                    updated_config = AgentMCPService._sync_variable_list_to_properties_list(agent_id, existing_config)

                    # 确保返回结构完整
                    result_config = {
                        "agent_id": agent_id,
                        "name": updated_config.get("name", ""),
                        "description": updated_config.get("description", ""),
                        "properties_list": updated_config.get("properties_list", []),
                        "is_mcp_tool": updated_config.get("is_mcp_tool", False),
                        "mcp_url": updated_config.get("mcp_url", ""),
                        "server_id": updated_config.get("server_id", uuid.uuid4().hex),
                    }
                    return result_config

            except Exception as e:
                logger.warning(f"查询已有MCP配置失败，agent_id: {agent_id}, 错误: {str(e)}")

            # 2. 如果没有配置，构造默认数据
            logger.info(f"未找到MCP配置，构造默认数据，agent_id: {agent_id}")
            server_id = uuid.uuid4().hex
            agent_config = {
                "agent_id": agent_id,
                "name": "",
                "description": "",
                "properties_list": [],
                "is_mcp_tool": False,
                "mcp_url": f"{ApiConfig.MCP_AGENT_URL}{server_id}/",
                "server_id": server_id,
            }

            # 3. 查询 AGENT_COLLECTION 获取智能体基本信息（name, description）
            try:
                agent_info = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.AGENT_COLLECTION, doc_id=ObjectId(agent_id)
                )

                if agent_info:
                    agent_config["name"] = agent_info.get("agent_name", "")
                    agent_config["description"] = agent_info.get("description", "")
            except Exception as e:
                logger.warning(f"查询智能体基本信息失败，agent_id: {agent_id}, 错误: {str(e)}")

            # 2. 查询 ARRANGE_AGENT_COLLECTION 获取 variable_list
            try:
                arrange_agent_info = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(agent_id)
                )
                if arrange_agent_info and "variable_list" in arrange_agent_info:
                    variable_list = arrange_agent_info["variable_list"]
                    if isinstance(variable_list, list):
                        properties_list = []
                        # 添加问题变量以及会话id变量
                        properties_list.append(
                            {
                                "name": "input",
                                "type": "string",
                                "required": True,
                                "description": "用户输入的问题或指令",
                                "example": "",
                            }
                        )
                        properties_list.append(
                            {
                                "name": "conversation_id",
                                "type": "string",
                                "required": True,
                                "description": "会话ID，用于管理对话隔离",
                                "example": "",
                            }
                        )

                        # 3. 将 variable_list 转换为 properties_list 格式
                        for variable_name in variable_list:
                            property_item = {
                                "name": str(variable_name),
                                "type": "",
                                "required": True,
                                "description": "",
                                "example": "",
                            }
                            properties_list.append(property_item)

                        agent_config["properties_list"] = properties_list
            except Exception as e:
                logger.warning(f"查询智能体编排信息失败，agent_id: {agent_id}, 错误: {str(e)}")

            return agent_config
        except Exception as e:
            logger.exception(f"查询智能体MCP配置异常，agent_id: {agent_id}")
            raise

    @staticmethod
    def _register_mcp_agent(
        account_id: str,
        agent_id: str,
        name: str,
        description: str,
        properties_list: list,
        origin_name: Optional[str] = None,
    ):
        """
        注册智能体为MCP工具

        Args:
            account_id: 账户ID
            agent_id: 智能体ID
            name: MCP服务名称
            description: 服务描述
            properties_list: 参数属性列表
            origin_name: 原名称（用于更新时删除旧服务）
        """
        from main import shared_mcp

        # 如果是更新,先删除旧服务
        if origin_name:
            tool_name = f"{account_id}_{origin_name}"
            if tool_name in shared_mcp._tool_manager._tools:
                del shared_mcp._tool_manager._tools[tool_name]

        # 验证和解析 properties_list,提取固定参数和自定义参数
        if not properties_list or not isinstance(properties_list, list):
            logger.warning(f"⚠️ properties_list 参数格式错误: {properties_list}")
            properties_list = []

        fixed_params = ["input", "conversation_id"]
        custom_params = []

        for prop in properties_list:
            param_name = prop.get("name")
            if param_name and param_name not in fixed_params:
                custom_params.append(param_name)

        # 定义智能体调用函数（动态参数）
        async def agent_func(
            _account_id=account_id, _agent_id=agent_id, _name=name, input: str = "", conversation_id: str = "", **kwargs
        ):
            """
            调用智能体
            """
            from base_utils.mysql_util import SessionLocal
            from base_utils.redis_util import RedisUtil
            from main import app
            from service_agent_manage.entity.agent import CallAgentParams
            from service_agent_manage.langchain_core.agent_executor import AgentExecutor

            logger.info(f"👤 用户 {_account_id} 通过MCP调用智能体 {_name}")

            # 构造 agent_params,将自定义参数拼接到 prompt_params
            agent_params = {}
            if kwargs:
                prompt_params = {}
                for param_name, param_value in kwargs.items():
                    prompt_params[param_name] = param_value
                agent_params["prompt_params"] = prompt_params

            # 构造调用参数
            params = CallAgentParams(
                agent_id=_agent_id, input=input, conversation_id=conversation_id, agent_params=agent_params
            )

            # 获取 token（从 Redis 缓存中获取）
            token = ""
            try:
                redis = app.state.redis_pool
                token_info = await RedisUtil.get_cached_data(key=_account_id, redis=redis)
                if token_info:
                    token = token_info.get("value", "")
            except Exception as e:
                logger.warning(f"⚠️ 获取用户 token 失败: {str(e)}")

            # 创建模拟请求对象
            class MockRequest:
                class State:
                    account_id = _account_id

                class Headers:
                    def get(self, key: str, default=None):
                        """模拟 headers.get() 方法"""
                        if key == "token":
                            return token
                        return default

                class App:
                    class State:
                        redis_pool = None

                    state = State()

                state = State()
                headers = Headers()
                app = App()

            # 注入 redis_pool
            mock_request = MockRequest()
            try:
                mock_request.app.state.redis_pool = app.state.redis_pool
            except Exception as e:
                logger.warning(f"⚠️ 注入 redis_pool 失败: {str(e)}")

            # 创建数据库会话
            db = SessionLocal()
            try:
                # 初始化执行器
                executor = AgentExecutor()
                init_success = await executor.initialize(params, mock_request, db, conversation_type=2)

                if not init_success:
                    import traceback

                    error_traceback = traceback.format_exc()
                    error_msg = f"智能体mcp初始化失败: {error_traceback}"
                    return {"error": error_msg, "success": False}

                # 收集流式输出
                result = await executor.execute()

                return {
                    "result": result.get("content", ""),
                    "talk_id": executor.talk_id,
                    "conversation_id": conversation_id,
                    "success": True,
                }

            except Exception as e:
                # 捕获所有异常并返回详细堆栈信息
                import traceback

                error_traceback = traceback.format_exc()
                error_msg = f"智能体mcp执行异常: {str(e)}"

                return {
                    "error": error_msg,
                    "exception_type": type(e).__name__,
                    "traceback": error_traceback,
                    "success": False,
                }
            finally:
                db.close()

        # 动态构造函数签名
        params = [
            Parameter(name="input", kind=Parameter.POSITIONAL_OR_KEYWORD, default=Parameter.empty, annotation=str),
            Parameter(
                name="conversation_id", kind=Parameter.POSITIONAL_OR_KEYWORD, default=Parameter.empty, annotation=str
            ),
        ]

        # 添加自定义参数
        annotations = {"input": str, "conversation_id": str}
        for param in properties_list:
            param_name = param.get("name")
            if param_name and param_name not in fixed_params:
                # 获取参数类型
                param_type = str
                param_type_str = param.get("type", "string")

                # 转换类型字符串为实际类型
                if param_type_str == "string":
                    param_type = str
                elif param_type_str == "integer":
                    param_type = int
                elif param_type_str == "number":
                    param_type = float
                elif param_type_str == "boolean":
                    param_type = bool
                elif param_type_str == "array":
                    param_type = list
                elif param_type_str == "object":
                    param_type = dict

                # 检查是否必填
                if param.get("required", False):
                    default_value = Parameter.empty  # 必填参数不设置默认值
                else:
                    default_value = ""

                params.append(
                    Parameter(
                        name=param_name,
                        kind=Parameter.POSITIONAL_OR_KEYWORD,
                        default=default_value,
                        annotation=param_type,
                    )
                )
                annotations[param_name] = param_type

        agent_func.__signature__ = Signature(params)
        agent_func.__annotations__ = annotations
        # 动态生成文档字符串
        # doc_lines = [f"{description}\n\n参数说明:"]
        # doc_lines.append("- input (必填, 类型: string): 用户输入的问题或指令")
        # doc_lines.append("- conversation_id (必填, 类型: string): 对话ID,用于管理对话隔离")

        # # 添加自定义参数说明
        # for param in properties_list:
        #     param_name = param.get("name")
        #     if param_name and param_name not in fixed_params:
        #         param_type = param.get("type", "string")
        #         param_desc = param.get("description", "")
        #         required_text = "必填" if param.get("required", False) else "可选"
        #         doc_lines.append(f"- {param_name} ({required_text}, 类型: {param_type}): {param_desc}")

        agent_func.__doc__ = description

        # 注册工具
        shared_mcp.tool(agent_func, name=f"{account_id}_{name}")
        logger.info(f"✅ 注册智能体MCP服务成功: {account_id}_{name}")

    @staticmethod
    def _unregister_mcp_agent(account_id: str, name: str):
        """
        取消注册智能体MCP服务

        Args:
            account_id: 账户ID
            name: MCP服务名称
        """
        from main import shared_mcp

        tool_name = f"{account_id}_{name}"
        if tool_name in shared_mcp._tool_manager._tools:
            del shared_mcp._tool_manager._tools[tool_name]
            logger.info(f"✅ 取消注册智能体MCP服务成功: {tool_name}")

    @staticmethod
    def _refresh_mcp_agent_url(agent_id: str):
        server_id = uuid.uuid4().hex
        MongodbUtil.update_one(
            CollectionConfig.INSIDE_MCP_CONFIG, {"mcp_id": agent_id}, {"$set": {"server_id": server_id}}
        )
        return {"mcp_url": f"{ApiConfig.MCP_AGENT_URL}{server_id}/", "server_id": server_id}
