#!/usr/bin/env python
"""
LangChain Agent API
基于 LangChain 1.0 的智能体调用接口
"""

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response
from loguru import logger
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from base_utils.ret_util import RetUtil
from service_agent_manage.entity.agent import CallAgentParams
from service_agent_manage.langchain_core.agent_executor import AgentExecutor
from service_agent_manage.langchain_core.stream_processor import StreamProcessor
from service_agent_manage.service.agent_service import AgentService
from service_mcp_manage.service.mcp_service import MCP_service
from service_model_manage.service.model_family_service import ModelFamilyService

router = APIRouter()


def get_db(request: Request):
    db = request.app.state.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/call_agent_v1_withtag", summary="调用智能体")
async def call_agent(
    chat_request: Request,
    params: CallAgentParams,
    db: Session = Depends(get_db),
    conversation_type: int = 2,
) -> EventSourceResponse:
    """
    基于 LangChain 1.0 的智能体调用接口

    Args:
        chat_request: FastAPI 请求对象
        params: 智能体调用参数
        db: 数据库会话
        conversation_type: 对话类型

    Returns:
        EventSourceResponse: SSE 流式响应
    """
    try:
        logger.info(f"开始调用智能体 | agent_id={params.agent_id}")

        # 1. 初始化执行器
        executor = AgentExecutor()
        if not await executor.initialize(params, chat_request, db, conversation_type):
            logger.error("Agent 初始化失败")
            return RetUtil.response_error(message="智能体配置验证失败")

        # 2. 流式执行
        async def stream_generator():
            """流式生成器"""
            try:
                # 创建流处理器
                processor = StreamProcessor(
                    db=db,
                    talk_id=executor.talk_id,
                    params=params.model_dump(),
                    prompt=executor.config.prompt,
                    request=chat_request,
                    kb_sources=executor.config.kb_sources,
                    enable_think=executor.config.enable_think,
                    enable_citation=executor.config.enable_citation,
                    conversation_type=conversation_type,
                )

                # 执行并处理流
                agent_stream = executor.execute_stream()
                async for sse_message in processor.process_stream(agent_stream):
                    yield sse_message

                logger.info(f"智能体调用完成 | talk_id={executor.talk_id}")

            except Exception as err:
                logger.exception(f"智能体流式执行异常 | err={err}")
                error_payload = RetUtil.response_stream(
                    data={"token": "系统繁忙，请稍后再试", "talk_id": executor.talk_id, "error": True}
                )
                yield json.dumps(error_payload, ensure_ascii=False)
                raise

        return EventSourceResponse(stream_generator())

    except Exception as e:
        logger.exception(f"调用智能体异常: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get_tools_list", summary="智能体编排-获取系统工具与MCP工具列表")
async def get_tools_list(
    chat_request: Request,
    team_codes: list = Body([""], description="团队ID列表（如果为空，则查询个人工具）", embed=True),
    db: Session = Depends(get_db),
) -> Response:
    """工具列表接口：返回系统工具与外部MCP工具（级联结构）"""
    try:
        account_id = chat_request.state.account_id
        user_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, account_id)
        user_id_list, admin_id_list = await ModelFamilyService.get_account_id_by_user_attribute(
            db, user_attribute, account_id
        )

        # 系统工具：包含内置与自定义
        user_tools_info_list = await AgentService.tool_query_by_user(
            user_id_list, team_codes if team_codes != [""] else None
        )
        admin_tools_info_list = await AgentService.tool_query_by_user(admin_id_list)
        system_children = []
        if admin_tools_info_list:
            system_children.append(
                {
                    "value": "1",
                    "leaf": False,
                    "label": "内置",
                    "children": [
                        {"value": t.get("_id", ""), "label": t.get("tool_name", "")} for t in admin_tools_info_list
                    ],
                }
            )
        if user_attribute == 0 and user_tools_info_list:
            system_children.append(
                {
                    "value": "0",
                    "leaf": False,
                    "label": "自定义",
                    "children": [
                        {"value": t.get("_id", ""), "label": t.get("tool_name", "")} for t in user_tools_info_list
                    ],
                }
            )
        system_tools_node = {"value": "system_tools", "leaf": False, "label": "系统工具", "children": system_children}

        # MCP工具：仅保留规定字段
        mcp_tools = await MCP_service.query_mcp_config_by_account_id(
            account_id=account_id, team_code=team_codes, name=None
        )
        mcp_children = []
        for item in mcp_tools:
            tool_list = item.get("tool_list", []) or []
            tool_children = []
            for tool in tool_list:
                if isinstance(tool, dict):
                    tool_name = tool.get("tool_name") or tool.get("name") or ""
                else:
                    tool_name = str(tool)
                tool_children.append({"value": tool_name, "label": tool_name})
            mcp_children.append(
                {
                    "value": item.get("id"),
                    "leaf": False,
                    "label": item.get("name", ""),
                    "children": tool_children,
                }
            )
        mcp_tools_node = {"value": "mcp_tools", "leaf": False, "label": "MCP工具", "children": mcp_children}

        return RetUtil.response_ok([system_tools_node, mcp_tools_node])
    except Exception as e:
        detail = f"查询工具集列表错误{str(e)}"
        logger.exception(detail)
        raise HTTPException(status_code=400, detail=detail)

