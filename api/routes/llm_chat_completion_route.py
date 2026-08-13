# -*- coding: UTF-8 -*-
"""
@Project :tiance-base
@File    :llm_chat_completion_api.py
@Author  :JianbinLi
@Date    :2024/08/29 09:11
"""

import io
import json
import time
import traceback

import openai
import pandas as pd
import requests
from bson import ObjectId
from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import Response
from loguru import logger
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from base_configs.minio_config import MinioConfig
from base_configs.model_config import ModelConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.mysql_util import SessionLocal
from base_utils.redis_util import RedisUtil
from base_utils.ret_util import RetUtil
from service_agent_manage.service.agent_service import AgentService  # 调用方法获取运行中的大模型
from service_knowledge_manage.api.routes.knowledge_hub_route import knwolege_retrieval
from service_model_manage.entity.chat_completion_entity import (
    ChatCompletionHistoryParams,
    ChatCompletionListParams,
    ChatCompletionListParams_mem,
    ChatCompletionRequestParams,
    ChatCompletionRequestParams_r1,
    ChatCompletionRequestParams_v1,
    ChatLikeReviewParams,
    ExportChatCompletionHistoryParams,
    Multimodel_ChatParams,
    multi_model_ChatCompletionRequestParams,
    vl_ChatCompletionRequestParams,
)
from service_model_manage.service import QAKnowledgeRetrieval
from service_model_manage.service.chat_completion_service import OpenAILLMService
from service_model_manage.service.chat_db_service import ChatConversationService
from service_model_manage.service.KnowledgeTrace import KnowledgeTrace, ThinkingProcessor
from service_model_manage.service.QAKnowledgeRetrieval import KnowledgeRetrievalLLMQA, ChatAgent_tools_Service
from service_permission_manage.entity.config_entity import ConfigQueryEntity
from service_permission_manage.service.config_service import ConfigService
from service_toolset_manage.service.toolset_service import BochaService
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_agent


# logger = loguru logger (auto-migrated)
def _build_chunk_content_with_images(chunk_results: list) -> str:
    """构建包含图片描述的chunk内容"""
    if not chunk_results:
        return ""

    processed_chunks = []

    for chunk in chunk_results:
        chunk_content = chunk.get("chunk_content", "")
        reference_nodes = chunk.get("reference_node", [])

        # 提取图片节点的描述
        image_descriptions = []
        for node in reference_nodes:
            if node.get("src_node_type") == "image" or node.get("src_node_type") == "table":
                image_text = node.get("src_node_text", "")
                if image_text.strip():
                    if node.get("src_node_type") == "image":
                        image_descriptions.append(f"<image>{image_text}</image>")
                    elif node.get("src_node_type") == "table":
                        image_descriptions.append(f"<table>{image_text}</table>")
        # 如果有图片描述，添加到chunk内容末尾
        if image_descriptions:
            # 查找"图XX"模式并在其后添加图片描述
            import re

            pattern = r"(图\d+|图[一二三四五六七八九十百千万]+)"

            def replace_image_match(match):
                figure_ref = match.group(1)
                # 找到对应的图片描述（如果有多个图片，按顺序添加）
                description = ""
                if image_descriptions:
                    # 简单的匹配逻辑：如果有图片描述，添加第一个
                    description = image_descriptions.pop(0)
                return f"{figure_ref}{description}"

            # 替换第一个匹配的图引用
            modified_content = re.sub(pattern, replace_image_match, chunk_content, count=1)

            # 如果还有剩余的图片描述，添加到末尾
            if image_descriptions:
                modified_content += "\n" + "\n".join(image_descriptions)

            processed_chunks.append(modified_content)
        else:
            processed_chunks.append(chunk_content)

    return "\n\n".join(processed_chunks)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


router = APIRouter()

# 溯源流式回答接口
async def stream_llm_with_chunk(
    db: Session,
    chat_request: Request,
    request: ChatCompletionRequestParams_v1,
    chunk_content: str,
    model_list: list,
    citation_open: int,
    retrival_info: list,
    account_id: str,
    retrival_params,
):
    openAILLMService = OpenAILLMService(id=request.id)
    content = ""
    think = ""
    think_time = 0
    stream_count = 0
    tag_buf = ""
    text_num = 0
    content_type = "text"
    in_thinking = 0
    start_time = time.time()

    talk_id, talk_num = ChatConversationService.save_talk_data_file(
        db=db,
        conversation_id=request.conversation_id,
        account_id=account_id,
        token=content,
        images=[],
        prompt=request.system_prompts,
        think=think,
        think_time=think_time,
        question=retrival_params.user_query,
        model_id=request.model_uid,
        kb_id="",
        ag_id="",
        type=request.type,
        talk_id=request.talk_id,
        retrival_info=retrival_info,
    )
    ChatConversationService.save_talk_data_file_stop(
        db=db,
        conversation_id=request.conversation_id,
        account_id=account_id,
        type=request.type,
        talk_id=talk_id,
        talk_num=talk_num,
    )

    result = MongodbUtil.query_doc_by_id(
        collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(request.id)
    )
    is_think = result["is_think"]
    thinking_processor = ThinkingProcessor()
    citation_processor = KnowledgeTrace()

    async def check_stop_status():
        redis = chat_request.app.state.redis_pool
        status = await RedisUtil.get_cached_data(key=f"{talk_id}{talk_num}", redis=redis)
        sta = int(status.get("value")) if status else 0
        return sta

    def build_response(result_text):
        return {
            "result": result_text,
            "tokens_consume": 0,
            "query": retrival_params.user_query,
            "model_uid": request.model_uid,
            "tool_outputs": [],
            "conversation_id": request.conversation_id,
            "talk_id": talk_id,
            "talk_num": talk_num,
            "retrival_info": retrival_info,
        }

    if request.model_uid in model_list and citation_open == 1:
        async for chunk in await openAILLMService.stream_chat_file(
            db=db, request=request, chunk_content=chunk_content, type=request.type, model_list=model_list
        ):
            if chunk.choices[0].delta.content != "" and chunk.choices[0].delta.content != None:
                token = chunk.choices[0].delta.content
                tag_buf += token
                skip_think, token, content_type, in_thinking = thinking_processor.process(token, is_think)
                if skip_think:
                    continue
                results = []
                if content_type == "thinking":
                    think += token
                    results = [{"token": token, "type": "thinking", "think_time": 0}]
                elif content_type == "text":
                    text_num += len(token)
                    content += token
                if in_thinking == 4:
                    stream_count += 1
                if content_type == "text":
                    eff_think_time = 0
                    if stream_count == 1:
                        think_time = round(time.time() - start_time, 1)
                        eff_think_time = think_time
                    skip_token, processed_token, results = citation_processor.process_token_citation(
                        token=token, content_type=content_type, think_time=eff_think_time
                    )
                    if skip_token:
                        continue
                if results:
                    for result_text in results:
                        if await check_stop_status() == 3:
                            break
                        resp = RetUtil.response_stream(data=build_response(result_text))
                        yield json.dumps(resp, ensure_ascii=False)
    else:
        async for chunk in await openAILLMService.stream_chat_file(
            db=db, request=request, chunk_content=chunk_content, type=request.type, model_list=model_list
        ):
            if chunk.choices[0].delta.content != "" and chunk.choices[0].delta.content != None:
                token = chunk.choices[0].delta.content
                tag_buf += token
                skip_think, token, content_type, in_thinking = thinking_processor.process(token, is_think)
                if skip_think:
                    continue
                if content_type == "thinking":
                    think += token
                elif content_type == "text":
                    text_num += len(token)
                    content += token
                if in_thinking == 4:
                    stream_count += 1
                if stream_count == 1:
                    think_time = round(time.time() - start_time, 1)
                    result = {"token": token, "type": content_type, "think_time": think_time}
                else:
                    result = {"token": token, "type": content_type, "think_time": 0}
                if await check_stop_status() == 3:
                    break
                resp = RetUtil.response_stream(data=build_response(result))
                yield json.dumps(resp, ensure_ascii=False)

    cleaned_content, citation_numbers = KnowledgeTrace.process_content(content)
    data = {
        "prompt": request.system_prompts,
        "user": retrival_params.user_query,
        "images": [],
        "assistant": {
            "content": cleaned_content,
            "think": think,
            "think_time": think_time,
            "retrival_info": retrival_info,
            "chunk_citation": citation_numbers,
        },
        "type": 0,
    }
    data = json.dumps(data)
    ChatConversationService.update_talk_data(db=db, talk_id=talk_id, token_data=data, talk_num=talk_num)

    return


