#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：config_manage_api.py
@Author  ：YunPeng
@Date    ：2024/8/29 14.17
"""
from base_configs.api_config import ApiConfig
from fastapi import APIRouter
from service_config_manage.api.routes import get_model_info_route, file_upload_download_route


api_router = APIRouter()

api_router.include_router(get_model_info_route.router, prefix=ApiConfig.CONFIG_MANAGE_ROUTE, tags=["模型信息获取"])
api_router.include_router(file_upload_download_route.router, prefix=ApiConfig.CONFIG_MANAGE_ROUTE, tags=["文件上传下载"])