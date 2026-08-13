#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：get_model_info.py
@Author  ：YunPeng
@Date    ：2024/8/27 10.40
"""

from fastapi import APIRouter
from fastapi.responses import Response
from loguru import logger
from service_permission_manage.service.config_service import ConfigService
from base_utils.ret_util import RetUtil
from service_config_manage.service.get_model_info_service import ConfigService

# logger = loguru logger (auto-migrated)
router = APIRouter()


@router.post("/get_model_type", summary="获取模型类型")
async def get_model_type() -> Response:
    """
    获取模型类型
    :return:
    """
    try:
        # 业务逻辑处理
        model_type_list = await ConfigService.get_model_type_list()

        return RetUtil.response_ok(data=model_type_list)
    except (Exception, RuntimeError) as e:
        logger.exception("get_model_type error")
        return RetUtil.response_error(message="系统异常，请稍后再试")


@router.post("/get_model_engine", summary="获取模型引擎类型")
async def get_model_engine() -> Response:
    """
    获取模型引擎类型
    :return:
    """
    try:
        # 业务逻辑处理
        model_engine_list = await ConfigService.get_model_engine_list()

        return RetUtil.response_ok(data=model_engine_list)
    except (Exception, RuntimeError) as e:
        logger.exception("get_model_engine error")
        return RetUtil.response_error(message="系统异常，请稍后再试")


@router.post("/get_model_quantization", summary="获取模型量化类型")
async def get_model_quantization() -> Response:
    """
    获取模型量化类型
    :return:
    """
    try:
        # 业务逻辑处理
        model_quantization_list = await ConfigService.get_model_quantization_list()

        return RetUtil.response_ok(data=model_quantization_list)
    except (Exception, RuntimeError) as e:
        logger.exception("get_model_quantization error")
        return RetUtil.response_error(message="系统异常，请稍后再试")


@router.post("/get_model_size", summary="获取模型大小")
async def get_model_size() -> Response:
    """
    获取模型大小
    :return:
    """
    try:
        # 业务逻辑处理
        model_size_list = await ConfigService.get_model_size_list()
        return RetUtil.response_ok(data=model_size_list)
    except (Exception, RuntimeError) as e:
        logger.exception("get_model_size error")
        return RetUtil.response_error(message="系统异常，请稍后再试")


@router.post("/get_model_format", summary="获取模型形式")
async def get_model_format() -> Response:
    """
    获取模型形式
    :return:
    """
    try:
        # 业务逻辑处理

        model_format_list = await ConfigService.get_model_format_list()

        return RetUtil.response_ok(data=model_format_list)
    except (Exception, RuntimeError) as e:
        logger.exception("get_model_format error")
        return RetUtil.response_error(message="系统异常，请稍后再试")

