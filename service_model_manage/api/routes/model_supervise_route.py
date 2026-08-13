#!/usr/bin/env python
"""
@Project    :   tiance-base
@File    :   model_supervise_route.py
@Author  :   WEIHAO HONG
@Time    :   2024/08/29 12:01:53
"""

import requests
from bson import ObjectId
from fastapi import APIRouter, Body
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from loguru import logger

from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.ret_util import RetUtil
from service_model_manage.entity.model_supervise_entity import ModelRunInfoResponse
from service_model_manage.service.model_supervise_service import ModelSuperviseService

# logger = loguru logger (auto-migrated)
router = APIRouter()

"""
    @brief 获取所有运行的模型信息

    @param[in]  model_type     模型类型（必填）

    @return   返回正在运行的所有模型信息
"""


@router.post(
    "/model_running_info",
    summary="获取所有运行的模型信息",
    response_model=ModelRunInfoResponse,
)
async def model_running_info(
    model_type: str = Body(
        "rerank", description="模型类型 大模型=LLM 嵌入模型=embedding 重排模型=rerank 语音模型=audio"
    ),
    model_id: str = Body("", description="模型id(模糊查询)", embed=True),
    page: int = Body(1, description="页码"),
    page_size: int = Body(10, description="分页大小"),
) -> Response:
    try:
        # 记录日志
        logger.info(
            "->获取运行模型信息 | params=%s",
            jsonable_encoder({"model_type": model_type, "model_id": model_id, "page": page, "page_size": page_size}),
        )

        # 业务逻辑处理
        result = await ModelSuperviseService.get_models(
            model_type=model_type, page=page, page_size=page_size, model_id=model_id
        )
        if model_type == "audio":
            for i in result["result"]:
                is_realtime = MongodbUtil.query_doc_by_id(CollectionConfig.MODEL_RUN_COLLECTION, ObjectId(i["id"])).get(
                    "is_realtime", False
                )
                i["is_realtime"] = is_realtime
        """
        {
            "status": "true",
              "msg": "success", 
              "data": [
                    {
                        "model_id":"qwen2-instruct",
                        "model_uid":"qwen2-7B-instruct",
                        "address":"10.8.21.164",
                        "gpu_idx":"1,2",
                        "model_size_in_billions":"7",
                        "quantization":"Int4",
                        "replica":1
                    }
                ]   
            }
        """
        return RetUtil.response_ok(data=result)
    except requests.exceptions.RequestException as e:
        return RetUtil.response_error(
            message="cannot establish connection to xinference, please check your config or xinference server.\
                                      error {}".format(e.args[0])
        )
    except (Exception, RuntimeError) as e:
        logger.exception("获取模型运行信息失败: {}", str(e))
        return RetUtil.response_error(message="Server Internal Error")


"""
    @brief 暂停运行的模型

    @param[in]  model_uid     模型id（必填）

    @return   启动成功时返回模型启动信息
"""


@router.post("/model_pause", summary="暂停运行的模型")
async def model_pause(
    model_uid: str = Body(..., embed=True, description="模型id"),
) -> Response:
    try:
        # 记录日志
        logger.info("模型暂停接口调用 | 参数: model_uid={}", model_uid)

        # 业务逻辑处理
        # print(model_uid)
        """
        {“status": "true", "msg": "success", "data": {}}
        """
        if await ModelSuperviseService.pause_model(model_uid):
            return RetUtil.response_ok(data="")
        # else:
        #     return RetUtil.response_error(message="ternimate failed")
    except requests.exceptions.RequestException as e:
        return RetUtil.response_error(
            message="cannot establish connection to xinference, please check your config or xinference server.\
                                      error {}".format(e.args[0])
        )
    except RuntimeError as e:
        # print("enter")
        logger.exception("模型暂停异常 | model_uid={} | xinference terminate 失败", model_uid)
        return RetUtil.response_error(message=f"xinference terminate failed error {str(e)}")
    # except (Exception, RuntimeError) as e:
    #     logger.error("系统异常 | model_uid=%s", model_uid, exc_info=True)
    #     return RetUtil.response_error(message="系统异常，请稍后再试")


"""
    @brief 模型重启

    @param[in]  model_uid     模型id（必填）

    @return   启动成功时返回模型启动信息
"""


@router.post("/model_restart", summary="模型重启")
async def model_restart(model_uid: str = Body(..., embed=True, description="模型id")) -> Response:
    try:
        # 记录日志
        logger.info("->模型重启接口调用 | params=%s", jsonable_encoder({"model_uid": model_uid}))

        # 业务逻辑处理
        if await ModelSuperviseService.restart_model(model_uid):
            return RetUtil.response_ok(data="")
        # else:
        #     return RetUtil.response_error(message="restart failed")
        """
        {“status": "true", "msg": "success", "data": {}}
        """
        # return RetUtil.response_ok(data="success")
    except RuntimeError as e:
        logger.exception("重启失败，未找到模型 | model_uid={}", model_uid)
        return RetUtil.response_error(message="restart failed, model not exists")
    except (Exception, RuntimeError) as e:
        logger.exception("模型重启接口异常 | model_uid={}", model_uid)
        return RetUtil.response_error(message="系统异常，请稍后再试")


"""
    @brief 模型删除

    @param[in]  model_uid     模型id（必填）

    @return   启动成功时返回模型启动信息
"""


@router.delete("/model_uid_delete", summary="模型删除")
async def model_uid_delete(model_uid: str = Body(..., embed=True, description="模型id")) -> Response:
    try:
        # 记录日志
        logger.info("->模型删除接口调用 | params={}", jsonable_encoder({"model_uid": model_uid}))

        # 业务逻辑处理
        if await ModelSuperviseService.delete_model(model_uid):
            return RetUtil.response_ok(data="")
        # else:
        #     return RetUtil.response_error(message="delete failed")
        """
        {“status": "true", "msg": "success", "data": {}}
        """
    except requests.exceptions.RequestException as e:
        logger.exception("模型删除接口请求异常 | model_uid={} | error={}", model_uid, str(e))
        return RetUtil.response_error(
            message="cannot establish connection to xinference, please check your config or xinference server.\
                                      error {}".format(e.args[0])
        )
    except (Exception, RuntimeError) as e:
        logger.exception("模型删除接口系统异常 | model_uid={}", model_uid)
        return RetUtil.response_error(message="系统异常，请稍后再试")
