#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base 
@File    ：api_config.py
@Author  ：TaoMeng
@Date    ：2024/8/25 22:49 
"""


class ApiConfig(object):
    """
    API配置
    """
    SERVICE_IP = "0.0.0.0"

    # 服务端口
    SERVICE_PORT = 9101

    # 根路由
    ROOT_ROUTE = "/tc/llm/base"

    # 鉴权路由
    PERMISSION_AUTH_ROUTE = "/permission-auth"
    PERMISSION_MANAGE_RESOURCE_ROUTE = "/permission-manage/resource"


    #API 版本
    MODEL_SERVICE_VERSION = "v0.1"

    SECRET_KEY = '114514'
    AUTH_CONFIG = {'permission-manage': 'RES_1861326972626538496'}
