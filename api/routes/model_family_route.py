#!/usr/bin/env python
"""
@Project    :   tiance-base
@File    :   model_family_route.py
@Author  :   WEIHAO HONG
@Time    :   2024/08/29 12:01:49
"""

import pymongo
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from loguru import logger
from sqlalchemy.orm import Session

from base_utils.mongodb_util import MongodbUtil
from base_utils.ret_util import RetUtil
from service_model_manage.entity.model_famliy_entity import ModelListEntity
from service_model_manage.service.model_family_service import ModelFamilyService


# logger = loguru logger (auto-migrated)
def get_db(request: Request):
    db = request.app.state.SessionLocal()
    try:
        yield db
    finally:
        db.close()


router = APIRouter()


"""
    @brief 根据model_id和model_type获取模型启动信息
    
    @param[in]  model_id      查询的模型ID（必填）
    @param[in]  model_type     模型类型（当前运行的模型ID（必填）

    @return   启动成功时返回模型启动信息
"""


@router.post("/model_start_info", summary="模型启动信息接口")
async def model_start_info(
    model_id: str = Body(..., description="当前运行模型"),
    model_type: str = Body(..., description="要切换的新模型"),
) -> Response:
    try:
        # 记录日志
        logger.info("模型启动进入 model_start_info | model_id={} | model_type={}", model_id, model_type)

        # 业务逻辑处理
        result = ModelFamilyService.get_model_family_by_model_id_and_model_type(
            model_id=model_id, model_type=model_type
        )
        return RetUtil.response_ok(data=result)
    except pymongo.errors.ServerSelectionTimeoutError as e:
        logger.exception("MongoDB连接超时: {}", str(e))
        return RetUtil.response_error(message="mongodb connect failed, please check your config")
    except (Exception, RuntimeError) as e:
        logger.exception("Server内部异常: {}", str(e))
        return RetUtil.response_error(message="Server Internal Error")


@router.post("/model_create", summary="新增模型", response_model=ModelListEntity)
async def model_create_info(model_info: ModelListEntity) -> Response:
    """
    功能说明：新增模型信息，
    添加成功，则返回该模型的全部信息。
    """

    try:
        logger.info("新增模型| model_name={}", model_info.model_id)

        model_llm_details_dict = model_info.model_llm_details.model_dump() if model_info.model_llm_details else None
        model_emb_details_dict = model_info.model_emb_details.model_dump() if model_info.model_emb_details else None

        # 无重名模型，则创建新模型
        models = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"_id": model_info.model_id})

        if len(list(models)) == 0:
            model = await ModelFamilyService.model_create(
                model_id=model_info.model_id,
                model_type=model_info.model_type,
                model_description=model_info.model_description,
                model_llm_details=model_llm_details_dict,
                model_emb_details=model_emb_details_dict,
            )
            return RetUtil.response_ok(data=True)

        else:
            models = MongodbUtil.query_docs_by_condition(
                ModelFamilyService._collection_name, {"_id": model_info.model_id}
            )
            models = list(models)
            model = models[0]
            if model.get("is_remove") == True:
                model = await ModelFamilyService.model_update(
                    model_id=model_info.model_id,
                    model_type=model_info.model_type,
                    model_description=model_info.model_description,
                    model_llm_details=model_llm_details_dict,
                    model_emb_details=model_emb_details_dict,
                )
                return RetUtil.response_ok(data=True)
            else:
                # raise HTTPException(status_code=400, detail="The model already exists, please rename your model")
                return RetUtil.response_error(message="The model already exists, please rename your model")
        # if len(list(models)) == 0:
        #     model = await ModelFamilyService.model_create(
        #         model_id=model_info.model_id,
        #         model_type=model_info.model_type,
        #         model_description=model_info.model_description,
        #         model_llm_details=model_llm_details_dict,
        #         model_emb_details=model_emb_details_dict
        #     )
        # else:
        #     # 模型存在并且已经被删除（等价于不存在） 或者模型不存在
        #     for model in  models:
        #         if (model.get("_id") == True and model.get("is_remove") == True) or (model.get("_id") == False):
        #             if model.get("is_remove") == True:
        #                 model = await ModelFamilyService.model_create(
        #                     model_id=model_info.model_id,
        #                     model_type=model_info.model_type,
        #                     model_description=model_info.model_description,
        #                     model_llm_details=model_llm_details_dict,
        #                     model_emb_details=model_emb_details_dict
        #                 )
        #                 return RetUtil.response_ok(data=True)
        #         #模型存在 没被移除 （存在）
        #         else:
        #             raise HTTPException(status_code=400, detail="The model already exists, please rename your model")

    except pymongo.errors.ServerSelectionTimeoutError as e:
        detail = f"MongoDB connection failed: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="MongoDB connection failed, please check your config")

    except HTTPException as e:
        detail = f"Model Not Exists: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="The model already exists, please rename your model")

    except Exception as e:
        detail = f"Server Internal Error: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="Server Internal Error")


