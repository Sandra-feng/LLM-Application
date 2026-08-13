#!/usr/bin/env python
"""
@File         :knowledge_route.py
@Description  :
@Author       :QiangQu
@Date         :2024/09/03 15:10:28
"""

import datetime
import json
import re
from typing import Optional, List
from zipfile import ZipFile

from bson import ObjectId
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Request,
    UploadFile, HTTPException,
)
from fastapi.responses import Response
from loguru import logger
from sqlalchemy.orm import Session

from base_configs.minio_config import MinioConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.milvus_util import MilvusUtil
from base_utils.minio_util import MinIoUtil
from base_utils.mongodb_util import MongodbUtil
from base_utils.mysql_util import SessionLocal
from base_utils.ret_util import RetUtil
from service_agent_manage.service.agent_service import AgentService
from service_knowledge_manage.entity.knowledge_entity import (
    KnowledgeInfo,
    KnowledgeRetrievalSettingUpdate,
)
from service_knowledge_manage.service.knowledge_evaluation import Knowledge_Evaluation_service
from service_knowledge_manage.service.knowledge_file_service import (
    Knowledge_File_service,
)
from service_knowledge_manage.service.knowledge_service import KnowledgeService
from service_usr_manage.service.snow_util import generate_unique_id
from service_workflow_manage.service.workflow_service import (
    WorkflowNodeService,
)


# logger = loguru logger (auto-migrated)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


router = APIRouter()


@router.post("/chunk_highlight_pdf_by_node", summary="在源pdf中找到切片所在位置并高亮，使用node做输入")
async def chunk_highlight_pdf_by_node(
    kb_id: str = Body(..., description="知识库id"),
    chunk_id: str = Body(..., description="切片id"),
    file_path: str = Body(..., description="文件路径")
):
    try:
        logger.info("->切片溯源高亮")
        result = await KnowledgeService.chunk_highlight_by_node(
            kb_id=kb_id,
            chunk_id=chunk_id,
            file_path=file_path
        )
        logger.info(f"->切片溯源高亮成功：chunk_id={chunk_id}")
        return RetUtil.response_ok(result)
    except Exception as e:
        detail = f"切片溯源高亮失败：{str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message=detail)



@router.post("/chunk_highlight_pdf", summary="在源pdf中找到切片所在位置并高亮")
async def chunks_highlight(
    file_path: str = Body(..., description="pdf文件在minio桶的路径"),
    kb_id: str = Body(..., description="知识库id"),
    chunk: str = Body(..., description="切片字符串"),
    page: list = Body(..., description="切片所在页码（1开头）"),
    abandon_area: dict = Body(..., description="页眉页脚等区域"),
):
    try:
        logger.info("->切片溯源高亮")
        result = await KnowledgeService.chunk_highlight(
            file_path=file_path,
            kb_id=kb_id,
            chunk=chunk,
            page_list=page,
            abandon_area=abandon_area,
        )
        logger.info("->切片溯源高亮成功")
        return RetUtil.response_ok(result)

    except Exception as e:
        detail = f"切片溯源高亮失败：{str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message=detail)


@router.post(
    "/get_all_knowledge",
    summary="获取所有知识库，不分页返回",
    response_model=KnowledgeInfo,
)
async def aget_all_knowledge() -> Response:
    try:
        # 头尾下标
        kb_list, kb_len = await KnowledgeService.get_all_kb()
        logger.info(f"查询到所有知识库数量:{kb_len}")
        return RetUtil.response_ok(data=kb_list)

    except Exception as e:
        logger.exception("获取所有知识库失败", str(e))
        return RetUtil.response_error(message="获取所有知识库失败")


@router.post(
    "/get_all_emb_model_info",
    summary="获取所有嵌入模型及其维度信息",
)
async def get_all_emb_model_info() -> Response:
    try:
        # 头尾下标
        emb_model_list = []
        emb_model = await WorkflowNodeService.running_embedding_model()
        for model in emb_model:
            result = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                doc_id=ObjectId(model["id"]),
            )
            if result["is_external"] == False:
                result = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_FAMILY_COLLECTION,
                    doc_id=result["model_id"],
                )
                emb_model_list.append(
                    {
                        "embedding_model": model,
                        "dimension": result["model_emb_details"]["model_embedding_dimension"],
                        "max_token": result["model_emb_details"]["model_contex_length"],
                    }
                )
            else:
                emb_model_list.append({"embedding_model": model, "dimension": result["max_tokens"]})
        logger.info(f"嵌入模型及其维度信息列表：{emb_model_list}")
        return RetUtil.response_ok(data=emb_model_list)

    except Exception as e:
        logger.exception("获取所有嵌入模型及其维度信息失败", str(e))
        return RetUtil.response_error(message="获取所有嵌入模型及其维度信息失败")


