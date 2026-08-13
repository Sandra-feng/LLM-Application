import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from loguru import logger
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTasks

from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.mysql_util import query2dict_acc, query2dict_status
from base_utils.ret_util import RetUtil
from base_utils.time_util import TimeUtil
from service_agent_manage.entity.agent_entity import (
    AgentInfo,
    ArrangeAgentInfo,
    QueryAgentInfo1,
    QueryTeamAgentInfo,
    TestAgentInfo,
    TestAgentInfo_v1,
    TestAgentInfo_v2,
    TypeItemDelete,
    TypeItemDict,
    TypeItemUpdateDict,
)
from service_agent_manage.entity.agent_vo import (
    AgentListRequest,
    ApiResponse,
    CreateAgentRequest,
    UpdateAgentRequest,
)
from service_agent_manage.service.agent_service import AgentService
from service_agent_manage.service.call_agent_service import AgentCallOptimizer
from service_model_manage.entity.chat_completion_entity import (
    ChatCompletionRequestParams,
    ChatCompletionRequestParams_v1,
)

# logger = loguru logger (auto-migrated)
from service_model_manage.model.mem_chat_model import MemberChat_Model
from service_model_manage.service.chat_completion_service import OpenAILLMService
from service_model_manage.service.chat_db_service import ChatConversationService
from service_model_manage.service.model_family_service import ModelFamilyService
from service_permission_auth.entity.usr_auth_entity import UsrEntity
from service_permission_auth.service.usr_auth_service import UsrAuthService
from service_prompt_manage.model.prompt_info_model import Prompt_Model
from service_usr_manage.model.usr_model import Usr_Model
from service_usr_manage.service.usr_service import UsrService

router = APIRouter()


def get_db(request: Request):
    db = request.app.state.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.delete("/agent_delete_v1", summary="删除智能体v1")  # 使用中
async def agent_delete(
    chat_request: Request, agent_id: str = Body(..., embed=True, examples=["test"], description="智能体id")
) -> Response:
    try:
        # headers = dict(chat_request.headers)
        # account_id = ChatConversationService.get_account_id(headers=headers)
        account_id = chat_request.state.account_id
        if not account_id:
            return RetUtil.return_error(message="用户id不存在")
        result = await AgentService.delete_agent(agent_id, account_id)
        return RetUtil.response_ok({})
    except Exception as e:
        logger.exception(f"智能体创建异常: {e}")
        return Response(content=f"命令执行异常: {e}", media_type="text/plain")


@router.get("/agent_has_tool_or_kb_export", summary="判断是否有工具或者知识库")  # 使用
async def agent_has_tool_or_kb_export(agent_id: str):
    try:
        result = await AgentService.agent_has_tool_or_kb_export(agent_id)
        if isinstance(result, dict):
            return RetUtil.response_ok(result)
        else:
            return RetUtil.response_error(message="查询智能体失败")

    except Exception as e:
        detail = f"查询工具与知识库失败：{str(e)}"
        logger.exception(e)
        raise HTTPException(status_code=500, detail=detail)


@router.post("/agent_import", summary="导入智能体")  # 使用中
async def agent_import(
    chat_request: Request,
    is_save_kn: bool = Body(False, description="是否导入知识库"),
    is_save_tool: bool = Body(False, description="是否导入工具"),
    file_obj: UploadFile = File(..., description="文件"),
    team_code: str = Body(None, description="团队ID列表（如果为空，则为个人工具）"),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    # 后台清理文件
    async def delete_file(file_path: str):
        try:
            if os.path.exists(file_path) and file_path.endswith(".zip"):
                os.remove(file_path)
                logger.info(f"zip压缩包文件已删除: {file_path}")
            elif os.path.exists(file_path) and not file_path.endswith(".zip"):
                shutil.rmtree(file_path)
                logger.info(f"解压文件夹已删除: {file_path}")
        except Exception as e:
            logger.exception(f"删除文件或zip压缩包失败: {file_path}, 错误信息: {e}")

    zip_file_folder = ""

    try:
        account_id = chat_request.state.account_id
        zip_file_folder, report_m = await AgentService.agent_import(
            file_obj, is_save_kn, is_save_tool, account_id, team_code, db
        )

        return RetUtil.return_ok(
            data={"message": ("导入个人智能体成功\n" if team_code == "" else "导入团队智能体成功\n") + report_m}
        )

    except KeyError as e:
        detail2 = f"缺少字段：{str(e)}"
        logger.exception(detail2)
        detail = "所上传的文件不符合规范，请检查后重新上传"
        raise HTTPException(status_code=400, detail=detail)

    except HTTPException as e:
        raise HTTPException(status_code=400, detail=e.detail)

    except Exception as e:
        detail = f"导入智能体失败：{str(e)}"
        logger.exception(f"导入智能体异常：{e}")
        raise HTTPException(status_code=500, detail=detail)

    finally:
        background_tasks.add_task(delete_file, str(zip_file_folder))


@router.get("/agent_export", summary="导出智能体")  # 使用
async def agent_export(
    agent_id: str, is_save_kn: bool, is_save_tool: bool, background_tasks: BackgroundTasks = BackgroundTasks()
):
    # 后台清理文件
    async def delete_file(file_path: str):
        try:
            if os.path.exists(file_path) and file_path.endswith(".zip"):
                os.remove(file_path)
                logger.info(f"zip压缩包文件已删除: {file_path}")
            elif os.path.exists(file_path) and not file_path.endswith(".zip"):
                shutil.rmtree(file_path)
                logger.info(f"解压文件夹已删除: {file_path}")
        except Exception as e:
            logger.exception(f"删除文件或zip压缩包失败: {file_path}, 错误信息: {e}")

    zip_file_path = ""
    try:
        # 调用服务层的导出智能体方法
        zip_file_path = await AgentService.agent_export(agent_id, is_save_kn, is_save_tool)

        # 检查文件是否存在
        if not zip_file_path or not os.path.exists(zip_file_path):
            return RetUtil.response_error(message="智能体导出失败，压缩文件不存在")

        # 返回ZIP文件给前端
        return FileResponse(path=zip_file_path, filename=f"{agent_id}_导出", media_type="application/zip")

    except KeyError as e:
        logger.info(f"导出智能体异常：{e}")
        detail = "所上传的文件不符合规范，请检查后重新上传"
        raise HTTPException(status_code=400, detail=detail)

    except HTTPException as he:
        raise HTTPException(status_code=500, detail=he.detail)

    except Exception as e:
        detail = f"导出智能体失败：{str(e)}"
        logger.info(f"导出智能体异常：{e}")
        raise HTTPException(status_code=500, detail=detail)

    finally:
        if zip_file_path:
            background_tasks.add_task(delete_file, str(zip_file_path))
            zip_file_folder = Path(zip_file_path).with_suffix("")
            background_tasks.add_task(delete_file, str(zip_file_folder))


@router.post("/agent_copy", summary="复制智能体")  # 使用
async def agent_copy(
    agent_id: str = Body(..., embed=True, examples=["test"], description="智能体id"),
    db: Session = Depends(get_db),
) -> Response:
    try:
        # 调用服务层的复制智能体方法
        result = await AgentService.copy_agent(agent_id, db)
        if result:
            return RetUtil.response_ok({"message": "智能体复制成功"})
        else:
            return RetUtil.response_error(message="智能体复制失败")
    except Exception as e:
        logger.exception(f"复制智能体异常: {e}")
        return Response(content=f"复制智能体异常: {e}", media_type="text/plain")


@router.delete("/agent_delete", summary="删除智能体")  # 使用
async def agent_delete(agent_id: str = Body(..., embed=True, examples=["test"], description="智能体id")) -> Response:
    try:
        result = await AgentService.delete_agent(agent_id)
        if result == False:
            return RetUtil.return_error(message="该智能体id不存在")
        return RetUtil.response_ok(result)
    except Exception as e:
        logger.exception(f"智能体删除异常: {e}")
        return Response(content=f"智能体删除异常: {e}", media_type="text/plain")


@router.post("/agent_test", summary="测试智能体")  # 使用
async def agent_test(params: TestAgentInfo) -> Response:
    try:
        result = MongodbUtil.query_docs_by_condition(
            CollectionConfig.ARRANGE_AGENT_COLLECTION, search_condition={"_id": ObjectId(params.agent_id)}
        )
        for item in result:
            model_uid = item["model_uid"]
            prompt = item["prompt"]
            kb_list = item["kb_list"]
            tool_list = item["tool_list"]
        openAILLMService = OpenAILLMService()
        result = await AgentService.test_agent(params)
        doc_result = []

        if len(result) < 10 and len(kb_list) > 0:
            docs = await knowledge_retrieval(params.input, kb_list)
            for doc in docs:
                for item in doc:
                    doc_result.append(item["entity"]["content"])
            prompt_answer = f"""
            尽可能以有用且准确的方式回复人类。
            知识库知识:{doc_result}
            根据用户输入和检索到的知识库内容和你自己的知识进行知识整合，对用户问题进行回答。
            """
            prompt_answer = prompt + prompt_answer

            async def astream_response():
                response_content = ""
                async for chunk in await openAILLMService.stream_chat(
                    request=ChatCompletionRequestParams(
                        question=params.input,
                        system_prompts=prompt_answer,
                        chatbot=params.chatbot,
                        history=3,
                        max_token_length=4096,
                        temperature=0.8,
                        model_uid=model_uid,
                    )
                ):
                    if chunk.choices[0].delta.content != "":
                        token = chunk.choices[0].delta.content
                        yield f"{json.dumps(RetUtil.response_stream(data=token), ensure_ascii=False)}"
                        if token is not None:
                            response_content += token
                        else:
                            # 处理 None 的情况，例如给一个默认值或者跳过
                            pass

        else:
            result = json.loads(result)
            for tool in tool_list:
                if tool["tool_name"] == result["tool_name"]:
                    tool_url = tool["tool_url"]
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(tool_url, json=result["params"])
            result = response.json()
            logger.info(f"工具结果:{str(result)}")
            prompt_answer = f"""
            尽可能以有用且准确的方式回复人类。
            工具返回结果:{result}
            根据用户输入结合工具返回结果对用户问题进行回答。
            """
            prompt_answer = prompt + prompt_answer

            async def astream_response():
                response_content = ""
                async for chunk in await openAILLMService.stream_chat(
                    request=ChatCompletionRequestParams(
                        question=params.input,
                        system_prompts=prompt_answer,
                        chatbot=params.chatbot,
                        history=3,
                        max_token_length=4096,
                        temperature=0.8,
                        model_uid=model_uid,
                    )
                ):
                    if chunk.choices[0].delta.content != "":
                        token = chunk.choices[0].delta.content
                        yield f"{json.dumps(RetUtil.response_stream(data=token), ensure_ascii=False)}"
                        if token is not None:
                            response_content += token
                        else:
                            # 处理 None 的情况，例如给一个默认值或者跳过
                            pass

        return EventSourceResponse(astream_response())
    except Exception as e:
        logger.exception(f"测试智能体异常: {e}")
        return Response(content=f"测试智能体异常: {e}", media_type="text/plain")


@router.post("/running_llm_list", summary="获取运行中的大语言模型列表")  # 使用中
async def running_model_list() -> Response:
    try:
        result = await AgentService.running_LLM_model()
        return RetUtil.response_ok(result)
    except Exception as e:
        logger.exception(f"返回运行中大语言模型列表异常: {e}")
        return Response(content=f"返回运行中大语言模型列表异常: {e}", media_type="text/plain")


@router.post("/agent_arrange_info", summary="智能体编排信息")  # 使用中
async def agent_arrange_info(
    chat_request: Request,
    db: Session = Depends(get_db),
    agent_id: str = Body(..., embed=True, examples=["test"], description="智能体id"),
) -> Response:
    try:
        logger.info("->获取智能体编排信息")
        result = await AgentService.agent_arrange_info(chat_request, agent_id, db)
        logger.info("->获取智能体编排信息成功")
        return RetUtil.response_ok(result)

    except Exception as e:
        detail = f"获取智能体编排信息失败：{(str(e))}"
        logger.exception(detail)
        return RetUtil.response_error(message=detail)


@router.post("/agent_create_v1", summary="新增智能体v1")  # 使用中
async def agent_create(params: AgentInfo, chat_request: Request, db: Session = Depends(get_db)) -> Response:
    try:
        account_id = chat_request.state.account_id
        if await AgentService.agent_exist(params.agent_name, account_id):
            return RetUtil.response_error("智能体已存在")
        if isinstance(params.team_code, str):
            result, object_id = await AgentService.create_team_agent(
                params.agent_name,
                params.description,
                account_id,
                params.team_code,
                params.type_name,
                params.item_type,
                db,
            )
            return RetUtil.response_ok({"build_time": TimeUtil.timestamp_to_date(time.time()), "agent_id": object_id})
        # 判断智能体是否存在
        else:
            result, object_id = await AgentService.create_agent(
                params.agent_name,
                params.description,
                account_id,
                params.item_type,
                params.type_name,
            )
            return RetUtil.response_ok({"build_time": TimeUtil.timestamp_to_date(time.time()), "agent_id": object_id})
    except Exception as e:
        logger.exception(f"智能体创建异常: {e}")
        return Response(content=f"命令执行异常: {e}", media_type="text/plain")


@router.post("/agent_arrange_v1", summary="编排智能体v1")  # 使用中
async def agent_arrange(chat_request: Request, params: ArrangeAgentInfo) -> Response:
    try:
        account_id = chat_request.state.account_id
        if not account_id:
            return RetUtil.return_error(message="用户id不存在")
        result = await AgentService.arrange_agent(
            agent_id=params.agent_id,
            account_id=account_id,
            model_params=params.model_params,
            prompt=params.prompt,
            recall_setting=params.recall_setting,
            kb_list=params.kb_list,
            tool_list=params.tool_list,
            variable_list=params.variable_list,
            promptHtml=params.promptHtml,
            prompt_id=params.prompt_id,
            is_question_rewriting=params.is_question_rewriting,
        )

        result1 = await AgentService.update_agent_status(agent_id=params.agent_id, status=0)
        return RetUtil.response_ok(result)
    except Exception as e:
        logger.exception(f"编排智能体异常: {e}")
        return Response(content=f"编排智能体异常: {e}", media_type="text/plain")


@router.post("/query_agent_v1", summary="查询智能体列表v1")  # 使用中
async def query_agent_list(params: QueryAgentInfo1, chat_request: Request, db: Session = Depends(get_db)) -> Response:
    try:
        start = time.time()
        account_id = chat_request.state.account_id

        if not account_id:
            return RetUtil.return_error(message="用户id不存在")

        if isinstance(params.team_codes, list):
            result = await AgentService.query_team_agent(
                params.agent_name,
                params.page,
                params.page_size,
                account_id,
                params.team_codes,
                params.item_type,
                params.id,
                db=db,
                status=params.status,
            )
            return RetUtil.response_ok(result)
        else:
            result = await AgentService.query_agent(
                params.agent_name, params.page, params.page_size, account_id, params.item_type, params.id, params.status
            )
            return RetUtil.response_ok(result)
    except Exception as e:
        detail = f"查询智能体列表异常：{str(e)}"
        logger.exception(f"查询智能体列表异常: {e}")
        return RetUtil.response_error(message=detail)


@router.post("/knowledge_list_test", summary="知识库列表(带用户权限)")
async def knowledge_list(
    chat_request: Request,
) -> Response:
    try:
        account_id = chat_request.state.account_id
        result = await AgentService.list_knowledge_test(account_id)
        return RetUtil.response_ok(result)
    except Exception as e:
        logger.exception(f"返回知识库列表异常: {e}")
        return Response(content=f"返回知识库列表异常: {e}", media_type="text/plain")


@router.post("/tool_list_user", summary="工具集列表(带用户权限)")  # 使用中 (1.3.2版本将废弃)
async def tool_list(
    chat_request: Request,
    team_codes: list = Body("", description="团队ID列表（如果为空，则查询个人工具）", embed=True),
    db: Session = Depends(get_db),
) -> Response:
    try:
        account_id = chat_request.state.account_id
        user_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, account_id)
        user_id_list, admin_id_list = await ModelFamilyService.get_account_id_by_user_attribute(
            db, user_attribute, account_id
        )
        user_tools_info_list = await AgentService.tool_query_by_user(user_id_list, team_codes)
        admin_tools_info_list = await AgentService.tool_query_by_user(admin_id_list)
        if user_attribute == 0:
            result = [{"integrated": admin_tools_info_list}, {"customized": user_tools_info_list}]
        else:
            result = [{"integrated": admin_tools_info_list}]
        return RetUtil.response_ok(result)
    except Exception as e:
        detail = f"查询工具集列表错误{str(e)}"
        logger.exception(detail)
        # 返回HTTP错误响应
        raise HTTPException(status_code=400, detail=detail)