@router.post("/model_update", summary="修改模型", response_model=ModelListEntity)
async def model_update_info(model_info: ModelListEntity) -> Response:
    """
    功能说明： 对指定model_id的模型信息进行修改（model_id不会变）
    param model_id: 模型名称，
    param model_type: 模型类型，
    param model_description: 模型的相关描述，
    param model_XXX_details: 其他参数，
    修改成功，则返回该模型修改后的全部信息。
    """
    try:
        logger.info("->修改模型 | model_id={}", model_info.model_id)

        model = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"_id": model_info.model_id})
        if len(list(model)) == 0:
            # raise HTTPException(status_code=400, detail="The model not exists, please create your model")
            return RetUtil.response_error(message="The model not exists, please create your model")

        model_llm_details_dict = model_info.model_llm_details.model_dump() if model_info.model_llm_details else None
        model_emb_details_dict = model_info.model_emb_details.model_dump() if model_info.model_emb_details else None

        model = await ModelFamilyService.model_update(
            model_id=model_info.model_id,
            model_type=model_info.model_type,
            model_description=model_info.model_description,
            model_llm_details=model_llm_details_dict,
            model_emb_details=model_emb_details_dict,
        )
        return RetUtil.response_ok(data=True)

    except pymongo.errors.ServerSelectionTimeoutError as e:
        detail = f"MongoDB connection failed: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="MongoDB connection failed, please check your config")

    except HTTPException as e:
        detail = f"Model Not Exists: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="The model not exists, please create your model")

    except Exception as e:
        detail = f"Server Internal Error: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="Server Internal Error")


@router.delete("/model_delete", summary="删除模型")
async def model_delete_info(model_id: str = Body(..., description="需要删除的模型id", embed=True)) -> Response:
    """
    功能说明： 根据模型id，删除模型（修改标识符 is_remove 为 1）
    param model_id: 模型名称，
    修改成功，则返回删除模型的全部信息。
    """
    try:
        logger.info("->删除模型 | model_id={}", model_info.model_id)

        model = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"_id": model_id})
        if len(list(model)) == 0:
            # raise HTTPException(status_code=400, detail="The model not exists, please create your model")
            return RetUtil.response_error(message="The model not exists, please create your model")
        else:
            model = await ModelFamilyService.model_delete(model_id=model_id)
            return RetUtil.response_ok(data=True)

    except pymongo.errors.ServerSelectionTimeoutError as e:
        detail = f"MongoDB connection failed: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="MongoDB connection failed, please check your config")

    except HTTPException as e:
        detail = f"Model Not Exists: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="The model not exists, please create your model")

    except Exception as e:
        detail = f"Server Internal Error: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="Server Internal Error")


@router.post("/model_judge", summary="模型是否存在")
async def model_info(model_id: str = Body(..., description="需要判断的模型id", embed=True)) -> Response:
    """
    功能说明： 判断该模型是否存在

    """
    try:
        model = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"_id": model_id})
        if len(list(model)) == 0:
            return RetUtil.response_ok(data=True)

        else:
            model = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"_id": model_id})
            model = list(model)
            model = model[0]
            if model.get("is_remove") == True:
                return RetUtil.response_ok(data=True)
            else:
                # raise HTTPException(status_code=400, detail="The model already exists, please rename your model")
                return RetUtil.response_error(message="The model already exists, please rename your model")

    except pymongo.errors.ServerSelectionTimeoutError as e:
        detail = f"MongoDB connection failed: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="MongoDB connection failed, please check your config")

    except HTTPException as e:
        detail = f"Model Not Exists: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="The model already exists, please rename your model")

    except Exception as e:
        detail = f"Server Internal Error: {str(e)}"
        logger.exception(detail)
        return RetUtil.response_error(message="Server Internal Error")


@router.post("/model_info", summary="指定类型模型信息")
async def model_info(
    model_id: str = Body("", description="模型id(模糊查询)", embed=True),
    model_type: str = Body(..., description="模型类型", embed=True),
) -> Response:
    """
    功能说明： 根据模型类型，返回该类型下的所有模型的基本信息
                {"model_id:"qwen2-instruct","model_type":"llm","model_description":"xxx"}

    param model_type: 模型类型，包括LLM，embedding等。
    返回满足条件的模型基本信息列表[{},{},{}...]
    """
    try:
        logger.info(
            "->指定模型id, 指定类型模型信息 | 参数: {}",
            jsonable_encoder({"model_type": model_type, "model_id": model_id}),
        )

        models = await ModelFamilyService.get_model_list_by_model_type(model_type=model_type, model_id=model_id)

        return RetUtil.response_ok(data=models)

    except pymongo.errors.ServerSelectionTimeoutError as e:
        logger.exception("异常: {}", str(e))
        return RetUtil.response_error(message="mongodb connect failed, please check your config")

    except (Exception, RuntimeError) as e:
        logger.exception("异常: {}", str(e))
        return RetUtil.response_error(message="Server Internal Error")