@router.post(
    "/get_all_rerank_model_info",
    summary="获取所有重排模型及其维度信息",
)
async def get_all_rerank_model_info() -> Response:
    try:
        results = []
        result = MongodbUtil.query_docs_by_condition(
            collection_name=CollectionConfig.MODEL_RUN_COLLECTION, search_condition={}
        )
        for item in result:
            if item["status"] == "running" and item["model_type"] == "rerank" and item["is_delete"] == False:
                if item["is_external"] == False:
                    data = {
                        "model_name": item["model_uid"],
                        "id": str(item["_id"]),
                        "model_uid": item["model_uid"],
                        "is_external": item["is_external"],
                    }
                else:
                    data = {
                        "model_name": item["model_name"],
                        "id": str(item["_id"]),
                        "model_uid": item["model_uid"],
                        "is_external": item["is_external"],
                    }
                results.append(data)
        logger.info(f"重排模型及其维度信息列表：{results}")
        return RetUtil.response_ok(data=results)

    except Exception as e:
        logger.exception("获取所有重排模型及其维度信息失败", str(e))
        return RetUtil.response_error(message="获取所有重排模型及其维度信息失败")


@router.post("/prompt_store", summary="提示词入库")
async def knowledge_query(
    id: str = Body(..., embed=True, examples=[""], description="id"),
    prompt: str = Body(..., embed=True, examples=[""], description="提示词"),
) -> Response:
    try:
        input_info = {"id": id, "prompt": prompt}
        # logger.info(f"提示词入库入参信息:{input_info}")
        MongodbUtil.update_docs_by_condition(
            collection_name=CollectionConfig.KB_COLLECTION,
            search_condition={"_id": ObjectId(id)},
            replace_data={"$set": {"prompt": prompt}},
        )
        logger.info("提示词入库成功")
        return RetUtil.response_ok(data="提示词入库成功")
    except Exception as e:
        logger.exception("提示词入库入库失败", str(e))
        return RetUtil.response_error(message="提示词入库入库失败")


@router.post("/retrieval_setting_update", summary="修改切片检索")
async def knowledge_update(request: KnowledgeRetrievalSettingUpdate) -> Response:
    try:
        rerank_id=request.rerank_id
        if rerank_id != '':
            model_data = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                doc_id=ObjectId(rerank_id),
            )
            if model_data:
                rerank_model = model_data.get("model_uid", "")
        else:
            rerank_model = request.rerank_model
        await KnowledgeService.slice_retrieval_update(
            request.id,
            rerank_model,
            request.retrieval_count,
            request.score,
            request.top_k,
            request.rerank_id,
            request.enhance_rounds,
            request.search_type,
            request.fusion_weights,
        )
        changing_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info("修改切片检索成功")
        return RetUtil.response_ok(data={"changing_time": changing_time})

    except Exception as e:
        logger.exception(f"修改切片检索失败: {e}")
        return RetUtil.response_error(message="修改切片检索失败")


@router.post("/call_create_knowledge", summary="创建知识库")
async def call_create_knowledge(
        chat_request: Request,
        kb_name: str = Body(..., embed=True, examples=["test_py"], description="知识库名称"),
        description: Optional[str] = Body("", description="描述知识库"),
        embedding_id: str = Body(..., description="嵌入模型id"),
        rerank_id: str = Body("", description="重排模型id"),
        team_code: Optional[str] = Body("", description="团队id")
) -> Response:
    try:
        # 获取当前用户ID
        account_id = chat_request.state.account_id
        # 获取运行中、外部模型
        external_model = MongodbUtil.query_docs_by_condition(
            CollectionConfig.MODEL_RUN_COLLECTION,
            {"_id":ObjectId(embedding_id),"model_type": "embedding", "status": "running", "is_delete": False},
        )
        for model in external_model:
            if model["is_external"]:
                dimension = model["max_model_len"]
                max_tokens = model["max_tokens"]
                model_name= model["model_name"] if model.get("model_name", None) else model["model_uid"]
            else:
                result = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_FAMILY_COLLECTION, doc_id=model["model_id"]
                )
                model_name=model["model_uid"]
                dimension = result["model_emb_details"]["model_embedding_dimension"]
                max_tokens = result["model_emb_details"].get("model_contex_length", None)
        knowledge_dict = {
            "kb_name": kb_name,
            "description": description,
            "team_code": team_code,
            "embedding_id": embedding_id,
            "embedding_model": model_name,
            "embedding_dimension": dimension,
            "rerank_id": rerank_id,
            "embedding_max_tokens": max_tokens
        }
        knowledge_obj = KnowledgeInfo(**knowledge_dict)
        result, info, new_kb_id = await KnowledgeService.kb_create(knowledge_obj, account_id)
        # 根据结果返回对应响应
        if result:
            logger.info(f"成功创建知识库: {knowledge_obj.kb_name}")
            return RetUtil.response_ok(data={"knowledge_id": str(new_kb_id)})
        else:
            logger.exception(f"创建知识库失败: {info}")
            return RetUtil.response_error(message=info)

    except Exception as e:
        logger.exception(f"创建知识库失败: {e}")
        return RetUtil.response_error(message=f"创建知识库失败: {e}")