@router.post("/agent_update", summary="修改智能体信息")  # 使用
async def workflow_update(
    chat_request: Request,
    agent_id: str = Body(..., embed=True, examples=["id"], description="智能体id"),
    agent_name: str = Body(..., embed=True, examples=["test"], description="名称"),
    description: str = Body(..., embed=True, examples=["desc"], description="描述"),
    team_code: Optional[str] = Body(None, description="团队代码", examples=["10001"]),
    item_type: str = Body(None, description="子类别", examples=["0"]),
    db: Session = Depends(get_db),
) -> Response:
    try:
        code = item_type
        account_id = chat_request.state.account_id
        if team_code == None:
            # 用户是否存在
            user_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, account_id)
            if user_attribute == None:
                return RetUtil.response_error(message="用户不存在")
            result = await AgentService.update_agent(agent_id, agent_name, description, code)
            if result == False:
                return RetUtil.response_error("修改智能体信息异常")
            return RetUtil.response_ok(result)
        else:
            # 用户是否存在
            user_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, account_id)
            if user_attribute == None:
                return RetUtil.response_error(message="用户不存在")
            result = await AgentService.update_team_agent(agent_id, agent_name, description, team_code, db, code)
            if result == False:
                return RetUtil.response_error("修改智能体信息异常")
            return RetUtil.response_ok(result)
    except Exception as e:
        logger.exception(f"智能体基础信息修改异常: {e}")
        return Response(content=f"智能体修改异常: {e}", media_type="text/plain")


@router.post("/creat_api", summary="生成智能体api")
async def creat_api(
    chat_request: Request,
    agent_id: str = Body(..., embed=True, examples=["id"], description="智能体id"),
    db: Session = Depends(get_db),
) -> Response:
    try:
        # headers = dict(chat_request.headers)
        # account_id = ChatConversationService.get_account_id(headers=headers)
        account_id = chat_request.state.account_id
        app_id = UsrAuthService.get_app_id(db=db, account_id=account_id)
        if app_id == "":
            return RetUtil.response_ok("account_id无效")
        params = {"prompt_params": {"example_a": "example_a"}, "kb_list": ["example"], "tool_list": ["example"]}
        param = str({"agent_id": agent_id, "agent_input": "", "agent_params": params, "system_prompts": ""})
        body = f"curl --location '$location.origin$/api/outside/agent/manage/call_agent_api' \
        --header 'App-id: {app_id}' \
        --header 'content-type: application/json' \
        --data '{param}'"

        return RetUtil.response_ok(body)
    except Exception as e:
        detail = f"服务器错误{str(e)}"
        logger.exception(detail)
        # 返回HTTP错误响应
        raise HTTPException(status_code=400, detail=detail)


@router.post("/call_agent_api", summary="生成智能体api")
async def call_agent_api(chat_request: Request, params: TestAgentInfo_v2, db: Session = Depends(get_db)):
    try:
        account_id = chat_request.state.account_id
        new_params = TestAgentInfo_v1
        new_params.account_id = account_id
        new_params.agent_params = params.agent_params
        new_params.input = params.agent_input
        new_params.agent_id = params.agent_id
        new_params.system_prompts = params.system_prompts
        new_params.prompt_id = params.prompt_id
        conversation_id = params.conversation_id

        agent_q = MongodbUtil.query_doc_by_id(CollectionConfig.AGENT_COLLECTION, doc_id=ObjectId(params.agent_id))
        if not agent_q:
            return RetUtil.response_error(message="该智能体不存在")

        # 首先判断这个智能体是否是该用户的智能体或者所属团队的智能体
        team_code = agent_q.get("team_code", "")
        role = True
        if team_code:
            teams = UsrAuthService.usr_team(db=db, auth=UsrEntity(account_id=account_id))
            teams = [team["team_code"] for team in teams]
            if team_code not in teams:
                role = False
        else:
            if agent_q["account_id"] != account_id:
                role = False
        if not role:
            return RetUtil.response_error(message="该智能体不属于当前用户!")

        # 确保智能体是发布状态
        if agent_q["status"] != 1:
            return RetUtil.response_error(message="该智能体未发布，请发布后使用")

        if conversation_id != "":
            conversation_info = (
                db.query(MemberChat_Model)
                .filter(MemberChat_Model.conversation_id == conversation_id, MemberChat_Model.status == 1)
                .first()
            )
            if not conversation_info:
                # 不存在conversation_id对应的对话，则创建一个新的对话
                create_time = ChatConversationService.local_time()
                update_time = create_time

                db_config = MemberChat_Model(
                    conversation_id=conversation_id,
                    account_id=account_id,
                    model_id="",
                    type=12,
                    kb_id="",
                    ag_id=params.agent_id,
                    create_time=create_time,
                    update_time=update_time,
                )
                db.add(db_config)
                db.commit()
                db.refresh(db_config)
            elif conversation_info.account_id != account_id:
                # 若该conversation_id被别的用户所使用
                return RetUtil.response_error(message="该conversation_id已被使用！")
        else:
            check_talk_list = ChatConversationService.check_talk_list(
                db=db, account_id=account_id, type=12, model_id="", kb_id="", ag_id=params.agent_id
            )
            conversation_id = check_talk_list[0]
        new_params.conversation_id = conversation_id
        return await call_agent(chat_request, new_params, db, 12)
    except Exception as e:
        logger.exception(f"智能体调用出错: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get_running_model_list", summary="获取指定类型的运行模型列表")  # 使用中
async def query_agent_list(
    model_type: str = Body(..., embed=True, examples=["LLM"], description="模型类型"),
) -> Response:
    try:
        logger.info(f"查询的模型类型：{model_type}")
        internal_model_list, external_model_list = await AgentService.get_running_model_list(model_type)
        result = []
        if internal_model_list["children"]:
            result.append(internal_model_list)
        if external_model_list["children"]:
            result.append(external_model_list)
        return RetUtil.response_ok(result)
    except Exception as e:
        logger.exception(f"获取指定类型的运行模型列表异常: {e}")
        return Response(content=f"获取指定类型的运行模型列表异常: {e}", media_type="text/plain")