@router.delete(
    "/chat_delete",
    summary="chat_delete",
)
async def chat_delete(
    request: ChatCompletionHistoryParams, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    try:
        logger.info("->删除问答")
        res = ChatConversationService.check_talk_delete(db=db, conversation_id=request.conversation_id)
        logger.info("->删除问答成功")
        return RetUtil.response_ok(res)

    except Exception as e:
        details = f"删除问答失败：{str(e)}"
        logger.error(details, exc_info=True)
        return RetUtil.response_error(message=details)


@router.delete(
    "/conversation_delete",
    summary="conversation_delete",
)
async def conversation_delete(
    request: ChatCompletionHistoryParams, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    # # 检查账号id
    try:
        logger.info("->删除对话")
        res = ChatConversationService.check_talk_delete(db=db, conversation_id=request.conversation_id)
        logger.info("->删除问答成功")
        res = ChatConversationService.check_conversation_delete(db=db, conversation_id=request.conversation_id)
        logger.info("->删除对话成功")
        return RetUtil.response_ok(res)

    except Exception as e:
        details = f"删除对话失败：{str(e)}"
        logger.error(details, exc_info=True)
        return RetUtil.response_error(message=details)


@router.post(
    "/chat_list",
    summary="chat_list",
)
async def chat_list(
    request: ChatCompletionListParams, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    # # 检查账号id
    try:
        logger.info("->获取对话id列表")
        account_id = chat_request.state.account_id
        check_talk_list = ChatConversationService.check_talk_list(
            db=db,
            account_id=account_id,
            type=request.type,
            model_id=request.model_id,
            kb_id=request.kb_id,
            ag_id=request.ag_id,
        )
        logger.info("->获取对话id列表成功")
        return RetUtil.response_ok(check_talk_list)

    except Exception as e:
        details = f"获取对话id列表失败：{str(e)}"
        logger.error(details, exc_info=True)
        return RetUtil.response_error(message=details)


@router.post(
    "/mem_chat_list",
    summary="mem_chat_list",
)
async def mem_chat_list(
    request: ChatCompletionListParams_mem, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    # # 检查账号id
    try:
        logger.info("->获取对话id列表")
        account_id = chat_request.state.account_id
        check_talk_list = ChatConversationService.creat_chat(
            db=db,
            account_id=account_id,
            type=request.type,
            model_id=request.model_id,
            kb_id=request.kb_id,
            ag_id=request.ag_id,
            creat=request.creat,
        )
        logger.info("->获取对话id列表成功")
        return RetUtil.response_ok(check_talk_list)

    except Exception as e:
        details = f"获取对话id列表失败：{str(e)}"
        logger.error(details, exc_info=True)
        return RetUtil.response_error(message=details)


@router.get("/chat_history_external", summary="获取对话历史的外部接口")
async def chat_history_external(
    chat_request: Request,
    conversation_id: str = Query(None, description="conversation_id<UNK>"),
    db: Session = Depends(get_db),
):
    try:
        logger.info("->获取对话历史")
        talk_info = ChatConversationService.check_talk_info_history(db=db, conversation_id=conversation_id)
        logger.info("->获取对话历史成功")
        return RetUtil.response_ok(talk_info)

    except Exception as e:
        detail = f"获取对话历史失败：{str(e)}"
        logger.error(detail, exc_info=True)
        return RetUtil.response_error(message=detail)


@router.post(
    "/chat_history",
    summary="chat_history",
)
async def chat_history(
    request: ChatCompletionHistoryParams, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    # # 检查账号id
    try:
        logger.info("->获取对话历史")
        talk_info = ChatConversationService.check_talk_info_history(db=db, conversation_id=request.conversation_id)
        logger.info("->获取对话历史成功")
        return RetUtil.response_ok(talk_info)

    except Exception as e:
        detail = f"查询对话历史失败：{str(e)}"
        logger.error(detail, exc_info=True)
        return RetUtil.response_error(message=detail)


@router.post(
    "/stream_chat_completion_v1",
    summary="stream流式回答",
)
async def stream_chat_completion_v1(
    request: ChatCompletionRequestParams_v1, chat_request: Request, db: Session = Depends(get_db)
) -> EventSourceResponse:
    logger.info(
        "开始 stream_chat_completion_v1 | conversation_id={} | model_uid={} | type={}",
        request.conversation_id,
        request.model_uid,
        request.type,
    )
    # # 检查账号id
    account_id = chat_request.state.account_id
    retrival_params = request.retrival_params
    # 获取知识溯源配置
    citation_open = 0
    model_list = []
    ci_rows = ConfigService.query_config_by_key(db=db, config_key="citation")
    citation_raw = ci_rows[0].config_value if ci_rows else "0"
    citation_open = int(citation_raw)
    model_rows = ConfigService.query_config_by_key(db=db, config_key="citation_model")
    model_raw = model_rows[0].config_value if model_rows else ""
    model_list = [m.strip() for m in model_raw.split(",") if m.strip()] if model_raw else []
    # 检索知识库
    KnowledgeRetrieval1 = KnowledgeRetrievalLLMQA(request, knwolege_retrieval)
    # 如果没有问题改写，process_v1返回的rewrite_query就是用户原问题
    chunk_content, stream_type, retrival_info, rewrite_query = await KnowledgeRetrieval1.process_v1(
        db, model_list, citation_open
    )
    # 如果没有问答模型，仅返回检索结果
    if request.model_uid == "":
        # 保存检索数据
        ChatConversationService.save_talk_data_retrival(
            db=db,
            conversation_id=request.conversation_id,
            account_id=account_id,
            token=retrival_info,
            question=retrival_params.user_query,
            kb_id=retrival_params.kb_name,
            model_id="",
            ag_id="",
            type=1,
        )
        return RetUtil.response_ok(data=retrival_info)

    # 对话部分
    citation_processor = KnowledgeTrace()
    from contextvars import ContextVar
    from io import StringIO
    from types import SimpleNamespace

    # 准备一个“全局”content对象（并发安全）
    CONTENT_CTX: ContextVar[SimpleNamespace] = ContextVar("CONTENT_CTX")

    async def astream_response():
        content = ""  # 回答正文
        think = ""  # 思考正文
        content_ctx = SimpleNamespace(raw=StringIO(), display=StringIO())
        CONTENT_CTX.set(content_ctx)
        try:
            openAILLMService = OpenAILLMService(request.id)
            response_content = ""
            logger.info("开始流式对话输出 | conversation_id={}", request.conversation_id)
            # 确保本作用域所需变量已定义
            start_time = time.time()
            thinking_processor = ThinkingProcessor()
            talk_id = ""
            # 初始化计数与耗时，避免未定义变量
            stream_count = 0
            text_num = 0
            think_time = 0
            content_type = "text"
            tag_buf = ""

            # # 模型配置
            result = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(request.id)
            )
            is_think = result["is_think"]

            def build_response(result_text):
                return {
                    "result": result_text,
                    "tokens_consume": 0,
                    "query": retrival_params.user_query,
                    "model_uid": request.model_uid,
                    "retrival_info": retrival_info,
                    "tool_outputs": [],
                    "conversation_id": request.conversation_id,
                }

            if request.model_uid in model_list and citation_open == 1:  # 溯源
                async for chunk in await openAILLMService.stream_chat_v1_with_Synonyms(
                    db=db,
                    request=request,
                    chunk_content=chunk_content,
                    type=stream_type,
                    model_list=model_list,
                    rewrite_query=rewrite_query,
                ):
                    token = chunk.choices[0].delta.content
                    if not token:  # 跳过没有文本内容的帧（role/tool_calls/空字符串等）
                        continue
                    tag_buf += token
                    skip_think, token, content_type, in_thinking = thinking_processor.process(token, is_think)
                    if skip_think:
                        continue
                    results = []
                    if content_type == "thinking":
                        think += token
                        results = [{"token": token, "type": "thinking", "think_time": 0}]
                    elif content_type == "text":
                        text_num += len(token)  # 计算正文的长度
                        content += token
                        content_ctx.display.write(token)
                    if in_thinking == 4:
                        stream_count += 1  # 记录什么时候思考完成产生第一个正文需要yeild的流,计算思考时间
                    # 仅在正文阶段进行 citation 解析，并保证第一段正文也参与解析
                    if content_type == "text":
                        eff_think_time = 0
                        if stream_count == 1:
                            think_time = round(time.time() - start_time, 1)
                            logger.info("模型思考阶段 | 耗时=%.1fs", think_time)
                            eff_think_time = think_time
                        skip_token, processed_token, results = citation_processor.process_token_citation(
                            token=token, content_type=content_type, think_time=eff_think_time
                        )
                        if skip_token:
                            continue
                    if results:
                        for result_text in results:
                            yield json.dumps(
                                RetUtil.response_stream(data=build_response(result_text)), ensure_ascii=False
                            )

            else:
                async for chunk in await openAILLMService.stream_chat_v1_with_Synonyms(
                    db=db,
                    request=request,
                    chunk_content=chunk_content,
                    type=stream_type,
                    model_list=model_list,
                    rewrite_query=rewrite_query,  # 如果没有问题改写，这里的rewrite_query就是用户原问题
                ):
                    token = chunk.choices[0].delta.content
                    if not token:  # 跳过没有文本内容的帧（role/tool_calls/空字符串等）
                        continue
                    tag_buf += token
                    skip_think, token, content_type, in_thinking = thinking_processor.process(token, is_think)
                    if skip_think:
                        continue
                    if content_type == "thinking":
                        think += token
                    elif content_type == "text":
                        text_num += len(token)  # 计算正文的长度
                        content += token
                        content_ctx.display.write(token)
                    if in_thinking == 4:
                        stream_count += 1  # 记录什么时候思考完成产生第一个正文需要yeild的流,计算思考时间
                    if stream_count == 1:
                        think_time = round(time.time() - start_time, 1)
                        logger.info("模型思考阶段 | 耗时=%.1fs", think_time)
                        result = {"token": token, "type": content_type, "think_time": think_time}
                    else:
                        result = {"token": token, "type": content_type, "think_time": 0}

                    yield json.dumps(RetUtil.response_stream(data=build_response(result)), ensure_ascii=False)

            # 输出完成后保存记录
            logger.info(
                "流式输出完成 | 总耗时={:.3f}s | conversation_id={}", time.time() - start_time, request.conversation_id
            )
            # logger.info(tag_buf)
            # 调试：完整 token 输出（repr），便于查看包含 citation 的原始内容
            # logger.info("TOKEN_DUMP_REPR: {}", repr(tag_buf))
            raw_text = content_ctx.display.getvalue()
            cleaned_content, citation_numbers = KnowledgeTrace.process_content(raw_text)
            data = {
                "user": retrival_params.user_query,
                "assistant": {
                    "content": cleaned_content,
                    "think": think,
                    "think_time": think_time,
                    "retrival_info": retrival_info,
                    "chunk_citation": citation_numbers,
                },
                "type": 0,
            }

            ChatConversationService.save_talk_history_v1(
                db=db,
                conversation_id=request.conversation_id,
                account_id=account_id,
                data=data,
                model_id=request.model_uid,
                kb_id=retrival_params.kb_name if stream_type == 0 else "",
                ag_id="",
                type=stream_type,
            )

        except Exception as e:
            logger.exception("流式输出异常: {}", str(e))
            result = "系统繁忙,请稍后再试"
            response_result = {
                "result": result,
                "tokens_consume": 0,
                "query": retrival_params.user_query,
                "model_uid": request.model_uid,
                "retrival_info": retrival_info,
                "tool_outputs": [],
                "conversation_id": request.conversation_id,
            }
            yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"

    return EventSourceResponse(astream_response())

@router.post(
    "/stream_chat_completion_v1_file",
    summary="stream流式回答",
)
async def stream_chat_completion_v1_file(
    request: ChatCompletionRequestParams_v1, chat_request: Request, db: Session = Depends(get_db)
) -> EventSourceResponse:
    start_time0 = time.time()
    # # 检查账号id
    account_id = chat_request.state.account_id
    logger.info(
        "首页使用语言模型问答... | conv_id={} | model={} | type={}",
        request.conversation_id,
        request.model_uid,
        request.type,
    )
    retrival_params = request.retrival_params
    # 获取知识溯源配置
    citation_open = 0
    model_list = []
    ci_rows = ConfigService.query_config_by_key(db=db, config_key="citation")
    citation_raw = ci_rows[0].config_value if ci_rows else "0"
    citation_open = int(citation_raw)
    model_rows = ConfigService.query_config_by_key(db=db, config_key="citation_model")
    model_raw = model_rows[0].config_value if model_rows else ""
    model_list = [m.strip() for m in model_raw.split(",") if m.strip()] if model_raw else []
    # 判断是否挂载知识库,挂载数据库就返回chunk_content切片
    KnowledgeRetrieval = KnowledgeRetrievalLLMQA(request, knwolege_retrieval)
    retrival_info, chunk_content = await KnowledgeRetrieval.process_v1_file(model_list, citation_open)
    for sub_retrival_info in retrival_info:
        docs_index = []
        # if sub_retrival_info.get("child_docs", []):
        for sub_docs in sub_retrival_info.get("child_docs", []):
            docs_index.append(int(sub_docs.get("reference_chunk_id")))
        sub_retrival_info["child_docs"] = docs_index
    talk_id = ""

    async def astream_response():
        try:
            async for resp in stream_llm_with_chunk(
                db=db,
                chat_request=chat_request,
                request=request,
                chunk_content=chunk_content,
                model_list=model_list,
                citation_open=citation_open,
                retrival_info=retrival_info,
                account_id=account_id,
                retrival_params=retrival_params,
            ):
                yield resp
            logger.info(
                "模型问答已完成 | 总耗时={}",
                time.time() - start_time0,
            )
        except Exception as e:
            logger.exception(f"异常: {str(e)}")
            talk_id = getattr(request, "talk_id", "") or ""
            if talk_id != "":
                ChatConversationService.delete_talk(db=db, talk_id=talk_id)
            result = {"token": "系统繁忙,请稍后再试", "type": "text", "think_time": 0}
            response_result = {
                "result": result,
                "tokens_consume": 0,
                "query": "",
                "model_uid": "",
                "tool_outputs": "",
                "conversation_id": "",
                "talk_id": "",
                "talk_num": "",
            }
            yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"

    return EventSourceResponse(astream_response())

@router.post(
    "/stream_chat_OnlineSearch_v1",
    summary="首页联网搜索流式回答",
)
async def stream_chat_OnlineSearch_v1(request: ChatCompletionRequestParams_v1, chat_request: Request, db: Session = Depends(get_db)
) -> EventSourceResponse:
    logger.info("开始进行联网搜索流式回答...")
    start_time0 = time.time()
    account_id = chat_request.state.account_id
    retrival_params = request.retrival_params
    # 获取知识溯源配置
    citation_open = 0
    model_list = []
    ci_rows = ConfigService.query_config_by_key(db=db, config_key="citation")
    citation_raw = ci_rows[0].config_value if ci_rows else "0"
    citation_open = int(citation_raw)
    model_rows = ConfigService.query_config_by_key(db=db, config_key="citation_model")
    model_raw = model_rows[0].config_value if model_rows else ""
    model_list = [m.strip() for m in model_raw.split(",") if m.strip()] if model_raw else []
    # 判断是否挂载知识库,挂载数据库就返回chunk_content切片
    KnowledgeRetrieval = KnowledgeRetrievalLLMQA(request, knwolege_retrieval)
    kb_retrival_info, kb_chunk_content = await KnowledgeRetrieval.process_v1_file(model_list, citation_open)
    for sub_retrival_info in kb_retrival_info:
        docs_index = []
        # if sub_retrival_info.get("child_docs", []):
        for sub_docs in sub_retrival_info.get("child_docs", []):
            docs_index.append(int(sub_docs.get("reference_chunk_id")))
        sub_retrival_info["child_docs"] = docs_index
    # 获取web搜索结果，按顺序输出
    user_query = getattr(retrival_params, "user_query", "") if retrival_params else ""
    KnowledgeRetrieval = KnowledgeRetrievalLLMQA(request, knwolege_retrieval)
    web_retrival_info, web_chunk_content = await KnowledgeRetrieval.web_search_and_build_chunk(
        db=db,
        user_query=user_query,
        model_list=model_list,
        citation_open=citation_open,
        kb_retrival_info=kb_retrival_info,
    )

    if kb_chunk_content:
        chunk_content = f"{kb_chunk_content}\n\n{web_chunk_content}" if web_chunk_content else kb_chunk_content
    else:
        chunk_content = web_chunk_content
    retrival_info = kb_retrival_info + web_retrival_info
    # logger.info("返回前端的检索结果（带网络搜索结果): {}", retrival_info)
    logger.info("作为模型输入的chunk_content（带网络搜索结果): {}", chunk_content)


    async def astream_response():
        try:#流式回答|+溯源功能
            async for resp in stream_llm_with_chunk(
                db=db,
                chat_request=chat_request,
                request=request,
                chunk_content=chunk_content,
                model_list=model_list,
                citation_open=citation_open,
                retrival_info=retrival_info,
                account_id=account_id,
                retrival_params=retrival_params,
            ):
                yield resp
            logger.info(
                "首页（语言模型）联网搜索流式回答完成 | 总耗时={}",
                time.time() - start_time0,
            )
        except Exception as e:
            logger.exception(f"异常: {str(e)}")
            talk_id = getattr(request, "talk_id", "") or ""
            if talk_id != "":
                ChatConversationService.delete_talk(db=db, talk_id=talk_id)
            result = {"token": "系统繁忙,请稍后再试", "type": "text", "think_time": 0}
            response_result = {
                "result": result,
                "tokens_consume": 0,
                "query": "",
                "model_uid": "",
                "tool_outputs": "",
                "conversation_id": "",
                "talk_id": "",
                "talk_num": "",
            }
            yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"

    return EventSourceResponse(astream_response())


        # if request.need_search:
@router.post(
    "/stream_chat_OnlineSearch_tools_v1",
    summary="首页联网搜索流式回答（工具内置版）",
)
async def stream_chat_OnlineSearch_tools_v1(request: ChatCompletionRequestParams_v1, chat_request: Request, db: Session = Depends(get_db)
) -> EventSourceResponse:
    logger.info("开始进行联网搜索流式回答(🔨工具内置版，模型自主决定搜索方案)...")
    start_time0 = time.time()
    account_id = chat_request.state.account_id
    retrival_params = request.retrival_params
    # 获取知识溯源配置
    citation_open = 0
    model_list = []
    ci_rows = ConfigService.query_config_by_key(db=db, config_key="citation")
    citation_raw = ci_rows[0].config_value if ci_rows else "0"
    citation_open = int(citation_raw)
    model_rows = ConfigService.query_config_by_key(db=db, config_key="citation_model")
    model_raw = model_rows[0].config_value if model_rows else ""
    model_list = [m.strip() for m in model_raw.split(",") if m.strip()] if model_raw else []
    logger.info("溯源开关={}, 支持溯源模型列表={}", citation_open, model_list)
    # logger.info("知识溯源配置: {}", model_list)
    logger.info("调用的模型为{}",request.model_uid)
    user_query = getattr(retrival_params, "user_query", "") if retrival_params else ""
    logger.info("用户问题:{}", user_query)
    if not user_query:
        try:
            talk_info = ChatConversationService.check_talk_info_history(db=db, conversation_id=request.conversation_id)
            if isinstance(talk_info, list) and len(talk_info) > 0:
                last = talk_info[-1]
                user_query = last.get("user", user_query) or user_query
        except Exception:
            pass

    async def astream_response():
        try:
            agent_service = ChatAgent_tools_Service(request, knwolege_retrieval)
            agent = agent_service.build_agent(db=db, user_query=user_query, model_list=model_list, citation_open=citation_open)
            logger.info("已创建Agent自主调用工具")

            parse_agent_retrival_info = ChatAgent_tools_Service.parse_agent_retrival_info
            result = await agent.ainvoke({"input": user_query})
            logger.info("Agent已完成调用工具, 返回检索结果长度:{}", len(result))
            tool_data = parse_agent_retrival_info(result)
            kb_retrival_info = tool_data.get("kb_results", [])
            kb_chunk_content = tool_data.get("kb_chunk", "")
            web_results = tool_data.get("web_results", [])

            web_retrival_info = []
            chunk_items = []
            start_idx = len(kb_retrival_info) + 1
            for idx, item in enumerate(web_results[:8], start=start_idx):
                title = item.get("name") or ""
                url = item.get("url") or ""
                snippet = item.get("snippet") or ""
                summary = item.get("summary") or ""
                siteIcon = item.get("siteIcon") or ""
                if not snippet:
                    continue
                web_retrival_info.append({"reference_title": title, "web_url": url, "snippet": snippet, "summary": summary, "siteIcon": siteIcon,"type": "web_search"})
                if request.model_uid in model_list and citation_open == 1:
                    chunk_items.append(f"引用编号：[{idx}] {title}\nURL: {url}\n{summary}")
                else:
                    chunk_items = [i["summary"] for i in web_retrival_info if "summary" in i]
            web_chunk_content = "\n\n".join(chunk_items)
            if kb_chunk_content:
                chunk_content = f"{kb_chunk_content}\n\n{web_chunk_content}" if web_chunk_content else kb_chunk_content
            else:
                chunk_content = web_chunk_content
            retrival_info = kb_retrival_info + web_retrival_info
            logger.info("已解析检索结果:{}", chunk_content)
            async for resp in stream_llm_with_chunk(
                db=db,
                chat_request=chat_request,
                request=request,
                chunk_content=chunk_content,
                model_list=model_list,
                citation_open=citation_open,
                retrival_info=retrival_info,
                account_id=account_id,
                retrival_params=retrival_params,
            ):
                yield resp
            logger.info(
                "（语言模型）联网搜索流式回答完成 | 总耗时={}",
                time.time() - start_time0,
            )
        except Exception as e:
            logger.exception(f"异常: {str(e)}")
            talk_id = getattr(request, "talk_id", "") or ""
            if talk_id:
                try:
                    ChatConversationService.delete_talk(db=db, talk_id=talk_id)
                except Exception:
                    pass
            result = {"token": "系统繁忙,请稍后再试", "type": "text", "think_time": 0}
            response_result = {
                "result": result,
                "tokens_consume": 0,
                "query": "",
                "model_uid": "",
                "tool_outputs": "",
                "conversation_id": "",
                "talk_id": "",
                "talk_num": "",
            }
            yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"

    return EventSourceResponse(astream_response())


# @router.post(
#     "/chunk_chat_completion_v1",
#     summary="chunk式回答",
# )
# async def chunk_chat_completion_v1(
#     request: ChatCompletionRequestParams_v1, chat_request: Request, db: Session = Depends(get_db)
# ) -> Response:
#     logger.info(
#         "chunk_chat_completion_v1 请求开始  | conversation_id={} | model_uid={} | rag_label={}",
#         request.conversation_id,
#         request.model_uid,
#         request.rag_label,
#     )
#     # # 检查账号id
#     account_id = chat_request.state.account_id
#     try:
#         # 业务逻辑处理
#         openAILLMService = OpenAILLMService(request.id)
#         retrival_info = []
#         if request.rag_label == 1 and request.retrival_param:
#             retrival_params = request.retrival_params
#             retrival_result = await knwolege_retrieval(retrival_params)
#             retrival_result = json.loads(retrival_result.body)
#             # 解析知识库检索内容
#             chunk_results = retrival_result.get("data").get("results")
#             retrival_info = [
#                 {
#                     "reference_kb": retrival_params.kb_name,
#                     "reference_file": chunk.get("file_name"),
#                     "reference_chunk_id": chunk.get("number"),
#                 }
#                 for chunk in chunk_results
#             ]
#             logger.info("知识库检索完成 | 结果数量=%d", len(chunk_results))
#
#         if request.conversation_id == "":
#             logger.info("未提供 conversation_id，新建会话")
#             response_content = openAILLMService.chunk_chat_v1(request)
#             # 创建会话id
#             conversation_id = ChatConversationService.creat_conversation_id(db=db, account_id=account_id)
#             # 保存问答数据
#             ChatConversationService.save_talk_data(
#                 db=db,
#                 conversation_id=conversation_id,
#                 account_id=account_id,
#                 token=response_content,
#                 question=retrival_params.user_query,
#             )
#
#         else:
#             logger.info("conversation_id=%s", request.conversation_id)
#             response_content = openAILLMService.chunk_chat_v1(request, db=db)
#             # 保存问答数据
#             ChatConversationService.save_talk_data(
#                 db=db,
#                 conversation_id=request.conversation_id,
#                 account_id=account_id,
#                 token=response_content,
#                 question=retrival_params.user_query,
#             )
#         response_result = {
#             "result": response_content,
#             "tokens_consume": 0,
#             "query": retrival_params.user_query,
#             "model_uid": request.model_uid,
#             "retrieval_info": retrival_info,
#             "tool_outputs": [],
#             "conversation_id": request.conversation_id,
#         }
#         return RetUtil.response_ok(response_result)
#
#     except Exception as e:
#         logger.error("llm推理服务失败", exc_info=True)
#         return RetUtil.response_error(message="llm推理服务失败,请重试")


@router.post(
    "/chat_list_prompt",
    summary="chat_list_prompt",
)
async def chat_list_prompt(
    request: ChatCompletionListParams, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    # # 检查账号id
    account_id = chat_request.state.account_id
    check_talk_list = ChatConversationService.check_talk_list_prompt(
        db=db,
        account_id=account_id,
        type=request.type,
        model_id=request.model_id,
        kb_id=request.kb_id,
        ag_id=request.ag_id,
    )
    return RetUtil.response_ok(check_talk_list)


@router.post("/chat_completion_prompt", summary="提示词流式回答")
async def achat_completion(
    chat_request: Request,
    db: Session = Depends(get_db),
    original_prompt: str = Body(..., embed=True, examples=["你是一名律师"], description="需要转换的提示语句"),
    query: str = Body(..., embed=True, examples=["自动优化"], description="需要转换的提示语句"),
    conversation_id: str = Body(..., embed=True, examples=["1"], description="需要转换的提示语句"),
) -> EventSourceResponse:
    account_id = chat_request.state.account_id

    async def astream_response():
        try:
            # 记录日志
            # LogUtil.log_json(
            #     describe="->调用LLM服务对用户的question进行回答",
            #     kwargs=jsonable_encoder({query}),
            # )
            logger.info("->调用LLM服务对用户的question进行回答")

            # 业务逻辑处理
            prompt_optimize_prompt = """
                  # 角色
            你是一位在提示词设计领域的专家，精通语言逻辑学，并具备丰富的实际设计经验。
            凭借扎实的理论基础和大量的实践案例，你能够根据用户的不同需求，精准且高效地构建出符合其期望的提示词框架。
            你的设计注重结构化与逻辑性，能够帮助用户解决复杂问题、达成多样化目标。
            你的工作不仅是为用户提供基础的框架设计，更是通过细致的需求分析、创新的内容构建和严谨的优化流程，使每一份提示词都能最大化发挥语言模型的潜力，满足不同使用场景的需求。


            ## 技能
            ### 技能 1: 剖析用户需求
            深度领会用户所提出需求的背景成因、目标意图以及详细具体的要求，精准挖掘出用户潜藏的想法与期待。

            ### 技能 2: 构建框架内容
            基于用户需求，打造出架构清晰、逻辑严密的框架内容，涵盖角色定位、背景阐述、技能设定、目标任务、限制条件、输出样式以及工作流程等核心要素。

            ### 技能 3: 精进内容表述
            运用精妙汉语词汇与逻辑学科知识，对相关内容予以优化，让其表述精确、简洁易懂，且富有想象力与创新力，充分激发语言模型的潜能。

            ## 限制:
            - 仅以精妙汉语词汇清晰阐述逻辑关联，规避使用过于繁杂或生僻的词汇。
            - 杜绝透露任何与“提示词设计”相关的信息，保证输出内容契合用户要求。
            - 所输出内容必须逻辑清晰、条理分明，符合专业设计的框架规范。 

## 示例1
输入：“你是一位数据库专家”
输出：
# 角色
你是一位资深的数据库专家，在数据库设计、管理、优化等方面拥有深厚的专业知识和丰富的实践经验。能够精准把握用户在数据库领域的各类需求，为用户提供专业、高效且实用的解决方案。

## 技能
### 技能 1: 理解用户需求
深入探究用户提出需求的背景、目标以及具体要求，敏锐挖掘出用户潜在的期望和想法。

### 技能 2: 设计数据库方案
依据用户需求，精心打造逻辑严谨、架构清晰的数据库设计方案，涵盖数据库架构规划、表结构设计、字段定义、关系建立等关键要素。

### 技能 3: 提供优化建议
运用专业知识，对现有数据库进行性能评估和分析，提出针对性的优化策略和建议，如查询优化、索引优化、存储优化等。

### 技能 4: 解决数据库问题
当用户遇到数据库故障、数据丢失、性能瓶颈等问题时，迅速分析问题原因，给出有效的解决方案和恢复措施。

## 限制:
- 仅以简洁明了的语言阐述相关内容，避免使用过于复杂或生僻的词汇。
- 输出内容必须聚焦于数据库领域相关问题，不涉及无关话题。
- 所输出内容需逻辑清晰、条理分明，符合专业的数据库设计与解决问题的规范。 

## 示例2
输入：“你是一位金融专家”
输出：

# 角色
你是一位资深金融专家，在金融领域造诣深厚，拥有全面且专业的金融知识体系，积累了丰富的实战经验与行业洞察。能依据用户不同的金融需求，条理清晰、准确专业地提供恰当建议与解决方案。

## 技能
### 技能 1: 理解用户金融需求
深入了解用户所提出金融需求的背景、目标以及具体细节，精准挖掘用户潜在的金融想法与期望。

### 技能 2: 提供金融方案
基于用户金融需求，制定出结构清晰、逻辑严谨的金融规划或解决方案，涵盖产品推荐、策略制定、风险评估等核心要点。

### 技能 3: 精准表述金融内容
运用准确的金融术语与清晰的逻辑，对相关金融内容进行阐述与优化，让表述精确、简洁易懂，充分展现专业素养。

## 限制:
- 仅以规范金融术语和通俗易懂语言阐述金融逻辑，避免使用过于晦涩或生僻词汇。
- 杜绝提供与金融无关的信息，确保输出内容紧扣用户金融需求。
- 所输出内容必须逻辑清晰、层次分明，符合金融专业规范。 

            注意：您正在编写的内容的另一个名称是“提示模板”。
            注意：当指示 AI 提供输出（例如分数）及其理由或推理时，请始终在分数之前要求写出理由。
            注意：您的输出必须是中文。
            注意：请注意您的行为，不要回答不相关的内容,只需要输出提示模板。

"""
            id, model = await AgentService.get_first_running_model()
            openAILLMService = OpenAILLMService(id=id)
            prompt = prompt_optimize_prompt
            response_content = ""
            talk_info = ChatConversationService.check_talk_info(db=db, conversation_id=conversation_id)
            if query == "自动优化":
                user_query = original_prompt
            elif talk_info and len(talk_info) == 0:
                user_query = original_prompt + "\n" + query
            else:
                user_query = query
            async for chunk in await openAILLMService.stream_chat_v1(
                db=db,
                request=ChatCompletionRequestParams_v1(
                    system_prompts=prompt,
                    chatbot=[],
                    history=3,
                    max_token_length=4096,
                    temperature=0.8,
                    conversation_id=conversation_id,
                    model_uid=model,
                    tool_label=0,
                    retrival_params={
                        "kb_name": "",
                        "user_query": user_query,
                        "rerank_model": "",
                        "recall_num": 0,
                        "rerank_num": 0,
                    },
                ),
                chunk_content="",
                type=4,
            ):
                if chunk.choices[0].delta.content != "":
                    token = chunk.choices[0].delta.content
                    yield f"{json.dumps(RetUtil.response_stream(data=token), ensure_ascii=False)}"
                    if token is not None:
                        response_content += token

            # LogUtil.log_json(describe="流式输出的最后结果:", answer=response_content)
            logger.info(f"流式输出的最后结果：{response_content}")
            # LogUtil.info(
            #     f"{conversation_id},{account_id},{response_content},{original_prompt if query == '自动优化' else query}")
            # 保存问答数据
            ChatConversationService.save_talk_data_v1(
                db=db,
                conversation_id=conversation_id,
                account_id=account_id,
                token=response_content,
                question=user_query,
                kb_id="",
                model_id="",
                ag_id="",
                type=4,
                retrival_info="",
            )

        except Exception as e:
            logger.error(f"流式输出异常：{str(e)}")
            result = "系统繁忙,请稍后再试"
            yield f"{json.dumps(RetUtil.response_stream(data=result), ensure_ascii=False)}"

    return EventSourceResponse(astream_response())


@router.post("/deepseek_r1_chat_completion", summary="deepseek_r1")
async def achat_completion(
    params: ChatCompletionRequestParams_r1,
    stream: bool = Body(..., embed=True, examples=[True], description="是否流式返回"),
) -> EventSourceResponse:
    response_content = ""
    # 记录日志
    # LogUtil.log_json(
    #     describe="->调用LLM服务对用户的question进行回答",
    #     kwargs=jsonable_encoder({params.question}),
    # )
    logger.info("->调用LLM服务对用户的question进行回答")

    # 业务逻辑处理
    openAILLMService = OpenAILLMService()
    openAILLMService.llm_model_client = openai.Client(api_key="not empty", base_url="http://10.8.21.166:11434/v1")
    openAILLMService.async_llm_model_client = openai.AsyncClient(
        api_key="not empty", base_url="http://10.8.21.166:11434/v1"
    )
    if stream == True:

        async def astream_response():
            try:
                response_content = ""
                async for chunk in await openAILLMService.stream_chat(
                    request=ChatCompletionRequestParams(
                        system_prompts=params.system_prompts,
                        chatbot=[],
                        history=3,
                        max_token_length=params.max_token_length,
                        temperature=params.temperature,
                        question=params.question,
                        model_uid="DeepSeek-R1-UD-IQ1_M",
                    )
                ):
                    if chunk.choices[0].delta.content != "":
                        token = chunk.choices[0].delta.content
                        yield f"{json.dumps(RetUtil.response_stream(data=token), ensure_ascii=False)}"
                        if token is not None:
                            response_content += token

                    # LogUtil.log_json(describe="流式输出的最后结果:", answer=response_content)
                    logger.info(f"->流式输出最后结果：{response_content}")

            except Exception as e:
                logger.error("llm推理服务失败,请重试")
                # LogUtil.error("异常:{0}".format(str(traceback.format_exc())))
                yield f"data: {RetUtil.response_error(message='llm推理服务失败,请重试')}\n\n"

        return EventSourceResponse(astream_response())

    else:
        response_content = openAILLMService.chunk_chat(
            request=ChatCompletionRequestParams(
                system_prompts=params.system_prompts,
                chatbot=[],
                history=3,
                max_token_length=params.max_token_length,
                temperature=params.temperature,
                question=params.question,
                model_uid="DeepSeek-R1-UD-IQ1_M",
            )
        )
        return RetUtil.response_ok(data=response_content)


@router.post(
    "/stop_talk",
    summary="stop_talk",
)
async def stop_workflow_talk(
    request: Request,
    talk_id: str = Body(..., embed=True, description="会话id"),
    talk_num: int = Body(0, embed=True, description="子会话"),
) -> Response:
    redis = request.app.state.redis_pool
    await RedisUtil.cache_data_static(key=talk_id, value=3, redis=redis)
    result = await RedisUtil.get_cached_data(key=talk_id, redis=redis)

    return RetUtil.response_ok(data={talk_id: result.get("value", "")})


@router.post(
    "/delete_talk",
    summary="delete_talk",
)
async def delete_talk(
    talk_id: str = Body(..., embed=True, description="会话id"),
    talk_num: int = Body(0, embed=True, description="子会话"),
    db: Session = Depends(get_db),
) -> Response:
    logger.info(f"->删除对话：{talk_id}")
    ChatConversationService.delete_talk(db=db, talk_id=talk_id)
    talk_status, talk_type = ChatConversationService.check_talk_status(db=db, talk_id=talk_id, talk_num=talk_num)
    return RetUtil.response_ok(data={talk_id: talk_status})


@router.post(
    "/chat_history_firstpage",
    summary="chat_history_firstpage",
)
async def chat_history_firstpage(
    request: ChatCompletionHistoryParams, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    # # 检查账号id
    #    headers = dict(chat_request.headers)
    #    account_id = ChatConversationService.get_account_id(headers=headers)
    talk_info = ChatConversationService.check_talk_info_history_firstpage(
        db=db, conversation_id=request.conversation_id
    )
    return RetUtil.response_ok(talk_info)


@router.post(
    "/like_talk",
    summary="like_talk",
)
async def like_talk(
    talk_id: str = Body(..., embed=True, description="会话id"),
    talk_num: int = Body(0, embed=True, description="子会话"),
    like_status: int = Body(0, embed=True, description="无状态0，点赞1，踩2"),
    db: Session = Depends(get_db),
) -> Response:
    logger.info(f"->评价对话：{talk_id}")
    talk_like_status = ChatConversationService.like_talk(
        db=db, talk_id=talk_id, talk_num=talk_num, like_status=like_status
    )
    return RetUtil.response_ok(data={talk_id: talk_like_status})


@router.post(
    "/multi_model_completion",
    summary="multi_model_completion",
)
async def multi_model_completion(
    request: multi_model_ChatCompletionRequestParams, chat_request: Request, db: Session = Depends(get_db)
) -> EventSourceResponse:
    # # 检查账号id
    account_id = chat_request.state.account_id
    retrival_params = request.retrival_params
    logger.info(
        "multi_model_completion 开始 | conv_id={} | model_id={} | type={} | images_count={}",
        request.conversation_id,
        request.id,
        request.type,
        len(request.images or []),
    )
    model = MongodbUtil.query_doc_by_id(
        collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(request.id)
    )
    if "modalities" in model and "image" in model["modalities"]:
        openAILLMService = OpenAILLMService(id=request.id)
    else:
        models = MongodbUtil.query_docs_by_condition(
            collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
            search_condition={"model_type": "LLM", "status": "running"},
        )
        for model in models:
            if "modalities" in model and "image" in model["modalities"]:
                openAILLMService = OpenAILLMService(id=str(model["_id"]))
                request.model_uid = model["model_uid"]
                break
    # openAILLMService.async_llm_model_client = openai.AsyncClient(
    #     api_key=ModelConfig.LLM_API_KEY, base_url="http://192.168.36.90:8004/v1", timeout=30
    # )
    if request.retrival_params.id:
        kb_name = MongodbUtil.query_doc_by_id(
            collection_name=CollectionConfig.KB_COLLECTION, doc_id=ObjectId(request.retrival_params.id)
        )["kb_name"]
        retrival_result = await knwolege_retrieval(retrival_params)
        retrival_result = json.loads(retrival_result.body)
        # 解析知识库检索内容
        chunk_results = retrival_result.get("data").get("results")
        logger.info("知识库检索完成 | 结果数量=%d", len(chunk_results))
        retrival_info = []
        for chunk in chunk_results:
            file_urls = ""
            if chunk.get("file_urls").endswith(".pdf"):
                file_urls = chunk.get("file_urls")
            else:
                file_urls = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, doc_id=chunk.get("file_id")
                ).get("pdf_path", chunk.get("file_urls"))
            retrival_info.append(
                {
                    "chunk_content": chunk.get("chunk_content"),
                    "recall_index": chunk.get("rerank_index") if "rerank_index" in chunk else chunk.get("recall_index"),
                    "recall_score": chunk.get("rerank_score") if "rerank_score" in chunk else chunk.get("recall_score"),
                    "reference_file": chunk.get("file_name"),
                    "reference_node": chunk.get("reference_node", []),
                    # "location": chunk.get("location"),
                    "file_urls": file_urls,
                    "page": chunk.get("page"),
                    "row": chunk.get("row"),
                    # "abandon_area": chunk.get("abandon_area"),
                    "reference_chunk_id": chunk.get("number"),
                    "reference_kb_name": kb_name,
                    "reference_kb_id": request.retrival_params.id,
                    "convert_path": chunk.get("convert_path", ""),
                    "remove_image_path": chunk.get("remove_image_path", ""),
                    "file_id": chunk.get("file_id", ""),
                    "chunk_id": chunk.get("chunk_id", ""),
                    "child_docs": [
                        {
                            "chunk_content": (
                                child.get("chunk_content")
                                if "chunk_content" in child
                                else child.get("entity", {}).get("content", "")
                            ),
                            "recall_index": child.get("rerank_index", child.get("recall_index", 0)),
                            "recall_score": child.get(
                                "rerank_score", child.get("recall_score", child.get("distance", 0))
                            ),
                            "reference_file": (
                                child.get("file_name")
                                if "file_name" in child
                                else child.get("entity", {}).get("file_name", "")
                            ),
                            "reference_node": child.get(
                                "reference_node", child.get("entity", {}).get("source_data", [])
                            ),
                            "file_urls": (
                                (child.get("file_urls"))
                                if child.get("file_urls", "").endswith(".pdf")
                                else MongodbUtil.query_doc_by_id(
                                    collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                                    doc_id=(
                                        child.get("file_id")
                                        if "file_id" in child
                                        else child.get("entity", {}).get("file_id")
                                    ),
                                ).get("pdf_path", child.get("file_urls", child.get("entity", {}).get("file_urls", "")))
                            ),
                            "page": child.get("page", []),
                            "row": child.get("row", []),
                            "reference_chunk_id": child.get("number", child.get("entity", {}).get("number")),
                            "reference_kb_name": kb_name,
                            "reference_kb_id": request.retrival_params.id,
                            "convert_path": child.get("convert_path", ""),
                            "remove_image_path": child.get("remove_image_path", ""),
                            "file_id": child.get("file_id", child.get("entity", {}).get("file_id", "")),
                            "child_docs": child.get("child_docs", []),
                        }
                        for child in chunk.get("child_docs", [])
                    ],
                }
            )
        # for item in retrival_info:
        #     page = item.get("page", [])
        # abandon_area = item.get("abandon_area", [])
        # 确保 page 和 abandon_area 的长度一致
        # assert len(page) == len(abandon_area), "Lengths of page and abandon_area must be the same"
        # 构建新的 abandon_area 字典
        # new_abandon_area = {str(p): a for p, a in zip(page, abandon_area)}
        # 更新 item 中的 abandon_area
        # item["abandon_area"] = new_abandon_area

        # 打印修改后的结果
        chunk_content = _build_chunk_content_with_images(chunk_results)
        logger.debug("知识库解析完成 | retrival_info条数=%d", len(retrival_info))
    else:
        logger.info("未挂载知识库检索")
        retrival_info = []
        chunk_content = ""
    # request.model_uid = "Qwen2_5-VL-72B-Instruct"
    talk_id = ""
    for sub_retrival_info in retrival_info:
        docs_index = []
        # if sub_retrival_info.get("child_docs", []):
        for sub_docs in sub_retrival_info.get("child_docs", []):
            docs_index.append(int(sub_docs.get("reference_chunk_id")))
        sub_retrival_info["child_docs"] = docs_index

    async def astream_response():
        try:
            response_content = ""
            content = ""
            think = ""
            think_time = 0
            # 保存问答数据
            talk_id, talk_num = ChatConversationService.save_talk_data_file(
                db=db,
                conversation_id=request.conversation_id,
                account_id=account_id,
                token=content,
                images=request.images,
                prompt=request.system_prompts,
                think=think,
                think_time=think_time,
                question=retrival_params.user_query,
                model_id=request.model_uid,
                kb_id="",
                ag_id="",
                type=request.type,
                talk_id=request.talk_id,
                retrival_info=retrival_info,
            )
            logger.info("已保存对话记录 | talk_id={} | talk_num={}", talk_id, talk_num)
            ChatConversationService.save_talk_data_file_stop(
                db=db,
                conversation_id=request.conversation_id,
                account_id=account_id,
                type=request.type,
                talk_id=talk_id,
                talk_num=talk_num,
            )
            async for chunk in await openAILLMService.vl_stream_chat(
                db=db, request=request, chunk_content=chunk_content, type=request.type
            ):
                if chunk.choices[0].delta.content != "" and chunk.choices[0].delta.content != None:
                    token = chunk.choices[0].delta.content
                    result = {"token": token, "type": "text", "think_time": think_time}
                    response_result = {
                        "result": result,
                        "tokens_consume": 0,
                        "query": retrival_params.user_query,
                        "model_uid": request.model_uid,
                        "tool_outputs": [],
                        "conversation_id": request.conversation_id,
                        "talk_id": talk_id,
                        "talk_num": talk_num,
                        "retrival_info": retrival_info,
                    }
                    content += token
                    # status = ChatConversationService.check_talk_stop_status(db=db, talk_id=talk_id, talk_num=talk_num)
                    redis = chat_request.app.state.redis_pool
                    status = await RedisUtil.get_cached_data(key=f"{talk_id}{str(talk_num)}", redis=redis)
                    if status:
                        status = int(status.get("value"))
                    # status == 3 代表中断
                    if status == 3:
                        break
                    else:
                        yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"
                    if token is not None:
                        response_content += token
                    # 数据库内存每隔10个token更新一次，以支持正确取得status标签，可以停止对话
                    # if len(response_content) % 15 == 0:
                    #     db.commit()
            data = {
                "prompt": request.system_prompts,
                "user": retrival_params.user_query,
                "images": request.images,
                "assistant": {
                    "content": content,
                    "think": think,
                    "think_time": think_time,
                    "retrival_info": retrival_info,
                },
                "type": 0,
            }
            data = json.dumps(data)
            ChatConversationService.update_talk_data(db=db, talk_id=talk_id, token_data=data, talk_num=talk_num)
            logger.info(
                "multi_model_completion 完成 | conv_id={} | account_id={} | 输出长度=%d | query={} | model={}",
                request.conversation_id,
                account_id,
                len(response_content),
                retrival_params.user_query,
                request.model_uid,
            )
        except Exception as e:
            logger.error("异常: {}", str(e), exc_info=True)
            if talk_id != "":
                ChatConversationService.delete_talk(db=db, talk_id=talk_id)
            result = {"token": "系统繁忙,请稍后再试", "type": "text", "think_time": 0}
            response_result = {
                "result": result,
                "tokens_consume": 0,
                "query": "",
                "model_uid": "",
                "tool_outputs": "",
                "conversation_id": "",
                "talk_id": "",
                "talk_num": "",
            }
            yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"

    return EventSourceResponse(astream_response())


@router.post(
    "/multi_model_chunk_completion",
    summary="multi_model_chunk_completion",
)
async def multi_model_chunk_completion(
    request: multi_model_ChatCompletionRequestParams, chat_request: Request, db: Session = Depends(get_db)
) -> EventSourceResponse:
    # print(f"请求体参数:--{request}")
    # # 检查账号id
    headers = dict(chat_request.headers)
    account_id = ChatConversationService.get_account_id(headers=headers)
    retrival_params = request.retrival_params
    openAILLMService = OpenAILLMService(id=request.id)
    openAILLMService.async_llm_model_client = openai.AsyncClient(
        api_key=ModelConfig.LLM_API_KEY, base_url="http://10.8.21.162:8004/v1", timeout=30
    )
    retrival_info = []
    chunk_content = ""
    request.model_uid = "qwen2-vl-instruct"

    response_content = ""
    content = ""
    think = ""
    think_time = 0

    token = await openAILLMService.vl_chunk_chat(
        db=db,
        request=vl_ChatCompletionRequestParams(
            model_uid=request.model_uid,
            image=request.image,
            question=retrival_params.user_query,
            system_prompts=request.system_prompts,
            max_token_length=request.max_token_length,
            temperature=request.temperature,
        ),
        chunk_content=chunk_content,
        type=3,
    )
    result = {"token": token, "type": "text", "think_time": think_time}

    return result


@router.post(
    "/Comprehensive_model_stream_completion",
    summary="Comprehensive_model_stream_completion",
)
async def Comprehensive_model_stream_completion(
    request: multi_model_ChatCompletionRequestParams, chat_request: Request, db: Session = Depends(get_db)
) -> EventSourceResponse:
    try:
        logger.info(
            "首页问答接口被调用 | conv_id={} | type={} | images_cnt={}",
            request.conversation_id,
            getattr(request, "type", None),
            len(getattr(request, "images", []) or []),
        )
        if request.id != "":
            model_data = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    doc_id=ObjectId(request.id),
                )
            if model_data:
                request.model_uid = model_data.get("model_uid", "") or request.model_uid
        have_image = False
        keywords = ["图中", "图片", "图里面"]
        talk_info = ChatConversationService.check_talk_info_history(
            db=db, conversation_id=request.conversation_id, type=request.type
        )
        if len(talk_info) > request.history:  # 记录多于指定历史轮数量，侧进行记录截断
            chatbot = talk_info[-(request.history + 1) : -1]
        else:
            chatbot = talk_info
        logger.debug("历史对话记录长度: %d", len(chatbot))  # 使用 logger.debug 记录历史对话，避免日志过大
        for idx, conversation in enumerate(chatbot):
            if "images" in conversation and len(conversation["images"]) > 0:
                have_image = True
                break
        if request.images != [] or any(keyword in request.retrival_params.user_query for keyword in keywords):
            models = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                search_condition={
                    "model_type": "LLM",
                    "status": "running",
                    "modalities": {"$exists": True, "$in": ["image"]},
                },
            )
            model = list(models)
            if len(model) == 0:

                async def astream_response():
                    result = {
                        "token": "本系统尚未接入多模态大模型,无法进行图片多模态对话",
                        "type": "text",
                        "think_time": 0,
                    }
                    response_result = {
                        "result": result,
                        "tokens_consume": 0,
                        "query": "",
                        "model_uid": "",
                        "tool_outputs": "",
                        "conversation_id": "",
                        "talk_id": "",
                        "talk_num": "",
                    }
                    yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"

                # 返回 EventSourceResponse 对象
                return EventSourceResponse(astream_response())
            else:
                logger.info("使用多模态模型问答，——>multi_model_completion")
                return await multi_model_completion(request, chat_request, db)  # 先 await
        elif have_image == False:
            # logger.info("进入纯文本分支（无历史图片且请求不含图/未命中关键词） -> stream_chat_completion_v1_file")
            online_configs = ConfigService.query_config_by_key(db=db, config_key="online_search")
            online_search = 0
            if online_configs:
                online_search = int(getattr(online_configs[0], "config_value", 0))
                logger.info("online_search:{}", online_search)
            
            if online_search == 1:
                tool_configs = ConfigService.query_config_by_key(db=db, config_key="tools_support_model")
                raw_models = tool_configs[0].config_value if tool_configs else ""
                support_models = [m.strip() for m in raw_models.split(",") if m.strip()] if raw_models else []
                logger.info("当前支持工具调用的模型:{}", support_models)
                # logger.info("模型uid:{}", request.model_uid)
                need_search = getattr(request, "onlineSearch", False) or False
                logger.info("onlineSearch:{}", need_search)
                if request.model_uid in support_models:
                    logger.info("模型{}支持搜索工具调用🌷", request.model_uid)
                    return await stream_chat_OnlineSearch_tools_v1(request, chat_request, db)
                elif need_search:
                    logger.info("模型{}不支持工具调用,但用户需要进行联网搜索", request.model_uid)
                    return await stream_chat_OnlineSearch_v1(request, chat_request, db)
                else:
                    logger.info("模型{}不支持工具调用,也无需进行联网搜索", request.model_uid)
                    return await stream_chat_completion_v1_file(request, chat_request, db)
            else:
                logger.info("进入文本问答分支 -> stream_chat_completion_v1_file")
                return await stream_chat_completion_v1_file(request, chat_request, db)
        else:
            logger.info("进入多模态问答分支（请求不带图但历史含图）")
            id, model = await AgentService.get_first_running_model()  # 获取运行中的大模型
            openAILLMService = OpenAILLMService(id=id)
            prompt = """
            请根据用户问题和历史记录来判断用户的这个问题是否需要调用多模态大模型,如果需要则输出True,不需要则输出False
            """
            is_multimode = openAILLMService.chunk_chat(
                db=db,
                request=ChatCompletionRequestParams_v1(
                    model_uid=model,
                    system_prompts=prompt,
                    conversation_id=request.conversation_id,
                    talk_id=request.talk_id,
                    retrival_params=request.retrival_params,
                ),
                chunk_content="",
                type=3,
            )

            index = is_multimode.find("</think>")  # 推理模型过滤思考内容
            if index != -1:
                is_multimode = is_multimode[index + len("</think>") :]
            # 去除空格和换行符
            is_multimode = is_multimode.strip()
            logger.info("多模态判定结果: %s (类型: %s)", is_multimode, type(is_multimode))
            if is_multimode == "True":
                models = MongodbUtil.query_docs_by_condition(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    search_condition={
                        "model_type": "LLM",
                        "status": "running",
                        "modalities": {"$exists": True, "$in": ["image"]},
                    },
                )
                model = list(models)
                if len(model) == 0:

                    async def astream_response():
                        result = {
                            "token": "本系统尚未接入多模态大模型,无法进行图片多模态对话",
                            "type": "text",
                            "think_time": 0,
                        }
                        response_result = {
                            "result": result,
                            "tokens_consume": 0,
                            "query": "",
                            "model_uid": "",
                            "tool_outputs": "",
                            "conversation_id": "",
                            "talk_id": "",
                            "talk_num": "",
                        }
                        yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"

                    # 返回 EventSourceResponse 对象
                    return EventSourceResponse(astream_response())
                else:
                    logger.info("多模态模型问答，——> multi_model_completion")
                    return await multi_model_completion(request, chat_request, db)  # 先 await
            else:
                logger.info("判定不需要多模态，转交文本问答 stream_chat_completion_v1_file")
                return await stream_chat_completion_v1_file(request, chat_request, db)  # 先 await
    except Exception as e:
        error_info = traceback.format_exc()
        logger.error("模型流式回答失败: {}", str(e), exc_info=True)

        async def astream_response():
            result = {"token": "模型流式回答失败,请稍后再试", "type": "text", "think_time": 0}
            response_result = {
                "result": result,
                "tokens_consume": 0,
                "query": "",
                "model_uid": "",
                "tool_outputs": "",
                "conversation_id": "",
                "talk_id": "",
                "talk_num": "",
            }
            ret = {"status": False, "message": error_info, "data": response_result}
            yield f"{json.dumps(ret, ensure_ascii=False)}"

        return EventSourceResponse(astream_response())


@router.get("/getPic")
async def getPic(url: str = Query(..., description="文件路径")) -> Response:
    try:
        full_url = f"http://{MinioConfig.END_POINT}{url}"
        response = requests.get(full_url)
        response.raise_for_status()  # 检查请求是否成功

        # 根据文件类型设置 media_type 和文件名
        if url.endswith(".jpg") or url.endswith(".jpeg"):
            media_type = "image/jpeg"
        elif url.endswith(".png"):
            media_type = "image/png"
        else:
            media_type = "application/octet-stream"

        return Response(content=response.content, media_type=media_type)
    except Exception as e:
        # LogUtil.info(str(traceback.format_exc()))
        detail = f"请求图片失败：{str(e)}"
        logger.error(detail, exc_info=True)
        return RetUtil.response_error(message="请求图片失败")


@router.get("/getFile")
async def getFile(
    url: str = Query(..., description="文件路径"),
    bucket_name: str = Query(None, description="桶名称"),
) -> Response:
    try:
        if bucket_name is None:
            bucket_name = MinioConfig.BUCKET_NAME
        full_url = f"http://{MinioConfig.END_POINT}/{bucket_name}/{url}"
        response = requests.get(full_url)
        response.raise_for_status()  # 检查请求是否成功
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".txt": "text/plain",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".ppt": "application/vnd.ms-powerpoint",
            ".md": "text/markdown",
            ".csv": "text/csv",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".html": "text/html",
        }
        import os

        media_type = mime_types.get(os.path.splitext(url)[1].lower(), "application/octet-stream")
        # print("response.content", response.content)
        # print("media_type", media_type)
        return Response(content=response.content, media_type=media_type)
    except Exception as e:
        # LogUtil.info(str(traceback.format_exc()))
        detail = f"请求图片失败：{str(e)}"
        logger.error(detail, exc_info=True)
        return RetUtil.response_error(message="请求图片失败")


@router.post(
    "/Question_generation",
    summary="Question_generation",
)
async def Question_generation(
    conversation_id: str = Body(..., examples=["CONVER_1905145519269875712"], description="conversation_id"),
    db: Session = Depends(get_db),
) -> Response:
    import random

    logger.info(f"智能追问的Question_generation方法被调用, conversation_id={conversation_id}")
    question_bank = [
        "你能帮我做些什么？",
        "如何提高我的工作效率？",
        "有什么好的学习方法推荐？",
        "如何保持健康的生活方式？",
        "最近有什么值得关注的科技新闻？",
        "如何有效管理时间？",
        "有哪些有趣的书籍推荐？",
        "如何改善睡眠质量？",
        "如何提高沟通能力？",
        "有哪些流行的旅游目的地？",
    ]
    # 根据conversion_id找到最新的talk_id
    try:
        temp = ChatConversationService.conversion_to_talk(db, conversation_id)
        talk_id = temp.talk_id
        import ast

        # # 先查询数据库中是否存在与 talk_id 对应的记录
        chat_obj = ChatConversationService.insert_question1(db, talk_id)
        if chat_obj != 0:  # 如果存在记录，直接使用记录中的问题
            question_list = ast.literal_eval(chat_obj.question)
            response = {"code": 200, "status": True, "message": "success", "data": question_list}
            return response
    except:
        response = {"code": 200, "status": True, "message": "success", "data": []}
        return response
    try:
        token = ChatConversationService.new_talk_id(db, talk_id)
        data = json.loads(token)
        # 删除 'retrival_info' 和 'chunk_citation' 字段
        if "assistant" in data and isinstance(data["assistant"], dict):
            assistant_data = data["assistant"]
            assistant_data.pop("retrival_info", None)  # 如果字段不存在，避免抛出异常
            assistant_data.pop("chunk_citation", None)  # 同上

            # 更新 data 中的 'assistant' 字段
            data["assistant"] = assistant_data
        prompt = """
    - Role: 人工智能对话分析专家
    - Background: 用户在与模型进行交互后，收到了模型的输出结果。用户可能会基于这个结果进一步探索、澄清或拓展相关问题。
    - Profile: 你是一位精通人工智能对话逻辑和用户心理的专家，能够精准地预测用户在获取信息后的下一步行动。
    - Skills: 你具备深度文本分析能力、用户意图预测技巧以及对话流程优化知识，能够基于模型的输出和用户的提问背景，推断用户可能的后续问题。
    - Goals: 根据模型的输出和用户的提问背景，预测用户最有可能提出的三个后续问题。
    - Constrains: 你的预测应基于模型输出的内容和用户的提问逻辑，避免过于宽泛或不相关的问题。
    - OutputFormat: 列出三个可能的后续问题，每个问题应简洁明了且具有针对性，并以"question"作为三个可能的后续问题的开始标志符。
    - Workflow:
      1. 分析用户提问的意图和背景。
      2. 解读模型输出内容，提取关键信息点。
      3. 基于用户意图和模型输出，预测用户可能的后续问题。
    - Examples:
      - 例子1：
      用户提问： {'user': '现在的时间是几点\n', 'assistant': {'content': '<think>\n好的，用户问现在的时间是几点。根据提供的个人知识，现在时间是2025年3月26日10:54。用户的问题很直接，只需要提供准确的时间。我要确保回复清晰明了，格式正确，不添加多余信息。所以 应该直接回答当前时间是几点几分。\n</think>\n\n现在的时间是10点54分。'}, 
      模型输出：
        基于用户的提问和模型的输出，用户可能会进一步探索以下几个方面:
        question
        1. 现在时间适合做什么？
        2. 如何有效的利用时间？
        3. 如何在没有网络的时候获取时间？
      - 例子2：用户提问： {'user': '你是谁\n', 'assistant': {'content': '我是天策，一款大语言模型助手。'}, 'type': 2}
        模型输出：
        基于用户的提问和模型的输出，用户可能会进一步探索以下几个方面:
        question
        1. 你能为我做些什么？
        2. 大语言模型的发展历程？
        3. 你的设计逻辑是什么？
      - 例子3：用户提问：  {'user': '九寨沟旅游功略？\n', 'assistant': {'content': '在去年夏天前往这个著名的自然保护区，体验了其壮观的自然景观和独特的藏族文化。在详细的准备工作之后，他们开始了旅程，沿途欣赏到了许多美丽风景
    到达九寨沟后，那里清澈的水、五彩斑斓的池塘和层叠的瀑布给他们留下了深刻印象。除了观赏自然美景，他们还积极参与了当地的民俗活动，如跳舞和品尝传统美食，从而更加深入地了解了藏族文化。虽然旅行时间短暂，但这次经历给作者留下了美好的回忆，并成为了一次次灵的成长之旅。作者总结道，旅行不仅是一次地理上的移动，更是一次心灵的旅程，让生活变得更加丰富多彩。'}, 'type': 2}
    
        模型输出：
        基于用户的提问和模型的输出，用户可能会进一步探索以下几个方面:
        question
        1. 九寨沟的周边游？
        2. 九寨沟的天气？
        3. 适合什么出行方式？
        """
        from service_agent_manage.api.routes.agent_route import running_model_list

        response = await running_model_list()

        # 检查返回值是否为 Response 对象
        if isinstance(response, Response):
            try:
                # 解析响应体中的 JSON 数据
                response_data = json.loads(response.body)

                # 检查返回的 JSON 数据是否符合预期格式
                if response_data.get("code") == 200 and response_data.get("status") is True:
                    # 获取 data 字段中的模型列表
                    model_list = response_data.get("data", [])
                    if model_list:
                        model_uid = model_list[0]  # 获取第一个模型的 UID
                        id, model = await AgentService.get_first_running_model()
                        openAILLMService = OpenAILLMService(id)
                        question_answer = openAILLMService.chunk_chat(
                            db=db,
                            request=ChatCompletionRequestParams_v1(
                                model_uid=model,
                                system_prompts=prompt,
                                conversation_id=conversation_id,
                                talk_id=talk_id,
                                retrival_params={
                                    "kb_name": "",
                                    "user_query": str(data),
                                    "rerank_model": "",
                                    "recall_num": 0,
                                    "rerank_num": 0,
                                },
                            ),
                            chunk_content="",
                            type=3,
                        )
                        index = question_answer.find("</think>")  # 推理模型过滤思考内容
                        if index != -1:
                            question_answer = question_answer[index + len("</think>") :]
                        lines = question_answer.strip().split("\n")
                        # 提取问题部分
                        questions = [
                            line.strip().split(". ", 1)[1]
                            for line in lines
                            if line.strip().startswith("1.")
                            or line.strip().startswith("2.")
                            or line.strip().startswith("3.")
                        ]
                        # 去除空格和换行符
                        # 直接生成列表
                        final_result = questions
                        if (
                            isinstance(final_result, list)
                            and len(final_result) == 3
                            and all(isinstance(q, str) for q in final_result)
                        ):
                            # 如果符合格式，正常返回
                            result = final_result
                        else:
                            # 如果不符合，返回三个随机问题组成的列表
                            result = random.sample(question_bank, 3)
            except Exception as e:
                logger.error("处理预测问题列表响应失败:", str(e), exc_info=True)
                result = random.sample(question_bank, 3)
    except:
        result = random.sample(question_bank, 3)

    chat_obj = ChatConversationService.insert_question(db, talk_id, str(result))
    question_list = ast.literal_eval(chat_obj.question)

    try:
        results = MongodbUtil.query_doc_by_id(collection_name="model_config", doc_id="model_config")
        tt = int(results["question"])
        if tt >= 3:
            tt = 3
        if tt <= 0:
            tt = 0
    except:
        tt = 3

    question_list = question_list[:tt]
    response = {"code": 200, "status": True, "message": "success", "data": question_list}

    return response


@router.post(
    "/Question_query",
    summary="Question_query",
)
async def Question_query(
    talk_id: str = Body(..., examples=["TALK_1904512317496889344"], description="talk_id"),
    db: Session = Depends(get_db),
) -> Response:
    question_obj = ChatConversationService.query_question(db, talk_id)
    question_str = question_obj.question
    # print("question_str", question_str)
    # print(type(question_str))
    import ast

    question_list = ast.literal_eval(question_str)
    # print(type(question_list))
    # 解析 JSON 字符串为 Python 列表
    # question_list = json.loads(question_str)
    # print("question",question)
    # questions = json.loads(question)
    # que= questions['question']
    return question_list


@router.post(
    "/like_talk_review",
    summary="like_talk_review",
)
async def like_talk_review(request: ChatLikeReviewParams, db: Session = Depends(get_db)) -> Response:
    try:
        talk_status = ChatConversationService.like_talk_review(
            db=db,
            talk_id=request.talk_id,
            talk_num=request.talk_num,
            talk_review=request.talk_review,
            answer_review_tag=request.answer_review_tag,
        )
        return RetUtil.response_ok(data=talk_status)

    except Exception as e:
        # LogUtil.info(str(traceback.format_exc()))
        detail = f"对话评价失败：{str(e)}"
        logger.error(detail, exc_info=True)
        return RetUtil.response_error(message=f"失败{e}")


@router.post(
    "/query_talk_review_config",
    summary="query_talk_review_config",
)
async def query_talk_review_config(db: Session = Depends(get_db)) -> Response:
    try:
        model_info = ConfigQueryEntity(config_name="talk_review_config")
        talk_status = ConfigService.config_query(db=db, config=model_info)
        talk_config = talk_status["result"][0]["config"]["config_description"]
        return RetUtil.response_ok(data=talk_config)

    except Exception as e:
        detail = f"查询对话评价失败：{str(e)}"
        logger.error(detail, exc_info=True)
        return RetUtil.response_error(message=f"失败{e}")


@router.post(
    "/export_chat_history",
    summary="export_chat_history",
)
async def export_chat_history(request: ExportChatCompletionHistoryParams, db: Session = Depends(get_db)) -> Response:
    try:
        if request.conversation_id != []:
            talk_info = ChatConversationService.export_chat_history(
                db=db, conversation_id_list=request.conversation_id, talk_id_list=request.talk_id
            )
        else:
            return RetUtil.response_ok("conversation_id不能为空列表")

        excel_data = []
        # 处理数据
        for item in talk_info:
            excel_data.append(
                {
                    "talk_account_id": item["talk_account_id"],
                    "prompt": item["talk_content"]["prompt"],
                    "question": item["talk_content"]["user"],
                    "answer": item["talk_content"]["assistant"]["content"],
                    "talk_model_id": item["talk_model_id"],
                    "talk_attr": item["talk_attr"],
                    "think": item["talk_content"]["assistant"]["think"],
                    "think_time": item["talk_content"]["assistant"]["think_time"],
                    "retrival_info": str(item["talk_content"]["assistant"]["retrival_info"]),
                    "talk_review": item.get("talk_content", {}).get("talk_review", ""),
                    "answer_review_tag": item.get("talk_content", {}).get("answer_review_tag", []),
                }
            )

        # 创建DataFrame
        df = pd.DataFrame(excel_data)
        # 创建Excel文件在内存中
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="对话数据")

            # 获取工作簿和工作表对象进行格式设置
            workbook = writer.book
            worksheet = writer.sheets["对话数据"]

            # 设置列宽
            worksheet.set_column("A:A", 20)  # talk_account_id
            worksheet.set_column("B:B", 20)  # prompt
            worksheet.set_column("C:C", 20)  # question
            worksheet.set_column("D:D", 40)  # answer
            worksheet.set_column("E:E", 20)  # talk_model_id
            worksheet.set_column("F:F", 10)  # talk_attr
            worksheet.set_column("G:G", 30)  # think
            worksheet.set_column("H:H", 20)  # think_time
            worksheet.set_column("I:I", 10)  # retrival_info

            # 添加标题格式
            header_format = workbook.add_format(
                {"bold": True, "text_wrap": True, "valign": "top", "fg_color": "#D7E4BC", "border": 1}
            )

            # 应用标题格式
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)

        output.seek(0)
        # 直接返回Response
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=conversation_data.xlsx"},
        )

    except Exception as e:
        detail = f"到处excel失败：{str(e)}"
        logger.error(detail, exc_info=True)
        return RetUtil.response_error(message=detail)