@router.post("/call_delete_knowledge", summary="删除知识库")
async def call_delete_knowledge(
    chat_request: Request,
    db: Session = Depends(get_db),
    id: str = Body(..., description="知识库id", embed=True),
) -> Response:
    try:
        input_info = {"id": id}
        if id == "":
            return RetUtil.response_error(message="知识库ID不能为空")
        result = MongodbUtil.query_docs_by_condition(CollectionConfig.KB_COLLECTION, {"_id": ObjectId(id)})
        if len(list(result)) == 0:
            return RetUtil.response_error(message="删除的知识库不存在")

        account_id = chat_request.state.account_id
        is_own_knowledge = await Knowledge_File_service.is_own_knowledge(knowledge_id=id, account_id=account_id, db=db)
        if not is_own_knowledge:
            return RetUtil.response_error(message="数据越权")

        result = await knowledge_delete(chat_request=chat_request, id=id)
        response_body = result.body
        response_str = response_body.decode()
        result = json.loads(response_str)

        if result["status"]:
            logger.info("知识库删除成功")
            return RetUtil.response_ok("知识库删除成功")

        else:
            return RetUtil.response_error(message=str(result["message"]))

    except Exception as e:
        logger.exception("知识库删除失败", str(e))
        return RetUtil.response_error(message="知识库删除失败")


################################################################################# 改造知识库


@router.post("/knowledge_create", summary="创建知识库", response_model=KnowledgeInfo)
async def knowledge_create(knowledge_info: KnowledgeInfo, chat_request: Request) -> Response:
    """
    功能说明：新增知识库信息，创建知识库（支持混合检索）
    :param knowledge_info: 知识库信息（包含混合检索配置）
    :param chat_request: 请求信息，获取account_id
    :return: 知识库创建结果
    """
    try:
        # 获取用户账户ID
        account_id = getattr(chat_request.state, "account_id", None)
        if not account_id:
            logger.warning("无法获取账户ID")
            return RetUtil.response_error(message="用户认证失败，无法获取账户信息")

        # 输入参数验证
        if not knowledge_info.kb_name or not knowledge_info.kb_name.strip():
            return RetUtil.response_error(message="知识库名称不能为空")

        if not knowledge_info.embedding_model or not knowledge_info.embedding_model.strip():
            return RetUtil.response_error(message="嵌入模型不能为空")

        if knowledge_info.embedding_dimension <= 0:
            return RetUtil.response_error(message="嵌入维度必须大于0")

        if not knowledge_info.embedding_id or not knowledge_info.embedding_id.strip():
            return RetUtil.response_error(message="嵌入模型ID不能为空")

        # 记录创建知识库的操作
        logger.info(f"开始创建知识库: {knowledge_info.kb_name} ")

        # 调用服务层创建知识库
        result, info, new_kb_id = await KnowledgeService.kb_create(knowledge_info, account_id)

        if result:
            build_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"成功创建知识库: {knowledge_info.kb_name}")

            return RetUtil.response_ok(
                data={
                    "kb_id": str(new_kb_id),
                    "kb_name": knowledge_info.kb_name,
                    "build_time": build_time,
                    "embedding_dimension": knowledge_info.embedding_dimension,
                }
            )
        else:
            logger.exception(f"创建知识库失败: {info}")
            return RetUtil.response_error(message=info)

    except ValueError as ve:
        # 参数验证错误
        logger.exception(f"创建知识库参数错误: {str(ve)}")
        return RetUtil.response_error(message=f"参数错误: {str(ve)}")

    except Exception as e:
        # 系统异常
        logger.exception(f"创建知识库系统异常: {str(e)}")
        return RetUtil.response_error(message="创建知识库失败，请检查系统状态或联系管理员", error_code="SYSTEM_ERROR")