@router.post("/query_team_agent_v1", summary="查询团队智能体列表v1")
async def query_team_agent_v1(
    params: QueryTeamAgentInfo, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    try:
        account_id = chat_request.state.account_id

        if not account_id:
            return RetUtil.return_error(message="用户id不存在")
        result = await AgentService.query_team_agent(
            params.agent_name,
            params.page,
            params.page_size,
            account_id,
            params.team_code,
            params.id,
            db=db,
            status=params.status,
        )
        return RetUtil.response_ok(result)
    except Exception as e:
        logger.exception(f"查询智能体列表异常: {e}")
        return Response(content=f"查询智能体列表异常: {e}", media_type="text/plain")


@router.post("/agent_update_status", summary="修改发布状态")  # 使用中
async def agent_update_status(
    chat_request: Request,
    agent_id: str = Body(..., embed=True, examples=["id"], description="智能体id"),
    status: int = Body(..., embed=True, examples=[1], description="描述"),
    db: Session = Depends(get_db),
) -> Response:
    try:
        account_id = chat_request.state.account_id
        result = await AgentService.update_agent_status(agent_id, status)
        return RetUtil.response_ok(result)

    except Exception as e:
        logger.exception(f"智能体基础信息修改异常: {e}")
        return Response(content=f"智能体修改异常: {e}", media_type="text/plain")


@router.post("/create_item_type", summary="创建子类别")
async def create_item_type(params: TypeItemDict, chat_request: Request, db: Session = Depends(get_db)) -> Response:
    try:
        account_id = chat_request.state.account_id
        if await AgentService.type_item_exist(params.code, params.type_code):
            return RetUtil.return_error(message="类别已存在")

        usr_i = query2dict_acc(UsrService.query_usr_by_id(db=db, account_id=account_id), Usr_Model)

        account_name = usr_i["account_name"]
        usr_name = usr_i["usr_name"]
        result, code = await AgentService.create_item_type(
            params.code, params.type_code, params.name, params.description, account_name, usr_name
        )

        return RetUtil.response_ok({"code": code})
    except Exception as e:
        logger.exception(f"创建子类别异常: {e}")
        return Response(content=f"创建子类别异常: {e}", media_type="text/plain")


@router.post("/update_item_type", summary="修改子类别信息")
async def update_item_type(
    params: TypeItemUpdateDict, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    try:
        account_id = chat_request.state.account_id

        usr_i = query2dict_acc(UsrService.query_usr_by_id(db=db, account_id=account_id), Usr_Model)

        account_name = usr_i["account_name"]
        usr_name = usr_i["usr_name"]

        result = MongodbUtil.query_docs_by_condition(
            CollectionConfig.SYS_STATIC_DICT_ITEMS,
            search_condition={"code": params.code, "type_code": params.type_code},
        )
        i = 0
        for _ in result:
            i = i + 1

        result2 = MongodbUtil.query_docs_by_condition(
            CollectionConfig.SYS_STATIC_DICT_ITEMS, search_condition={"_id": ObjectId(params.id)}
        )
        for item in result2:
            subcode = item["code"]

        # 这里做i的判断是因为要保证两种情况:params.code为之前_id对应的数据，即不需要更新code;params.code是需要修改的，但是和已有的数据重复
        if subcode == params.code:
            i = i - 1

        if i > 0:
            return RetUtil.return_error(message="类别已存在")

        result = await AgentService.updata_item_type(params, account_name, usr_name)
        return RetUtil.response_ok({"data": result})
    except Exception as e:
        logger.exception(f"修改类别信息: {e}")
        return Response(content=f"修改类别信息: {e}", media_type="text/plain")


@router.delete("/delete_item_type", summary="删除类别")
async def delete_item_type(
    params: TypeItemDelete,
) -> Response:
    try:
        id = params.id

        result = MongodbUtil.query_docs_by_condition(
            CollectionConfig.SYS_STATIC_DICT_ITEMS, search_condition={"_id": ObjectId(id)}
        )
        docs = list(result)
        if not docs:
            return RetUtil.return_error(message="没有找到匹配的类别")

        result = await AgentService.delete_item_type(id)
        return RetUtil.response_ok(result)
    except Exception as e:
        logger.exception(f"子类别删除异常: {e}")
        return Response(content=f"子类别删除异常: {e}", media_type="text/plain")


@router.post("/query_item_type", summary="查询子类别")  # 使用中
async def query_type(
    code: str = Body(..., examples=["agnet-type"], description="智能体模糊查询名称"),
    type_code: str = Body(..., examples=["agnet-type"], description="智能体模糊查询名称"),
    name: str = Body(..., examples=["健康智能体"], description="健康智能体"),
    status: str = Body(..., examples=["1"], description="状态码"),
    page: int = Body(..., examples=[1], description="页码"),
    page_size: int = Body(..., examples=[2], description="页面大小"),
) -> Response:
    try:
        # status必选，code、name可选
        result = await AgentService.query_item_type(name, code, status, page, page_size, type_code)
        result["result"] = sorted(result["result"], key=lambda x: x["sort_no"])
        return RetUtil.response_ok(result)
    except Exception as e:
        detail = f"查询子类别异常：{str(e)}"
        logger.exception(f"查询子类别异常: {e}")
        return RetUtil.response_error(message=detail)


# @router.post("/call_agent_v1_withtag", summary="调用智能体v1")  # 使用中(1.3.2版本已废弃)
async def call_agent_withtag(
    chat_request: Request,
    params: TestAgentInfo_v1,
    db: Session = Depends(get_db),
    conversation_type: int = 2,
    is_workflow: Optional[bool] = False,
) -> EventSourceResponse:
    """
    优化后的智能体调用函数

    主要改进：
    1. 消除了三个重复的 astream_response 函数
    2. 将复杂逻辑拆分为多个小函数
    3. 统一了错误处理
    4. 提高了代码可读性和可维护性
    """
    try:
        logger.info("开始调用智能体")
        account_id = chat_request.state.account_id
        # 创建优化器实例
        optimizer = AgentCallOptimizer(db, params, account_id, conversation_type, chat_request, is_workflow)
        # 初始化数据
        if not await optimizer.initialize_agent_data():
            return RetUtil.response_error(message="智能体配置验证失败")
        # 执行调用
        return await optimizer.execute_agent_call()

    except Exception as e:
        logger.exception(f"调用智能体异常: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/call_agent_withtag_api", summary="生成智能体api")  # 使用
async def call_agent_withtag_api(chat_request: Request, params: TestAgentInfo_v2, db: Session = Depends(get_db)):
    try:
        account_id = chat_request.state.account_id
        new_params = TestAgentInfo_v1
        new_params.account_id = account_id
        new_params.agent_params = params.agent_params
        new_params.input = params.agent_input
        new_params.agent_id = params.agent_id
        new_params.system_prompts = params.system_prompts
        new_params.prompt_id = params.prompt_id
        new_params.need_new_source = params.need_new_source
        conversation_id = params.conversation_id

        agent_q = MongodbUtil.query_doc_by_id(CollectionConfig.AGENT_COLLECTION, doc_id=ObjectId(params.agent_id))
        if not agent_q:
            return RetUtil.response_error(message="该智能体不存在")

        # 首先判断这个智能体是否是该用户的智能体或者所属团队的智能体
        team_code = agent_q.get("team_code", "")
        role = True
        if team_code:
            teams = UsrAuthService.usr_team(db=db, auth=UsrEntity(account_id=account_id))
            teams = [team["team_code"] for team in teams]
            if team_code not in teams:
                role = False
        else:
            if agent_q["account_id"] != account_id:
                role = False
        if not role:
            return RetUtil.response_error(message="该智能体不属于当前用户!")

        # 确保智能体是发布状态
        if agent_q["status"] != 1:
            logger.info(f"智能体ID为{params.agent_id}的智能体未发布，请发布后使用")
            return RetUtil.response_ok(data="该智能体未发布，请发布后使用")

        if conversation_id != "":
            conversation_info = (
                db.query(MemberChat_Model)
                .filter(MemberChat_Model.conversation_id == conversation_id, MemberChat_Model.status == 1)
                .first()
            )
            if not conversation_info:
                # 不存在conversation_id对应的对话，则创建一个新的对话
                create_time = ChatConversationService.local_time()
                update_time = create_time

                db_config = MemberChat_Model(
                    conversation_id=conversation_id,
                    account_id=account_id,
                    model_id="",
                    type=12,
                    kb_id="",
                    ag_id=params.agent_id,
                    create_time=create_time,
                    update_time=update_time,
                )
                db.add(db_config)
                db.commit()
                db.refresh(db_config)
            elif conversation_info.account_id != account_id:
                # 若该conversation_id被别的用户所使用
                return RetUtil.response_error(message="该conversation_id已被使用！")
            elif conversation_info.ag_id != params.agent_id:
                # 若该conversation_id被别的智能体
                return RetUtil.response_error(message="该conversation_id已被使用！")
        else:
            check_talk_list = ChatConversationService.check_talk_list(
                db=db, account_id=account_id, type=12, model_id="", kb_id="", ag_id=params.agent_id
            )
            conversation_id = check_talk_list[0]

        new_params.conversation_id = conversation_id
        return await call_agent_withtag(chat_request, new_params, db, 12)
    except Exception as e:
        logger.exception(f"智能体调用出错: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========新增外部接口智能体新建、查询、修改、删除========


@router.post("/create_agent_api", summary="创建智能体", response_model=ApiResponse)  # 使用
async def create_agent(request: CreateAgentRequest, chat_request: Request, db: Session = Depends(get_db)) -> Response:
    """
    创建智能体接口

    Args:
        request: 创建智能体请求参数
        chat_request: HTTP请求对象
        db: 数据库会话

    Returns:
        ApiResponse: 统一响应格式，包含创建的智能体信息

    Raises:
        HTTPException: 当参数验证失败、权限不足或创建失败时抛出
    """
    try:
        # 获取用户账号ID
        account_id = chat_request.state.account_id
        if not account_id:
            return RetUtil.response_error(message="用户身份验证失败")

        # 检查智能体名称是否已存在
        if await AgentService.agent_exist(request.agent_name, account_id):
            return RetUtil.response_error(message="智能体名称已存在")

        # 根据是否有团队代码决定创建个人还是团队智能体
        if isinstance(request.team_code, str) and request.team_code.strip():
            # 创建团队智能体 - 需要验证用户是否属于该团队
            has_team_permission = await AgentService.verify_user_team_permission(
                account_id=account_id, team_code=request.team_code, db=db
            )

            if not has_team_permission:
                logger.info(f"用户无权限在团队中创建智能体: account_id={account_id}, team_code={request.team_code}")
                return RetUtil.response_error(message="您没有权限在该团队中创建智能体")

            result, agent_id = await AgentService.create_team_agent(
                agent_name=request.agent_name,
                desripition=request.description or "",
                account_id=account_id,
                team_code=request.team_code,
                type_name=request.type_name or "",
                code=request.item_type or "",
                db=db,
            )
        else:
            # 创建个人智能体
            result, agent_id = await AgentService.create_agent(
                agent_name=request.agent_name,
                desripition=request.description or "",
                account_id=account_id,
                code=request.item_type or "",
                type_name=request.type_name or "",
            )

        if not agent_id:
            return RetUtil.response_error(message="智能体创建失败")

        # 构造响应数据
        response_data = {
            "id": agent_id,
            "agent_name": request.agent_name,
            "description": request.description or "",
            "team_code": request.team_code,
            "item_type": request.item_type if request.item_type else "0",
            "type_name": request.type_name if request.type_name else "其他",
            "status": 0,  # 新创建的智能体默认未发布
            "created_at": TimeUtil.timestamp_to_date(time.time()),
            "created_by": account_id,
        }
        return RetUtil.response_ok(response_data)

    except Exception as e:
        error_msg = f"创建智能体异常: {str(e)}"
        logger.exception(f"{error_msg}: {e}")
        return RetUtil.response_error(message=error_msg)


@router.get("/list_agent_api", summary="查询智能体列表", response_model=ApiResponse)  # 使用
async def get_agent_list(
    params: AgentListRequest,
    chat_request: Request = None,
    db: Session = Depends(get_db),
) -> Response:
    """
    查询智能体列表接口

    Args:
        params: 查询智能体列表请求参数
        chat_request: HTTP请求对象
        db: 数据库会话

    Returns:
        ApiResponse: 包含智能体列表和分页信息
    """
    try:
        # 获取用户账号ID
        account_id = chat_request.state.account_id
        if not account_id:
            return RetUtil.response_error(message="用户身份验证失败")

        # 根据是否有团队代码决定查询个人还是团队智能体
        if isinstance(params.team_code, list) and params.team_code:
            # 查询团队智能体 - 需要验证用户是否属于这些团队
            valid_team_codes = []
            for team_code in params.team_code:
                has_permission = await AgentService.verify_user_team_permission(
                    account_id=account_id, team_code=team_code, db=db
                )
                if has_permission:
                    valid_team_codes.append(team_code)
                else:
                    logger.info(f"用户尝试查询无权限的团队智能体: account_id={account_id}, team_code={team_code}")

            if not valid_team_codes:
                # 用户没有任何团队权限，返回空结果
                logger.info(f"用户没有任何团队权限，返回空结果: account_id={account_id}")
                return RetUtil.response_ok({"total": 0, "result": []})

            result = await AgentService.query_team_agent(
                agent_name=params.agent_keyword or "",
                page=params.page,
                page_size=params.page_size,
                account_id=account_id,
                team_code_list=valid_team_codes,
                code=params.item_type or "",
                id=params.id,
                db=db,
                status=params.status,
            )
        else:
            # 查询个人智能体
            result = await AgentService.query_agent(
                agent_name=params.agent_keyword or "",
                page=params.page,
                page_size=params.page_size,
                account_id=account_id,
                code=params.item_type or "",
                id=params.id,
                status=params.status,
            )

        if not result:
            return RetUtil.response_error(message="查询智能体列表失败")

        logger.info(f"查询智能体列表成功，共{len(result['result'])}条记录, account_id={account_id}")
        return RetUtil.response_ok(result)

    except Exception as e:
        error_msg = f"查询智能体列表异常: {str(e)}"
        logger.exception(f"{error_msg}: {e}")
        return RetUtil.response_error(message=error_msg)


@router.post("/update_agent_api", summary="更新智能体")  # 使用
async def update_agent(
    chat_request: Request,
    update_agent_request: UpdateAgentRequest,
    db: Session = Depends(get_db),
) -> Response:
    """
    更新智能体接口

    Args:
        chat_request: HTTP请求对象
        update_agent_request: 更新智能体请求参数
        db: 数据库会话
    Raises:
        HTTPException: 当参数验证失败、权限不足或更新失败时抛出
    """
    try:
        # 获取用户账号ID
        account_id = chat_request.state.account_id
        if not account_id:
            return RetUtil.response_error(message="用户身份验证失败")

        # 新增：agent_name非空校验
        if not update_agent_request.agent_name or update_agent_request.agent_name.strip() == "":
            return RetUtil.response_error(message="智能体名称不能为空")

        # 验证用户是否有权限操作该智能体
        has_permission, agent_info = await AgentService.verify_agent_permission(
            account_id=account_id, agent_id=update_agent_request.agent_id, db=db
        )

        if not has_permission:
            if agent_info is None:
                return RetUtil.response_error(message="智能体不存在")
            else:
                return RetUtil.response_error(message="您没有权限修改该智能体")

        # 获取原始类型
        origin_is_team = bool(agent_info.get("team_code"))
        # 获取目标类型
        target_is_team = bool(update_agent_request.team_code)
        # 禁止跨类型修改
        if origin_is_team != target_is_team:
            return RetUtil.response_error(message="不允许个人与团队智能体互相转换")

        # 用户是否存在
        user_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, account_id)
        if user_attribute == None:
            return RetUtil.response_error(message="用户不存在")

        # 如果修改了team_code，需要验证新的团队权限
        if update_agent_request.team_code and update_agent_request.team_code != agent_info.get("team_code"):
            has_new_team_permission = await AgentService.verify_user_team_permission(
                account_id=account_id, team_code=update_agent_request.team_code, db=db
            )

            if not has_new_team_permission:
                logger.info(
                    f"用户无权限将智能体移动到新团队: account_id={account_id}, agent_id={update_agent_request.agent_id}, new_team_code={update_agent_request.team_code}"
                )
                return RetUtil.response_error(message="您没有权限将智能体移动到该团队")

        if update_agent_request.team_code == None:
            result = await AgentService.update_agent(
                agent_id=update_agent_request.agent_id,
                agent_name=update_agent_request.agent_name,
                description=update_agent_request.description or "",
                code=update_agent_request.item_type if update_agent_request.item_type else "0",
            )
            if result == False:
                return RetUtil.response_error("修改智能体信息异常")
            return JSONResponse({"code": 200, "status": True, "message": "success"})
        else:
            result = await AgentService.update_team_agent(
                agent_id=update_agent_request.agent_id,
                agent_name=update_agent_request.agent_name,
                description=update_agent_request.description or "",
                team_code=update_agent_request.team_code,
                db=db,
                code=update_agent_request.item_type if update_agent_request.item_type else "0",
            )
            if result == False:
                return RetUtil.response_error("修改智能体信息异常")
            return JSONResponse({"code": 200, "status": True, "message": "success"})

    except Exception as e:
        error_msg = f"更新智能体异常: {str(e)}"
        logger.exception(f"{error_msg}: {e}")
        return RetUtil.response_error(message=error_msg)


@router.delete("/delete_agent_api", summary="删除智能体")  # 使用
async def delete_agent(
    agent_id: str = Body(..., embed=True, examples=["test"], description="智能体id"),
    chat_request: Request = None,
    db: Session = Depends(get_db),
) -> Response:
    """
    删除智能体接口

    Args:
        agent_id: 智能体ID
        chat_request: HTTP请求对象
        db: 数据库会话
    """
    try:
        # 获取用户账号ID
        account_id = chat_request.state.account_id if chat_request else None
        if not account_id:
            return RetUtil.response_error(message="用户身份验证失败")

        # 验证用户是否有权限操作该智能体
        has_permission, agent_info = await AgentService.verify_agent_permission(
            account_id=account_id, agent_id=agent_id, db=db
        )

        if not has_permission:
            if agent_info is None:
                return RetUtil.response_error(message="智能体不存在")
            else:
                logger.info(f"用户尝试删除无权限的智能体: account_id={account_id}, agent_id={agent_id}")
                return RetUtil.response_error(message="您没有权限删除该智能体")

        result = await AgentService.delete_agent(agent_id)
        if result == False:
            return RetUtil.return_error(message="删除智能体失败")

        logger.info(f"智能体删除成功: agent_id={agent_id}, account_id={account_id}")
        return JSONResponse({"code": 200, "status": True, "message": "success"})

    except Exception as e:
        error_msg = f"删除智能体异常: {str(e)}"
        logger.exception(f"{error_msg}: {e}")
        return RetUtil.response_error(message=error_msg)


@router.post("/workflow_call_agent_withtag", summary="调用智能体v1")  # 使用
async def workflow_call_agent_withtag(
    chat_request: Request,
    params: TestAgentInfo_v1,
    db: Session = Depends(get_db),
    conversation_type: int = 2,
    is_workflow: Optional[int] = Query(0, description="团队代码", examples=[10001]),
):
    try:
        tag_buf = ""
        content_type = "text"
        start_tag = "<think>"
        end_tag = "</think>"
        start_time = time.time()
        logger.info(msg="调用智能体")
        account_id = chat_request.state.account_id
        params_dic = params.agent_params
        try:
            params_dic_id = ChatConversationService.task_query_id(params_dic, account_id)
        except:
            yield "知识库检索出错，请检查知识库配置"
        kb_list = []

        result = MongodbUtil.query_doc_by_id(
            CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(params.agent_id)
        )

        result.update(params_dic_id)
        model_params = result["model_params"]
        # 如果模型配置参数中不存在presence_penalty与frequency_penalty惩罚参数，设置默认值为1
        if model_params.get("presence_penalty", None) is None:
            model_params["presence_penalty"] = 0
        if model_params.get("frequency_penalty", None) is None:
            model_params["frequency_penalty"] = 0
        # 如果入参中没有prompt_id
        if params.prompt_id == "":
            # 从编排中拿prompt_id
            prompt_id = result.get("prompt_id", "")
            # 如果编排中也没有
            if prompt_id == "":
                prompt = result["prompt"]
            # 如果编排中有
            else:
                prompt_info = query2dict_status(
                    db.query(Prompt_Model)
                    .filter(Prompt_Model.prompt_id == prompt_id, Prompt_Model.status != 0)
                    .first(),
                    Prompt_Model,
                )
                if prompt_info is None:
                    prompt = ""
                else:
                    prompt = prompt_info["prompt_content"]
        else:
            prompt_info = query2dict_status(
                db.query(Prompt_Model)
                .filter(Prompt_Model.prompt_id == params.prompt_id, Prompt_Model.status != 0)
                .first(),
                Prompt_Model,
            )
            if prompt_info is None:
                prompt = ""
            else:
                prompt = prompt_info["prompt_content"]
        prompt = ChatConversationService.prompt_params(params_dic, prompt)

        # 获取历史system_prompt
        talk_info = ChatConversationService.check_talk_info_history(db=db, conversation_id=params.conversation_id)
        if len(talk_info) > model_params["history"]:  # 记录多于指定历史轮数量，侧进行记录截断
            chatbot = talk_info[-model_params["history"] :]
        else:
            chatbot = talk_info
        history_system_prompts = ""
        if params.system_prompts == "":
            for idx, conversation in enumerate(chatbot):
                if conversation.get("prompt", None):
                    history_system_prompts = conversation["prompt"]
                    break
        recall_setting = result["recall_setting"]
        # if "知识库ID不存在，请给出正确的知识库ID" in result['kb_list']:
        #     return RetUtil.response_error(message="知识库ID不存在，请给出正确的知识库ID")
        # if "工具ID不存在，请给出正确的工具ID" in result['tool_list']:
        #     return RetUtil.response_error(message="工具ID不存在，请给出正确的工具ID")
        # 查询知识库列表
        for kb in result["kb_list"]:
            kb_result = MongodbUtil.query_doc_by_id(CollectionConfig.KB_COLLECTION, doc_id=ObjectId(kb))
            kb_list.append(
                {
                    "id": kb,
                    "kb_name": kb_result["kb_name"],
                    "embedding_model": kb_result["embedding_model"],
                    "rerank_model": kb_result["rerank_model"],
                    "top_k": kb_result["top_k"],
                    "score": kb_result["score"],
                    "enhance_rounds": kb_result.get("enhance_rounds", 0),
                }
            )
        # 查询工具列表
        tool_list = await AgentService.tool_list(result)
        TOOLS = []
        for tool_info in tool_list:
            tool_parm = tool_info["tool_parm"]
            tool_url = tool_info["tool_url"]
            tool_method = tool_info["method"]
            tool_function = tool_parm["function"]
            tool_function["parameters"] = tool_parm["function"].get("parameters", {})

            TOOLS.append({"type": "function", "function": tool_function})
        if len(TOOLS):
            # redis=aioredis.Redis
            tool_result, tool_use = await AgentService.tool_agent(chat_request, params, model_params, TOOLS, tool_list)
        else:
            tool_use = False

        talk_id = ""
        new_source = []
        if tool_use == True:
            # 保存问答数据
            talk_id = ChatConversationService.save_talk_data_agent(
                db=db,
                conversation_id=params.conversation_id,
                account_id=account_id,
                token="",
                question=params.input,
                kb_id="",
                model_id="",
                ag_id=params.agent_id,
                type=conversation_type,
                system_prompt=params.system_prompts,
            )
            ChatConversationService.save_talk_data_file_stop(
                db=db,
                conversation_id=params.conversation_id,
                account_id=account_id,
                type=conversation_type,
                talk_id=talk_id,
                talk_num=0,
            )

            # 调用大模型
            async def astream_response():
                try:
                    alltime = 0
                    in_thinking = 0
                    tag_buf = ""
                    content_type = "text"
                    start_tag = "<think>"
                    end_tag = "</think>"
                    content = ""
                    think = ""
                    stream_count = 0
                    if params.system_prompts != "":
                        final_prompt = f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息:{tool_result}{params.system_prompts}回答用户的问题。
                        注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}以及{params.system_prompts}就是事实。
                        """
                    else:
                        if history_system_prompts != "":
                            final_prompt = f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息:{tool_result}{history_system_prompts}回答用户的问题。
                                                    注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}以及{history_system_prompts}就是事实。
                                                    """
                        else:
                            final_prompt = f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息{tool_result}回答用户的问题。
                        注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}就是事实。
    """
                    # 业务逻辑处理
                    openAILLMService = OpenAILLMService(id=model_params["id"])
                    response_content = ""
                    first_output = True
                    content = ""
                    result = MongodbUtil.query_doc_by_id(
                        collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(model_params["id"])
                    )

                    is_think = result["is_think"]
                    async for chunk in openAILLMService.workflow_stream_chat_v1_with_penalty(
                        db=db,
                        request=ChatCompletionRequestParams_v1(
                            model_uid=model_params["model_uid"],
                            temperature=model_params["temperature"],
                            history=0,
                            max_token_length=model_params["max_token_length"],
                            conversation_id=params.conversation_id,
                            system_prompts=final_prompt,
                            retrival_params={
                                "kb_name": "",
                                "user_query": params.input,
                                "rerank_model": "",
                                "recall_num": 0,
                                "rerank_num": 0,
                            },
                            presence_penalty=model_params["presence_penalty"],
                            frequency_penalty=model_params["frequency_penalty"],
                        ),
                        chunk_content="",
                        type=conversation_type,
                    ):
                        if (
                            chunk.choices[0].delta.content != ""
                            and chunk.choices[0].delta.content is not None
                            and len(chunk.choices[0].delta.content) > 0
                        ):
                            token = chunk.choices[0].delta.content
                            tag_buf += token
                            if is_think:
                                if in_thinking == 0 and "<" in chunk.choices[0].delta.content:
                                    in_thinking = 1
                                elif in_thinking != 4:
                                    in_thinking = 2
                                    content_type = "thinking"
                                if start_tag in tag_buf:
                                    in_thinking = 2
                                    content_type = "thinking"
                                    if len(tag_buf.split(start_tag)) > 1:
                                        token = tag_buf.split(start_tag)[-1]
                                        tag_buf = tag_buf.replace(start_tag, "")

                                    else:
                                        tag_buf = tag_buf.replace(start_tag, "")
                                        continue
                                if in_thinking == 2 and "<" in tag_buf:
                                    in_thinking = 3
                                if end_tag in tag_buf:
                                    in_thinking = 4
                                    content_type = "text"
                                    if len(tag_buf.split(end_tag)) > 1:
                                        token = tag_buf.split(end_tag)[-1]
                                        tag_buf = tag_buf.replace(end_tag, "")
                                    else:
                                        tag_buf = tag_buf.replace(end_tag, "")
                                        continue
                                    tag_buf.replace(end_tag, "")
                                if in_thinking == 1 or in_thinking == 3:
                                    continue
                            if content_type == "thinking" and token is not None:
                                think += token
                            elif content_type == "text" and token is not None:
                                content += token
                            if in_thinking == 4:
                                stream_count += 1  # 记录什么时候思考完成产生第一个正文需要yeild的流,计算思考时间

                            status = ChatConversationService.check_talk_stop_status(db=db, talk_id=talk_id, talk_num=0)
                            # status == 3 代表中断

                            if status == 3:
                                data = {
                                    "prompt": params.system_prompts,
                                    "user": params.input,
                                    "assistant": {"content": content, "think": think, "think_time": alltime},
                                    "type": conversation_type,
                                    "new_source": new_source,
                                }
                                data = json.dumps(data)
                                await ChatConversationService.update_talk_data_agent(
                                    db=db, talk_id=talk_id, token_data=data
                                )
                                break
                            else:
                                if first_output:
                                    if stream_count == 1:
                                        think_time = round(time.time() - start_time, 1)
                                    else:
                                        think_time = 0
                                    result_data = {
                                        "token": token,
                                        "talk_id": talk_id,
                                        "new_source": new_source,
                                        "type": content_type,
                                        "think_time": think_time,
                                    }
                                    first_output = False
                                else:
                                    if stream_count == 1:
                                        think_time = round(time.time() - start_time, 1)
                                    else:
                                        think_time = 0
                                    result_data = {
                                        "token": token,
                                        "talk_id": talk_id,
                                        "type": content_type,
                                        "think_time": think_time,
                                    }

                                yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                                if think_time != 0:
                                    alltime = think_time
                                # if is_workflow != 1:
                                #     data = {"prompt":params.system_prompts,"user": params.input, "assistant":  {"content": content,"think": think, "think_time": alltime}, "type": conversation_type,"new_source":new_source}
                                #     data = json.dumps(data)
                                #     await ChatConversationService.update_talk_data_agent(db=db, talk_id=talk_id,
                                #                                                    token_data=data)

                    data = {
                        "prompt": params.system_prompts,
                        "user": params.input,
                        "assistant": {"content": content, "think": think, "think_time": alltime},
                        "type": conversation_type,
                        "new_source": new_source,
                    }
                    data = json.dumps(data)
                    await ChatConversationService.update_talk_data_agent(db=db, talk_id=talk_id, token_data=data)
                except Exception as e:
                    logger.exception(f"调用智能体异常: {e}")
                    if talk_id != "":
                        ChatConversationService.delete_talk(db=db, talk_id=talk_id)
                    result = "系统繁忙,请稍后再试"
                    result_data = {"token": result, "talk_id": talk_id, "new_source": new_source}
                    yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                    raise

        else:
            if len(kb_list) > 0:
                logger.info(f"知识库:{kb_list}")
                try:
                    docs, new_source = await knowledge_retrieval(params, recall_setting, kb_list)
                except:
                    yield "知识库检索出错，请检查知识库配置"
                if params.system_prompts != "":
                    prompt_answer = f"""
                    {prompt}
                    尽可能以有用且准确的方式回复人类。
                    知识库知识:{docs}
                    个人知识：{params.system_prompts}
                    根据用户输入和检索到的知识库内容、个人知识和你自己的知识进行知识整合，对用户问题进行回答。
                                    """
                else:
                    if history_system_prompts != "":
                        prompt_answer = f"""
                                            {prompt}
                                            尽可能以有用且准确的方式回复人类。
                                            知识库知识:{docs}
                                            个人知识：{history_system_prompts}
                                            根据用户输入和检索到的知识库内容、个人知识和你自己的知识进行知识整合，对用户问题进行回答。
                                                            """
                    else:
                        prompt_answer = f"""
                        {prompt}
                        尽可能以有用且准确的方式回复人类。
                        知识库知识:{docs}
                        根据用户输入和检索到的知识库内容和你自己的知识进行知识整合，对用户问题进行回答。
                    """
                # 保存问答数据
                talk_id = ChatConversationService.save_talk_data_agent(
                    db=db,
                    conversation_id=params.conversation_id,
                    account_id=account_id,
                    token="",
                    question=params.input,
                    kb_id="",
                    model_id="",
                    ag_id=params.agent_id,
                    type=conversation_type,
                    system_prompt=params.system_prompts,
                )
                ChatConversationService.save_talk_data_file_stop(
                    db=db,
                    conversation_id=params.conversation_id,
                    account_id=account_id,
                    type=conversation_type,
                    talk_id=talk_id,
                    talk_num=0,
                )

                async def astream_response():
                    try:
                        alltime = 0
                        in_thinking = 0
                        tag_buf = ""
                        content_type = "text"
                        start_tag = "<think>"
                        end_tag = "</think>"
                        content = ""
                        think = ""
                        stream_count = 0
                        openAILLMService = OpenAILLMService(id=model_params["id"])
                        response_content = ""
                        content = ""
                        first_output = True

                        result = MongodbUtil.query_doc_by_id(
                            collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(model_params["id"])
                        )

                        is_think = result["is_think"]

                        async for chunk in openAILLMService.workflow_stream_chat_v1_with_penalty(
                            db=db,
                            request=ChatCompletionRequestParams_v1(
                                model_uid=model_params["model_uid"],
                                temperature=model_params["temperature"],
                                history=model_params["history"],
                                max_token_length=model_params["max_token_length"],
                                system_prompts=prompt_answer,
                                conversation_id=params.conversation_id,
                                retrival_params={
                                    "kb_name": "",
                                    "user_query": params.input,
                                    "rerank_model": "",
                                    "recall_num": 0,
                                    "rerank_num": 0,
                                },
                                presence_penalty=model_params["presence_penalty"],
                                frequency_penalty=model_params["frequency_penalty"],
                            ),
                            chunk_content="",
                            type=conversation_type,
                        ):
                            if (
                                chunk.choices[0].delta.content != ""
                                and chunk.choices[0].delta.content is not None
                                and len(chunk.choices[0].delta.content) > 0
                            ):
                                token = chunk.choices[0].delta.content
                                tag_buf += token
                                if is_think:
                                    if in_thinking == 0 and "<" in chunk.choices[0].delta.content:
                                        in_thinking = 1
                                    elif in_thinking != 4:
                                        in_thinking = 2
                                        content_type = "thinking"
                                    if start_tag in tag_buf:
                                        in_thinking = 2
                                        content_type = "thinking"
                                        if len(tag_buf.split(start_tag)) > 1:
                                            token = tag_buf.split(start_tag)[-1]
                                            tag_buf = tag_buf.replace(start_tag, "")
                                            if token == "" or token == None:
                                                continue
                                        else:
                                            tag_buf = tag_buf.replace(start_tag, "")
                                            continue
                                    if in_thinking == 2 and "<" in tag_buf:
                                        in_thinking = 3
                                    if end_tag in tag_buf:
                                        in_thinking = 4
                                        content_type = "text"
                                        if len(tag_buf.split(end_tag)) > 1:
                                            token = tag_buf.split(end_tag)[-1]
                                            tag_buf = tag_buf.replace(end_tag, "")
                                            if token == "" or token == None:
                                                continue
                                        else:
                                            tag_buf = tag_buf.replace(end_tag, "")
                                            continue
                                        tag_buf.replace(end_tag, "")
                                    if in_thinking == 1 or in_thinking == 3:
                                        continue
                                if content_type == "thinking" and token is not None:
                                    think += token
                                elif content_type == "text" and token is not None:
                                    content += token
                                if in_thinking == 4:
                                    stream_count += 1  # 记录什么时候思考完成产生第一个正文需要yeild的流,计算思考时间

                                status = ChatConversationService.check_talk_stop_status(
                                    db=db, talk_id=talk_id, talk_num=0
                                )
                                # status == 3 代表中断

                                if status == 3:
                                    data = {
                                        "prompt": params.system_prompts,
                                        "user": params.input,
                                        "assistant": {"content": content, "think": think, "think_time": alltime},
                                        "type": conversation_type,
                                        "new_source": new_source,
                                    }
                                    data = json.dumps(data)
                                    await ChatConversationService.update_talk_data_agent(
                                        db=db, talk_id=talk_id, token_data=data
                                    )
                                    break
                                else:
                                    if first_output:
                                        if stream_count == 1:
                                            think_time = round(time.time() - start_time, 1)
                                        else:
                                            think_time = 0
                                        result_data = {
                                            "token": token,
                                            "talk_id": talk_id,
                                            "new_source": new_source,
                                            "type": content_type,
                                            "think_time": think_time,
                                        }
                                        first_output = False
                                    else:
                                        if stream_count == 1:
                                            think_time = round(time.time() - start_time, 1)
                                        else:
                                            think_time = 0
                                        result_data = {
                                            "token": token,
                                            "talk_id": talk_id,
                                            "type": content_type,
                                            "think_time": think_time,
                                        }

                                    yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                                    if think_time != 0:
                                        alltime = think_time
                                    # if is_workflow != 1:
                                    #     data = {"prompt":params.system_prompts,"user": params.input, "assistant":  {"content": content,"think": think, "think_time": alltime}, "type": conversation_type,"new_source":new_source}
                                    #     data = json.dumps(data)
                                    #     await ChatConversationService.update_talk_data_agent(db=db, talk_id=talk_id,
                                    #                                                    token_data=data)
                        data = {
                            "prompt": params.system_prompts,
                            "user": params.input,
                            "assistant": {"content": content, "think": think, "think_time": alltime},
                            "type": conversation_type,
                            "new_source": new_source,
                        }
                        data = json.dumps(data)
                        await ChatConversationService.update_talk_data_agent(db=db, talk_id=talk_id, token_data=data)
                    except Exception as e:
                        logger.exception(f"调用智能体异常: {e}")
                        if talk_id != "":
                            ChatConversationService.delete_talk(db=db, talk_id=talk_id)
                        result = "系统繁忙,请稍后再试"
                        result_data = {"token": result, "talk_id": talk_id, "new_source": new_source}
                        yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                        raise

            else:
                if params.system_prompts != "":
                    prompt_answer = f"""
                    {prompt}
                    尽可能以有用且准确的方式回复人类。
                    个人知识：{params.system_prompts}
                    根据用户输入和个人知识和你自己的知识进行知识整合，对用户问题进行回答。
                                    """
                else:
                    if history_system_prompts != "":
                        prompt_answer = f"""
                                            {prompt}
                                            尽可能以有用且准确的方式回复人类。
                                            个人知识：{history_system_prompts}
                                            根据用户输入和个人知识和你自己的知识进行知识整合，对用户问题进行回答。
                                                            """
                    else:
                        prompt_answer = prompt
                # 保存问答数据
                talk_id = ChatConversationService.save_talk_data_agent(
                    db=db,
                    conversation_id=params.conversation_id,
                    account_id=account_id,
                    token="",
                    question=params.input,
                    kb_id="",
                    model_id="",
                    ag_id=params.agent_id,
                    type=conversation_type,
                    system_prompt=params.system_prompts,
                )

                ChatConversationService.save_talk_data_file_stop(
                    db=db,
                    conversation_id=params.conversation_id,
                    account_id=account_id,
                    type=conversation_type,
                    talk_id=talk_id,
                    talk_num=0,
                )

                async def astream_response():
                    try:
                        in_thinking = 0
                        alltime = "0"
                        tag_buf = ""
                        content_type = "text"
                        start_tag = "<think>"
                        end_tag = "</think>"
                        content = ""
                        think = ""
                        stream_count = 0
                        # 业务逻辑处理
                        openAILLMService = OpenAILLMService(id=model_params["id"])
                        response_content = ""
                        content = ""
                        first_output = True

                        result = MongodbUtil.query_doc_by_id(
                            collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(model_params["id"])
                        )

                        is_think = result["is_think"]

                        async for chunk in openAILLMService.workflow_stream_chat_v1_with_penalty(
                            db=db,
                            request=ChatCompletionRequestParams_v1(
                                model_uid=model_params["model_uid"],
                                system_prompts=prompt_answer,
                                conversation_id=params.conversation_id,
                                temperature=model_params["temperature"],
                                history=model_params["history"],
                                max_token_length=model_params["max_token_length"],
                                retrival_params={
                                    "kb_name": "",
                                    "user_query": params.input,
                                    "rerank_model": "",
                                    "recall_num": 0,
                                    "rerank_num": 0,
                                },
                                presence_penalty=model_params["presence_penalty"],
                                frequency_penalty=model_params["frequency_penalty"],
                            ),
                            chunk_content="",
                            type=conversation_type,
                        ):
                            # yield '{"status": true, "message": "success", "data": {"token": "今天", "talk_id": "TALK_1947553527861743616", "new_source": [], "type": "text", "think_time": 0}}'
                            if (
                                chunk.choices[0].delta.content != ""
                                and chunk.choices[0].delta.content is not None
                                and len(chunk.choices[0].delta.content) > 0
                            ):
                                token = chunk.choices[0].delta.content
                                tag_buf += token
                                if is_think:
                                    if in_thinking == 0 and "<" in chunk.choices[0].delta.content:
                                        in_thinking = 1
                                    elif in_thinking != 4:
                                        in_thinking = 2
                                        content_type = "thinking"
                                    if start_tag in tag_buf:
                                        in_thinking = 2
                                        content_type = "thinking"
                                        if len(tag_buf.split(start_tag)) > 1:
                                            token = tag_buf.split(start_tag)[-1]
                                            tag_buf = tag_buf.replace(start_tag, "")

                                        else:
                                            tag_buf = tag_buf.replace(start_tag, "")
                                            continue
                                    if in_thinking == 2 and "<" in tag_buf:
                                        in_thinking = 3
                                    if end_tag in tag_buf:
                                        in_thinking = 4
                                        content_type = "text"
                                        if len(tag_buf.split(end_tag)) > 1:
                                            token = tag_buf.split(end_tag)[-1]
                                            tag_buf = tag_buf.replace(end_tag, "")
                                        else:
                                            tag_buf = tag_buf.replace(end_tag, "")
                                            continue
                                        tag_buf.replace(end_tag, "")
                                    if in_thinking == 1 or in_thinking == 3:
                                        continue
                                if content_type == "thinking" and token is not None:
                                    think += token
                                elif content_type == "text" and token is not None:
                                    content += token
                                if in_thinking == 4:
                                    stream_count += 1  # 记录什么时候思考完成产生第一个正文需要yeild的流,计算思考时间

                                status = ChatConversationService.check_talk_stop_status(
                                    db=db, talk_id=talk_id, talk_num=0
                                )
                                # status == 3 代表中断
                                if token is not None:
                                    response_content += token
                                if status == 3:
                                    data = {
                                        "prompt": params.system_prompts,
                                        "user": params.input,
                                        "assistant": {"content": content, "think": think, "think_time": alltime},
                                        "type": conversation_type,
                                        "new_source": new_source,
                                    }
                                    data = json.dumps(data)
                                    await ChatConversationService.update_talk_data_agent(
                                        db=db, talk_id=talk_id, token_data=data
                                    )
                                    break
                                else:
                                    if first_output:
                                        if stream_count == 1:
                                            think_time = round(time.time() - start_time, 1)

                                        else:
                                            think_time = 0

                                        result_data = {
                                            "token": token,
                                            "talk_id": talk_id,
                                            "new_source": new_source,
                                            "type": content_type,
                                            "think_time": think_time,
                                        }
                                        first_output = False
                                    else:
                                        if stream_count == 1:
                                            think_time = round(time.time() - start_time, 1)

                                        else:
                                            think_time = 0
                                        result_data = {
                                            "token": token,
                                            "talk_id": talk_id,
                                            "type": content_type,
                                            "think_time": think_time,
                                        }
                                    if think_time != 0:
                                        alltime = think_time
                                    yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                                    # if is_workflow !=1:
                                    #     data = {"prompt":params.system_prompts,"user": params.input, "assistant":  {"content": content,"think": think, "think_time": alltime}, "type": conversation_type,"new_source":new_source}
                                    #     data = json.dumps(data)
                                    #     await ChatConversationService.update_talk_data_agent(db=db, talk_id=talk_id,
                                    #                                                    token_data=data)
                        data = {
                            "prompt": params.system_prompts,
                            "user": params.input,
                            "assistant": {"content": content, "think": think, "think_time": alltime},
                            "type": conversation_type,
                            "new_source": new_source,
                        }
                        data = json.dumps(data)
                        await ChatConversationService.update_talk_data_agent(db=db, talk_id=talk_id, token_data=data)
                    except Exception as e:
                        logger.exception(f"调用智能体异常: {e}")
                        if talk_id != "":
                            ChatConversationService.delete_talk(db=db, talk_id=talk_id)
                        result = "系统繁忙,请稍后再试"
                        result_data = {"token": result, "talk_id": talk_id, "new_source": new_source}
                        yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                        raise

        if is_workflow == 1:
            async for token_json in astream_response():
                yield token_json
            # '{"status": true, "message": "success", "data": {"token": "我和", "talk_id": "TALK_1947548903452839936", "type": "text", "think_time": 0}}'
            # for i in range(50):
            #     yield '{"status": true, "message": "success", "data": {"token": "我和", "talk_id": "TALK_1947548903452839936", "type": "text", "think_time": 0}}'

    except Exception as e:
        logger.exception(f"调用智能体异常: {e}")


@router.post("/call_agent_v1", summary="调用智能体v1")
async def call_agent(
    chat_request: Request, params: TestAgentInfo_v1, db: Session = Depends(get_db), conversation_type: int = 2
):
    try:
        account_id = chat_request.state.account_id
        params_dic = params.agent_params
        params_dic_id = ChatConversationService.task_query_id(params_dic, account_id)
        kb_list = []

        result = MongodbUtil.query_doc_by_id(
            CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(params.agent_id)
        )

        result.update(params_dic_id)
        model_params = result["model_params"]
        # 如果模型配置参数中不存在presence_penalty与frequency_penalty惩罚参数，设置默认值为1
        if model_params.get("presence_penalty", None) is None:
            model_params["presence_penalty"] = 0
        if model_params.get("frequency_penalty", None) is None:
            model_params["frequency_penalty"] = 0
        # 如果入参中没有prompt_id
        if params.prompt_id == "":
            # 从编排中拿prompt_id
            prompt_id = result.get("prompt_id", "")
            # 如果编排中也没有
            if prompt_id == "":
                prompt = result["prompt"]
            # 如果编排中有
            else:
                prompt_info = query2dict_status(
                    db.query(Prompt_Model)
                    .filter(Prompt_Model.prompt_id == prompt_id, Prompt_Model.status != 0)
                    .first(),
                    Prompt_Model,
                )
                if prompt_info is None:
                    prompt = ""
                else:
                    prompt = prompt_info["prompt_content"]
        else:
            prompt_info = query2dict_status(
                db.query(Prompt_Model)
                .filter(Prompt_Model.prompt_id == params.prompt_id, Prompt_Model.status != 0)
                .first(),
                Prompt_Model,
            )
            if prompt_info is None:
                prompt = ""
            else:
                prompt = prompt_info["prompt_content"]
        prompt = ChatConversationService.prompt_params(params_dic, prompt)

        # 获取历史system_prompt
        talk_info = ChatConversationService.check_talk_info_history(db=db, conversation_id=params.conversation_id)
        if len(talk_info) > model_params["history"]:  # 记录多于指定历史轮数量，侧进行记录截断
            chatbot = talk_info[-model_params["history"] :]
        else:
            chatbot = talk_info
        history_system_prompts = ""
        if params.system_prompts == "":
            for idx, conversation in enumerate(chatbot):
                if conversation.get("prompt", None):
                    history_system_prompts = conversation["prompt"]
                    break

        recall_setting = result["recall_setting"]
        if "知识库ID不存在，请给出正确的知识库ID" in result["kb_list"]:
            return RetUtil.response_error(message="知识库ID不存在，请给出正确的知识库ID")
        if "工具ID不存在，请给出正确的工具ID" in result["tool_list"]:
            return RetUtil.response_error(message="工具ID不存在，请给出正确的工具ID")
        # 查询知识库列表
        for kb in result["kb_list"]:
            kb_result = MongodbUtil.query_doc_by_id(CollectionConfig.KB_COLLECTION, doc_id=ObjectId(kb))
            kb_list.append(
                {
                    "id": kb,
                    "kb_name": kb_result["kb_name"],
                    "embedding_model": kb_result["embedding_model"],
                    "rerank_model": kb_result["rerank_model"],
                    "top_k": kb_result["top_k"],
                    "score": kb_result["score"],
                }
            )
        # 查询工具列表
        tool_list = await AgentService.tool_list(result)
        TOOLS = []
        for tool_info in tool_list:
            tool_parm = tool_info["tool_parm"]
            tool_url = tool_info["tool_url"]
            tool_method = tool_info["method"]
            tool_function = tool_parm["function"]
            tool_function["parameters"] = tool_parm["function"].get("parameters", {})

            TOOLS.append({"type": "function", "function": tool_function})
        if len(TOOLS):
            # redis=aioredis.Redis
            tool_result, tool_use = await AgentService.tool_agent(chat_request, params, model_params, TOOLS, tool_list)
        else:
            tool_use = False

        talk_id = ""
        new_source = []
        if tool_use == True:
            # 保存问答数据
            talk_id = ChatConversationService.save_talk_data_agent(
                db=db,
                conversation_id=params.conversation_id,
                account_id=account_id,
                token="",
                question=params.input,
                kb_id="",
                model_id="",
                ag_id=params.agent_id,
                type=conversation_type,
                system_prompt=params.system_prompts,
            )
            ChatConversationService.save_talk_data_file_stop(
                db=db,
                conversation_id=params.conversation_id,
                account_id=account_id,
                type=conversation_type,
                talk_id=talk_id,
                talk_num=0,
            )

            # 调用大模型
            async def astream_response():
                try:
                    if params.system_prompts != "":
                        final_prompt = f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息:{tool_result}{params.system_prompts}回答用户的问题。
                        注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}以及{params.system_prompts}就是事实。
                        """
                    else:
                        if history_system_prompts != "":
                            final_prompt = f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息:{tool_result}{history_system_prompts}回答用户的问题。
                                                    注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}以及{history_system_prompts}就是事实。
                                                    """
                        else:
                            final_prompt = f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息{tool_result}回答用户的问题。
                        注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}就是事实。
    """
                    # 业务逻辑处理
                    openAILLMService = OpenAILLMService(id=model_params["id"])
                    response_content = ""
                    first_output = True
                    async for chunk in await openAILLMService.stream_chat_v1_with_penalty(
                        db=db,
                        request=ChatCompletionRequestParams_v1(
                            model_uid=model_params["model_uid"],
                            temperature=model_params["temperature"],
                            history=0,
                            max_token_length=model_params["max_token_length"],
                            conversation_id=params.conversation_id,
                            system_prompts=final_prompt,
                            retrival_params={
                                "kb_name": "",
                                "user_query": params.input,
                                "rerank_model": "",
                                "recall_num": 0,
                                "rerank_num": 0,
                            },
                            presence_penalty=model_params["presence_penalty"],
                            frequency_penalty=model_params["frequency_penalty"],
                        ),
                        chunk_content="",
                        type=conversation_type,
                    ):
                        if chunk.choices[0].delta.content != "":
                            token = chunk.choices[0].delta.content
                            status = ChatConversationService.check_talk_stop_status(db=db, talk_id=talk_id, talk_num=0)
                            # status == 3 代表中断
                            if token is not None:
                                response_content += token
                            if status == 3:
                                break
                            else:
                                if first_output:
                                    result_data = {"token": token, "talk_id": talk_id, "new_source": new_source}
                                    first_output = False
                                else:
                                    result_data = {"token": token, "talk_id": talk_id}

                                yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                                data = {
                                    "prompt": params.system_prompts,
                                    "user": params.input,
                                    "assistant": {"content": response_content},
                                    "type": conversation_type,
                                    "new_source": new_source,
                                }
                                data = json.dumps(data)
                                await ChatConversationService.update_talk_data_agent(
                                    db=db, talk_id=talk_id, token_data=data
                                )
                except Exception as e:
                    logger.exception(f"调用智能体异常: {e}")
                    if talk_id != "":
                        ChatConversationService.delete_talk(db=db, talk_id=talk_id)
                    result = "系统繁忙,请稍后再试"
                    result_data = {"token": result, "talk_id": talk_id, "new_source": new_source}
                    yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                    raise

        else:
            if len(kb_list) > 0:
                docs, new_source = await knowledge_retrieval(params, recall_setting, kb_list)

                if params.system_prompts != "":
                    prompt_answer = f"""
                    {prompt}
                    尽可能以有用且准确的方式回复人类。
                    知识库知识:{docs}
                    个人知识：{params.system_prompts}
                    根据用户输入和检索到的知识库内容、个人知识和你自己的知识进行知识整合，对用户问题进行回答。
                                    """
                else:
                    if history_system_prompts != "":
                        prompt_answer = f"""
                                            {prompt}
                                            尽可能以有用且准确的方式回复人类。
                                            知识库知识:{docs}
                                            个人知识：{history_system_prompts}
                                            根据用户输入和检索到的知识库内容、个人知识和你自己的知识进行知识整合，对用户问题进行回答。
                                                            """
                    else:
                        prompt_answer = f"""
                        {prompt}
                        尽可能以有用且准确的方式回复人类。
                        知识库知识:{docs}
                        根据用户输入和检索到的知识库内容和你自己的知识进行知识整合，对用户问题进行回答。
                    """
                # 保存问答数据
                talk_id = ChatConversationService.save_talk_data_agent(
                    db=db,
                    conversation_id=params.conversation_id,
                    account_id=account_id,
                    token="",
                    question=params.input,
                    kb_id="",
                    model_id="",
                    ag_id=params.agent_id,
                    type=conversation_type,
                    system_prompt=params.system_prompts,
                )
                ChatConversationService.save_talk_data_file_stop(
                    db=db,
                    conversation_id=params.conversation_id,
                    account_id=account_id,
                    type=conversation_type,
                    talk_id=talk_id,
                    talk_num=0,
                )

                async def astream_response():
                    try:
                        openAILLMService = OpenAILLMService(id=model_params["id"])
                        response_content = ""
                        first_output = True
                        async for chunk in await openAILLMService.stream_chat_v1_with_penalty(
                            db=db,
                            request=ChatCompletionRequestParams_v1(
                                model_uid=model_params["model_uid"],
                                temperature=model_params["temperature"],
                                history=model_params["history"],
                                max_token_length=model_params["max_token_length"],
                                system_prompts=prompt_answer,
                                conversation_id=params.conversation_id,
                                retrival_params={
                                    "kb_name": "",
                                    "user_query": params.input,
                                    "rerank_model": "",
                                    "recall_num": 0,
                                    "rerank_num": 0,
                                },
                                presence_penalty=model_params["presence_penalty"],
                                frequency_penalty=model_params["frequency_penalty"],
                            ),
                            chunk_content="",
                            type=conversation_type,
                        ):
                            if chunk.choices[0].delta.content != "":
                                token = chunk.choices[0].delta.content
                                status = ChatConversationService.check_talk_stop_status(
                                    db=db, talk_id=talk_id, talk_num=0
                                )
                                # status == 3 代表中断
                                if token is not None:
                                    response_content += token
                                if status == 3:
                                    break
                                else:
                                    if first_output:
                                        result_data = {"token": token, "talk_id": talk_id, "new_source": new_source}
                                        first_output = False
                                    else:
                                        result_data = {"token": token, "talk_id": talk_id}
                                    yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                                    data = {
                                        "prompt": params.system_prompts,
                                        "user": params.input,
                                        "assistant": {"content": response_content},
                                        "type": conversation_type,
                                        "new_source": new_source,
                                    }
                                    data = json.dumps(data)
                                    await ChatConversationService.update_talk_data_agent(
                                        db=db, talk_id=talk_id, token_data=data
                                    )
                    except Exception as e:
                        logger.exception(f"调用智能体异常: {e}")
                        if talk_id != "":
                            ChatConversationService.delete_talk(db=db, talk_id=talk_id)
                        result = "系统繁忙,请稍后再试"
                        result_data = {"token": result, "talk_id": talk_id, "new_source": new_source}
                        yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                        raise

            else:
                if params.system_prompts != "":
                    prompt_answer = f"""
                    {prompt}
                    尽可能以有用且准确的方式回复人类。
                    个人知识：{params.system_prompts}
                    根据用户输入和个人知识和你自己的知识进行知识整合，对用户问题进行回答。
                                    """
                else:
                    if history_system_prompts != "":
                        prompt_answer = f"""
                                            {prompt}
                                            尽可能以有用且准确的方式回复人类。
                                            个人知识：{history_system_prompts}
                                            根据用户输入和个人知识和你自己的知识进行知识整合，对用户问题进行回答。
                                                            """
                    else:
                        prompt_answer = prompt
                # 保存问答数据
                talk_id = ChatConversationService.save_talk_data_agent(
                    db=db,
                    conversation_id=params.conversation_id,
                    account_id=account_id,
                    token="",
                    question=params.input,
                    kb_id="",
                    model_id="",
                    ag_id=params.agent_id,
                    type=conversation_type,
                    system_prompt=params.system_prompts,
                )
                ChatConversationService.save_talk_data_file_stop(
                    db=db,
                    conversation_id=params.conversation_id,
                    account_id=account_id,
                    type=conversation_type,
                    talk_id=talk_id,
                    talk_num=0,
                )

                async def astream_response():
                    try:
                        # 业务逻辑处理
                        openAILLMService = OpenAILLMService(id=model_params["id"])
                        response_content = ""
                        first_output = True
                        async for chunk in await openAILLMService.stream_chat_v1_with_penalty(
                            db=db,
                            request=ChatCompletionRequestParams_v1(
                                model_uid=model_params["model_uid"],
                                system_prompts=prompt_answer,
                                conversation_id=params.conversation_id,
                                temperature=model_params["temperature"],
                                history=model_params["history"],
                                max_token_length=model_params["max_token_length"],
                                retrival_params={
                                    "kb_name": "",
                                    "user_query": params.input,
                                    "rerank_model": "",
                                    "recall_num": 0,
                                    "rerank_num": 0,
                                },
                                presence_penalty=model_params["presence_penalty"],
                                frequency_penalty=model_params["frequency_penalty"],
                            ),
                            chunk_content="",
                            type=conversation_type,
                        ):
                            if chunk.choices[0].delta.content != "":
                                token = chunk.choices[0].delta.content
                                status = ChatConversationService.check_talk_stop_status(
                                    db=db, talk_id=talk_id, talk_num=0
                                )
                                # status == 3 代表中断
                                if token is not None:
                                    response_content += token
                                if status == 3:
                                    break
                                else:
                                    if first_output:
                                        result_data = {"token": token, "talk_id": talk_id, "new_source": new_source}
                                        first_output = False
                                    else:
                                        result_data = {"token": token, "talk_id": talk_id}
                                    yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                                    data = {
                                        "prompt": params.system_prompts,
                                        "user": params.input,
                                        "assistant": {"content": response_content},
                                        "type": conversation_type,
                                        "new_source": new_source,
                                    }
                                    data = json.dumps(data)
                                    await ChatConversationService.update_talk_data_agent(
                                        db=db, talk_id=talk_id, token_data=data
                                    )
                    except Exception as e:
                        logger.exception(f"调用智能体异常: {e}")
                        if talk_id != "":
                            ChatConversationService.delete_talk(db=db, talk_id=talk_id)
                        result = "系统繁忙,请稍后再试"
                        result_data = {"token": result, "talk_id": talk_id, "new_source": new_source}
                        yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
                        raise

        return EventSourceResponse(astream_response())

    except Exception as e:
        logger.exception(f"调用智能体异常: {e}")