@router.post("/model_prompt_info", summary="修改模型时的原信息提示", response_model=ModelListEntity)
async def model_prompt_info(model_id: str = Body(..., description="修改模型时模型id", embed=True)) -> Response:
    try:
        # logger.info("->指定类型模型信息: {}", jsonable_encoder({"model_id": model_id}))
        logger.info("->获取模型信息")

        models = await ModelFamilyService.get_model_list_by_model_id(model_id=model_id)
        logger.info("->获取模型信息成功")
        return RetUtil.response_ok(data=models)

    except pymongo.errors.ServerSelectionTimeoutError as e:
        logger.exception("MongoDB connection failed: {}", str(e))
        return RetUtil.response_error(message="MongoDB connection failed, please check your config")

    except HTTPException as e:
        logger.exception("Model Not Exists: {}", str(e))
        return RetUtil.response_error(message="The model not exists, please create your model")

    except Exception as e:
        logger.exception("Server Internal Error: %{}", str(e))
        return RetUtil.response_error(message="Server Internal Error")


@router.post("/model_update_test", summary="修改模型测试(鉴别用户权限)", response_model=ModelListEntity)
async def model_update_info(
    model_info: ModelListEntity, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    """
    功能说明： 先根据用户id对用户权限进行判断, 只有管理员权限(attribute : 1)才能对指定model_id的模型信息进行修改,
              并保存执行修改操作的用户id。否则无修改权限
    model_info: 模型基本信息，包括模型名称，模型类型，模型描述，模型参数等。
    param model_id: 模型名称,
    param model_type: 模型类型,
    param model_description: 模型的相关描述,
    param model_XXX_details: 其他参数,
    param account_id: 用户id,
    param db: 连接Mysql数据库, 注入依赖。
    修改成功, 保存执行修改操作的用户id, 返回该模型修改后的全部信息。
    """
    try:
        account_id = chat_request.state.account_id
        logger.info("->修改模型(鉴权) | account_id={} | payload={}", account_id, jsonable_encoder(model_info))

        # 通过account_id在User表中获取用户角色
        user_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, account_id)
        logger.info(
            "用户角色判定 | account_id={} | role={}", account_id, ("超级管理员" if user_attribute else "普通用户")
        )

        if not user_attribute:
            logger.warning("用户无权限修改模型信息 | account_id={} | model_id={}", account_id, model_info.model_id)
            return RetUtil.response_error(message="用户无权限修改模型信息")

        model = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"_id": model_info.model_id})
        if len(list(model)) == 0:
            # raise HTTPException(status_code=400, detail="The model not exists, please create your model")
            return RetUtil.response_error(message="Model Not Exists, please rename your model")

        model_llm_details_dict = model_info.model_llm_details.model_dump() if model_info.model_llm_details else None
        model_emb_details_dict = model_info.model_emb_details.model_dump() if model_info.model_emb_details else None

        model = await ModelFamilyService.model_update(
            model_id=model_info.model_id,
            model_type=model_info.model_type,
            model_description=model_info.model_description,
            model_llm_details=model_llm_details_dict,
            model_emb_details=model_emb_details_dict,
            account_id=account_id,
        )

        logger.info("修改模型成功 | account_id={} | model_id={}", account_id, model_info.model_id)
        return RetUtil.response_ok(data=True)

    except pymongo.errors.ServerSelectionTimeoutError as e:
        logger.exception("MongoDB connection failed")
        return RetUtil.response_error(message="MongoDB connection failed, please check your config")

    except HTTPException as e:
        logger.exception("Model Not Exists")
        return RetUtil.response_error(message="The model not exists, please create your model")

    except Exception as e:
        logger.exception("Server Internal Error")
        return RetUtil.response_error(message="Server Internal Error")