@router.delete("/knowledge_delete", summary="删除知识库", response_model=KnowledgeInfo)
async def knowledge_delete(chat_request: Request, id: str = Body(..., description="知识库id", embed=True)) -> Response:
    """
    功能说明：删除知识库，根据知识库id进行删除操作
    :param knowledge_id: 知识库id
    :return: 删除知识库成功
    """
    try:
        input_info = {"id": id}
        # logger.info(f"删除知识库入参信息:{input_info}")
        account_id = chat_request.state.account_id
        agent_name_list = await KnowledgeService.is_in_agent_list(id, account_id)
        workflow_name_list = await KnowledgeService.is_in_workflow_list(id, account_id)
        logger.info(f"查询到知识库被用于智能体的智能体名称列表:{agent_name_list}")
        logger.info(f"查询到知识库被用于工作流的工作流名称列表{workflow_name_list}")
        if agent_name_list and workflow_name_list:
            logger.info(f"无法删除知识库ID:{id}")
            return RetUtil.response_error(
                message=f"知识库被运用于智能体  {','.join(agent_name_list)}  与工作流  {','.join(workflow_name_list)}  中，无法被删除"
            )
        elif agent_name_list:
            logger.info(f"无法删除知识库ID:{id}")
            return RetUtil.response_error(message=f"知识库被运用于智能体  {','.join(agent_name_list)}  中，无法被删除")
        elif workflow_name_list:
            logger.info(f"无法删除知识库ID:{id}")
            return RetUtil.response_error(
                message=f"知识库被运用于工作流  {','.join(workflow_name_list)}  中，无法被删除"
            )
        # 知识库是否存在
        condition = {"_id": ObjectId(id)}
        is_exist = await KnowledgeService.is_knowledge_exist(condition)
        if not is_exist:
            return RetUtil.response_error(message="知识库不存在")

        result, info = await KnowledgeService.kb_delete(id)

        if result:
            logger.info("删除知识库成功")
            return RetUtil.response_ok(data=info)
        else:
            return RetUtil.response_error(message=info)

    except Exception as e:
        logger.exception("删除知识库失败:", str(e))
        return RetUtil.response_error(message="删除知识库失败")


@router.post("/knowledge_update", summary="修改知识库")
async def knowledge_update_new(
    id: str = Body(..., description="知识库id", embed=True),
    kb_name: str = Body("", description="知识库名称", embed=True),
    description: str = Body(..., description="知识库描述", embed=True),
    team_code: Optional[str] = Body("", description="团队id", embed=True),
) -> Response:
    try:
        input_info = {"id": id, "kb_name": kb_name, "description": description, "team_code": team_code}
        # logger.info(f"修改知识库入参信息:{input_info}")

        # 知识库是否存在
        condition = {"_id": ObjectId(id)}
        is_exist = await KnowledgeService.is_knowledge_exist(condition)
        if not is_exist:
            return RetUtil.response_error(message="知识库不存在")

        await KnowledgeService.kb_update(id, kb_name, description, team_code)
        logger.info("修改知识库成功")
        changing_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return RetUtil.response_ok(data={"changing_time": changing_time})

    except Exception as e:
        logger.exception("修改知识库失败", str(e))
        return RetUtil.response_error(message="修改知识库失败")