######################################################################################以下是现在不在使用的接口####################################################################################

# @router.post("/agent_create", summary="新增智能体")
# async def agent_create(params: AgentInfo) -> Response:
#     try:
#         result = await AgentService.create_agent(params.agent_name, params.descripition)
#         return RetUtil.response_ok(result)
#     except Exception as e:
#         logger.exception(f"智能体创建异常: {e}")
#         return Response(content=f"命令执行异常: {e}", media_type="text/plain")
#
# @router.post("/query_agent_list", summary="查询智能体列表")
# async def query_agent_list(params: QueryAgentInfo1) -> Response:
#     try:
#         result = await AgentService.query_agent(params.agent_name, params.page, params.page_size, params.item_type)
#         return RetUtil.response_ok(result)
#     except Exception as e:
#         logger.exception(f"查询智能体列表异常: {e}")
#         return Response(content=f"查询智能体列表异常: {e}", media_type="text/plain")
#
# @router.post("/tool_list", summary="工具集列表")
# async def tool_list() -> Response:
#     try:
#         result = await AgentService.list_tool()
#         return RetUtil.response_ok(result)
#     except Exception as e:
#         logger.exception(f"返回工具集列表异常: {e}")
#         return Response(content=f"返回工具集列表异常: {e}", media_type="text/plain")
#
#
# @router.post("/running_model_list_v1", summary="获取运行中的大语言模型列表")
# async def running_model_list() -> Response:
#     try:
#         result = await AgentService.running_LLM_model()
#         result.append("DeepSeek-R1-671B")
#         return RetUtil.response_ok(result)
#     except Exception as e:
#         logger.exception(f"返回运行中大语言模型列表异常: {e}")
#         return Response(content=f"返回运行中大语言模型列表异常: {e}", media_type="text/plain")
#
# @router.post("/agent_arrange", summary="编排智能体")
# async def agent_arrange(params: ArrangeAgentInfo) -> Response:
#     try:
#         result = await AgentService.arrange_agent(
#             params.agent_id, params.model_params, params.prompt, params.kb_list, params.tool_list
#         )
#         return RetUtil.response_ok(result)
#     except Exception as e:
#         logger.exception(f"编排智能体异常: {e}")
#         return Response(content=f"编排智能体异常: {e}", media_type="text/plain")
# @router.post("/update_type", summary="修改类别信息")
# async def update_type(params: TypeUpdateDict, chat_request: Request, db: Session = Depends(get_db)) -> Response:
#     try:
#         account_id = chat_request.state.account_id
#
#         usr_i = query2dict_acc(UsrService.query_usr_by_id(db=db, account_id=account_id), Usr_Model)
#
#         account_name = usr_i["account_name"]
#         usr_name = usr_i["usr_name"]
#
#         condition = {"code": params.code}
#
#         result = MongodbUtil.query_docs_by_condition(
#             collection_name=CollectionConfig.SYS_STATIC_DICT_TYPE, search_condition=condition
#         )
#         i = 0
#         for _ in result:
#             i = i + 1
#
#         result2 = MongodbUtil.query_docs_by_condition(
#             CollectionConfig.SYS_STATIC_DICT_TYPE, search_condition={"_id": ObjectId(params.id)}
#         )
#         for item in result2:
#             subcode = item["code"]
#
#         # 这里做i的判断是因为要保证两种情况:params.code为之前_id对应的数据，即不需要更新code;params.code是需要修改的，但是和已有的数据重复
#         if subcode == params.code:
#             i = i - 1
#
#         if i > 0:
#             return RetUtil.return_error(message="类别已存在")
#
#         result = await AgentService.update_type(params, account_name, usr_name)
#
#         return RetUtil.response_ok({"data": result})
#     except Exception as e:
#         logger.exception(f"修改类别信息: {e}")
#         return Response(content=f"修改类别信息: {e}", media_type="text/plain")
#
# @router.post("/agent_team_create_v1", summary="新增智能体v1")
# async def agent_team_create(params: AgentTeamInfo, chat_request: Request, db: Session = Depends(get_db)) -> Response:
#     try:
#         account_id = chat_request.state.account_id
#         if await AgentService.agent_exist(params.agent_name, account_id):
#             return RetUtil.return_error("智能体已存在")
#         result, object_id = await AgentService.create_team_agent(
#             params.agent_name, params.description, account_id, params.team_code, db
#         )
#         return RetUtil.response_ok({"build_time": TimeUtil.timestamp_to_date(time.time()), "agent_id": object_id})
#     except Exception as e:
#         logger.exception(f"智能体创建异常: {e}")
#         return Response(content=f"命令执行异常: {e}", media_type="text/plain")
#
# # 老的调用智能体函数，过于复杂（留存以查看逻辑），优化后请看上面
# async def call_agent_withtag_old(
#     chat_request: Request,
#     params: TestAgentInfo_v1,
#     db: Session = Depends(get_db),
#     conversation_type: int = 2,
#     is_workflow: Optional[int] = Query(0, description="团队代码", examples=[10001]),
# ):
#     try:
#         tag_buf = ""
#         content_type = "text"
#         start_tag = "<think>"
#         end_tag = "</think>"
#         start_time = time.time()
#         logger.info(msg="调用智能体")
#         account_id = chat_request.state.account_id
#         params_dic = params.agent_params
#         params_dic_id = ChatConversationService.task_query_id(params_dic, account_id)
#         kb_list = []
#
#         result = MongodbUtil.query_doc_by_id(
#             CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(params.agent_id)
#         )
#
#         result.update(params_dic_id)
#         model_params = result["model_params"]
#         # 如果模型配置参数中不存在presence_penalty与frequency_penalty惩罚参数，设置默认值为1
#         if model_params.get("presence_penalty", None) is None:
#             model_params["presence_penalty"] = 0
#         if model_params.get("frequency_penalty", None) is None:
#             model_params["frequency_penalty"] = 0
#         # 如果入参中没有prompt_id
#         if params.prompt_id == "":
#             # 从编排中拿prompt_id
#             prompt_id = result.get("prompt_id", "")
#             # 如果编排中也没有
#             if prompt_id == "":
#                 prompt = result["prompt"]
#             # 如果编排中有
#             else:
#                 prompt_info = query2dict_status(
#                     db.query(Prompt_Model)
#                     .filter(Prompt_Model.prompt_id == prompt_id, Prompt_Model.status != 0)
#                     .first(),
#                     Prompt_Model,
#                 )
#                 if prompt_info is None:
#                     prompt = ""
#                 else:
#                     prompt = prompt_info["prompt_content"]
#         else:
#             prompt_info = query2dict_status(
#                 db.query(Prompt_Model)
#                 .filter(Prompt_Model.prompt_id == params.prompt_id, Prompt_Model.status != 0)
#                 .first(),
#                 Prompt_Model,
#             )
#             if prompt_info is None:
#                 prompt = ""
#             else:
#                 prompt = prompt_info["prompt_content"]
#         prompt = ChatConversationService.prompt_params(params_dic, prompt)
#
#         # 获取历史system_prompt
#         talk_info = ChatConversationService.check_talk_info_history(db=db, conversation_id=params.conversation_id)
#         if len(talk_info) > model_params["history"]:  # 记录多于指定历史轮数量，进行记录截断
#             chatbot = talk_info[-model_params["history"] :]
#         else:
#             chatbot = talk_info
#         history_system_prompts = ""
#         if params.system_prompts == "":
#             for idx, conversation in enumerate(chatbot):
#                 if conversation.get("prompt", None):
#                     history_system_prompts = conversation["prompt"]
#                     break
#
#         recall_setting = result["recall_setting"]
#         if "知识库ID不存在，请给出正确的知识库ID" in result["kb_list"]:
#             return RetUtil.response_error(message="知识库ID不存在，请给出正确的知识库ID")
#         if "工具ID不存在，请给出正确的工具ID" in result["tool_list"]:
#             return RetUtil.response_error(message="工具ID不存在，请给出正确的工具ID")
#         # 查询知识库列表
#         for kb in result["kb_list"]:
#             kb_result = MongodbUtil.query_doc_by_id(CollectionConfig.KB_COLLECTION, doc_id=ObjectId(kb))
#             kb_list.append(
#                 {
#                     "id": kb,
#                     "kb_name": kb_result["kb_name"],
#                     "embedding_model": kb_result["embedding_model"],
#                     "rerank_model": kb_result["rerank_model"],
#                     "top_k": kb_result["top_k"],
#                     "score": kb_result["score"],
#                     "enhance_rounds": kb_result.get("enhance_rounds", 0),
#                 }
#             )
#         # 查询工具列表
#         tool_list = await AgentService.tool_list(result)
#         TOOLS = []
#         for tool_info in tool_list:
#             tool_parm = tool_info["tool_parm"]
#             tool_url = tool_info["tool_url"]
#             tool_method = tool_info["method"]
#             tool_function = tool_parm["function"]
#             tool_function["parameters"] = tool_parm["function"].get("parameters", {})
#
#             TOOLS.append({"type": "function", "function": tool_function})
#         if len(TOOLS):
#             # redis=aioredis.Redis
#             tool_result, tool_use = await AgentService.tool_agent(chat_request, params, model_params, TOOLS, tool_list)
#         else:
#             tool_use = False
#
#         talk_id = ""
#         new_source = []
#         if tool_use == True:
#             # 保存问答数据
#             talk_id = ChatConversationService.save_talk_data_agent(
#                 db=db,
#                 conversation_id=params.conversation_id,
#                 account_id=account_id,
#                 token="",
#                 question=params.input,
#                 kb_id="",
#                 model_id="",
#                 ag_id=params.agent_id,
#                 type=conversation_type,
#                 system_prompt=params.system_prompts,
#             )
#             ChatConversationService.save_talk_data_file_stop(
#                 db=db,
#                 conversation_id=params.conversation_id,
#                 account_id=account_id,
#                 type=conversation_type,
#                 talk_id=talk_id,
#                 talk_num=0,
#             )
#
#             # 调用大模型
#             async def astream_response():
#                 try:
#                     alltime = 0
#                     in_thinking = 0
#                     tag_buf = ""
#                     content_type = "text"
#                     start_tag = "<think>"
#                     end_tag = "</think>"
#                     content = ""
#                     think = ""
#                     stream_count = 0
#                     if params.system_prompts != "":
#                         final_prompt = f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息:{tool_result}{params.system_prompts}回答用户的问题。
#                         注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}以及{params.system_prompts}就是事实。
#                         """
#                     else:
#                         if history_system_prompts != "":
#                             final_prompt = f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息:{tool_result}{history_system_prompts}回答用户的问题。
#                                                     注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}以及{history_system_prompts}就是事实。
#                                                     """
#                         else:
#                             final_prompt = f"""{prompt} \\n你得到的信息都是准确且和问题相关的,请基于得到的信息{tool_result}回答用户的问题。
#                         注意:你得到的经过工具调用后得到的准确无误的信息,要让用户相信，你提供的{tool_result}就是事实。
#     """
#                     # 业务逻辑处理
#                     openAILLMService = OpenAILLMService(id=model_params["id"])
#                     response_content = ""
#                     first_output = True
#                     content = ""
#                     result = MongodbUtil.query_doc_by_id(
#                         collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(model_params["id"])
#                     )
#
#                     is_think = result["is_think"]
#                     async for chunk in await openAILLMService.stream_chat_v1_with_penalty(
#                         db=db,
#                         request=ChatCompletionRequestParams_v1(
#                             model_uid=model_params["model_uid"],
#                             temperature=model_params["temperature"],
#                             history=0,
#                             max_token_length=model_params["max_token_length"],
#                             conversation_id=params.conversation_id,
#                             system_prompts=final_prompt,
#                             retrival_params={
#                                 "kb_name": "",
#                                 "user_query": params.input,
#                                 "rerank_model": "",
#                                 "recall_num": 0,
#                                 "rerank_num": 0,
#                             },
#                             presence_penalty=model_params["presence_penalty"],
#                             frequency_penalty=model_params["frequency_penalty"],
#                         ),
#                         chunk_content="",
#                         type=conversation_type,
#                     ):
#                         if chunk.choices[0].delta.content != "" and chunk.choices[0].delta.content is not None:
#                             token = chunk.choices[0].delta.content
#                             tag_buf += token
#                             if is_think:
#                                 if in_thinking == 0 and "<" in chunk.choices[0].delta.content:
#                                     in_thinking = 1
#                                 elif in_thinking != 4:
#                                     in_thinking = 2
#                                     content_type = "thinking"
#                                 if start_tag in tag_buf:
#                                     in_thinking = 2
#                                     content_type = "thinking"
#                                     if len(tag_buf.split(start_tag)) > 1:
#                                         token = tag_buf.split(start_tag)[-1]
#                                         tag_buf = tag_buf.replace(start_tag, "")
#
#                                     else:
#                                         tag_buf = tag_buf.replace(start_tag, "")
#                                         continue
#                                 if in_thinking == 2 and "<" in tag_buf:
#                                     in_thinking = 3
#                                 if end_tag in tag_buf:
#                                     in_thinking = 4
#                                     content_type = "text"
#                                     if len(tag_buf.split(end_tag)) > 1:
#                                         token = tag_buf.split(end_tag)[-1]
#                                         tag_buf = tag_buf.replace(end_tag, "")
#                                     else:
#                                         tag_buf = tag_buf.replace(end_tag, "")
#                                         continue
#                                     tag_buf.replace(end_tag, "")
#                                 if in_thinking == 1 or in_thinking == 3:
#                                     continue
#                             if content_type == "thinking" and token is not None:
#                                 think += token
#                             elif content_type == "text" and token is not None:
#                                 content += token
#                             if in_thinking == 4:
#                                 stream_count += 1  # 记录什么时候思考完成产生第一个正文需要yeild的流,计算思考时间
#
#                             status = ChatConversationService.check_talk_stop_status(db=db, talk_id=talk_id, talk_num=0)
#                             # status == 3 代表中断
#
#                             if status == 3:
#                                 break
#                             else:
#                                 if first_output:
#                                     if stream_count == 1:
#                                         think_time = round(time.time() - start_time, 1)
#                                     else:
#                                         think_time = 0
#                                     result_data = {
#                                         "token": token,
#                                         "talk_id": talk_id,
#                                         "new_source": new_source,
#                                         "type": content_type,
#                                         "think_time": think_time,
#                                     }
#                                     first_output = False
#                                 else:
#                                     if stream_count == 1:
#                                         think_time = round(time.time() - start_time, 1)
#                                     else:
#                                         think_time = 0
#                                     result_data = {
#                                         "token": token,
#                                         "talk_id": talk_id,
#                                         "type": content_type,
#                                         "think_time": think_time,
#                                     }
#
#                                 yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
#                                 if think_time != 0:
#                                     alltime = think_time
#                                 if is_workflow != 1:
#                                     data = {
#                                         "prompt": params.system_prompts,
#                                         "user": params.input,
#                                         "assistant": {"content": content, "think": think, "think_time": alltime},
#                                         "type": conversation_type,
#                                         "new_source": new_source,
#                                     }
#                                     data = json.dumps(data)
#                                     await ChatConversationService.update_talk_data_agent(
#                                         db=db, talk_id=talk_id, token_data=data
#                                     )
#
#                 except Exception as e:
#                     logger.exception(f"调用智能体异常: {e}")
#                     if talk_id != "":
#                         ChatConversationService.delete_talk(db=db, talk_id=talk_id)
#                     result = "系统繁忙,请稍后再试"
#                     result_data = {"token": result, "talk_id": talk_id, "new_source": new_source}
#                     yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
#                     raise
#
#         else:
#             if len(kb_list) > 0:
#                 docs, new_source = await knowledge_retrieval(params, recall_setting, kb_list)
#
#                 if params.system_prompts != "":
#                     prompt_answer = f"""
#                         {prompt}
#                         尽可能以有用且准确的方式回复人类。
#                         知识库知识:{docs}
#                         个人知识：{params.system_prompts}
#                         根据用户输入和检索到的知识库内容、个人知识和你自己的知识进行知识整合，对用户问题进行回答。
#                     """
#                 else:
#                     if history_system_prompts != "":
#                         prompt_answer = f"""
#                             {prompt}
#                             尽可能以有用且准确的方式回复人类。
#                             知识库知识: {docs}
#                             个人知识：{history_system_prompts}
#                             根据用户输入和检索到的知识库内容、个人知识和你自己的知识进行知识整合，对用户问题进行回答。
#                         """
#                     else:
#                         prompt_answer = f"""
#                             {prompt}
#                             尽可能以有用且准确的方式回复人类。
#                             知识库知识:{docs}
#                             根据用户输入和检索到的知识库内容和你自己的知识进行知识整合，对用户问题进行回答。
#                         """
#                 # 保存问答数据
#                 talk_id = ChatConversationService.save_talk_data_agent(
#                     db=db,
#                     conversation_id=params.conversation_id,
#                     account_id=account_id,
#                     token="",
#                     question=params.input,
#                     kb_id="",
#                     model_id="",
#                     ag_id=params.agent_id,
#                     type=conversation_type,
#                     system_prompt=params.system_prompts,
#                 )
#                 ChatConversationService.save_talk_data_file_stop(
#                     db=db,
#                     conversation_id=params.conversation_id,
#                     account_id=account_id,
#                     type=conversation_type,
#                     talk_id=talk_id,
#                     talk_num=0,
#                 )
#
#                 async def astream_response():
#                     try:
#                         alltime = 0
#                         in_thinking = 0
#                         tag_buf = ""
#                         content_type = "text"
#                         start_tag = "<think>"
#                         end_tag = "</think>"
#                         content = ""
#                         think = ""
#                         stream_count = 0
#                         openAILLMService = OpenAILLMService(id=model_params["id"])
#                         response_content = ""
#                         content = ""
#                         first_output = True
#
#                         result = MongodbUtil.query_doc_by_id(
#                             collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(model_params["id"])
#                         )
#
#                         is_think = result["is_think"]
#
#                         async for chunk in await openAILLMService.stream_chat_v1_with_penalty(
#                             db=db,
#                             request=ChatCompletionRequestParams_v1(
#                                 model_uid=model_params["model_uid"],
#                                 temperature=model_params["temperature"],
#                                 history=model_params["history"],
#                                 max_token_length=model_params["max_token_length"],
#                                 system_prompts=prompt_answer,
#                                 conversation_id=params.conversation_id,
#                                 retrival_params={
#                                     "kb_name": "",
#                                     "user_query": params.input,
#                                     "rerank_model": "",
#                                     "recall_num": 0,
#                                     "rerank_num": 0,
#                                 },
#                                 presence_penalty=model_params["presence_penalty"],
#                                 frequency_penalty=model_params["frequency_penalty"],
#                             ),
#                             chunk_content="",
#                             type=conversation_type,
#                         ):
#                             if chunk.choices[0].delta.content != "" and chunk.choices[0].delta.content is not None:
#                                 token = chunk.choices[0].delta.content
#                                 tag_buf += token
#                                 if is_think:
#                                     if in_thinking == 0 and "<" in chunk.choices[0].delta.content:
#                                         in_thinking = 1
#                                     elif in_thinking != 4:
#                                         in_thinking = 2
#                                         content_type = "thinking"
#                                     if start_tag in tag_buf:
#                                         in_thinking = 2
#                                         content_type = "thinking"
#                                         if len(tag_buf.split(start_tag)) > 1:
#                                             token = tag_buf.split(start_tag)[-1]
#                                             tag_buf = tag_buf.replace(start_tag, "")
#
#                                         else:
#                                             tag_buf = tag_buf.replace(start_tag, "")
#                                             continue
#                                     if in_thinking == 2 and "<" in tag_buf:
#                                         in_thinking = 3
#                                     if end_tag in tag_buf:
#                                         in_thinking = 4
#                                         content_type = "text"
#                                         if len(tag_buf.split(end_tag)) > 1:
#                                             token = tag_buf.split(end_tag)[-1]
#                                             tag_buf = tag_buf.replace(end_tag, "")
#                                         else:
#                                             tag_buf = tag_buf.replace(end_tag, "")
#                                             continue
#                                         tag_buf.replace(end_tag, "")
#                                     if in_thinking == 1 or in_thinking == 3:
#                                         continue
#                                 if content_type == "thinking" and token is not None:
#                                     think += token
#                                 elif content_type == "text" and token is not None:
#                                     content += token
#                                 if in_thinking == 4:
#                                     stream_count += 1  # 记录什么时候思考完成产生第一个正文需要yeild的流,计算思考时间
#
#                                 status = ChatConversationService.check_talk_stop_status(
#                                     db=db, talk_id=talk_id, talk_num=0
#                                 )
#                                 # status == 3 代表中断
#
#                                 if status == 3:
#                                     break
#                                 else:
#                                     if first_output:
#                                         if stream_count == 1:
#                                             think_time = round(time.time() - start_time, 1)
#                                         else:
#                                             think_time = 0
#                                         result_data = {
#                                             "token": token,
#                                             "talk_id": talk_id,
#                                             "new_source": new_source,
#                                             "type": content_type,
#                                             "think_time": think_time,
#                                         }
#                                         first_output = False
#                                     else:
#                                         if stream_count == 1:
#                                             think_time = round(time.time() - start_time, 1)
#                                         else:
#                                             think_time = 0
#                                         result_data = {
#                                             "token": token,
#                                             "talk_id": talk_id,
#                                             "type": content_type,
#                                             "think_time": think_time,
#                                         }
#
#                                     yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
#                                     if think_time != 0:
#                                         alltime = think_time
#                                     if is_workflow != 1:
#                                         data = {
#                                             "prompt": params.system_prompts,
#                                             "user": params.input,
#                                             "assistant": {"content": content, "think": think, "think_time": alltime},
#                                             "type": conversation_type,
#                                             "new_source": new_source,
#                                         }
#                                         data = json.dumps(data)
#                                         await ChatConversationService.update_talk_data_agent(
#                                             db=db, talk_id=talk_id, token_data=data
#                                         )
#
#                     except Exception as e:
#                         logger.exception(f"调用智能体异常: {e}")
#                         if talk_id != "":
#                             ChatConversationService.delete_talk(db=db, talk_id=talk_id)
#                         result = "系统繁忙,请稍后再试"
#                         result_data = {"token": result, "talk_id": talk_id, "new_source": new_source}
#                         yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
#                         raise
#
#             else:
#                 if params.system_prompts != "":
#                     prompt_answer = f"""
#                     {prompt}
#                     尽可能以有用且准确的方式回复人类。
#                     个人知识：{params.system_prompts}
#                     根据用户输入和个人知识和你自己的知识进行知识整合，对用户问题进行回答。
#                                     """
#                 else:
#                     if history_system_prompts != "":
#                         prompt_answer = f"""
#                                             {prompt}
#                                             尽可能以有用且准确的方式回复人类。
#                                             个人知识：{history_system_prompts}
#                                             根据用户输入和个人知识和你自己的知识进行知识整合，对用户问题进行回答。
#                                                             """
#                     else:
#                         prompt_answer = prompt
#                 # 保存问答数据
#                 talk_id = ChatConversationService.save_talk_data_agent(
#                     db=db,
#                     conversation_id=params.conversation_id,
#                     account_id=account_id,
#                     token="",
#                     question=params.input,
#                     kb_id="",
#                     model_id="",
#                     ag_id=params.agent_id,
#                     type=conversation_type,
#                     system_prompt=params.system_prompts,
#                 )
#
#                 ChatConversationService.save_talk_data_file_stop(
#                     db=db,
#                     conversation_id=params.conversation_id,
#                     account_id=account_id,
#                     type=conversation_type,
#                     talk_id=talk_id,
#                     talk_num=0,
#                 )
#
#                 async def astream_response():
#                     try:
#                         in_thinking = 0
#                         alltime = "0"
#                         tag_buf = ""
#                         content_type = "text"
#                         start_tag = "<think>"
#                         end_tag = "</think>"
#                         content = ""
#                         think = ""
#                         stream_count = 0
#                         # 业务逻辑处理
#                         openAILLMService = OpenAILLMService(id=model_params["id"])
#                         response_content = ""
#                         content = ""
#                         first_output = True
#
#                         result = MongodbUtil.query_doc_by_id(
#                             collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(model_params["id"])
#                         )
#
#                         is_think = result["is_think"]
#
#                         async for chunk in await openAILLMService.stream_chat_v1_with_penalty(
#                             db=db,
#                             request=ChatCompletionRequestParams_v1(
#                                 model_uid=model_params["model_uid"],
#                                 system_prompts=prompt_answer,
#                                 conversation_id=params.conversation_id,
#                                 temperature=model_params["temperature"],
#                                 history=model_params["history"],
#                                 max_token_length=model_params["max_token_length"],
#                                 retrival_params={
#                                     "kb_name": "",
#                                     "user_query": params.input,
#                                     "rerank_model": "",
#                                     "recall_num": 0,
#                                     "rerank_num": 0,
#                                 },
#                                 presence_penalty=model_params["presence_penalty"],
#                                 frequency_penalty=model_params["frequency_penalty"],
#                             ),
#                             chunk_content="",
#                             type=conversation_type,
#                         ):
#                             if chunk.choices[0].delta.content != "" and chunk.choices[0].delta.content is not None:
#                                 token = chunk.choices[0].delta.content
#                                 tag_buf += token
#                                 if is_think:
#                                     if in_thinking == 0 and "<" in chunk.choices[0].delta.content:
#                                         in_thinking = 1
#                                     elif in_thinking != 4:
#                                         in_thinking = 2
#                                         content_type = "thinking"
#                                     if start_tag in tag_buf:
#                                         in_thinking = 2
#                                         content_type = "thinking"
#                                         if len(tag_buf.split(start_tag)) > 1:
#                                             token = tag_buf.split(start_tag)[-1]
#                                             tag_buf = tag_buf.replace(start_tag, "")
#
#                                         else:
#                                             tag_buf = tag_buf.replace(start_tag, "")
#                                             continue
#                                     if in_thinking == 2 and "<" in tag_buf:
#                                         in_thinking = 3
#                                     if end_tag in tag_buf:
#                                         in_thinking = 4
#                                         content_type = "text"
#                                         if len(tag_buf.split(end_tag)) > 1:
#                                             token = tag_buf.split(end_tag)[-1]
#                                             tag_buf = tag_buf.replace(end_tag, "")
#                                         else:
#                                             tag_buf = tag_buf.replace(end_tag, "")
#                                             continue
#                                         tag_buf.replace(end_tag, "")
#                                     if in_thinking == 1 or in_thinking == 3:
#                                         continue
#                                 if content_type == "thinking" and token is not None:
#                                     think += token
#                                 elif content_type == "text" and token is not None:
#                                     content += token
#                                 if in_thinking == 4:
#                                     stream_count += 1  # 记录什么时候思考完成产生第一个正文需要yeild的流,计算思考时间
#
#                                 status = ChatConversationService.check_talk_stop_status(
#                                     db=db, talk_id=talk_id, talk_num=0
#                                 )
#                                 # status == 3 代表中断
#                                 if token is not None:
#                                     response_content += token
#                                 if status == 3:
#                                     break
#                                 else:
#                                     if first_output:
#                                         if stream_count == 1:
#                                             think_time = round(time.time() - start_time, 1)
#
#                                         else:
#                                             think_time = 0
#
#                                         result_data = {
#                                             "token": token,
#                                             "talk_id": talk_id,
#                                             "new_source": new_source,
#                                             "type": content_type,
#                                             "think_time": think_time,
#                                         }
#                                         first_output = False
#                                     else:
#                                         if stream_count == 1:
#                                             think_time = round(time.time() - start_time, 1)
#
#                                         else:
#                                             think_time = 0
#                                         result_data = {
#                                             "token": token,
#                                             "talk_id": talk_id,
#                                             "type": content_type,
#                                             "think_time": think_time,
#                                         }
#                                     if think_time != 0:
#                                         alltime = think_time
#                                     yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
#                                     if is_workflow != 1:
#                                         data = {
#                                             "prompt": params.system_prompts,
#                                             "user": params.input,
#                                             "assistant": {"content": content, "think": think, "think_time": alltime},
#                                             "type": conversation_type,
#                                             "new_source": new_source,
#                                         }
#                                         data = json.dumps(data)
#                                         await ChatConversationService.update_talk_data_agent(
#                                             db=db, talk_id=talk_id, token_data=data
#                                         )
#
#                     except Exception as e:
#                         logger.exception(f"调用智能体异常: {e}")
#                         if talk_id != "":
#                             ChatConversationService.delete_talk(db=db, talk_id=talk_id)
#                         result = "系统繁忙,请稍后再试"
#                         result_data = {"token": result, "talk_id": talk_id, "new_source": new_source}
#                         yield f"{json.dumps(RetUtil.response_stream(data=result_data), ensure_ascii=False)}"
#                         raise
#
#         if is_workflow == 1:
#             return astream_response()
#             # async for token_json in astream_response():
#             #     yield token_json
#             # '{"status": true, "message": "success", "data": {"token": "我和", "talk_id": "TALK_1947548903452839936", "type": "text", "think_time": 0}}'
#             # for i in range(50):
#             #     yield '{"status": true, "message": "success", "data": {"token": "我和", "talk_id": "TALK_1947548903452839936", "type": "text", "think_time": 0}}'
#         else:
#             return EventSourceResponse(astream_response())
#
#     except Exception as e:
#         logger.exception(f"调用智能体异常: {e}")
#
# @router.post("/create_type", summary="创建类别")
# async def create_type(params: TypeDict, chat_request: Request, db: Session = Depends(get_db)) -> Response:
#     try:
#         account_id = chat_request.state.account_id
#         if await AgentService.type_exist(params.code):
#             return RetUtil.return_error(message="类别已存在")
#
#         usr_i = query2dict_acc(UsrService.query_usr_by_id(db=db, account_id=account_id), Usr_Model)
#
#         account_name = usr_i["account_name"]
#         usr_name = usr_i["usr_name"]
#         result, code = await AgentService.create_type(
#             params.code, params.name, params.description, account_name, usr_name
#         )
#
#         return RetUtil.response_ok({"code": code})
#     except Exception as e:
#         logger.exception(f"创建类别: {e}")
#         return Response(content=f"创建类别: {e}", media_type="text/plain")
#
# @router.delete("/delete_type", summary="删除类别")
# async def delete_type(
#     params: TypeDelete,
# ) -> Response:
#     try:
#         id = params.id
#         result = MongodbUtil.query_docs_by_condition(
#             CollectionConfig.SYS_STATIC_DICT_TYPE, search_condition={"_id": ObjectId(id)}
#         )
#         docs = list(result)
#         if not docs:
#             return RetUtil.return_error(message="没有找到匹配的类别")
#
#         result = await AgentService.delete_type(id)
#         return RetUtil.response_ok(result)
#     except Exception as e:
#         logger.exception(f"删除类别: {e}")
#         return Response(content=f"删除类别: {e}", media_type="text/plain")
#
#
# @router.post("/query_type", summary="查询类别")
# async def query_type(
#     code: str = Body(..., examples=["agnet-type"], description="智能体模糊查询名称"),
#     name: str = Body(..., examples=["健康智能体"], description="健康智能体"),
#     status: str = Body(..., examples=["1"], description="状态码"),
#     page: int = Body(..., examples=[1], description="页码"),
#     page_size: int = Body(..., examples=[2], description="页面大小"),
# ) -> Response:
#     try:
#         # status必选，code、name可选
#         result = await AgentService.query_type(name, code, status, page, page_size)
#         return RetUtil.response_ok({"data": result})
#     except Exception as e:
#         logger.exception(f"查询类别异常: {e}")
#         return Response(content=f"查询类别异常: {e}", media_type="text/plain")
#
# @router.post("/user_team_permission", summary="所属团队鉴权")
# async def agent_team_create(
#     chat_request: Request,
#     db: Session = Depends(get_db),
#     team_code: str = Body(..., embed=True, examples=["id"], description="智能体id"),
# ) -> Response:
#     try:
#         account_id = chat_request.state.account_id
#         result = db.query(Team_Model).filter(Team_Model.status == 1, Team_Model.team_code == team_code).first()
#
#         team_id = result.id
#
#         result = (
#             db.query(TeamMem_Model.team_id)
#             .filter(TeamMem_Model.account_id == account_id, TeamMem_Model.status == 1, TeamMem_Model.team_id == team_id)
#             .first()
#         )
#         if result == None:
#             return RetUtil.response_ok("no")
#         else:
#             return RetUtil.response_ok("yes")
#     except Exception as e:
#         logger.exception(f"智能体创建异常: {e}")
#         return Response(content=f"命令执行异常: {e}", media_type="text/plain")
#