@router.delete(
    "/chat_workflow_delete",
    summary="chat_workflow_delete",
)
async def chat_workflow_delete(
    request: ChatCompletionHistoryParams, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    # print(f"stream请求体参数:--{request}")
    # # 检查账号id
    account_id = chat_request.state.account_id
    res = ChatConversationService.chat_workflow_delete(db=db, conversation_id=request.conversation_id)
    return RetUtil.response_ok(res)


@router.post(
    "/multimodel_chat",
    summary="multimodel_chat",
)
async def multimodel_caht(
    request: Multimodel_ChatParams, chat_request: Request, db: Session = Depends(get_db)
) -> EventSourceResponse:
    # # 检查账号id
    account_id = chat_request.state.account_id
    openAILLMService = OpenAILLMService(id="690484d5e0413c31b6c36870")

    async def astream_response():
        try:
            response_content = ""
            content = ""
            think = ""
            think_time = 0
            # 保存问答数据
            talk_id, talk_num = ChatConversationService.save_talk_data_file(
                db=db,
                conversation_id=request.conversation_id,
                account_id=account_id,
                token=content,
                images=request.images,
                prompt="",
                think=think,
                think_time=think_time,
                question=request.user_query,
                model_id="",
                kb_id="",
                ag_id="",
                type=request.type,
                talk_id=request.talk_id,
                retrival_info=[],
            )
            logger.info("已保存对话记录 | talk_id={} | talk_num={}", talk_id, talk_num)
            ChatConversationService.save_talk_data_file_stop(
                db=db,
                conversation_id=request.conversation_id,
                account_id=account_id,
                type=request.type,
                talk_id=talk_id,
                talk_num=talk_num,
            )
            from pathlib import Path

            BAN_PATH = Path(__file__).resolve().parent.parent.parent.parent / "违禁词.txt"
            if not BAN_PATH.exists():
                raise RuntimeError(f"找不到违禁词文件：{BAN_PATH}")
            BAN_WORDS = BAN_PATH.read_text(encoding="u8").splitlines()

            # ---------- 2. 建 DFA ----------
            _DFA = {}
            for word in BAN_WORDS:
                word = word.lower().strip()
                if not word:
                    continue
                node = _DFA
                for ch in word:
                    node = node.setdefault(ch, {})
                node["#"] = True  # 结束标记

            def has_ban(text: str) -> bool:
                text = text.lower()
                for i in range(len(text)):
                    node = _DFA
                    for ch in text[i:]:
                        if "#" in node:  # 走到结尾 => 命中
                            return True
                        if ch not in node:
                            break
                        node = node[ch]
                    else:  # for...else：正常结束也检查
                        if "#" in node:
                            return True
                return False

            is_prohibited = has_ban(request.user_query)
            if is_prohibited == True:
                logger.info("违禁词违禁")
                result = {
                    "token": "您的输入包含违规内容，请修改后重新提交。感谢理解与配合！",
                    "type": "text",
                    "think_time": think_time,
                }
                response_result = {
                    "result": result,
                    "tokens_consume": 0,
                    "query": request.user_query,
                    "model_uid": request.model_uid,
                    "tool_outputs": [],
                    "conversation_id": request.conversation_id,
                    "talk_id": talk_id,
                    "talk_num": talk_num,
                    "retrival_info": [],
                }
                yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"
                return
            else:
                is_prohibited = openAILLMService.multimodel_chunk_chat(db=db, request=request, type=request.type)
            logger.info(f"是否违禁：{is_prohibited}")
            if is_prohibited == "违禁":
                logger.info("名字违禁")
                result = {
                    "token": "您的输入包含违规内容，请修改后重新提交。感谢理解与配合！",
                    "type": "text",
                    "think_time": think_time,
                }
                response_result = {
                    "result": result,
                    "tokens_consume": 0,
                    "query": request.user_query,
                    "model_uid": request.model_uid,
                    "tool_outputs": [],
                    "conversation_id": request.conversation_id,
                    "talk_id": talk_id,
                    "talk_num": talk_num,
                    "retrival_info": [],
                }
                yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"
            else:
                async for chunk in await openAILLMService.multimodel_stream_chat(
                    db=db, request=request, type=request.type
                ):
                    if chunk.choices[0].delta.content != "" and chunk.choices[0].delta.content != None:
                        token = chunk.choices[0].delta.content
                        result = {"token": token, "type": "text", "think_time": think_time}
                        response_result = {
                            "result": result,
                            "tokens_consume": 0,
                            "query": request.user_query,
                            "model_uid": request.model_uid,
                            "tool_outputs": [],
                            "conversation_id": request.conversation_id,
                            "talk_id": talk_id,
                            "talk_num": talk_num,
                            "retrival_info": [],
                        }
                        content += token
                        # status = ChatConversationService.check_talk_stop_status(db=db, talk_id=talk_id, talk_num=talk_num)
                        redis = chat_request.app.state.redis_pool
                        status = await RedisUtil.get_cached_data(key=f"{talk_id}{str(talk_num)}", redis=redis)
                        if status:
                            status = int(status.get("value"))
                        # status == 3 代表中断
                        if status == 3:
                            break
                        else:
                            yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"
                        if token is not None:
                            response_content += token
                        # 数据库内存每隔10个token更新一次，以支持正确取得status标签，可以停止对话
                        # if len(response_content) % 15 == 0:
                        #     db.commit()
                data = {
                    "prompt": "",
                    "user": request.user_query,
                    "images": request.images,
                    "assistant": {
                        "content": content,
                        "think": think,
                        "think_time": think_time,
                        "retrival_info": [],
                    },
                    "type": 0,
                }
                data = json.dumps(data)
                ChatConversationService.update_talk_data(db=db, talk_id=talk_id, token_data=data, talk_num=talk_num)
                logger.info(
                    "multimodel_chat 完成 | conv_id={} | account_id={} | 输出长度=%d | query={} | model={}",
                    request.conversation_id,
                    account_id,
                    len(response_content),
                    request.user_query,
                    "",
                )
        except Exception as e:
            logger.error("异常: {}", str(e), exc_info=True)
            if talk_id != "":
                ChatConversationService.delete_talk(db=db, talk_id=talk_id)
            result = {"token": "系统繁忙,请稍后再试", "type": "text", "think_time": 0}
            response_result = {
                "result": result,
                "tokens_consume": 0,
                "query": "",
                "model_uid": "",
                "tool_outputs": "",
                "conversation_id": "",
                "talk_id": "",
                "talk_num": "",
            }
            yield f"{json.dumps(RetUtil.response_stream(data=response_result), ensure_ascii=False)}"

    return EventSourceResponse(astream_response())