@router.post("/knowledge_query", summary="查询知识库列表", response_model=KnowledgeInfo)
async def knowledge_query_new(
    chat_request: Request,
    page: int = Body(..., description="页码", embed=True),
    page_size: int = Body(..., description="分页大小", embed=True),
    kb_name: str = Body("", description="知识库名称", embed=True),
    team_codes: Optional[list] = Body([], description="团队id", embed=True),
    id: str = Body(..., description="知识库id", embed=True),
) -> Response:
    """
    功能说明：分页查询知识库列表，根据知识库名称进行模糊查询
    :param page: 页码
    :param page_size: 分页大小
    :param kb_name: 知识库名称
    :param chat_request: 请求信息，获取account_id
    :param team_codes: 团队id
    :return: 知识库数量，知识库列表
    """
    try:
        account_id = chat_request.state.account_id

        input_info = {"id": id, "kb_name": kb_name, "page": page, "page_size": page_size, "team_codes": team_codes}
        # logger.info(f"查询知识库列表入参信息:{input_info}")

        # 添加查询条件: 模糊查询知识库名称，用户id/团队id，查询该用户/团队创建的知识库
        if team_codes:
            if id:
                try:
                    id = ObjectId(id)
                    condition = {
                        "$and": [
                            {
                                "$or": [
                                    {"kb_name": {"$regex": f"{re.escape(kb_name)}(_.*)?", "$options": "i"}},
                                    {"description": {"$regex": f"{re.escape(kb_name)}(_.*)?", "$options": "i"}},
                                ]
                            },
                            {"_id": id},  # 精确匹配 _id
                            {"team_code": {"$in": team_codes}},
                            {"temp": {"$exists": False}},
                        ]
                    }

                except Exception as e:
                    return RetUtil.response_ok(data={"total": 0, "result": []})
            else:
                condition = {
                    "$or": [
                        {
                            "kb_name": {
                                "$regex": f"{re.escape(kb_name)}(\\_.*)?",
                                "$options": "i",
                            }
                        },
                        {
                            "description": {
                                "$regex": f"{re.escape(kb_name)}(\\_.*)?",
                                "$options": "i",
                            }
                        },
                    ],
                    "team_code": {"$in": team_codes},
                    "temp": {"$exists": False},
                }
        else:
            if id:
                try:
                    id = ObjectId(id)
                    condition = {
                        "$and": [
                            {
                                "$or": [
                                    {"kb_name": {"$regex": f"{re.escape(kb_name)}(_.*)?", "$options": "i"}},
                                    {"description": {"$regex": f"{re.escape(kb_name)}(_.*)?", "$options": "i"}},
                                ]
                            },
                            {"_id": id},  # 精确匹配 _id
                            {"account_id": account_id},
                            {"team_code": ""},
                            {"temp": {"$exists": False}},
                        ]
                    }

                except Exception as e:
                    return RetUtil.response_ok(data={"total": 0, "result": []})
            else:
                condition = {
                    "$or": [
                        {
                            "kb_name": {
                                "$regex": f"{re.escape(kb_name)}(\\_.*)?",
                                "$options": "i",
                            }
                        },
                        {
                            "description": {
                                "$regex": f"{re.escape(kb_name)}(\\_.*)?",
                                "$options": "i",
                            }
                        },
                    ],
                    "account_id": account_id,
                    "team_code": "",
                    "temp": {"$exists": False},
                }

        kb_list, kb_len = await KnowledgeService.get_kb_pagination(condition, page, page_size)
        if isinstance(kb_list, bool):
            return RetUtil.response_error(message=kb_len)
        knowledge_id_list = [item["id"] for item in kb_list]
        result = {"total": kb_len, "result": kb_list}
        logger.info(f"分页获取用户/团队创建的知识库数量:{len(kb_list)}")
        logger.info(f"分页获取用户/团队创建的知识库ID列表:{knowledge_id_list}")

        return RetUtil.response_ok(data=result)

    except Exception as e:
        logger.exception("获取知识库列表失败", str(e))
        return RetUtil.response_error(message="获取知识库列表失败")


@router.post("/knowledge_describe", summary="获取指定知识库文件数与处理结果数")
async def knowledge_describe(id: str = Body(..., description="知识库id", embed=True)) -> Response:
    try:
        # 知识库是否存在
        condition = {"_id": ObjectId(id)}
        is_exist = await KnowledgeService.is_knowledge_exist(condition)
        if not is_exist:
            return RetUtil.response_error(message="知识库不存在")

        # 获取知识库描述
        description = await KnowledgeService.get_kb_describe(id)

        # 获取知识库详细信息
        (
            file_count,
            result_count,
            id,
            prompt,
            retrieval_count,
            rerank_model,
            top_k,
            score,
            rerank_id,
            enhance_rounds,
            max_tokens,
            search_type,
            fusion_weights,
            is_rerank,
        ) = await KnowledgeService.knowledge_describe(id)
        describe_info = {
            "file_count": file_count,
            "result_count": result_count,
            "description": description,
            "id": id,
            "prompt": prompt,
            "retrieval_count": retrieval_count,
            "rerank_model": rerank_model,
            "top_k": top_k,
            "score": score,
            "rerank_id": rerank_id,
            "enhance_rounds": enhance_rounds,
            "max_tokens": max_tokens,
            "search_type": search_type,
            "fusion_weights": fusion_weights,
            "is_rerank": is_rerank,
        }
        return RetUtil.response_ok(describe_info)

    except Exception as e:
        logger.exception("获取指定知识库文件数与处理结果数失败")
        return RetUtil.response_error(message="获取指定知识库文件数与处理结果数失败")


