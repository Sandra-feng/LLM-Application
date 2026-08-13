#!/usr/bin/env python
# -*- encoding: utf-8 -*-
"""
@File         :knowledge_manage_api.py
@Description  :
@Author       :QiangQu
@Date         :2024/09/03 14:58:50
"""

from base_configs.api_config import ApiConfig
from service_knowledge_manage.api.routes import knowledge_route, file_route, knowledge_hub_route
from fastapi import APIRouter

api_router = APIRouter()

api_router.include_router(knowledge_route.router, prefix=ApiConfig.MODEL_MANAGE_ROUTE, tags=["知识库知识库管理"])
api_router.include_router(file_route.router, prefix=ApiConfig.MODEL_MANAGE_ROUTE, tags=["知识库文件管理"])
api_router.include_router(knowledge_hub_route.router, prefix=ApiConfig.MODEL_MANAGE_ROUTE, tags=["知识库知识库中心"])
