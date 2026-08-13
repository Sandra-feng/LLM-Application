#!/usr/bin/env python
# -*- encoding: utf-8 -*-
"""
@Project ：tiance-base
@File    ：test_config.py
@Author  ：Yun Peng
@Date    ：2024/8/29 14.51
"""

from base_configs.api_config import ApiConfig

# 模型管理测试路由
ROUTE = f"http://127.0.0.1:{ApiConfig.CONFIG_SERVICE_PORT}{ApiConfig.ROOT_ROUTE}{ApiConfig.CONFIG_MANAGE_ROUTE}"