@router.post("/knowledge_whole_export", summary="知识库所有内容导出")
async def knowledge_whole_export(id: str = Body(..., description="知识库id", embed=True)):
    try:
        input_info = {"id": id}
        # logger.info(f"知识库所有内容导出入参信息:{input_info}")

        # 知识库是否存在
        condition = {"_id": ObjectId(id)}
        is_exist = await KnowledgeService.is_knowledge_exist(condition)
        if not is_exist:
            return RetUtil.response_error(message="知识库不存在")

        output_json = {"origin_knowledge_id": id}
        temp_id = generate_unique_id("Temp", datacenter_id=1, worker_id=1)

        # 先导出知识库基本信息
        knowledge_info = MongodbUtil.query_doc_by_id(CollectionConfig.KB_COLLECTION, doc_id=ObjectId(id))
        knowledge_info.pop("_id", None)
        output_json["knowledge_info"] = knowledge_info

        # 再导出知识库上传文件基本信息
        upload_file_list = []
        upload_file_info_list = MongodbUtil.query_docs_by_condition(
            collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
            search_condition={"knowledge_id": id},
        )
        for file in list(upload_file_info_list):
            upload_file_list.append(file)
        logger.info(f"导出知识库文件数量：{len(upload_file_info_list)}")
        output_json["upload_file_list"] = upload_file_list

        # 再获取向量数据库切片内容
        chunk_data_list = []
        create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        milvus_connection = MilvusUtil("default")
        iterator = milvus_connection.iterator_collection(batch_size=100, collection_name=f"_{id}")

        while True:
            result = iterator.next()
            if not result:
                iterator.close()
                break
            for chunk_data in result:
                chunk_data.pop("index", None)
                chunk_data["create_time"] = create_time
                for i in range(len(chunk_data["vector"])):
                    chunk_data["vector"][i] = float(chunk_data["vector"][i])
                chunk_data_list.append(chunk_data)

        # 使用完则关闭连接
        milvus_connection.close_connection()
        output_json["chunk_data_list"] = chunk_data_list
        logger.info(f"导出知识库切片数量：{len(chunk_data_list)}")
        local_folder = Path(__file__).parents[3] / "upload" / "temp_download" / temp_id
        os.makedirs(local_folder, exist_ok=True)
        json_file_path = local_folder / "output.json"
        with open(json_file_path, "w", encoding="utf-8") as json_file:
            json.dump(output_json, json_file, ensure_ascii=False, indent=4)

        # 最后获取minio远程文件并压缩
        await KnowledgeService.download_minio_folder(
            bucket_name=MinioConfig.BUCKET_NAME,
            prefix=f"{id}/",
            local_folder=f"{Path(__file__).parents[3]}/upload/temp_download/{temp_id}",
        )

        local_folder = Path(__file__).parents[3] / "upload" / "temp_download" / temp_id
        os.makedirs(local_folder, exist_ok=True)
        zip_file_path = Path(__file__).parents[3] / "upload" / f"{temp_id}.zip"
        with ZipFile(zip_file_path, "w") as zipf:
            for root, dirs, files in os.walk(local_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, local_folder)
                    zipf.write(file_path, arcname)
        # 返回压缩包
        logger.info("知识库导出成功")
        return RetUtil.response_ok("导出成功")

    except Exception as e:
        logger.exception("获取指定知识库文件数与处理结果数失败", str(e))
        return RetUtil.response_error(message="获取指定知识库文件数与处理结果数失败")


