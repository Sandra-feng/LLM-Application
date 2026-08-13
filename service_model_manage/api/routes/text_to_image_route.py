import os
import time

import openai
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request
from loguru import logger
from sqlalchemy.orm import Session

# from xinference.client import Client
from base_configs.model_config import ModelConfig
from base_utils.mysql_util import SessionLocal
from base_utils.ret_util import RetUtil
from service_agent_manage.service.agent_service import AgentService
from service_model_manage.entity.chat_completion_entity import ChatCompletionHistoryParams, ChatCompletionListParams_mem
from service_model_manage.service.chat_db_service import ChatConversationService
from service_model_manage.service.text_to_image_service import (
    get_image_count,
    get_question,
    image_save,
)

# logger = loguru logger (auto-migrated)
router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


client = openai.AsyncClient(api_key=ModelConfig.AUDIO_API_KEY, base_url=ModelConfig.IMAGE_API_BASE)


@router.post("/get_pic_count", summary="获取生成图片数量")
async def get_pic_count(
    question: str = Body(..., embed=True, description="用户提问"),
):
    try:
        # 获取生成图片数量
        # 获取用户提问翻译并去除图片数量信息
        logger.info(f"用户的提问为: {question}")
        number = await get_image_count(question)
        new_question = await get_question(question)
        logger.info(f"识别到用户文生图的数量为: {number}")
        logger.info(f"获取到翻译用户提问并去除提问中关于图片的量词: {new_question}")

        return RetUtil.response_ok({"question": new_question, "number": number})

    except Exception as e:
        detail = f"获取生成图片数量：失败原因<{str(e)}>"
        logger.error("获取生成图片数量失败", exc_info=True)
        return RetUtil.response_error(message=detail)