@router.post("/model_create_test", summary="新增模型(鉴别用户权限)", response_model=ModelListEntity)
async def model_create_info(
    model_info: ModelListEntity, chat_request: Request, db: Session = Depends(get_db)
) -> Response:
    """
    功能说明：先根据用户id鉴别用户权限， 只有管理员权限(attribute : 1)才能新增模型, 并保存执行修改操作的用户id。
    否则无新增模型权限。
    model_info: 模型基本信息，包括模型名称，模型类型，模型描述，模型参数等。
    param model_id: 模型名称,
    param model_type: 模型类型,
    param model_description: 模型的相关描述,
    param model_XXX_details: 其他参数,
    param account_id: 用户id,
    param db: 连接Mysql数据库, 注入依赖。
    添加成功，则返回该模型的全部信息。
    """
    try:
        account_id = chat_request.state.account_id
        logger.info("->新增模型 | account_id={} | payload={}", account_id, jsonable_encoder(model_info))

        user_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, account_id)
        logger.info(
            "用户角色判定 | account_id={} | role={}", account_id, ("超级管理员" if user_attribute else "普通用户")
        )

        if not user_attribute:
            logger.warning("用户无权限新增模型 | account_id={}", account_id)
            return RetUtil.response_error(message="用户无权限新增模型")

        model_llm_details_dict = model_info.model_llm_details.model_dump() if model_info.model_llm_details else None
        model_emb_details_dict = model_info.model_emb_details.model_dump() if model_info.model_emb_details else None

        # 无重名模型，则创建新模型
        models = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"_id": model_info.model_id})

        if len(list(models)) == 0:
            # LogUtil.info(f"数据1models{models}")
            model = await ModelFamilyService.model_create(
                model_id=model_info.model_id,
                model_type=model_info.model_type,
                model_description=model_info.model_description,
                model_llm_details=model_llm_details_dict,
                model_emb_details=model_emb_details_dict,
                account_id=account_id,
            )
            logger.info("新增模型成功 | account_id={} | model_id={}", account_id, model_info.model_id)
            return RetUtil.response_ok(data=True)

        else:
            models = MongodbUtil.query_docs_by_condition(
                ModelFamilyService._collection_name, {"_id": model_info.model_id}
            )
            models = list(models)
            model = models[0]
            if model.get("is_remove") == True:
                model = await ModelFamilyService.model_update(
                    model_id=model_info.model_id,
                    model_type=model_info.model_type,
                    model_description=model_info.model_description,
                    model_llm_details=model_llm_details_dict,
                    model_emb_details=model_emb_details_dict,
                    account_id=account_id,
                )
                logger.info("恢复已删除模型成功 | account_id={} | model_id={}", account_id, model_info.model_id)
                return RetUtil.response_ok(data=True)
            else:
                # raise HTTPException(status_code=400, detail="The model already exists, please rename your model")
                return RetUtil.response_error(message="The model not exists, please check your model")
    except pymongo.errors.ServerSelectionTimeoutError as e:
        logger.exception("MongoDB connection failed")
        return RetUtil.response_error(message="MongoDB connection failed, please check your config")

    except HTTPException as e:
        logger.exception("Model Already Exists")
        return RetUtil.response_error(message="The model already exists, please rename your model")

    except Exception as e:
        logger.exception("Server Internal Error")
        return RetUtil.response_error(message="Server Internal Error")


@router.delete("/model_delete_test", summary="删除模型(鉴别用户权限)")
async def model_delete_info(
    chat_request: Request,
    model_id: str = Body(..., description="需要删除的模型id", embed=True),
    db: Session = Depends(get_db),
) -> Response:
    """
    功能说明： 根据模型id删除模型, 修改标识符 is_remove 为 1, 同时更新进行该操作的用户id
    param model_id: 模型名称，
    param account_id: 用户id,
    修改成功，则返回删除模型的全部信息。
    """
    try:
        account_id = chat_request.state.account_id
        logger.info("->删除模型 | account_id={} | model_id={}", account_id, model_id)

        user_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, account_id)
        logger.info(
            "用户角色判定 | account_id={} | role={}", account_id, ("超级管理员" if user_attribute else "普通用户")
        )

        if not user_attribute:
            logger.warning("用户无权限删除模型 | account_id={} | model_id={}", account_id, model_id)
            return RetUtil.response_error(message="用户无权限删除模型")

        model = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"_id": model_id})
        if len(list(model)) == 0:
            # raise HTTPException(status_code=400, detail="The model not exists, please create your model")
            return RetUtil.response_error(message="The model not exists, please create your model")
        else:
            model = await ModelFamilyService.model_delete(model_id=model_id, account_id=account_id)
            logger.info("删除模型成功 | account_id={} | model_id={}", account_id, model_id)
            return RetUtil.response_ok(data=True)

    except pymongo.errors.ServerSelectionTimeoutError as e:
        logger.exception("MongoDB connection failed")
        return RetUtil.response_error(message="MongoDB connection failed, please check your config")

    except HTTPException as e:
        logger.exception("Model Not Exists")
        return RetUtil.response_error(message="The model not exists, please create your model")

    except Exception as e:
        logger.exception("Server Internal Error")
        return RetUtil.response_error(message="Server Internal Error")