@router.post("/knowledge_whole_import", summary="知识库所有内容导入")
async def knowledge_whole_import(
    request: Request,
    team_code: Optional[str] = Body("", description="团队id"),
    file_obj: UploadFile = File(..., description="压缩包文件"),
):
    try:
        temp_folder = Path(__file__).parents[3] / "upload" / "temp_import"
        os.makedirs(temp_folder, exist_ok=True)

        # 保存上传的文件到临时文件夹
        temp_zip_path = temp_folder / file_obj.filename
        with open(temp_zip_path, "wb") as temp_file:
            temp_file.write(await file_obj.read())

        # 解压上传的文件
        with ZipFile(temp_zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_folder)

        if temp_zip_path.exists():
            os.remove(temp_zip_path)

        extracted_folder_name = None
        for item in zip_ref.namelist():
            if not item.endswith("/"):
                extracted_folder_name = os.path.dirname(item)
                break

        # 初始化结果字典
        result = {"json_content": None, "files": []}

        # 遍历解压后的文件夹
        extracted_folder_path = temp_folder / extracted_folder_name
        for root, dirs, files in os.walk(extracted_folder_path):
            for file in files:
                file_path = Path(root) / file
                if file.endswith(".json"):
                    # 读取 JSON 文件内容
                    with open(file_path, encoding="utf-8") as json_file:
                        result["json_content"] = json.load(json_file)
                else:
                    # 记录其他文件路径
                    result["files"].append(str(file_path.relative_to(temp_folder)))
        # 导入知识库信息
        knowledge_info = result["json_content"]["knowledge_info"]
        knowledge_info.pop("_id", None)
        knowledge_info["team_code"] = team_code
        insert_data = MongodbUtil.insert_one(collection_name=CollectionConfig.KB_COLLECTION, doc_content=knowledge_info)
        kb_id = str(insert_data.inserted_id)

        # 建立minio远程文件路径与文件名称关联字典
        remote_path_dict = {}
        minio_file_list = result["files"]
        for minio_file in minio_file_list:
            remote_file_name = os.path.basename(minio_file)
            remote_path_dict[remote_file_name] = minio_file

        # 导入上传文件基本信息与上传文件至minio文件服务器
        account_id = request.state.account_id
        origin_knowledge_id = result["json_content"]["origin_knowledge_id"]
        file_id_dict = {}
        upload_file_list = result["json_content"]["upload_file_list"]
        other_file_list = result["files"]
        for upload_file in upload_file_list:
            if upload_file.get("pdf_path", ""):
                upload_file["pdf_path"] = upload_file["pdf_path"].replace(str(origin_knowledge_id), str(kb_id))
            if upload_file.get("account_id", ""):
                upload_file["account_id"] = account_id
            remote_path = f"{kb_id}/{upload_file['file_name']}"
            _id = generate_unique_id("F", datacenter_id=1, worker_id=1)
            create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            file_id_dict[upload_file["_id"]] = _id
            upload_file["_id"] = _id
            upload_file["knowledge_id"] = kb_id
            upload_file["create_time"] = create_time
            try:
                await run_in_threadpool(
                    MinIoUtil.upload_file,
                    "tiance-base",
                    remote_path,
                    temp_folder / remote_path_dict[upload_file["file_name"]],
                )
                upload_file["remote_path"] = remote_path
                other_file_list.remove(upload_file["file_name"])
            except Exception as e:
                logger.exception("远程文件下载到本地失败", str(e))
                upload_file["remote_path"] = ""
            MongodbUtil.insert_one(
                collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                doc_content=upload_file,
            )

        # 导入其他文件至文件服务器
        for other_file in other_file_list:
            try:
                remote_path = f"{kb_id}/{other_file}"
                remote_path = remote_path.replace("\\", "/")
                await run_in_threadpool(
                    MinIoUtil.upload_file,
                    "tiance-base",
                    remote_path,
                    temp_folder / other_file,
                )
            except Exception as e:
                logger.exception("远程文件上传失败", str(e))

        # 导入向量知识库切块内容
        milvus_connection = MilvusUtil("default")
        milvus_id = f"_{kb_id}"
        milvus = MilvusUtil()
        await milvus.create_collection(collection_name=milvus_id, dim=knowledge_info["embedding_dimension"])
        chunk_data_list = result["json_content"]["chunk_data_list"]
        for chunk_data in chunk_data_list:
            create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            chunk_data["file_time"] = create_time
            chunk_data["file_id"] = file_id_dict[chunk_data["file_id"]]
            if chunk_data.get("source_data", None):
                for source_data in chunk_data["source_data"]:
                    if source_data.get("images_urls", None):
                        for image_url_index in range(len(source_data["images_urls"])):
                            source_data["images_urls"][image_url_index] = source_data["images_urls"][
                                image_url_index
                            ].replace(str(origin_knowledge_id), str(kb_id))
            if chunk_data.get("create_time", None):
                chunk_data["create_time"] = create_time

        batch_size = 100  # 每批次插入的数据量
        for i in range(0, len(chunk_data_list), batch_size):
            batch_data = chunk_data_list[i : i + batch_size]
            await milvus.add_document(collection_name=f"_{kb_id}", data=batch_data)
        logger.info("知识库导入成功")
        return RetUtil.response_ok("导入成功")

    except Exception as e:
        logger.exception("知识库所有内容导入失败", str(e))
        return RetUtil.response_error(message="知识库所有内容导入失败")