@router.post("/text_to_image", summary="文生图")
async def text_to_image(
    request: Request,
    question: str = Body(..., embed=True, description="用户提问"),
    new_question: str = Body(..., embed=True, description="用户提问英文"),
    number: int = Body(..., embed=True, description="生成图片数量"),
    conversation_id: str = Body(..., embed=True, description="对话ID"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    talk_id: str = Body("", embed=True, description="会话ID"),
    db: Session = Depends(get_db),
):
    try:
        logger.info(
            f"（文生图任务）text_to_image called | conv_id={conversation_id} | talk_id={talk_id} | num={number}"
        )
        # 生成图片base-64编码，这里不获取url，因为获取的url实际上是部署文生图模型的本地路径
        time1 = time.time()
        model_uid = ""
        internal_model_list, external_model_list = await AgentService.get_running_model_list(model_type="image")
        if internal_model_list["children"]:
            for model in internal_model_list["children"]:
                model_uid = model["model_uid"]
                break
        else:
            for model in external_model_list["children"]:
                model_uid = model["model_uid"]
                break
        if not model_uid:
            return RetUtil.response_error(message="图像模型不存在，请检查系统是否启动图像模型")
        response = await client.images.generate(
            model=model_uid, prompt=new_question, n=number, size="512x512", response_format="b64_json"
        )
        time2 = time.time()
        logger.info(f"模型生成图片耗时(s): {time2 - time1:.3f} | model={model_uid} | num={number}")
        # 保存图片并获取本地与远程地址
        local_paths, remote_paths = await image_save(response)
        if not local_paths:
            logger.warning("图片保存失败：local_paths 为空")
            return RetUtil.response_error(message="图片保存失败")

        # 删除本地文件
        def delete_local_files(local_paths: list):
            for local_path in local_paths:
                if os.path.exists(local_path):
                    os.remove(local_path)

        # 清除本地文件
        background_tasks.add_task(delete_local_files, local_paths)
        time3 = time.time()
        # 保存对话数据
        account_id = request.state.account_id
        talk_id, talk_num = ChatConversationService.save_talk_data_image(
            db=db,
            conversation_id=conversation_id,
            account_id=account_id,
            images=remote_paths,
            question=question,
            model_id=model_uid,
            kb_id="",
            ag_id="",
            type=6,
            talk_id=talk_id,
        )
        time4 = time.time()
        logger.info(f"MYSQL 保存图片对话数据耗时(s): {time4 - time3:.3f} | talk_id={talk_id} | talk_num={talk_num}")
        return RetUtil.response_ok({"remote_paths": remote_paths, "talk_id": talk_id})

    except Exception as e:
        detail = f"文生图失败：失败原因<{str(e)}>"
        logger.error("text_to_image 发生异常", exc_info=True)
        return RetUtil.response_error(message=detail)


@router.post("/text_to_image_chat_list", summary="文生图对话列表")
async def text_to_image_chat_list(
    request: ChatCompletionListParams_mem, chat_request: Request, db: Session = Depends(get_db)
):
    # request中的type为6,model_id、kb_id、ag_id均为""，create根据前端传入判断
    logger.info(f"文生图对话列表请求体参数:--{str(request)}")

    # 创建新对话或者查询对话列表
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

    return RetUtil.response_ok(check_talk_list)


@router.post("/text_to_image_history", summary="文生图历史")
async def text_to_image_history(request: ChatCompletionHistoryParams, db: Session = Depends(get_db)):
    logger.info(f"查询文生图历史的请求体参数: {request}")

    # 查询所有对话的第一条会话信息
    talk_info = ChatConversationService.check_talk_info_history_firstpage(
        db=db, conversation_id=request.conversation_id
    )
    return RetUtil.response_ok(talk_info)


# @router.post("/image_to_image", summary="图生图")
# async def image_to_image(
#     request: Request,
#     db: Session = Depends(get_db),
#     conversation_id: str = Form(..., description="对话ID"),
#     img_file: Optional[UploadFile] = File(None, description="文件"),
#     img_path: Optional[str] = Form(None, description="对话ID"),
#     prompt: str = Form("", description="用户提问"),
#     talk_id: str = Form("", description="会话ID"),
#     background_tasks: BackgroundTasks = BackgroundTasks(),
# ):
#     try:
#         if prompt == "":
#             return RetUtil.response_error(message="输入不能为空")
#         logger.info(f"图生图参数:--conversation_id：{conversation_id}--prompt{prompt}")
#         # 获取图生图结果
#         model_uid = ""
#         client = Client(ModelConfig.DEFAULT_IMAGE_URL)
#         internal_model_list, external_model_list = await AgentService.get_running_model_list(model_type="image")
#         if internal_model_list["children"]:
#             for model in internal_model_list["children"]:
#                 model_uid = model["model_uid"]
#                 break
#         else:
#             for model in external_model_list["children"]:
#                 model_uid = model["model_uid"]
#                 break
#         if not model_uid:
#             return RetUtil.response_error(message="图像模型不存在，请检查系统是否启动图像模型")
#         model = client.get_model(model_uid)
#         if img_file != None:
#             image_data = await img_file.read()
#             import io

#             from PIL import Image

#             image = Image.open(io.BytesIO(image_data))
#             if image.mode != "RGB":
#                 image = image.convert("RGB")
#                 output = io.BytesIO()
#                 image.save(output, format="PNG")
#                 output.seek(0)
#                 image_data = output.getvalue()
#         elif img_path != None:
#             remote_path = img_path
#             image_data = await remote_image_data(remote_path)
#         else:
#             RetUtil.response_error(message="文件路径与文件内容都为空，请检查入参")
#         question = await get_question(prompt)

#         try:
#             # 设置超时时间（例如：60秒）
#             timeout_seconds = 60
#             time1 = time.time()
#             response = model.image_to_image(prompt=question, image=image_data, response_format="b64_json")
#             time2 = time.time()
#             logger.info(f"图生图时间：《{time2 - time1}》")
#         except asyncio.TimeoutError:
#             return RetUtil.response_error(message="响应时间过长，请稍后再试")

#         local_path, remote_path = await save_img(image_data)

#         # 保存图片并获取本地与远程地址
#         local_paths, remote_paths = await image_to_image_save(response)
#         if not local_paths:
#             return RetUtil.response_error(message="图片保存失败")

#         def delete_local_files(local_paths: list):
#             for local_path in local_paths:
#                 if os.path.exists(local_path):
#                     os.remove(local_path)

#         # 清除本地文件
#         background_tasks.add_task(delete_local_files, local_paths)
#         background_tasks.add_task(delete_local_files, [local_path])

#         # 保存对话数据
#         account_id = request.state.account_id
#         talk_id, talk_num = ChatConversationService.save_talk_data_image(
#             db=db,
#             conversation_id=conversation_id,
#             account_id=account_id,
#             images=remote_paths,
#             question=prompt,
#             model_id=model_uid,
#             kb_id="",
#             ag_id="",
#             type=6,
#             talk_id=talk_id,
#             image=remote_path,
#         )

#         return RetUtil.response_ok({"remote_paths": remote_paths, "talk_id": talk_id, "self_image": remote_path})

#     except Exception as e:
#         detail = f"图生图失败：失败原因<{str(e)}>"
#         logger.error("image_to_image 发生异常", exc_info=True)
#         return RetUtil.response_error(message=detail)
