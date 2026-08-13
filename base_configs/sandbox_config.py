# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：model_config.py
@Author  ：ChenDu
@Date    ：2025/05/20 17:33
"""

from base_configs.api_config import ApiConfig


class SandboxConfig(object):
    """
    沙盒配置
    """
    SANDBOX_URL = "http://10.8.21.165:9102"
    API_CONFIG = 'ty-sandbox'

    CODE_EXECUTION_CONNECT_TIMEOUT = 10.0
    CODE_EXECUTION_READ_TIMEOUT = 60.0
    CODE_EXECUTION_WRITE_TIMEOUT = 10.0