@router.post(
    "/evaluation_delete",
    description="批量删除文件ID对应的所有测评数据（含主表、设置、问题、答案、结果表）"
)
async def delete_evaluation_tasks(
        file_ids: List[str] = Body(..., embed=True, description="测评任务文件ID列表（必填，KNOWLEDGE_EVALUATION表主键）"),
        db: Session = Depends(get_db),
):
    try:
        if not file_ids:
            return RetUtil.response_error(message="文件ID列表不能为空")
        delete_result = Knowledge_Evaluation_service.batch_delete_evaluation_data(
            db=db,
            file_ids=file_ids
        )
        if delete_result["success"]:
            return RetUtil.response_ok(
                data=f"批量删除成功：共处理{len(file_ids)}个文件，删除{delete_result['delete_count']}条数据",
            )
        else:
            raise Exception(delete_result["message"])

    except Exception as e:
        logger.exception(f"批量删除测评任务系统错误：{str(e)}")
        return RetUtil.response_error(message=f"删除失败：{str(e)}")

@router.post(
    "/hit_stat",
    description="测评结果，包含文件下所有状态3/4/5的测评命中/未命中统计（通过文件ID查询）"
)
async def query_evaluation_hit_stat(
    file_id: str = Body(..., embed=True, description="文件ID（必传，查询该文件的所有有效测评统计）"),
    db: Session = Depends(get_db),
):
    try:
        result = Knowledge_Evaluation_service.get_hit_stat(
            db=db, file_id=file_id
        )
        return RetUtil.response_ok(data=result)
    except Exception as e:
        logger.exception(f"命中统计查询失败（file_id={file_id}）：{str(e)}")
        return RetUtil.response_error(message=f"查询失败：{str(e)}")

@router.post(
    "/evaluation_dataset",
    summary="知识库下的评测数据集",
    description="知识库下的评测数据集"
)
async def query_evaluation_param(
    kb_id: str = Body(...,embed=True, description="测评任务ID"),
    file_name: Optional[str] = Body(None, embed=True, description="文件名称（模糊匹配，可选）"),
    page: int = Body(1, embed=True, ge=1, description="页码（默认1，最小1）"),
    page_size: int = Body(10, embed=True, ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db),
):
    try:
        result = Knowledge_Evaluation_service.get_evaluation_dataset(
            db=db,
            knowledge_id=kb_id,
            file_name=file_name,
            page=page,
            page_size=page_size
        )
        return RetUtil.response_ok(data=result)
    except Exception as e:
        logger.exception(f"检索参数查询失败（evaluation_id={kb_id}）：{str(e)}")
        return RetUtil.response_error(message=f"查询失败：{str(e)}")

@router.post(
    "/evaluation_single_delete",
    description="删除单个测评ID对应的所有关联数据（精准删除）"
)
async def delete_single_evaluation(
        evaluation_id: str = Body(..., embed=True, description="测评设置ID（KnowledgeEvaluationSetting表主键，必填）"),
        db: Session = Depends(get_db),
):
    try:
        # 调用服务层执行单个测评删除
        delete_result = Knowledge_Evaluation_service.delete_single_evaluation(
            db=db,
            evaluation_id=evaluation_id
        )
        if delete_result["success"]:
            return RetUtil.response_ok(
                data=f"测评ID【{evaluation_id}】删除成功，共删除{delete_result['delete_count']}条数据",
            )
        else:
            raise Exception(delete_result["message"])
    except Exception as e:
        logger.exception(f"删除单个测评ID系统错误（evaluation_id={evaluation_id}）：{str(e)}")
        return RetUtil.response_error(message=f"删除失败：{str(e)}")
@router.get("/ori_chunk_result", summary="获取原始切片内容")
async def ori_chunk_result(
    kb_id: str = Body(..., description="知识库id"),
    chunk_id: str = Body(..., description="切片id")
):
    try:
        logger.info(f"->开始获取知识库[{kb_id}]中切片[{chunk_id}]的原始内容")
        result = await KnowledgeService.ori_chunk_result(
            kb_id=kb_id,
            chunk_id=chunk_id
        )
        logger.info(f"->获取原始切片内容成功，chunk_id: {chunk_id}")
        return RetUtil.response_ok(result)
    except Exception as e:
        detail = f"获取原始切片内容失败：{str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message=detail)
