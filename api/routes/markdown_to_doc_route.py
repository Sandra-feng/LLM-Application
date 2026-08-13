# import pypandoc, tempfile, io

from loguru import logger
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from base_utils.mysql_util import SessionLocal
from base_utils.ret_util import RetUtil
from service_agent_manage.service.agent_service import AgentService
from service_model_manage.entity.chat_completion_entity import (
    ChatCompletionHistoryParams,
    ChatCompletionListParams_mem,
    ChatCompletionRequestParams_v1,
)
from service_model_manage.service.chat_completion_service import OpenAILLMService
from service_model_manage.service.chat_db_service import ChatConversationService
# logger = loguru logger (auto-migrated)
router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/doc_ppt_chat_list", summary="文档/PPT生成对话列表")
async def doc_chat_list(request: ChatCompletionListParams_mem, chat_request: Request, db: Session = Depends(get_db)):
    # request中的type为7，文档生成对话列表查询，model_id、kb_id、ag_id均为""，create根据前端传入判断
    # request中的type为8，文档生成对话列表查询，model_id、kb_id、ag_id均为""，create根据前端传入判断
    # logger.info(f"->创建新对话或者查询对话列表请求体参数: {str(request)}")

    # 创建新对话或者查询对话列表
    logger.info("->查询对话列表")
    account_id = chat_request.state.account_id
    check_talk_list = ChatConversationService.create_text_to_image_chat(
        db=db,
        account_id=account_id,
        type=request.type,
        model_id=request.model_id,
        kb_id=request.kb_id,
        ag_id=request.ag_id,
        create=request.creat,
    )
    logger.info("->查询对话列表成功")
    return RetUtil.response_ok(check_talk_list)


@router.post("/doc_ppt_history", summary="doc/PPT生成历史")
async def text_to_image_history(request: ChatCompletionHistoryParams, db: Session = Depends(get_db)):
    # logger.info(f"文档/PPT生成历史查询请求体参数:--{str(request)}")

    # 查询所有对话的第一条会话信息
    logger.info("->查询所有对话第一条会话信息")
    talk_info = ChatConversationService.check_talk_info_history_firstpage(
        db=db, conversation_id=request.conversation_id
    )
    logger.info("->所有对话第一条会话信息查询成功")
    return RetUtil.response_ok(talk_info)


@router.post("/generate_filename", summary="生成文件名")
async def generate_filename(
    question: str = Body(..., embed=True, description="用户提出的问题"),
    answer: str = Body(..., embed=True, description="模型生成的回答"),
    conversation_id: str = Body(..., embed=True, description="模型生成的回答"),
    chat_request: Request = None,
    db: Session = Depends(get_db),
) -> Response:
    """
    根据用户提出的问题和模型生成的回答，调用大模型生成一个合适的文件名。

    Args:
        question (str): 用户提出的问题。
        answer (str): 模型生成的回答。
        db (Session): 数据库会话。

    Returns:
        JSONResponse: 包含生成的文件名的 JSON 响应。
    """
    try:
        # 构建提示词，要求大模型生成文件名
        logger.info("->调用大模型生成文件名")
        prompt_for_filename = f"""
                请根据以下对话内容生成一个合适的文件名：
                用户问题：{question}
                回答内容：{answer}
                文件名应简洁明了，能够反映对话的主题，只需要返回文件实际名称，不需要文件类型后缀以及其他描述。
                """
        # 调用大模型生成文件名
        id, model = await AgentService.get_first_running_model()
        openAILLMService = OpenAILLMService(id=id)
        # 假设 OpenAILLMService 使用的是 OpenAI 的 API
        # 如果使用其他 LLM 服务，需要相应调整调用方式
        response = await openAILLMService.stream_chat_v1_with_penalty(
            request=ChatCompletionRequestParams_v1(
                model_uid=model,
                system_prompts=prompt_for_filename,
                conversation_id=conversation_id,
                max_token_length=8192,
                temperature=0.8,
                history=0,
                presence_penalty=0,
                frequency_penalty=0,
                retrival_params={"user_query": prompt_for_filename},
            ),
            db=db,
            chunk_content="",
            type=0,
            model_list=[],
        )

        # 提取生成的文件名
        generated_text = ""
        async for chunk in response:
            if chunk.choices[0].delta.content != "" and chunk.choices[0].delta.content != None:
                generated_text += chunk.choices[0].delta.content

        # 假设文件名是生成文本的第一部分，实际应用中可以根据模型输出调整
        filename = generated_text.strip().split("\n")[0]
        logger.info(f"生成文件名成功，生成的文件名：{filename}")
        result = {"filename": filename}

        # 返回文件名
        return RetUtil.response_ok(data=result)

    except Exception as e:
        detail = f"生产文件名失败：{str(e)}"
        logger.error(detail, exc_info=True)
        return RetUtil.response_error(message=str(e))
