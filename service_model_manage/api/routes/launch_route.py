#!/usr/bin/env python

"""
@File         :launch_route.py
@Description  :
@Author       :QiangQu
@Date         :2024/08/28 18:19:17
"""
from sqlalchemy.orm import Session
from bson import ObjectId
from fastapi import APIRouter, Body
from fastapi.responses import Response
from loguru import logger
from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.ret_util import RetUtil
from service_model_manage.entity.launch_entity import AccessModelInfo, CommonModelInfo, LLMModelInfo
from service_model_manage.service.launch_service import LaunchService
from fastapi import Depends

# logger = loguru logger (auto-migrated)
router = APIRouter()


@router.post("/llm_model_launch", summary="LLM模型启动")
async def llm_model_launch(params: LLMModelInfo) -> Response:
    try:
        params_dict = dict(params)
        logger.info("->LLM模型启动")
        response = await LaunchService.llm_model_launch(params_dict)

        if response.get("status"):
            logger.info("->LLM模型启动成功")
            data = response.get("data")
            return RetUtil.response_ok(data=data)
        else:
            # 抛出模型启动异常
            raise Exception(response.get("message"))

    except Exception as e:
        detail = f"LLM模型启动失败：{str(e)}"
        logger.exception(detail)
        raise RetUtil.response_error(message=detail)


@router.post("/common_model_launch", summary="通用模型启动")
async def common_model_launch(params: CommonModelInfo) -> Response:
    try:
        logger.info("->通用模型启动")
        params_dict = dict(params)

        response = await LaunchService.common_model_launch(params_dict)
        if response.get("status"):
            logger.info("->通用模型启动成功")
            data = response.get("data")
            return RetUtil.response_ok(data=data)
        else:
            # 抛出模型启动异常
            raise Exception(response.get("message"))

    except Exception as e:
        detail = f"通用模型启动失败：{str(e)}"
        logger.exception(detail)
        raise RetUtil.response_error(message=detail)


@router.post("/access_model", summary="外部模型接入")
async def access_model(params: AccessModelInfo) -> Response:
    try:
        logger.info("->接入外部模型")
        params = dict(params)
        if params["api_key"] == "":
            params["api_key"] = "not empty"
        response = await LaunchService.access_model(params)
        if response.get("status"):
            logger.info("->外部模型接入成功")
            data = response.get("data")
            return RetUtil.response_ok(data=data)
        else:
            # 抛出模型启动异常
            raise Exception(response.get("message"))

    except Exception as e:
        detail = f"外部模型接入失败：{str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="外部模型接入失败")


@router.post("/access_model_info", summary="获取外部模型信息")
async def access_model_info() -> Response:
    try:
        logger.info("->获取外部模型信息")
        data = []
        results = MongodbUtil.query_docs_by_condition(
            collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
            search_condition={"is_external": True, "is_delete": False},
        )
        for result in results:
            result["_id"] = str(result["_id"])
            data.append(result)
        logger.info("->获取外部模型信息成功")
        return RetUtil.response_ok(data=data)

    except Exception as e:
        detail = f"获取外部模型信息失败：{str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="获取外部模型列表失败")


@router.post("/access_model_status", summary="外部模型状态更新")
async def access_model_update(
    id: str = Body(..., embed=True, examples=["67e4b9fdc9a1cc62f5607b7e"], description="模型运行数据库唯一标识"),
    is_delete: bool = Body(..., embed=True, examples=[True], description="模型是否被删除"),
    status: str = Body(..., embed=True, examples=["running"], description="模型状态"),
) -> Response:
    try:
        logger.info("->更新外部模型状态信息")
        MongodbUtil.update_one(
            collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
            query_filter={"_id": ObjectId(id)},
            update_operation={"$set": {"is_delete": is_delete, "status": status}},
        )
        logger.info("->外部模型状态信息更新成功")
        return RetUtil.response_ok(data="外部模型状态信息更新成功")
    except Exception as e:
        detail = f"外部模型状态信息更新失败：{str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="外部模型状态信息更新失败")


@router.post("/access_model_update", summary="外部模型更新")
async def access_model(
    id: str = Body(..., embed=True, examples=["67e4b9fdc9a1cc62f5607b7e"], description="工作流id"),
    params: AccessModelInfo = Body(...),
) -> Response:
    try:
        logger.info("->更新外部模型")
        params = dict(params)
        response = await LaunchService.access_model_update(id, params)
        if response.get("status"):
            logger.info("->外部模型更新成功")
            data = response.get("data")
            return RetUtil.response_ok(data=data)
        else:
            # 抛出模型启动异常
            raise Exception(response.get("message"))

    except Exception as e:
        detail = f"外部模型更新失败：{str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="外部模型更新失败")

#添加一个接口，查询数据库，获取在线搜索配置

# @router.post("/test", summary="通用模型启动")
# async def test(
#     workflow_id: list = Body(..., embed=True, examples=[["67502d2fdf37c2774fa6fe25"], "123"], description="工作流id"),
# ) -> Response:
#     try:
#         return RetUtil.response_ok(data="ok")
#     except Exception as e:
#         detail = f"模型启动失败：{str(e)}"
#         logger.exception(detail)
#         # 返回HTTP错误响应
#         RetUtil.response_error(data="erro")
